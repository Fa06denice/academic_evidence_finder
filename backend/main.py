import json
import logging
import os
import base64
import re
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from analyzer import PaperAnalyzer
from scholar_client import SemanticScholarClient
from cache_manager import CacheManager
from paper_index import (
    backfill_paper_index,
    clear_paper_index_store,
    index_papers,
    paper_index_stats,
    search_local_papers,
)
from verify_graph import (
    langgraph_verify_available,
    stream_literature_review_graph,
    stream_verify_claim_graph,
    workflow_graphs,
)
from paper_chat import (
    chroma_debug_info,
    classify_question_intent,
    fetch_full_text,
    fetch_pdf_bytes,
    build_text_blocks,
    build_rag_chunks,
    build_document_profile_context,
    build_rag_system_prompt,
    build_sources_payload,
    clear_chroma_store,
    retrieve_relevant_sources,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Academic Evidence Finder API", version="1.0.0")


def _cors_allow_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=4)

def _get_clients():
    provider  = os.getenv("LLM_PROVIDER", "groq").lower()
    api_key   = os.getenv("LLM_API_KEY", "")
    ss_key    = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    extra     = [os.getenv(f"LLM_API_KEY_{i}", "")
                 for i in range(2, 10) if os.getenv(f"LLM_API_KEY_{i}")]
    scholar   = SemanticScholarClient(api_key=ss_key or None)
    analyzer  = PaperAnalyzer(api_key=api_key, provider=provider, extra_keys=extra)
    cache     = CacheManager()
    backfill_paper_index(cache)
    return scholar, analyzer, cache

scholar, analyzer, cache = _get_clients()

_text_cache: dict[str, tuple[str, str]] = {}
_text_blocks_cache: dict[str, tuple[list[dict], str]] = {}
_rag_cache: dict[str, tuple[list[dict], str]] = {}
_paper_profile_cache: dict[str, dict] = {}

# ── Cache helpers ─────────────────────────────────────────────────────────────────
def _cache_get_summary(pid: str) -> Optional[str]:
    try:
        if hasattr(cache, 'get_summary'):
            return cache.get_summary(pid)
        entry = cache.cache.get(f"summary_{pid}")
        return entry.get("data") if isinstance(entry, dict) else None
    except Exception:
        return None

def _cache_set_summary(pid: str, summary: str):
    try:
        if hasattr(cache, 'set_summary'):
            cache.set_summary(pid, summary)
        else:
            from datetime import datetime
            cache.cache[f"summary_{pid}"] = {"data": summary, "ts": datetime.now().isoformat()}
            cache._save()
    except Exception:
        pass


def _cache_get_paper_profile(paper_key: str) -> Optional[dict]:
    try:
        if hasattr(cache, "get_paper_profile"):
            return cache.get_paper_profile(paper_key)
        return cache.cache.get("paper_profiles", {}).get(paper_key)
    except Exception:
        return None


def _cache_set_paper_profile(paper_key: str, profile: dict):
    try:
        if hasattr(cache, "set_paper_profile"):
            cache.set_paper_profile(paper_key, profile)
        else:
            if "paper_profiles" not in cache.cache:
                cache.cache["paper_profiles"] = {}
            cache.cache["paper_profiles"][paper_key] = profile
            cache._save()
    except Exception:
        pass

# ── Helpers ──────────────────────────────────────────────────────────────────────
def _sse(event_type: str, data: dict) -> str:
    payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def _run_with_heartbeat(
    fn,
    *args,
    message: str,
    step: Optional[int] = None,
    total: Optional[int] = None,
    interval: float = 8.0,
    **kwargs,
):
    future = executor.submit(fn, *args, **kwargs)
    while True:
        try:
            yield {"kind": "result", "value": future.result(timeout=interval)}
            return
        except FutureTimeoutError:
            payload = {"message": message}
            if step is not None:
                payload["step"] = step
            if total is not None:
                payload["total"] = total
            yield {"kind": "heartbeat", "value": payload}


def _paper_cache_key(paper: dict) -> str:
    ext = paper.get("externalIds") or {}
    return (
        paper.get("paperId")
        or ext.get("DOI")
        or ext.get("PubMed")
        or paper.get("title")
        or ""
    ).strip().lower()


def _normalize_title(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _prioritize_exact_title_matches(papers: list, title: str) -> list:
    if not title:
        return papers

    wanted = _normalize_title(title)
    if not wanted:
        return papers

    def rank(paper: dict):
        actual = _normalize_title(paper.get("title", ""))
        exact = 1 if actual == wanted else 0
        contains = 1 if wanted and wanted in actual else 0
        return (exact, contains, paper.get("citationCount") or 0)

    return sorted(papers, key=rank, reverse=True)

def _fetch_papers(
    queries: list,
    max_papers: int,
    year: Optional[str],
    exclude_ids: Optional[set] = None,
) -> tuple[list, Optional[str]]:
    per_query = max(max_papers, 15)
    local_per_query = min(per_query, max(2, min(max_papers, 4)))
    seen      = set(exclude_ids or [])
    papers    = []
    search_errors: list[str] = []

    for q in queries:
        local_batch = search_local_papers(
            q,
            limit=local_per_query,
            year_filter=year,
            exclude_ids=seen,
            cache_manager=cache,
        )
        for p in local_batch:
            pid = p.get("paperId", "")
            if pid and pid not in seen:
                seen.add(pid)
                papers.append(p)

    for q in queries:
        cached = cache.get_search(q, year)
        batch  = cached if cached else scholar.search(q, limit=per_query, year=year or None)
        if batch:
            index_papers(batch, cache_manager=cache)
        if not cached and batch:
            cache.set_search(q, batch, year)
        if not cached and not batch and getattr(scholar, "last_error", None):
            search_errors.append(scholar.last_error)
        for p in batch:
            pid = p.get("paperId", "")
            if pid and pid not in seen:
                seen.add(pid)
                papers.append(p)
    papers = sorted(papers, key=lambda p: p.get("citationCount") or 0, reverse=True)
    error = search_errors[0] if search_errors and not papers else None
    return papers[:max_papers], error


_RETRY_SUFFIXES = [
    ["systematic review", "meta-analysis"],
    ["randomized controlled trial", "cohort study"],
]

def _enrich_queries(base_queries: list, round_idx: int) -> list:
    suffixes = _RETRY_SUFFIXES[round_idx % len(_RETRY_SUFFIXES)]
    return [f"{q} {sfx}" for q in base_queries for sfx in suffixes]


# ── Request models ────────────────────────────────────────────────────────────────
class ClaimRequest(BaseModel):
    claim: str
    max_papers: int = 7
    year_filter: Optional[str] = None

class TopicRequest(BaseModel):
    topic: str
    max_papers: int = 7
    year_filter: Optional[str] = None
    exact_title: bool = False

class ClaimReviewRequest(BaseModel):
    claim: str
    items: list = []

class SummarizeRequest(BaseModel):
    paper: dict

class FetchPaperRequest(BaseModel):
    paper: dict

class ChatRequest(BaseModel):
    paper: dict
    question: str
    history: list = []

# ── Routes ─────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    stats = cache.stats()
    return {
        "status": "ok",
        "model": analyzer.current_model,
        "cache": stats,
        "paper_index": paper_index_stats(),
        "chroma": chroma_debug_info(),
    }


@app.get("/api/graphs")
def graphs():
    return workflow_graphs()


@app.post("/api/verify")
def verify_claim(req: ClaimRequest):
    def legacy_generate():
        try:
            early = analyzer.validate_claim(req.claim)
            if early:
                yield _sse("verdict", {"data": early})
                yield _sse("done", {})
                return

            yield _sse("progress", {"message": "Generating search queries…", "step": 1, "total": 4})
            base_queries = None
            for update in _run_with_heartbeat(
                analyzer.transform_query,
                req.claim,
                topic_mode=False,
                max_papers=req.max_papers,
                message="Generating search queries…",
                step=1,
                total=4,
            ):
                if update["kind"] == "heartbeat":
                    yield _sse("progress", update["value"])
                else:
                    base_queries = update["value"]

            yield _sse("progress", {"message": "Searching literature…", "step": 2, "total": 4})
            papers = None
            search_error = None
            for update in _run_with_heartbeat(
                _fetch_papers,
                base_queries,
                req.max_papers,
                req.year_filter,
                message="Searching literature…",
                step=2,
                total=4,
            ):
                if update["kind"] == "heartbeat":
                    yield _sse("progress", update["value"])
                else:
                    papers, search_error = update["value"]

            if not papers:
                yield _sse("error", {"message": search_error or "No papers found. Try rephrasing."})
                yield _sse("done", {})
                return

            yield _sse("papers", {"data": papers})
            yield _sse("progress", {"message": f"Analysing {len(papers)} papers…", "step": 3, "total": 4})

            all_results: list[tuple] = []
            seen_ids: set = {p.get("paperId", "") for p in papers}

            for i, paper in enumerate(papers):
                pid      = paper.get("paperId", "")
                cached   = cache.get_analysis(pid, req.claim)
                analysis = cached
                if not analysis:
                    for update in _run_with_heartbeat(
                        analyzer.analyze_paper,
                        paper,
                        req.claim,
                        message=f"Analysing paper {i + 1} / {len(papers)}…",
                        step=3,
                        total=4,
                    ):
                        if update["kind"] == "heartbeat":
                            yield _sse("progress", update["value"])
                        else:
                            analysis = update["value"]
                if not cached and pid:
                    cache.set_analysis(pid, req.claim, analysis)
                yield _sse("analysis", {
                    "index": i, "total": len(papers),
                    "paper_id": pid, "paper": paper, "analysis": analysis,
                })
                all_results.append((paper, analysis))

            MIN_SCORE   = 3
            MAX_RETRIES = 1
            relevant    = [(p, a) for p, a in all_results if a.get("relevance_score", 0) >= MIN_SCORE]

            retry_round = 0
            while len(relevant) < req.max_papers and retry_round < MAX_RETRIES:
                retry_round += 1

                # How many more relevant papers do we still need?
                missing = req.max_papers - len(relevant)

                yield _sse("progress", {
                    "message": f"Only {len(relevant)} relevant papers found — searching deeper…",
                    "step": 3, "total": 4,
                })

                extra_papers, extra_error = _fetch_papers(
                    _enrich_queries(base_queries, retry_round - 1),
                    missing,           # fetch only what is still needed
                    req.year_filter,
                    exclude_ids=seen_ids,
                )
                if not extra_papers:
                    if extra_error:
                        yield _sse("warning", {"message": extra_error})
                    break

                # Freeze index base + total BEFORE the loop so they stay stable
                retry_base  = len(all_results)
                retry_total = retry_base + len(extra_papers)

                for j, paper in enumerate(extra_papers):
                    pid    = paper.get("paperId", "")
                    seen_ids.add(pid)
                    cached   = cache.get_analysis(pid, req.claim)
                    analysis = cached
                    if not analysis:
                        for update in _run_with_heartbeat(
                            analyzer.analyze_paper,
                            paper,
                            req.claim,
                            message=f"Analysing paper {retry_base + j + 1} / {retry_total}…",
                            step=3,
                            total=4,
                        ):
                            if update["kind"] == "heartbeat":
                                yield _sse("progress", update["value"])
                            else:
                                analysis = update["value"]
                    if not cached and pid:
                        cache.set_analysis(pid, req.claim, analysis)
                    yield _sse("analysis", {
                        "index":    retry_base + j,
                        "total":    retry_total,
                        "paper_id": pid,
                        "paper":    paper,
                        "analysis": analysis,
                    })
                    all_results.append((paper, analysis))
                    if analysis.get("relevance_score", 0) >= MIN_SCORE:
                        relevant.append((paper, analysis))

            if len(relevant) < req.max_papers:
                yield _sse("warning", {
                    "message": (
                        f"Only {len(relevant)} of the {req.max_papers} requested papers had sufficient "
                        "relevance to the claim after an additional search round. "
                        "The verdict is based on available evidence — consider rephrasing the claim "
                        "or broadening the search for more comprehensive results."
                    )
                })

            yield _sse("progress", {"message": "Synthesizing verdict…", "step": 4, "total": 4})
            overall = None
            for update in _run_with_heartbeat(
                analyzer.overall_verdict,
                req.claim,
                all_results,
                message="Synthesizing verdict…",
                step=4,
                total=4,
            ):
                if update["kind"] == "heartbeat":
                    yield _sse("progress", update["value"])
                else:
                    overall = update["value"]
            yield _sse("verdict", {"data": overall})
            yield _sse("done", {})

        except Exception as exc:
            logger.exception("verify_claim error")
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})

    def graph_generate():
        try:
            logger.info("verify_claim using LangGraph workflow")
            early = analyzer.validate_claim(req.claim)
            if early:
                yield _sse("verdict", {"data": early})
                yield _sse("done", {})
                return

            for chunk in stream_verify_claim_graph(
                claim=req.claim,
                max_papers=req.max_papers,
                year_filter=req.year_filter,
                analyzer=analyzer,
                cache=cache,
                fetch_papers=_fetch_papers,
                enrich_queries=_enrich_queries,
                run_with_heartbeat=_run_with_heartbeat,
            ):
                event_type = chunk.get("type")
                if not event_type:
                    continue
                payload = {k: v for k, v in chunk.items() if k != "type"}
                yield _sse(event_type, payload)

            yield _sse("done", {})
        except Exception as exc:
            logger.exception("verify_claim graph error")
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})

    if not langgraph_verify_available():
        logger.warning("LangGraph unavailable; /api/verify is using the legacy workflow")
    generator = graph_generate if langgraph_verify_available() else legacy_generate
    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/review")
def literature_review(req: TopicRequest):
    def legacy_generate():
        try:
            yield _sse("progress", {"message": "Generating search queries…", "step": 1, "total": 3})
            base_queries = None
            for update in _run_with_heartbeat(
                analyzer.transform_query,
                req.topic,
                topic_mode=True,
                max_papers=req.max_papers,
                message="Generating search queries…",
                step=1,
                total=3,
            ):
                if update["kind"] == "heartbeat":
                    yield _sse("progress", update["value"])
                else:
                    base_queries = update["value"]

            yield _sse("progress", {"message": "Searching literature…", "step": 2, "total": 3})
            papers = None
            search_error = None
            for update in _run_with_heartbeat(
                _fetch_papers,
                base_queries,
                req.max_papers,
                req.year_filter,
                message="Searching literature…",
                step=2,
                total=3,
            ):
                if update["kind"] == "heartbeat":
                    yield _sse("progress", update["value"])
                else:
                    papers, search_error = update["value"]

            if not papers:
                yield _sse("error", {"message": search_error or "No papers found. Try rephrasing."})
                yield _sse("done", {})
                return

            yield _sse("papers", {"data": papers})
            all_results: list[tuple] = []
            seen_ids: set = {p.get("paperId", "") for p in papers}

            for i, paper in enumerate(papers):
                pid      = paper.get("paperId", "")
                cached   = cache.get_analysis(pid, req.topic)
                analysis = cached
                if not analysis:
                    for update in _run_with_heartbeat(
                        analyzer.analyze_paper,
                        paper,
                        req.topic,
                        message=f"Analysing paper {i + 1} / {len(papers)}…",
                        step=2,
                        total=3,
                    ):
                        if update["kind"] == "heartbeat":
                            yield _sse("progress", update["value"])
                        else:
                            analysis = update["value"]
                if not cached and pid:
                    cache.set_analysis(pid, req.topic, analysis)
                yield _sse("analysis", {
                    "index": i, "total": len(papers),
                    "paper_id": pid, "paper": paper, "analysis": analysis,
                })
                all_results.append((paper, analysis))

            MIN_SCORE   = 3
            MAX_RETRIES = 1
            relevant    = [(p, a) for p, a in all_results if a.get("relevance_score", 0) >= MIN_SCORE]
            retry_round = 0

            while len(relevant) < req.max_papers and retry_round < MAX_RETRIES:
                retry_round += 1
                missing = req.max_papers - len(relevant)

                yield _sse("progress", {
                    "message": f"Only {len(relevant)} relevant papers — searching deeper…",
                    "step": 2, "total": 3,
                })
                extra_papers, extra_error = _fetch_papers(
                    _enrich_queries(base_queries, retry_round - 1),
                    missing,
                    req.year_filter,
                    exclude_ids=seen_ids,
                )
                if not extra_papers:
                    if extra_error:
                        yield _sse("warning", {"message": extra_error})
                    break

                retry_base  = len(all_results)
                retry_total = retry_base + len(extra_papers)

                for j, paper in enumerate(extra_papers):
                    pid = paper.get("paperId", "")
                    seen_ids.add(pid)
                    cached   = cache.get_analysis(pid, req.topic)
                    analysis = cached
                    if not analysis:
                        for update in _run_with_heartbeat(
                            analyzer.analyze_paper,
                            paper,
                            req.topic,
                            message=f"Analysing paper {retry_base + j + 1} / {retry_total}…",
                            step=2,
                            total=3,
                        ):
                            if update["kind"] == "heartbeat":
                                yield _sse("progress", update["value"])
                            else:
                                analysis = update["value"]
                    if not cached and pid:
                        cache.set_analysis(pid, req.topic, analysis)
                    yield _sse("analysis", {
                        "index":    retry_base + j,
                        "total":    retry_total,
                        "paper_id": pid,
                        "paper":    paper,
                        "analysis": analysis,
                    })
                    all_results.append((paper, analysis))
                    if analysis.get("relevance_score", 0) >= MIN_SCORE:
                        relevant.append((paper, analysis))

            if len(relevant) < req.max_papers:
                yield _sse("warning", {
                    "message": (
                        f"Only {len(relevant)} of the {req.max_papers} requested papers were sufficiently "
                        "relevant to the topic after an additional search round."
                    )
                })

            yield _sse("progress", {"message": "Writing literature review…", "step": 3, "total": 3})
            review = None
            for update in _run_with_heartbeat(
                analyzer.literature_review,
                req.topic,
                all_results,
                message="Writing literature review…",
                step=3,
                total=3,
            ):
                if update["kind"] == "heartbeat":
                    yield _sse("progress", update["value"])
                else:
                    review = update["value"]
            yield _sse("review", {"data": review})
            yield _sse("done", {})

        except Exception as exc:
            logger.exception("literature_review error")
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})

    def graph_generate():
        try:
            logger.info("literature_review using LangGraph workflow")
            for chunk in stream_literature_review_graph(
                topic=req.topic,
                max_papers=req.max_papers,
                year_filter=req.year_filter,
                analyzer=analyzer,
                cache=cache,
                fetch_papers=_fetch_papers,
                enrich_queries=_enrich_queries,
                run_with_heartbeat=_run_with_heartbeat,
            ):
                event_type = chunk.get("type")
                if not event_type:
                    continue
                payload = {k: v for k, v in chunk.items() if k != "type"}
                yield _sse(event_type, payload)

            yield _sse("done", {})
        except Exception as exc:
            logger.exception("literature_review graph error")
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})

    if not langgraph_verify_available():
        logger.warning("LangGraph unavailable; /api/review is using the legacy workflow")
    generator = graph_generate if langgraph_verify_available() else legacy_generate
    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/verify/review")
async def review_from_claim_results(req: ClaimReviewRequest):
    try:
        selected_results: list[tuple[dict, dict]] = []
        for item in req.items:
            if not isinstance(item, dict):
                continue
            paper = item.get("paper")
            analysis = item.get("analysis")
            if isinstance(paper, dict) and isinstance(analysis, dict):
                selected_results.append((paper, analysis))

        if not selected_results:
            return JSONResponse(
                status_code=400,
                content={"error": "Select at least one analysed paper to generate a literature review."},
            )

        review = analyzer.literature_review(req.claim, selected_results)
        assessment = analyzer.review_relevance(req.claim, review, selected_results)
        return {"review": review, "assessment": assessment}

    except Exception as exc:
        logger.exception("review_from_claim_results error")
        return JSONResponse(
            status_code=500,
            content={"error": f"Literature review generation failed: {exc}"},
        )


@app.post("/api/search")
def search_papers(req: TopicRequest):
    def generate():
        try:
            yield _sse("progress", {"message": "Generating search queries…"})
            queries = None
            for update in _run_with_heartbeat(
                analyzer.transform_query,
                req.topic,
                topic_mode=True,
                max_papers=req.max_papers,
                message="Generating search queries…",
            ):
                if update["kind"] == "heartbeat":
                    yield _sse("progress", update["value"])
                else:
                    queries = update["value"]
            if req.exact_title and req.topic.strip():
                exact_queries = [f"\"{req.topic.strip()}\"", req.topic.strip()]
                deduped = []
                seen_queries = set()
                for q in exact_queries + (queries or []):
                    key = q.strip().lower()
                    if not key or key in seen_queries:
                        continue
                    seen_queries.add(key)
                    deduped.append(q)
                queries = deduped
            yield _sse("progress", {"message": "Searching…"})
            papers = None
            search_error = None
            for update in _run_with_heartbeat(
                _fetch_papers,
                queries,
                req.max_papers,
                req.year_filter,
                message="Searching…",
            ):
                if update["kind"] == "heartbeat":
                    yield _sse("progress", update["value"])
                else:
                    papers, search_error = update["value"]
            if not papers:
                yield _sse("error", {"message": search_error or "No papers found. Try rephrasing."})
                yield _sse("done", {})
                return
            if req.exact_title:
                papers = _prioritize_exact_title_matches(papers, req.topic)
            yield _sse("papers", {"data": papers})
            yield _sse("done", {})
        except Exception as exc:
            logger.exception("search_papers error")
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})
    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/summarize")
async def summarize_paper(req: SummarizeRequest):
    try:
        paper   = req.paper
        pid     = paper.get("paperId", "")
        cached  = _cache_get_summary(pid) if pid else None
        if cached:
            return {"summary": cached}
        summary = analyzer.summarize(paper)
        if pid:
            _cache_set_summary(pid, summary)
        return {"summary": summary}
    except Exception as exc:
        logger.exception("summarize_paper error")
        return JSONResponse(status_code=200, content={"summary": f"Summarization temporarily unavailable: {exc}"})


@app.post("/api/paper/fetch")
async def fetch_paper(req: FetchPaperRequest):
    paper = req.paper
    pid   = paper.get("paperId", "")
    cache_key = _paper_cache_key(paper)
    index_papers([paper], cache_manager=cache)

    if pid and pid in _text_cache:
        text, source = _text_cache[pid]
        text_blocks = _text_blocks_cache.get(cache_key or pid, ([], source))[0]
        return {
            "available": source != "unavailable",
            "source":    source,
            "pdf_b64":   None,
            "text_preview": text[:500],
            "text_blocks": text_blocks,
            "pid": pid,
        }

    text, source = fetch_full_text(paper)
    if pid and text:
        _text_cache[pid] = (text, source)

    pdf_b64 = None
    pdf_bytes = None
    if "PDF" in source:
        try:
            pdf_bytes, _ = fetch_pdf_bytes(paper)
            if pdf_bytes:
                pdf_b64 = base64.b64encode(pdf_bytes).decode()
        except Exception:
            pass

    text_blocks = build_text_blocks(text, source, pdf_bytes=pdf_bytes) if text else []
    if (cache_key or pid) and text_blocks:
        _text_blocks_cache[cache_key or pid] = (text_blocks, source)

    return {
        "available": bool(text) and source != "unavailable",
        "source":    source,
        "pdf_b64":   pdf_b64,
        "text_preview": text[:500] if text else "",
        "text_blocks": text_blocks,
        "pid": pid,
    }


@app.post("/api/paper/chat")
def paper_chat(req: ChatRequest):
    def generate():
        try:
            paper    = req.paper
            pid      = paper.get("paperId", "")
            question = req.question.strip()
            cache_key = _paper_cache_key(paper)
            strategy = classify_question_intent(question)

            if pid and pid in _text_cache:
                full_text, source = _text_cache[pid]
            else:
                full_text, source = fetch_full_text(paper)
                if pid and full_text:
                    _text_cache[pid] = (full_text, source)

            if not full_text:
                full_text = paper.get("abstract") or ""
                source    = "Abstract only (full text unavailable)"

            pdf_bytes = None
            if "PDF" in source:
                try:
                    pdf_bytes, _ = fetch_pdf_bytes(paper)
                except Exception:
                    logger.warning("paper_chat could not refetch PDF bytes for %s", cache_key or pid)

            if cache_key and cache_key in _text_blocks_cache:
                text_blocks, cached_source = _text_blocks_cache[cache_key]
                source = cached_source or source
            else:
                text_blocks = build_text_blocks(full_text, source, pdf_bytes=pdf_bytes) if full_text else []
                if cache_key and text_blocks:
                    _text_blocks_cache[cache_key] = (text_blocks, source)

            if cache_key and cache_key in _rag_cache:
                rag_chunks, cached_source = _rag_cache[cache_key]
                source = cached_source or source
            else:
                rag_chunks = build_rag_chunks(full_text, source, pdf_bytes=pdf_bytes)
                if cache_key and rag_chunks:
                    _rag_cache[cache_key] = (rag_chunks, source)

            document_profile = None
            profile_key = cache_key or pid
            if strategy in {"general", "hybrid"} and profile_key:
                if profile_key in _paper_profile_cache:
                    document_profile = _paper_profile_cache[profile_key]
                else:
                    cached_profile = _cache_get_paper_profile(profile_key)
                    if cached_profile:
                        document_profile = cached_profile
                        _paper_profile_cache[profile_key] = cached_profile
                    else:
                        profile_context = build_document_profile_context(text_blocks, source)
                        if profile_context:
                            document_profile = analyzer.paper_profile(paper, profile_context, source)
                            if document_profile:
                                _paper_profile_cache[profile_key] = document_profile
                                _cache_set_paper_profile(profile_key, document_profile)

            selected_sources = []
            if rag_chunks:
                source_limit = 8 if strategy in {"general", "hybrid"} else 6
                selected_sources = retrieve_relevant_sources(
                    rag_chunks,
                    question,
                    paper=paper,
                    max_sources=source_limit,
                )

            sys_prompt = build_rag_system_prompt(
                paper,
                question,
                selected_sources,
                source=source,
                document_profile=document_profile,
                strategy=strategy,
            )

            messages = [{"role": "system", "content": sys_prompt}]
            for turn in req.history[-6:]:
                role = turn.get("role", "user")
                if role in ("user", "assistant") and turn.get("content"):
                    messages.append({"role": role, "content": turn["content"]})
            messages.append({"role": "user", "content": question})

            stream = analyzer.stream_chat(
                messages=messages,
                temperature=0.1,
                max_tokens=800,
            )
            answer_text = ""
            for chunk in stream:
                token = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if token:
                    answer_text += token
                    yield _sse("token", {"text": token})
            yield _sse("sources", {"data": build_sources_payload(selected_sources, answer_text)})
            yield _sse("done", {})

        except Exception as exc:
            logger.exception("paper_chat error")
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.delete("/api/cache")
def clear_cache():
    cache.clear()
    _text_cache.clear()
    _text_blocks_cache.clear()
    _rag_cache.clear()
    _paper_profile_cache.clear()
    clear_chroma_store()
    clear_paper_index_store()
    return {"status": "cleared"}
