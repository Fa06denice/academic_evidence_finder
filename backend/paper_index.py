import json
import logging
import os
import re
from typing import Optional

from paper_chat import (
    _CHROMA_DIR,
    _EMBEDDING_API_KEY,
    _EMBEDDING_BASE_URL,
    _EMBEDDING_MODEL,
    OpenAICompatibleEmbeddingFunction,
    _normalize_ws,
    chromadb,
    ensure_chroma_storage,
)

logger = logging.getLogger(__name__)

_PAPER_COLLECTION = "papers_global"
_MIN_LOCAL_SCORE = float(os.getenv("PAPER_INDEX_MIN_SCORE", "0.18"))
_ACADEMIC_STOPWORDS = {
    "study", "studies", "effect", "effects", "review", "reviews", "systematic",
    "meta", "meta-analysis", "analysis", "trial", "trials", "randomized",
    "randomised", "controlled", "cohort", "clinical", "patients", "patient",
    "association", "associated", "investigation", "findings", "result", "results",
}


def _paper_id(paper: dict) -> str:
    ext = paper.get("externalIds") or {}
    return (
        paper.get("paperId")
        or ext.get("DOI")
        or ext.get("PubMed")
        or ""
    ).strip()


def _paper_year_matches(paper: dict, year_filter: Optional[str]) -> bool:
    if not year_filter:
        return True

    year = paper.get("year")
    if year is None:
        return False

    try:
        year_value = int(year)
    except (TypeError, ValueError):
        return False

    years = [int(token) for token in year_filter.replace("/", "-").split("-") if token.strip().isdigit()]
    if not years:
        return True
    if len(years) == 1:
        return year_value == years[0]
    return min(years) <= year_value <= max(years)


def _paper_document(paper: dict) -> str:
    tldr_obj = paper.get("tldr") or {}
    tldr_text = tldr_obj.get("text", "") if isinstance(tldr_obj, dict) else ""
    authors = ", ".join(
        a.get("name", "") for a in (paper.get("authors") or [])[:6] if a.get("name")
    )
    parts = [
        paper.get("title", ""),
        authors,
        paper.get("abstract", ""),
        tldr_text,
    ]
    return _normalize_ws("\n".join(part for part in parts if part))


def _query_terms(query: str) -> list[str]:
    terms = [term for term in re.findall(r"\b[a-z0-9][a-z0-9\-]{2,}\b", query.lower()) if len(term) > 2]
    filtered = [term for term in terms if term not in _ACADEMIC_STOPWORDS]
    return filtered or terms


def _paper_matches_query(paper: dict, query: str) -> tuple[bool, int, int]:
    terms = _query_terms(query)
    if not terms:
        return True, 0, 0

    title = str(paper.get("title") or "").lower()
    haystack = _paper_document(paper).lower()
    overlap = [term for term in terms if term in haystack]
    title_overlap = [term for term in terms if term in title]

    required = 1
    if len(terms) >= 4:
        required = 2
    if len(terms) >= 7:
        required = 3

    is_match = len(overlap) >= required
    if len(terms) >= 4 and not title_overlap:
        is_match = is_match and len(overlap) >= (required + 1)

    return is_match, len(overlap), len(title_overlap)


def paper_index_enabled() -> bool:
    return bool(chromadb and _EMBEDDING_API_KEY and _EMBEDDING_MODEL)


def _get_collection():
    if not paper_index_enabled():
        return None
    if not ensure_chroma_storage():
        return None

    client = chromadb.PersistentClient(path=_CHROMA_DIR)
    embedding_function = OpenAICompatibleEmbeddingFunction(
        api_key=_EMBEDDING_API_KEY,
        model=_EMBEDDING_MODEL,
        base_url=_EMBEDDING_BASE_URL,
    )
    return client.get_or_create_collection(
        name=_PAPER_COLLECTION,
        embedding_function=embedding_function,
        metadata={"hnsw:space": "cosine"},
    )


def paper_index_stats() -> dict:
    collection = _get_collection()
    if collection is None:
        return {"enabled": False, "papers": 0}
    try:
        return {"enabled": True, "papers": collection.count()}
    except Exception as exc:
        logger.warning("Could not read paper index stats: %s", exc)
        return {"enabled": True, "papers": 0}


def index_papers(papers: list[dict], cache_manager=None) -> int:
    collection = _get_collection()
    if collection is None or not papers:
        return 0

    ids = []
    documents = []
    metadatas = []

    for paper in papers:
        paper_id = _paper_id(paper)
        if not paper_id:
            continue

        doc = _paper_document(paper)
        if not doc:
            continue

        if cache_manager:
            try:
                cache_manager.set_paper(paper_id, paper)
            except Exception as exc:
                logger.warning("Could not cache paper %s: %s", paper_id, exc)

        ext = paper.get("externalIds") or {}
        ids.append(paper_id)
        documents.append(doc)
        metadatas.append({
            "paper_id": paper_id,
            "title": str(paper.get("title") or ""),
            "year": int(paper["year"]) if isinstance(paper.get("year"), int) else -1,
            "citation_count": int(paper.get("citationCount") or 0),
            "doi": str(ext.get("DOI") or ""),
            "abstract": str(paper.get("abstract") or "")[:4000],
            "authors_json": json.dumps(paper.get("authors") or [], ensure_ascii=False, default=str),
            "paper_json": json.dumps(paper, ensure_ascii=False, default=str),
        })

    if not ids:
        return 0

    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    logger.info("Indexed %d papers into global paper index", len(ids))
    return len(ids)


def search_local_papers(
    query: str,
    limit: int = 10,
    year_filter: Optional[str] = None,
    exclude_ids: Optional[set] = None,
    cache_manager=None,
) -> list[dict]:
    collection = _get_collection()
    if collection is None or not query.strip():
        return []

    try:
        result = collection.query(
            query_texts=[query],
            n_results=max(limit * 3, limit),
            include=["metadatas", "distances"],
        )
    except Exception as exc:
        logger.warning("Local paper index query failed, skipping local-first retrieval: %s", exc)
        return []

    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    seen = set(exclude_ids or [])
    papers: list[dict] = []

    for metadata, distance in zip(metadatas, distances):
        paper_id = metadata.get("paper_id")
        if not paper_id or paper_id in seen:
            continue

        paper = cache_manager.get_paper(paper_id) if cache_manager else None
        if not isinstance(paper, dict):
            raw_paper = metadata.get("paper_json")
            if isinstance(raw_paper, str) and raw_paper:
                try:
                    paper = json.loads(raw_paper)
                except json.JSONDecodeError:
                    paper = None
        if not isinstance(paper, dict):
            authors = []
            raw_authors = metadata.get("authors_json")
            if isinstance(raw_authors, str) and raw_authors:
                try:
                    authors = json.loads(raw_authors)
                except json.JSONDecodeError:
                    authors = []
            paper = {
                "paperId": paper_id,
                "title": metadata.get("title") or "Unknown",
                "abstract": metadata.get("abstract") or "",
                "year": metadata.get("year") if metadata.get("year", -1) != -1 else None,
                "citationCount": metadata.get("citation_count", 0),
                "authors": authors if isinstance(authors, list) else [],
                "externalIds": {"DOI": metadata.get("doi")} if metadata.get("doi") else {},
            }

        if not _paper_year_matches(paper, year_filter):
            continue

        local_score = round(1.0 - float(distance or 0.0), 4)
        if local_score < _MIN_LOCAL_SCORE:
            continue
        matches_query, overlap_count, title_overlap_count = _paper_matches_query(paper, query)
        if not matches_query:
            continue

        paper["_local_score"] = local_score
        paper["_local_overlap"] = overlap_count
        paper["_local_title_overlap"] = title_overlap_count
        papers.append(paper)
        seen.add(paper_id)

        if len(papers) >= limit:
            break

    if papers:
        papers.sort(
            key=lambda p: (
                p.get("_local_title_overlap", 0),
                p.get("_local_overlap", 0),
                p.get("_local_score", 0),
                p.get("citationCount") or 0,
            ),
            reverse=True,
        )
        logger.info("Local paper index returned %d paper(s) for query: %s", len(papers), query[:120])
    return papers


def backfill_paper_index(cache_manager) -> int:
    if not cache_manager or not paper_index_enabled():
        return 0

    collected: dict[str, dict] = {}

    try:
        for key, entry in (cache_manager.cache or {}).items():
            if not isinstance(entry, dict):
                continue
            data = entry.get("data")
            if key.startswith("paper_") and isinstance(data, dict):
                paper_id = _paper_id(data)
                if paper_id:
                    collected[paper_id] = data
            elif key.startswith("search_") and isinstance(data, list):
                for paper in data:
                    if not isinstance(paper, dict):
                        continue
                    paper_id = _paper_id(paper)
                    if paper_id:
                        collected[paper_id] = paper
    except Exception as exc:
        logger.warning("Could not backfill paper index from cache: %s", exc)
        return 0

    if not collected:
        return 0

    count = index_papers(list(collected.values()), cache_manager=cache_manager)
    if count:
        logger.info("Backfilled %d paper(s) into the global paper index from cache", count)
    return count
