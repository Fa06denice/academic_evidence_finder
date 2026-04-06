import json
import logging
import os
import base64
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from analyzer import PaperAnalyzer
from scholar_client import SemanticScholarClient
from cache_manager import CacheManager
from paper_chat import (
    fetch_pdf_bytes,
    extract_text_from_pdf,
    select_relevant_chunks,
    build_system_prompt,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Academic Evidence Finder API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    return scholar, analyzer, cache

scholar, analyzer, cache = _get_clients()

# In-memory PDF text cache  { paperId: full_text }
_pdf_cache: dict[str, str] = {}

# ── Cache helpers (compatible with all CacheManager versions) ─────────────────
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

# ── Helpers ──────────────────────────────────────────────────────────────────
def _sse(event_type: str, data: dict) -> str:
    payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
    return f"data: {payload}\n\n"

def _fetch_papers(queries: list, max_papers: int, year: Optional[str]) -> list:
    """Fetch from Semantic Scholar, dedup, sort by citations, return top max_papers."""
    per_query = max(max_papers, 15)
    seen, papers = set(), []
    for q in queries:
        cached = cache.get_search(q)
        batch  = cached if cached else scholar.search(q, limit=per_query, year=year or None)
        if not cached and batch:
            cache.set_search(q, batch)
        for p in batch:
            pid = p.get("paperId", "")
            if pid and pid not in seen:
                seen.add(pid)
                papers.append(p)
    papers = sorted(papers, key=lambda p: p.get("citationCount") or 0, reverse=True)
    return papers[:max_papers]

# ── Request models ────────────────────────────────────────────────────────────
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

class FetchPaperRequest(BaseModel):
    paper: dict  # full Semantic Scholar paper object

class ChatRequest(BaseModel):
    paper: dict
    question: str
    history: list = []  # list of {role, content}

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    stats = cache.stats()
    return {"status": "ok", "model": analyzer.current_model, "cache": stats}


@app.post("/api/verify")
def verify_claim(req: ClaimRequest):
    def generate():
        try:
            early = analyzer.validate_claim(req.claim)
            if early:
                yield _sse("verdict", {"data": early})
                yield _sse("done", {})
                return
            yield _sse("progress", {"message": "Generating search queries\u2026", "step": 1, "total": 4})
            queries = analyzer.transform_query(req.claim, topic_mode=False, max_papers=req.max_papers)
            yield _sse("progress", {"message": "Searching literature\u2026", "step": 2, "total": 4})
            papers = _fetch_papers(queries, req.max_papers, req.year_filter)
            if not papers:
                yield _sse("error", {"message": "No papers found. Try rephrasing."})
                yield _sse("done", {})
                return
            yield _sse("papers", {"data": papers})
            yield _sse("progress", {"message": f"Analysing {len(papers)} papers\u2026", "step": 3, "total": 4})
            results = []
            for i, paper in enumerate(papers):
                pid      = paper.get("paperId", "")
                cached   = cache.get_analysis(pid, req.claim)
                analysis = cached if cached else analyzer.analyze_paper(paper, req.claim)
                if not cached and pid:
                    cache.set_analysis(pid, req.claim, analysis)
                yield _sse("analysis", {"index": i, "total": len(papers), "paper_id": pid, "analysis": analysis})
                if analysis.get("relevance_score", 0) >= 5:
                    results.append((paper, analysis))
            yield _sse("progress", {"message": "Synthesizing verdict\u2026", "step": 4, "total": 4})
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
    def generate():
        try:
            yield _sse("progress", {"message": "Generating search queries\u2026", "step": 1, "total": 3})
            queries = analyzer.transform_query(req.topic, topic_mode=True, max_papers=req.max_papers)
            yield _sse("progress", {"message": "Searching literature\u2026", "step": 2, "total": 3})
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
                yield _sse("analysis", {"index": i, "total": len(papers), "paper_id": pid, "analysis": analysis})
                results.append((paper, analysis))
            yield _sse("progress", {"message": "Writing literature review\u2026", "step": 3, "total": 3})
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
    def generate():
        try:
            yield _sse("progress", {"message": "Generating search queries\u2026"})
            queries = analyzer.transform_query(req.topic, topic_mode=True, max_papers=req.max_papers)
            yield _sse("progress", {"message": "Searching\u2026"})
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
async def summarize_paper(req: SummarizeRequest):
    """Summarize a single paper — never returns 500."""
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
    """
    Attempt to retrieve the PDF for a paper.
    Returns:
      { available: bool, source: str, pdf_b64: str|null, text_preview: str, pid: str }
    The frontend uses pdf_b64 to render the PDF inline.
    Full text is cached server-side by paperId for subsequent chat calls.
    """
    paper = req.paper
    pid   = paper.get("paperId", "")

    # If we already have the text cached, skip re-fetching
    if pid and pid in _pdf_cache:
        preview = _pdf_cache[pid][:500]
        return {"available": True, "source": "cache", "pdf_b64": None,
                "text_preview": preview, "pid": pid}

    pdf_bytes, source = fetch_pdf_bytes(paper)

    if pdf_bytes:
        text = extract_text_from_pdf(pdf_bytes)
        if pid and text:
            _pdf_cache[pid] = text
        pdf_b64 = base64.b64encode(pdf_bytes).decode()
        return {
            "available": True,
            "source":    source,
            "pdf_b64":   pdf_b64,
            "text_preview": text[:500],
            "pid": pid,
        }

    # Fallback: use abstract only
    abstract = (paper.get("abstract") or "").strip()
    if pid and abstract:
        _pdf_cache[pid] = abstract
    return {
        "available": False,
        "source":    "abstract_only",
        "pdf_b64":   None,
        "text_preview": abstract[:500],
        "pid": pid,
    }


@app.post("/api/paper/chat")
def paper_chat(req: ChatRequest):
    """
    Stream a chat response grounded in the paper's text.
    Expects: { paper, question, history }
    Streams SSE tokens: { type:"token", text:"..." } then { type:"done" }
    """
    def generate():
        try:
            paper    = req.paper
            pid      = paper.get("paperId", "")
            question = req.question.strip()

            # Retrieve full text from cache or fall back to abstract
            full_text = _pdf_cache.get(pid, "") or (paper.get("abstract") or "")

            # Select relevant chunks for this question
            content  = select_relevant_chunks(full_text, question) if full_text else "No content available."
            sys_prompt = build_system_prompt(paper, content)

            # Build message list: system + history (last 6 turns) + new question
            messages = [{"role": "system", "content": sys_prompt}]
            for turn in req.history[-6:]:  # keep context window sane
                role = turn.get("role", "user")
                if role in ("user", "assistant") and turn.get("content"):
                    messages.append({"role": role, "content": turn["content"]})
            messages.append({"role": "user", "content": question})

            # Stream from Groq via analyzer's rotator
            client, model, _ = analyzer.rotator.current
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=800,
                stream=True,
            )
            for chunk in stream:
                token = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if token:
                    yield _sse("token", {"text": token})
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
    _pdf_cache.clear()
    return {"status": "cleared"}
