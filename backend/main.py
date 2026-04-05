import json
import logging
import os
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from analyzer import PaperAnalyzer
from scholar_client import SemanticScholarClient
from cache_manager import CacheManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Academic Evidence Finder API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=4)

# ── Clients (singleton) ────────────────────────────────────────────────────────
def _get_clients():
    provider  = os.getenv("LLM_PROVIDER", "groq").lower()
    api_key   = os.getenv("LLM_API_KEY", "")
    ss_key    = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    extra     = [os.getenv(f"LLM_API_KEY_{i}", "")
                 for i in range(2, 10) if os.getenv(f"LLM_API_KEY_{i}")]
    scholar   = SemanticScholarClient(api_key=ss_key or None)
    analyzer  = PaperAnalyzer(api_key=api_key, provider=provider, extra_keys=extra)
    cache     = CacheManager()
    return scholar, analyzer, cache

scholar, analyzer, cache = _get_clients()

# ── Helpers ────────────────────────────────────────────────────────────────────
def _sse(event_type: str, data: dict) -> str:
    payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
    return f"data: {payload}\n\n"

def _fetch_papers(queries: list, max_papers: int, year: Optional[str]) -> list:
    seen, papers = set(), []
    for q in queries:
        cached = cache.get_search(q)
        batch  = cached if cached else scholar.search(q, limit=max_papers, year=year or None)
        if not cached and batch:
            cache.set_search(q, batch)
        for p in batch:
            pid = p.get("paperId", "")
            if pid and pid not in seen:
                seen.add(pid)
                papers.append(p)
    papers = sorted(papers, key=lambda p: p.get("citationCount") or 0, reverse=True)
    return papers[:max_papers]

# ── Request models ─────────────────────────────────────────────────────────────
class ClaimRequest(BaseModel):
    claim: str
    max_papers: int = 7
    year_filter: Optional[str] = None

class TopicRequest(BaseModel):
    topic: str
    max_papers: int = 7
    year_filter: Optional[str] = None

class SummarizeRequest(BaseModel):
    paper: dict
    paper: dict

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    stats = cache.stats()
    return {"status": "ok", "model": analyzer.current_model, "cache": stats}


@app.post("/api/verify")
def verify_claim(req: ClaimRequest):
    """
    SSE stream: verify a scientific claim against the literature.
    Events: progress | papers | analysis | verdict | done | error
    """
    def generate():
        try:
            # 1. Validate
            early = analyzer.validate_claim(req.claim)
            if early:
                yield _sse("verdict", {"data": early})
                yield _sse("done", {})
                return

            # 2. Transform query
            yield _sse("progress", {"message": "Generating search queries…", "step": 1, "total": 4})
            queries = analyzer.transform_query(req.claim)

            # 3. Fetch papers
            yield _sse("progress", {"message": "Searching literature…", "step": 2, "total": 4})
            papers = _fetch_papers(queries, req.max_papers, req.year_filter)
            if not papers:
                yield _sse("error", {"message": "No papers found. Try rephrasing."})
                yield _sse("done", {})
                return
            yield _sse("papers", {"data": papers})

            # 4. Analyse each paper
            yield _sse("progress", {"message": f"Analysing {len(papers)} papers…", "step": 3, "total": 4})
            results, low_rel = [], []
            for i, paper in enumerate(papers):
                pid     = paper.get("paperId", "")
                cached  = cache.get_analysis(pid, req.claim)
                analysis = cached if cached else analyzer.analyze_paper(paper, req.claim)
                if not cached and pid:
                    cache.set_analysis(pid, req.claim, analysis)
                yield _sse("analysis", {
                    "index": i, "total": len(papers),
                    "paper_id": pid,
                    "analysis": analysis,
                })
                if analysis.get("relevance_score", 0) >= 5:
                    results.append((paper, analysis))
                else:
                    low_rel.append((paper, analysis))

            # 5. Overall verdict
            yield _sse("progress", {"message": "Synthesizing verdict…", "step": 4, "total": 4})
            overall = analyzer.overall_verdict(req.claim, results)
            yield _sse("verdict", {"data": overall})
            yield _sse("done", {})

        except Exception as exc:
            logger.exception("verify_claim error")
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/review")
def literature_review(req: TopicRequest):
    """
    SSE stream: generate a structured literature review on a topic.
    Events: progress | papers | analysis | review | done | error
    """
    def generate():
        try:
            yield _sse("progress", {"message": "Generating search queries…", "step": 1, "total": 3})
            queries = analyzer.transform_query(req.topic)

            yield _sse("progress", {"message": "Searching literature…", "step": 2, "total": 3})
            papers = _fetch_papers(queries, req.max_papers, req.year_filter)
            if not papers:
                yield _sse("error", {"message": "No papers found. Try rephrasing."})
                yield _sse("done", {})
                return
            yield _sse("papers", {"data": papers})

            results = []
            for i, paper in enumerate(papers):
                pid      = paper.get("paperId", "")
                cached   = cache.get_analysis(pid, req.topic)
                analysis = cached if cached else analyzer.analyze_paper(paper, req.topic)
                if not cached and pid:
                    cache.set_analysis(pid, req.topic, analysis)
                yield _sse("analysis", {
                    "index": i, "total": len(papers),
                    "paper_id": pid, "analysis": analysis,
                })
                results.append((paper, analysis))

            yield _sse("progress", {"message": "Writing literature review…", "step": 3, "total": 3})
            review = analyzer.literature_review(req.topic, results)
            yield _sse("review", {"data": review})
            yield _sse("done", {})

        except Exception as exc:
            logger.exception("literature_review error")
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/search")
def search_papers(req: TopicRequest):
    """
    SSE stream: search papers by topic (for the summarizer view).
    Events: progress | papers | done | error
    """
    def generate():
        try:
            yield _sse("progress", {"message": "Generating search queries…"})
            queries = analyzer.transform_query(req.topic)

            yield _sse("progress", {"message": "Searching…"})
            papers = _fetch_papers(queries, req.max_papers, req.year_filter)
            if not papers:
                yield _sse("error", {"message": "No papers found. Try rephrasing."})
                yield _sse("done", {})
                return
            yield _sse("papers", {"data": papers})
            yield _sse("done", {})

        except Exception as exc:
            logger.exception("search_papers error")
            yield _sse("error", {"message": str(exc)})
            yield _sse("done", {})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/summarize")
def summarize_paper(req: SummarizeRequest):
    """Summarize a single paper (non-streaming, fast)."""
    paper  = req.paper
    pid    = paper.get("paperId", "")
    cached = cache.get_summary(pid) if pid else None
    if cached:
        return {"summary": cached}
    summary = analyzer.summarize(paper)
    if pid:
        cache.set_summary(pid, summary)
    return {"summary": summary}


@app.delete("/api/cache")
def clear_cache():
    cache.clear()
    return {"status": "cleared"}
