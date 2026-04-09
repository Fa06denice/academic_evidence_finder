"""paper_chat.py — PDF fetch, parse, HTML full-text, and chat logic."""
import io
import hashlib
import logging
import math
import os
import re
import shutil
from collections import Counter
from typing import Optional

import httpx
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from openai import OpenAI

try:
    import chromadb
    from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
except Exception:  # pragma: no cover - optional dependency at runtime
    chromadb = None
    Documents = list[str]
    Embeddings = list[list[float]]
    EmbeddingFunction = object

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "AcademicEvidenceFinder/1.0 (research tool; contact: research@example.com)"
}
_CHUNK_SIZE   = 800
_MAX_CHUNKS   = 6
_TIMEOUT      = 15
_RAG_CHUNK_WORDS   = 180
_RAG_CHUNK_OVERLAP = 45
_DISPLAY_BLOCK_WORDS = 140
_PROFILE_CONTEXT_BLOCKS = 18
_PROFILE_CONTEXT_CHARS = 45000
_DEFAULT_CHROMA_ROOT = os.getenv("CHROMA_DIR", ".chroma")
_CHROMA_DIR_CHAT = os.getenv("CHROMA_DIR_CHAT", os.path.join(_DEFAULT_CHROMA_ROOT, "chat"))
_EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
_EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
_CHROMA_LAST_ERROR = ""

_STOPWORDS = {
    "a", "about", "after", "all", "also", "an", "and", "are", "as", "at", "be",
    "because", "been", "before", "being", "between", "both", "but", "by", "can",
    "could", "did", "do", "does", "during", "each", "for", "from", "had", "has",
    "have", "how", "if", "in", "into", "is", "it", "its", "may", "might", "more",
    "most", "no", "not", "of", "on", "or", "our", "out", "paper", "should",
    "study", "such", "than", "that", "the", "their", "them", "there", "these",
    "they", "this", "those", "through", "to", "under", "use", "used", "using",
    "was", "we", "were", "what", "when", "where", "which", "while", "who", "why",
    "will", "with", "within", "would", "you", "your",
}

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a precise academic paper assistant. You have been given the full text \
(or the best available excerpt) of the following paper:

Title:   {title}
Authors: {authors}
Year:    {year}
DOI:     {doi}
Content source: {source}

PAPER CONTENT:
{content}

\u2501\u2501\u2501 STRICT RULES \u2501\u2501\u2501
1. Answer ONLY based on what is written in the paper content above.
   Never use outside knowledge or training data about this paper.
2. When quoting the paper, copy the text verbatim and indicate its location
   (e.g. "Abstract", "Introduction", "Methods", "Results", "Discussion", "Conclusion").
3. If the paper does not address the question, say so explicitly:
   "This paper does not discuss [topic]."
4. Never invent statistics, results, or conclusions not present in the text.
5. If the user asks something outside the paper's scope, redirect:
   "That question goes beyond this paper. Based on this paper alone, I can tell you..."
6. Keep answers concise and direct. Lead with the answer, then the supporting quote.
7. If the content provided is only an abstract (no full text), mention it once and
   work within that limitation without apology.
"""

_RAG_SYSTEM_PROMPT = """\
You are a precise academic paper assistant.

You are answering about ONE paper using:
- a document-level overview synthesized from the paper itself
- retrieved source passages from the same paper

CHAT STRATEGY:
{strategy_label}

PAPER:
Title:   {title}
Authors: {authors}
Year:    {year}
DOI:     {doi}
Content source: {source}

QUESTION:
{question}

DOCUMENT-LEVEL OVERVIEW:
{document_overview_block}

RETRIEVED SOURCES:
{sources_block}

STRICT RULES:
1. Answer ONLY from the paper content represented by the overview and retrieved sources above.
2. Never use outside knowledge about the paper.
3. For specific factual claims, cite at least one source ID immediately after the claim, e.g. [S1] or [S1, S2].
4. For broad conceptual questions, you may use the document-level overview to synthesize the overall message of the paper, but you must stay faithful to the paper and support the key points with the closest relevant source IDs whenever possible.
5. Never cite a source ID that was not provided.
6. If no single passage directly answers the question, synthesize carefully from multiple passages instead of refusing too quickly.
7. Only say that the evidence is insufficient when both the overview and retrieved sources genuinely fail to support a grounded answer.
8. If the paper content available is only an abstract, mention that once and stay within that limitation.
9. Prefer direct, compact answers. Lead with the answer, then the evidence.
10. When quoting, quote verbatim and keep the citation right after the quote.
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(url: str, **kwargs) -> Optional[httpx.Response]:
    """GET with shared headers, follow redirects, swallow errors."""
    try:
        r = httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT,
                      follow_redirects=True, **kwargs)
        if r.status_code == 200:
            return r
    except Exception as exc:
        logger.warning("GET failed %s: %s", url, exc)
    return None


def _clean_html_text(soup: BeautifulSoup, selectors_to_remove: list[str] = None) -> str:
    """Extract readable text from a BeautifulSoup object, stripping noise."""
    for tag in soup.find_all(["script", "style", "nav", "header",
                               "footer", "aside", "figure", "noscript"]):
        tag.decompose()
    if selectors_to_remove:
        for sel in selectors_to_remove:
            for tag in soup.select(sel):
                tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n")).strip()


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _slugify(text: str, fallback: str = "document") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:40] or fallback


class OpenAICompatibleEmbeddingFunction(EmbeddingFunction):
    def __init__(self, api_key: str, model: str, base_url: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def __call__(self, input: Documents) -> Embeddings:
        texts = [_normalize_ws(text) for text in input]
        if not texts:
            return []
        resp = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in resp.data]


def _set_chroma_error(exc: Exception):
    global _CHROMA_LAST_ERROR
    _CHROMA_LAST_ERROR = str(exc)


def _tokenize(text: str) -> list[str]:
    return [
        tok for tok in re.findall(r"\b[a-z0-9][a-z0-9\-]{1,}\b", (text or "").lower())
        if tok not in _STOPWORDS
    ]


def _question_profile(question: str) -> dict:
    q = (question or "").lower()
    profile = {
        "expanded_query": question,
        "preferred_sections": [],
        "discouraged_sections": [],
        "extra_sources": 0,
    }

    findings_triggers = (
        "main finding", "main findings", "key finding", "key findings",
        "takeaway", "takeaways", "what did they find", "what were the findings",
        "what are the findings", "main result", "main results", "primary outcome",
        "conclusion", "conclusions", "main idea", "overall idea",
        "overall message", "big picture", "summary", "summarize",
    )
    methods_triggers = (
        "method", "methods", "methodology", "study design", "design",
        "participants", "sample", "statistical analysis",
    )
    limitations_triggers = (
        "limitation", "limitations", "weakness", "weaknesses", "bias",
        "confound", "drawback", "caveat", "caveats",
    )

    if any(trigger in q for trigger in findings_triggers):
        profile["expanded_query"] = (
            f"{question} results findings conclusion discussion primary outcome key result"
        ).strip()
        profile["preferred_sections"] = [
            "abstract", "results", "findings", "discussion", "conclusion", "summary",
        ]
        profile["discouraged_sections"] = ["methods", "limitations", "references"]
        profile["extra_sources"] = 4
        return profile

    if any(trigger in q for trigger in methods_triggers):
        profile["expanded_query"] = (
            f"{question} methods methodology study design participants measures statistical analysis"
        ).strip()
        profile["preferred_sections"] = [
            "methods", "methodology", "materials and methods", "study design", "participants",
        ]
        profile["discouraged_sections"] = ["discussion", "conclusion", "limitations"]
        return profile

    if any(trigger in q for trigger in limitations_triggers):
        profile["expanded_query"] = (
            f"{question} limitations weaknesses bias caveats interpretation"
        ).strip()
        profile["preferred_sections"] = ["limitations", "discussion", "conclusion"]
        profile["discouraged_sections"] = ["methods"]
        return profile

    return profile


def _section_weight(locator: str, profile: dict) -> float:
    locator_lower = (locator or "").lower()
    weight = 0.0

    for preferred in profile.get("preferred_sections", []):
        if preferred in locator_lower:
            weight += 1.5

    for discouraged in profile.get("discouraged_sections", []):
        if discouraged in locator_lower:
            weight -= 1.0

    return weight


def _rank_sources_for_question(sources: list[dict], question: str, max_sources: int) -> list[dict]:
    if not sources:
        return []

    profile = _question_profile(question)
    ranked = []
    for idx, source in enumerate(sources):
        base_score = float(source.get("score", 0.0))
        locator = source.get("locator") or source.get("section") or "Document"
        ranked.append((
            base_score + _section_weight(locator, profile),
            idx,
            source,
        ))

    ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)

    selected: list[dict] = []
    seen_ids: set[str] = set()
    for _, _, source in ranked:
        chunk_id = source.get("chunk_id")
        if chunk_id and chunk_id in seen_ids:
            continue
        if chunk_id:
            seen_ids.add(chunk_id)
        selected.append(dict(source))
        if len(selected) >= max_sources:
            break

    for idx, source in enumerate(selected, start=1):
        source["source_id"] = f"S{idx}"

    return selected


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if len(s) > 90 or len(s.split()) > 12:
        return False
    if s.endswith("."):
        return False
    if re.match(r"^\d+(\.\d+)*\s+[A-Z]", s):
        return True
    if s.isupper() and len(s.split()) <= 8:
        return True
    if re.match(r"^[A-Z][A-Za-z0-9/\-\s]{2,}$", s) and sum(ch.isupper() for ch in s) >= 2:
        return True
    common = {"abstract", "introduction", "background", "methods", "methodology",
              "results", "discussion", "conclusion", "limitations", "findings"}
    return s.lower() in common


# ── Source 1 : Semantic Scholar openAccessPdf ─────────────────────────────────

def _try_fetch_pdf(url: str) -> Optional[bytes]:
    if not url:
        return None
    r = _get(url)
    if r and "pdf" in r.headers.get("content-type", "").lower():
        return r.content
    return None


def _best_effort_make_writable(path: str):
    try:
        if os.path.isdir(path):
            os.chmod(path, 0o775)
            for root, dirs, files in os.walk(path):
                for dirname in dirs:
                    try:
                        os.chmod(os.path.join(root, dirname), 0o775)
                    except OSError:
                        pass
                for filename in files:
                    try:
                        os.chmod(os.path.join(root, filename), 0o664)
                    except OSError:
                        pass
        elif os.path.exists(path):
            os.chmod(path, 0o664)
    except OSError:
        pass


def ensure_chroma_storage(path: Optional[str] = None) -> bool:
    storage_dir = path or _CHROMA_DIR_CHAT
    if not chromadb:
        return False

    try:
        os.makedirs(storage_dir, exist_ok=True)
        _best_effort_make_writable(storage_dir)

        probe_path = os.path.join(storage_dir, ".write_probe")
        with open(probe_path, "w", encoding="utf-8") as probe:
            probe.write("ok")
        os.remove(probe_path)
        return True
    except OSError as exc:
        logger.warning("Chroma storage is not writable at %s: %s", storage_dir, exc)
        return False


# ── Source 2 : arXiv PDF ──────────────────────────────────────────────────────

def _arxiv_pdf_url(paper: dict) -> Optional[str]:
    ext = paper.get("externalIds") or {}
    arxiv_id = ext.get("ArXiv") or ext.get("arxiv")
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return None


# ── Source 3 : PubMed Central HTML full-text ──────────────────────────────────

def _fetch_pmc_html(pubmed_id: str) -> Optional[str]:
    """
    Use NCBI's efetch to get the PMC article HTML, then extract body text.
    PubMed ID → first resolve to PMCID via esearch.
    """
    if not pubmed_id:
        return None
    try:
        # Resolve PMID → PMCID
        search_url = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
            f"?dbfrom=pubmed&db=pmc&id={pubmed_id}&retmode=json"
        )
        r = _get(search_url)
        if not r:
            return None
        data = r.json()
        linksets = data.get("linksets", [])
        pmcids = []
        for ls in linksets:
            for ld in ls.get("linksetdbs", []):
                if ld.get("dbto") == "pmc":
                    pmcids.extend(ld.get("links", []))
        if not pmcids:
            return None
        pmcid = pmcids[0]

        # Fetch full-text HTML from PMC
        fetch_url = (
            f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/"
        )
        r = _get(fetch_url)
        if not r:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        # Target the article body
        article = soup.find("div", {"id": "maincontent"}) or \
                  soup.find("article") or \
                  soup.find("div", class_=re.compile(r"article|content", re.I))
        if article:
            text = _clean_html_text(article)
        else:
            text = _clean_html_text(soup)
        if len(text) > 500:
            logger.info("PMC HTML fetch OK for PMID %s (PMCID %s), %d chars",
                        pubmed_id, pmcid, len(text))
            return text
    except Exception as exc:
        logger.warning("PMC HTML fetch failed for PMID %s: %s", pubmed_id, exc)
    return None


# ── Source 4 : Europe PMC (DOI or title search) ───────────────────────────────

def _fetch_europe_pmc(doi: str = "", title: str = "") -> Optional[str]:
    """
    Query Europe PMC for open-access full text.
    Tries DOI first, then title. Returns body text or None.
    """
    query = f"DOI:{doi}" if doi else f'"{title}"'
    try:
        search_url = (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            f"?query={httpx.QueryParams({'query': query})}&format=json&resultType=core&pageSize=1"
        )
        r = _get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                 params={"query": query, "format": "json",
                         "resultType": "core", "pageSize": "1"})
        if not r:
            return None
        results = r.json().get("resultList", {}).get("result", [])
        if not results:
            return None
        hit = results[0]
        pmcid = hit.get("pmcid", "")
        if not pmcid:
            return None
        # Fetch full-text XML / HTML from Europe PMC
        ft_url = (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        )
        r = _get(ft_url)
        if not r:
            return None
        soup = BeautifulSoup(r.text, "xml")
        # Remove back matter (references, acknowledgments)
        for tag in soup.find_all(["ref-list", "ack", "app"]):
            tag.decompose()
        text = re.sub(r"\n{3,}", "\n\n",
                      soup.get_text(separator="\n")).strip()
        if len(text) > 500:
            logger.info("Europe PMC fetch OK (PMCID %s), %d chars", pmcid, len(text))
            return text
    except Exception as exc:
        logger.warning("Europe PMC fetch failed (doi=%s): %s", doi, exc)
    return None


# ── Source 5 : BioMed Central / Springer Open HTML scrape ─────────────────────

def _fetch_biomed_html(doi: str) -> Optional[str]:
    """
    Many BMC/Springer Open journals serve the full article HTML at
    https://doi.org/{doi} after a redirect. We scrape the article body.
    Works for JISSN, BMC Nutrition, etc.
    """
    if not doi:
        return None
    try:
        url = f"https://doi.org/{doi}"
        r = _get(url)
        if not r:
            return None
        ct = r.headers.get("content-type", "")
        if "pdf" in ct.lower():
            return None  # got a PDF redirect, handled elsewhere
        soup = BeautifulSoup(r.text, "html.parser")

        # Springer / BMC article body selectors (in priority order)
        selectors = [
            "div.c-article-body",
            "div.article__body",
            "section[data-title]",
            "div#Sec",
            "div.main-content",
            "article",
            "main",
        ]
        for sel in selectors:
            node = soup.select_one(sel)
            if node:
                text = _clean_html_text(node,
                    selectors_to_remove=[".c-article-references",
                                          ".c-article-further-reading",
                                          ".u-hide-print"])
                if len(text) > 500:
                    logger.info("BioMed/DOI scrape OK for %s, %d chars", doi, len(text))
                    return text
    except Exception as exc:
        logger.warning("BioMed HTML scrape failed for %s: %s", doi, exc)
    return None


# ── Main entry point ───────────────────────────────────────────────────────────

def fetch_full_text(paper: dict) -> tuple[str, str]:
    """
    Cascade through all available sources to get the fullest possible text.
    Returns (text, source_label) where source_label describes what was used.

    Priority:
      1. Semantic Scholar openAccessPdf  → PDF bytes → PyMuPDF
      2. arXiv PDF                       → PDF bytes → PyMuPDF
      3. PMC HTML (via NCBI eutils)      → HTML scrape
      4. Europe PMC full-text XML        → XML scrape
      5. BioMed Central / DOI HTML       → HTML scrape
      6. Abstract only (fallback)
    """
    ext   = paper.get("externalIds") or {}
    doi   = ext.get("DOI", "")
    pmid  = ext.get("PubMed", "")
    title = paper.get("title", "")

    # 1. Semantic Scholar openAccessPdf
    oa  = paper.get("openAccessPdf") or {}
    url = oa.get("url") if isinstance(oa, dict) else None
    if url:
        pdf = _try_fetch_pdf(url)
        if pdf:
            text = extract_text_from_pdf(pdf)
            if len(text) > 200:
                return text, "PDF (Semantic Scholar)"

    # 2. arXiv
    arxiv_url = _arxiv_pdf_url(paper)
    if arxiv_url:
        pdf = _try_fetch_pdf(arxiv_url)
        if pdf:
            text = extract_text_from_pdf(pdf)
            if len(text) > 200:
                return text, "PDF (arXiv)"

    # 3. PMC HTML
    if pmid:
        text = _fetch_pmc_html(pmid)
        if text:
            return text, "Full text (PubMed Central)"

    # 4. Europe PMC
    text = _fetch_europe_pmc(doi=doi, title=title)
    if text:
        return text, "Full text (Europe PMC)"

    # 5. BioMed Central / Springer Open DOI scrape
    if doi:
        text = _fetch_biomed_html(doi)
        if text:
            return text, "Full text (BioMed Central / publisher)"

    # 6. Abstract fallback
    abstract = (paper.get("abstract") or "").strip()
    if abstract:
        return abstract, "Abstract only (full text unavailable)"

    return "", "unavailable"


# ── PDF byte extraction (kept for backward compat) ────────────────────────────

def fetch_pdf_bytes(paper: dict) -> tuple[Optional[bytes], str]:
    """Legacy helper — prefer fetch_full_text() for new code."""
    oa  = paper.get("openAccessPdf") or {}
    url = oa.get("url") if isinstance(oa, dict) else None
    if url:
        pdf = _try_fetch_pdf(url)
        if pdf:
            return pdf, "openAccessPdf"
    arxiv_url = _arxiv_pdf_url(paper)
    if arxiv_url:
        pdf = _try_fetch_pdf(arxiv_url)
        if pdf:
            return pdf, "arXiv"
    return None, "unavailable"


# ── Text extraction ────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    try:
        doc  = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text.strip()
    except Exception as exc:
        logger.error("PDF text extraction failed: %s", exc)
        return ""


def extract_text_pages_from_pdf(pdf_bytes: bytes) -> list[dict]:
    pages: list[dict] = []
    try:
        doc = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
        for page_idx, page in enumerate(doc, start=1):
            text_blocks = []
            for block in sorted(page.get_text("blocks"), key=lambda item: (item[1], item[0])):
                block_text = _normalize_ws(block[4] if len(block) > 4 else "")
                if block_text:
                    text_blocks.append(block_text)
            text = "\n\n".join(text_blocks) if text_blocks else _normalize_ws(page.get_text())
            if text:
                pages.append({
                    "page": page_idx,
                    "section": f"Page {page_idx}",
                    "text": text,
                })
        doc.close()
    except Exception as exc:
        logger.error("PDF page extraction failed: %s", exc)
    return pages


def _split_word_windows(text: str,
                        chunk_words: int = _RAG_CHUNK_WORDS,
                        overlap_words: int = _RAG_CHUNK_OVERLAP) -> list[tuple[str, int, int]]:
    words = text.split()
    if not words:
        return []

    windows: list[tuple[str, int, int]] = []
    step = max(1, chunk_words - overlap_words)

    for start in range(0, len(words), step):
        end = min(len(words), start + chunk_words)
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            windows.append((chunk, start, end))
        if end >= len(words):
            break
    return windows


def _split_sentences(text: str) -> list[str]:
    cleaned = _normalize_ws(text)
    if not cleaned:
        return []
    sentences = re.split(r"(?<=[.!?])\s+(?=(?:[A-Z0-9\"'(]))", cleaned)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def _split_paragraphs(text: str) -> list[str]:
    raw = (text or "").replace("\r\n", "\n")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", raw) if part.strip()]
    if len(paragraphs) > 1:
        return paragraphs

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if lines:
        return lines

    cleaned = _normalize_ws(raw)
    return [cleaned] if cleaned else []


def _split_long_paragraph(text: str, max_words: int) -> list[str]:
    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        return [chunk for chunk, _, _ in _split_word_windows(text, chunk_words=max_words, overlap_words=max(20, max_words // 4))]

    groups: list[str] = []
    current: list[str] = []
    current_words = 0

    for sentence in sentences:
        sentence_words = len(sentence.split())
        if sentence_words > max_words:
            if current:
                groups.append(" ".join(current).strip())
                current = []
                current_words = 0
            groups.extend(
                chunk for chunk, _, _ in _split_word_windows(
                    sentence,
                    chunk_words=max_words,
                    overlap_words=max(20, max_words // 4),
                )
            )
            continue

        if current and current_words + sentence_words > max_words:
            groups.append(" ".join(current).strip())
            current = [sentence]
            current_words = sentence_words
            continue

        current.append(sentence)
        current_words += sentence_words

    if current:
        groups.append(" ".join(current).strip())

    return [group for group in groups if group]


def _semantic_units(text: str, max_words: int) -> list[dict]:
    units: list[dict] = []
    offset = 0

    for paragraph in _split_paragraphs(text):
        cleaned = _normalize_ws(paragraph)
        if not cleaned:
            continue

        parts = [cleaned] if len(cleaned.split()) <= max_words else _split_long_paragraph(cleaned, max_words)
        for part in parts:
            word_count = len(part.split())
            if not word_count:
                continue
            units.append({
                "text": part,
                "word_start": offset,
                "word_end": offset + word_count,
            })
            offset += word_count

    return units


def _merge_units(units: list[dict], target_words: int, overlap_units: int = 0) -> list[tuple[str, int, int]]:
    if not units:
        return []

    merged: list[tuple[str, int, int]] = []
    start_idx = 0

    while start_idx < len(units):
        end_idx = start_idx
        total_words = 0
        chunk_units: list[dict] = []

        while end_idx < len(units):
            unit = units[end_idx]
            unit_words = unit["word_end"] - unit["word_start"]
            if chunk_units and total_words + unit_words > target_words:
                break
            chunk_units.append(unit)
            total_words += unit_words
            end_idx += 1

        if not chunk_units:
            unit = units[start_idx]
            chunk_units = [unit]
            end_idx = start_idx + 1

        merged.append((
            "\n\n".join(unit["text"] for unit in chunk_units),
            chunk_units[0]["word_start"],
            chunk_units[-1]["word_end"],
        ))

        if end_idx >= len(units):
            break

        start_idx = max(start_idx + 1, end_idx - overlap_units)

    return merged


def _split_text_sections(text: str, source: str) -> list[dict]:
    raw_lines = (text or "").splitlines()
    if not raw_lines:
        return []

    default_section = "Abstract" if "abstract" in source.lower() else "Document"
    sections: list[dict] = []
    current_title = default_section
    current_lines: list[str] = []

    for line in raw_lines:
        stripped = line.strip()
        if _is_heading(stripped):
            if current_lines:
                sections.append({
                    "section": current_title,
                    "text": "\n".join(current_lines).strip(),
                })
                current_lines = []
            current_title = stripped.strip(": ")
            continue
        if not stripped:
            if current_lines and current_lines[-1] != "":
                current_lines.append("")
            continue
        current_lines.append(stripped)

    if current_lines:
        sections.append({
            "section": current_title,
            "text": "\n".join(current_lines).strip(),
        })

    return [section for section in sections if section["text"]]


def _build_blocks_for_text(text: str, section: str, locator: str, page: Optional[int]) -> list[dict]:
    units = _semantic_units(text, max_words=_DISPLAY_BLOCK_WORDS)
    if not units:
        return []

    slug = _slugify(locator or section or "document")
    blocks: list[dict] = []
    for idx, (block_text, word_start, word_end) in enumerate(_merge_units(units, target_words=_DISPLAY_BLOCK_WORDS, overlap_units=0)):
        blocks.append({
            "anchor_id": f"anchor-{page or 0}-{slug}-{idx}",
            "section": section or locator or "Document",
            "locator": locator or section or "Document",
            "page": page,
            "word_start": word_start,
            "word_end": word_end,
            "text": block_text,
        })
    return blocks


def build_text_blocks(full_text: str, source: str, pdf_bytes: Optional[bytes] = None) -> list[dict]:
    blocks: list[dict] = []

    if pdf_bytes:
        for page in extract_text_pages_from_pdf(pdf_bytes):
            blocks.extend(_build_blocks_for_text(
                page["text"],
                section=page["section"],
                locator=f"Page {page['page']}",
                page=page["page"],
            ))
    else:
        for section in _split_text_sections(full_text, source):
            blocks.extend(_build_blocks_for_text(
                section["text"],
                section=section["section"],
                locator=section["section"],
                page=None,
            ))

    if not blocks and full_text.strip():
        default_section = "Abstract" if "abstract" in source.lower() else "Document"
        blocks.extend(_build_blocks_for_text(
            full_text,
            section=default_section,
            locator=default_section,
            page=None,
        ))

    return blocks


def classify_question_intent(question: str) -> str:
    q = (question or "").lower().strip()
    if not q:
        return "specific"

    general_triggers = (
        "main idea", "main findings", "main finding", "key findings", "key finding",
        "main takeaway", "takeaway", "takeaways", "summary", "summarize",
        "overall conclusion", "overall message", "big picture", "what is this paper about",
        "what did they find", "what are the findings", "main result", "main results",
    )
    specific_triggers = (
        "how many", "what proportion", "what percentage", "what percent", "what was the p-value",
        "p value", "odds ratio", "hazard ratio", "confidence interval", "sample size",
        "n=", "dose", "dosage", "mg", "hours", "minutes", "days", "weeks",
        "age", "number of participants", "how much", "how often", "threshold",
        "cutoff", "exactly", "statistically significant",
    )

    has_general = any(trigger in q for trigger in general_triggers)
    has_specific = any(trigger in q for trigger in specific_triggers) or bool(re.search(r"\b\d+(?:\.\d+)?\b", q))

    if has_general and has_specific:
        return "hybrid"
    if has_general:
        return "general"
    return "specific"


def _sample_blocks_for_profile(text_blocks: list[dict], max_blocks: int = _PROFILE_CONTEXT_BLOCKS) -> list[dict]:
    if len(text_blocks) <= max_blocks:
        return text_blocks

    preferred_terms = (
        "abstract", "introduction", "background", "methods", "results",
        "discussion", "conclusion", "limitations", "summary",
    )
    selected_indices: list[int] = []

    for term in preferred_terms:
        for idx, block in enumerate(text_blocks):
            locator = (block.get("locator") or block.get("section") or "").lower()
            if term in locator and idx not in selected_indices:
                selected_indices.append(idx)
                break
        if len(selected_indices) >= max_blocks:
            break

    if len(selected_indices) < max_blocks:
        remaining = max_blocks - len(selected_indices)
        if remaining >= len(text_blocks):
            selected_indices.extend(idx for idx in range(len(text_blocks)) if idx not in selected_indices)
        else:
            step = (len(text_blocks) - 1) / max(remaining - 1, 1)
            for i in range(remaining):
                idx = round(i * step)
                if idx not in selected_indices:
                    selected_indices.append(idx)
            if len(selected_indices) < max_blocks:
                for idx in range(len(text_blocks)):
                    if idx not in selected_indices:
                        selected_indices.append(idx)
                    if len(selected_indices) >= max_blocks:
                        break

    selected_indices = sorted(selected_indices[:max_blocks])
    return [text_blocks[idx] for idx in selected_indices]


def build_document_profile_context(text_blocks: list[dict], source: str, max_chars: int = _PROFILE_CONTEXT_CHARS) -> str:
    if not text_blocks:
        return ""

    chosen_blocks = _sample_blocks_for_profile(text_blocks)
    header = f"Content source: {source}\nRepresentative blocks sampled across the full paper:\n"
    parts = [header]

    for block in chosen_blocks:
        locator = block.get("locator") or block.get("section") or "Document"
        excerpt = _normalize_ws(block.get("text") or "")
        if not excerpt:
            continue
        part = f"[{locator}]\n{excerpt}\n"
        if sum(len(piece) for piece in parts) + len(part) > max_chars:
            break
        parts.append(part)

    return "\n".join(parts).strip()


def format_document_profile(profile: Optional[dict]) -> str:
    if not profile:
        return "No document-level overview available."

    lines: list[str] = []
    overview = _normalize_ws(profile.get("overview") or "")
    if overview:
        lines.append(f"Overview: {overview}")

    findings = [item for item in (profile.get("main_findings") or []) if item]
    if findings:
        lines.append("Main findings:")
        lines.extend(f"- {item}" for item in findings[:4])

    methods = _normalize_ws(profile.get("methods_snapshot") or "")
    if methods:
        lines.append(f"Methods snapshot: {methods}")

    limitations = [item for item in (profile.get("limitations") or []) if item]
    if limitations:
        lines.append("Limitations:")
        lines.extend(f"- {item}" for item in limitations[:4])

    section_notes = profile.get("section_notes") or []
    if section_notes:
        lines.append("Section notes:")
        for note in section_notes[:6]:
            section = _normalize_ws(note.get("section") or "")
            summary = _normalize_ws(note.get("note") or "")
            if section and summary:
                lines.append(f"- {section}: {summary}")

    return "\n".join(lines) if lines else "No document-level overview available."


def _anchor_for_chunk(blocks: list[dict], section: str, page: Optional[int], word_start: int) -> Optional[str]:
    for block in blocks:
        if block.get("section") != section:
            continue
        if block.get("page") != page:
            continue
        if block["word_start"] <= word_start < block["word_end"]:
            return block["anchor_id"]
    for block in blocks:
        if block.get("section") == section and block.get("page") == page:
            return block["anchor_id"]
    return None


def build_rag_chunks(full_text: str, source: str, pdf_bytes: Optional[bytes] = None) -> list[dict]:
    chunks: list[dict] = []
    text_blocks = build_text_blocks(full_text, source, pdf_bytes=pdf_bytes)

    if pdf_bytes:
        for page in extract_text_pages_from_pdf(pdf_bytes):
            units = _semantic_units(page["text"], max_words=_RAG_CHUNK_WORDS)
            windows = _merge_units(units, target_words=_RAG_CHUNK_WORDS, overlap_units=1)
            for idx, (chunk_text, word_start, word_end) in enumerate(windows):
                chunks.append({
                    "section": page["section"],
                    "page": page["page"],
                    "word_start": word_start,
                    "word_end": word_end,
                    "text": chunk_text,
                    "locator": f"Page {page['page']}",
                    "chunk_index": idx,
                    "anchor_id": _anchor_for_chunk(text_blocks, page["section"], page["page"], word_start),
                })
    else:
        for section in _split_text_sections(full_text, source):
            units = _semantic_units(section["text"], max_words=_RAG_CHUNK_WORDS)
            windows = _merge_units(units, target_words=_RAG_CHUNK_WORDS, overlap_units=1)
            for idx, (chunk_text, word_start, word_end) in enumerate(windows):
                chunks.append({
                    "section": section["section"],
                    "page": None,
                    "word_start": word_start,
                    "word_end": word_end,
                    "text": chunk_text,
                    "locator": section["section"],
                    "chunk_index": idx,
                    "anchor_id": _anchor_for_chunk(text_blocks, section["section"], None, word_start),
                })

    if not chunks and full_text.strip():
        units = _semantic_units(full_text, max_words=_RAG_CHUNK_WORDS)
        windows = _merge_units(units, target_words=_RAG_CHUNK_WORDS, overlap_units=1)
        for idx, (chunk_text, word_start, word_end) in enumerate(windows):
            chunks.append({
                "section": "Abstract" if "abstract" in source.lower() else "Document",
                "page": None,
                "word_start": word_start,
                "word_end": word_end,
                "text": chunk_text,
                "locator": "Abstract" if "abstract" in source.lower() else "Document",
                "chunk_index": idx,
                "anchor_id": _anchor_for_chunk(
                    text_blocks,
                    "Abstract" if "abstract" in source.lower() else "Document",
                    None,
                    word_start,
                ),
            })

    for idx, chunk in enumerate(chunks):
        page = chunk.get("page") or 0
        locator = chunk.get("locator") or chunk.get("section") or "document"
        slug = re.sub(r"[^a-z0-9]+", "-", locator.lower()).strip("-")[:40] or "document"
        chunk["chunk_id"] = f"chunk-{page}-{slug}-{idx}"

    return chunks


def chroma_vector_enabled() -> bool:
    return bool(chromadb and _EMBEDDING_API_KEY and _EMBEDDING_MODEL)


def _collection_name_for_paper(paper: dict) -> str:
    ext = paper.get("externalIds") or {}
    seed = (
        paper.get("paperId")
        or ext.get("DOI")
        or ext.get("PubMed")
        or paper.get("title")
        or "paper"
    )
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return f"paper_{digest}"


def _get_chroma_collection(paper: dict):
    if not chroma_vector_enabled():
        return None
    if not ensure_chroma_storage(_CHROMA_DIR_CHAT):
        return None

    try:
        client = chromadb.PersistentClient(path=_CHROMA_DIR_CHAT)
        embedding_function = OpenAICompatibleEmbeddingFunction(
            api_key=_EMBEDDING_API_KEY,
            model=_EMBEDDING_MODEL,
            base_url=_EMBEDDING_BASE_URL,
        )
        return client.get_or_create_collection(
            name=_collection_name_for_paper(paper),
            embedding_function=embedding_function,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as exc:
        _set_chroma_error(exc)
        logger.warning("Chroma collection unavailable for paper chat, falling back to lexical retrieval: %s", exc)
        return None


def index_chunks_in_chroma(paper: dict, chunks: list[dict]) -> bool:
    collection = _get_chroma_collection(paper)
    if collection is None or not chunks:
        return False

    try:
        existing_count = collection.count()
        if existing_count > 0:
            logger.info("Chroma collection already populated for %s (%d chunks)", collection.name, existing_count)
            return True
    except Exception as exc:
        _set_chroma_error(exc)
        logger.warning("Could not inspect Chroma collection, falling back to lexical retrieval: %s", exc)
        return False

    ids = [chunk["chunk_id"] for chunk in chunks]
    docs = [chunk["text"] for chunk in chunks]
    metadatas = []
    for chunk in chunks:
        metadatas.append({
            "chunk_id": chunk["chunk_id"],
            "anchor_id": str(chunk.get("anchor_id") or ""),
            "locator": str(chunk.get("locator") or ""),
            "section": str(chunk.get("section") or ""),
            "page": int(chunk["page"]) if chunk.get("page") else -1,
            "word_start": int(chunk.get("word_start") or 0),
            "word_end": int(chunk.get("word_end") or 0),
        })

    try:
        collection.add(ids=ids, documents=docs, metadatas=metadatas)
        logger.info("Indexed %d chunks into Chroma collection %s", len(chunks), collection.name)
        return True
    except Exception as exc:
        _set_chroma_error(exc)
        logger.warning("Could not index chunks into Chroma, falling back to lexical retrieval: %s", exc)
        return False


def query_chroma_sources(paper: dict, question: str, max_sources: int = _MAX_CHUNKS) -> list[dict]:
    collection = _get_chroma_collection(paper)
    if collection is None:
        return []
    try:
        if collection.count() == 0:
            return []
    except Exception as exc:
        _set_chroma_error(exc)
        logger.warning("Could not inspect Chroma before querying, falling back to lexical retrieval: %s", exc)
        return []

    try:
        result = collection.query(
            query_texts=[question],
            n_results=max_sources,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        _set_chroma_error(exc)
        logger.warning("Could not query Chroma, falling back to lexical retrieval: %s", exc)
        return []

    docs = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    selected: list[dict] = []
    for idx, (doc, metadata, distance) in enumerate(zip(docs, metadatas, distances), start=1):
        page = metadata.get("page", -1)
        selected.append({
            "chunk_id": metadata.get("chunk_id"),
            "source_id": f"S{idx}",
            "text": doc,
            "anchor_id": metadata.get("anchor_id") or None,
            "locator": metadata.get("locator") or metadata.get("section") or "Document",
            "section": metadata.get("section") or "Document",
            "page": page if isinstance(page, int) and page > 0 else None,
            "word_start": metadata.get("word_start", 0),
            "word_end": metadata.get("word_end", 0),
            "score": 1.0 - float(distance or 0.0),
        })
    logger.info("Chroma returned %d sources for question: %s", len(selected), question[:120])
    return selected


def _retrieve_relevant_sources_lexical(chunks: list[dict], question: str,
                                       max_sources: int = _MAX_CHUNKS) -> list[dict]:
    if not chunks:
        return []

    profile = _question_profile(question)
    retrieval_query = profile.get("expanded_query") or question
    query_terms = _tokenize(retrieval_query)
    if not query_terms:
        selected = chunks[:max_sources]
        return [
            {**chunk, "source_id": f"S{i + 1}", "score": float(max_sources - i)}
            for i, chunk in enumerate(selected)
        ]

    tokenized_chunks = []
    doc_freq = Counter()
    for chunk in chunks:
        tokens = _tokenize(chunk["text"])
        tokenized_chunks.append(tokens)
        for token in set(tokens):
            doc_freq[token] += 1

    avgdl = sum(len(tokens) for tokens in tokenized_chunks) / max(len(tokenized_chunks), 1)
    k1 = 1.5
    b = 0.75

    query_phrases = [
        phrase.lower() for phrase in re.findall(r'"([^"]+)"', retrieval_query)
        if phrase and len(phrase.split()) >= 2
    ]

    scored: list[tuple[float, dict]] = []
    n_docs = len(chunks)

    for chunk, tokens in zip(chunks, tokenized_chunks):
        tf = Counter(tokens)
        score = 0.0
        dl = max(len(tokens), 1)
        text_lower = chunk["text"].lower()
        locator_lower = (chunk.get("locator") or "").lower()
        section_bonus = _section_weight(locator_lower, profile)

        for term in query_terms:
            freq = tf.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (n_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            denom = freq + k1 * (1 - b + b * dl / max(avgdl, 1))
            score += idf * (freq * (k1 + 1)) / max(denom, 1e-9)

            if term in locator_lower:
                score += 0.8

        for phrase in query_phrases:
            if phrase in text_lower:
                score += 2.5

        if chunk.get("page") == 1:
            score += 0.1

        score += section_bonus

        if score > 0:
            scored.append((score, chunk))

    if not scored:
        scored = [(1.0 / (i + 1), chunk) for i, chunk in enumerate(chunks[:max_sources])]
    else:
        scored.sort(key=lambda item: item[0], reverse=True)

    selected: list[dict] = []
    seen_locators: set[str] = set()

    for score, chunk in scored:
        locator_key = f"{chunk.get('page')}-{chunk.get('section')}"
        if locator_key in seen_locators and len(selected) < max_sources // 2:
            continue
        selected.append({**chunk, "score": score})
        seen_locators.add(locator_key)
        if len(selected) >= max_sources:
            break

    if len(selected) < max_sources:
        seen_texts = {item["text"] for item in selected}
        for score, chunk in scored:
            if chunk["text"] in seen_texts:
                continue
            selected.append({**chunk, "score": score})
            seen_texts.add(chunk["text"])
            if len(selected) >= max_sources:
                break

    return _rank_sources_for_question(selected, question, max_sources=max_sources)


def retrieve_relevant_sources(chunks: list[dict], question: str,
                              max_sources: int = _MAX_CHUNKS,
                              paper: Optional[dict] = None) -> list[dict]:
    profile = _question_profile(question)
    target_sources = max_sources + int(profile.get("extra_sources", 0))
    lexical_sources = _retrieve_relevant_sources_lexical(chunks, question, max_sources=target_sources)

    if not paper or not chroma_vector_enabled():
        return _rank_sources_for_question(lexical_sources, question, max_sources=max_sources)

    try:
        index_chunks_in_chroma(paper, chunks)
        vector_sources = query_chroma_sources(
            paper,
            profile.get("expanded_query") or question,
            max_sources=target_sources,
        )
    except Exception as exc:
        logger.warning("Chroma retrieval failed, falling back to lexical retrieval: %s", exc)
        return _rank_sources_for_question(lexical_sources, question, max_sources=max_sources)

    if not vector_sources:
        return _rank_sources_for_question(lexical_sources, question, max_sources=max_sources)

    merged: list[dict] = []
    seen_ids: set[str] = set()

    for source in vector_sources + lexical_sources:
        chunk_id = source.get("chunk_id")
        if chunk_id and chunk_id in seen_ids:
            continue
        if chunk_id:
            seen_ids.add(chunk_id)
        merged.append(dict(source))
        if len(merged) >= target_sources:
            break
    return _rank_sources_for_question(merged, question, max_sources=max_sources)


def build_rag_system_prompt(
    paper: dict,
    question: str,
    sources: list[dict],
    source: str = "unknown",
    document_profile: Optional[dict] = None,
    strategy: str = "specific",
) -> str:
    ext     = paper.get("externalIds") or {}
    authors = ", ".join(
        a.get("name", "") for a in (paper.get("authors") or [])[:4]
    ) or "Unknown"
    doi = ext.get("DOI", "N/A")

    sources_block = "\n\n".join(
        f"[{src['source_id']}] {src.get('locator') or src.get('section') or 'Document'}\n{src['text']}"
        for src in sources
    ) or "[S1] No source text available."

    strategy_labels = {
        "general": "General conceptual question: use the document-level overview to understand the whole paper, then support the answer with the most relevant retrieved sources.",
        "hybrid": "Hybrid question: combine document-level synthesis with tightly grounded evidence from the retrieved sources.",
        "specific": "Specific factual question: prioritize tightly grounded evidence from the retrieved sources and use the document overview only as secondary context.",
    }

    return _RAG_SYSTEM_PROMPT.format(
        title=paper.get("title", "Unknown"),
        authors=authors,
        year=paper.get("year", "N/A"),
        doi=doi,
        source=source,
        question=question,
        strategy_label=strategy_labels.get(strategy, strategy_labels["specific"]),
        document_overview_block=format_document_profile(document_profile)[:12000],
        sources_block=sources_block[:18000],
    )


def build_sources_payload(sources: list[dict], answer_text: str = "") -> dict:
    used_ids = sorted(set(re.findall(r"S\d+", answer_text or "")), key=lambda sid: int(sid[1:]))
    payload = []
    for src in sources:
        excerpt = src["text"]
        if len(excerpt) > 360:
            excerpt = excerpt[:357].rstrip() + "..."
        payload.append({
            "id": src["source_id"],
            "locator": src.get("locator") or src.get("section") or "Document",
            "section": src.get("section"),
            "page": src.get("page"),
            "anchor_id": src.get("anchor_id"),
            "excerpt": excerpt,
            "score": round(float(src.get("score", 0.0)), 3),
        })

    used = [src for src in payload if src["id"] in used_ids] or payload
    return {"all": payload, "used": used, "used_ids": used_ids}


def clear_chroma_store(path: Optional[str] = None):
    storage_dir = path or _CHROMA_DIR_CHAT
    if chromadb and os.path.isdir(storage_dir):
        shutil.rmtree(storage_dir, ignore_errors=True)
        logger.info("Cleared Chroma store at %s", storage_dir)


def chroma_debug_info(path: Optional[str] = None) -> dict:
    storage_dir = path or _CHROMA_DIR_CHAT
    return {
        "enabled": chroma_vector_enabled(),
        "dir": storage_dir,
        "dir_exists": os.path.isdir(storage_dir),
        "dir_writable": ensure_chroma_storage(storage_dir),
        "last_error": _CHROMA_LAST_ERROR,
    }


# ── Chunk selection ────────────────────────────────────────────────────────────

def _split_chunks(text: str, size: int = _CHUNK_SIZE) -> list[str]:
    words  = text.split()
    chunks = []
    step   = max(1, size // 5)
    for i in range(0, len(words), step):
        chunk = " ".join(words[i:i + size // 5 * 5])
        if chunk.strip():
            chunks.append(chunk.strip())
    return chunks


def select_relevant_chunks(text: str, question: str,
                           max_chunks: int = _MAX_CHUNKS) -> str:
    chunks   = _split_chunks(text)
    if not chunks:
        return text[:_CHUNK_SIZE * max_chunks]

    keywords = set(re.findall(r"\b\w{4,}\b", question.lower()))
    keywords -= {"what", "does", "this", "paper", "study", "that", "with",
                 "from", "have", "been", "they", "about", "which", "there",
                 "their", "these", "when", "where", "also", "would", "could"}

    def score(chunk: str) -> int:
        lower = chunk.lower()
        return sum(1 for kw in keywords if kw in lower)

    scored   = sorted(enumerate(chunks), key=lambda t: score(t[1]), reverse=True)
    selected = [chunks[0]]
    seen     = {0}
    for idx, chunk in scored:
        if len(selected) >= max_chunks:
            break
        if idx not in seen:
            selected.append(chunk)
            seen.add(idx)
    selected_with_idx = sorted(
        [(i, c) for i, c in enumerate(chunks) if c in selected],
        key=lambda t: t[0]
    )
    return "\n\n---\n\n".join(c for _, c in selected_with_idx)


# ── System prompt builder ──────────────────────────────────────────────────────

def build_system_prompt(paper: dict, content: str, source: str = "unknown") -> str:
    ext     = paper.get("externalIds") or {}
    authors = ", ".join(
        a.get("name", "") for a in (paper.get("authors") or [])[:4]
    ) or "Unknown"
    doi = ext.get("DOI", "N/A")
    return _SYSTEM_PROMPT.format(
        title   = paper.get("title", "Unknown"),
        authors = authors,
        year    = paper.get("year", "N/A"),
        doi     = doi,
        source  = source,
        content = content[:12000],
    )
