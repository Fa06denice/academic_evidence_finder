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
    fetch_full_text,
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

# In-memory full-text cache  { paperId: (text, source_label) }
_text_cache: dict[str, tuple[str, str]] = {}

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

# ── Helpers ──────────────────────────────────────────────────────────────────────
def _sse(event_type: str, data: dict) -> str:
    payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
    return f"data: {payload}\n\n"

def _fetch_papers(queries: list, max_papers: int, year: Optional[str]) -> list:
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

# ── Request models ────────────────────────────────────────────────────────────────
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
    paper: dict

class ChatRequest(BaseModel):
    paper: dict
    question: str
    history: list = []

# ── Routes ─────────────────────────────────────────────────────────────────────────

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
    Retrieve the fullest available text for a paper using the cascade:
      openAccessPdf PDF → arXiv PDF → PMC HTML → Europe PMC → BioMed DOI scrape → abstract
    Caches result server-side. Returns source label so the UI can show it.
    """
    paper = req.paper
    pid   = paper.get("paperId", "")

    # Return cached result immediately
    if pid and pid in _text_cache:
        text, source = _text_cache[pid]
        return {
            "available": source != "unavailable",
            "source":    source,
            "pdf_b64":   None,
            "text_preview": text[:500],
            "pid": pid,
        }

    # Run the full cascade
    text, source = fetch_full_text(paper)

    if pid and text:
        _text_cache[pid] = (text, source)

    # If we got a PDF (source says PDF), also encode it for inline viewer
    pdf_b64 = None
    if "PDF" in source:
        # Re-fetch PDF bytes just for the b64 (cheap, already cached at OS level)
        try:
            pdf_bytes, _ = fetch_pdf_bytes(paper)
            if pdf_bytes:
                pdf_b64 = base64.b64encode(pdf_bytes).decode()
        except Exception:
            pass

    return {
        "available": bool(text) and source != "unavailable",
        "source":    source,
        "pdf_b64":   pdf_b64,
        "text_preview": text[:500] if text else "",
        "pid": pid,
    }


@app.post("/api/paper/chat")
def paper_chat(req: ChatRequest):
    """
    Stream a chat response grounded in the paper's text.
    If the text isn't cached yet, runs the full-text cascade on-the-fly.
    """
    def generate():
        try:
            paper    = req.paper
            pid      = paper.get("paperId", "")
            question = req.question.strip()

            # Get or fetch full text
            if pid and pid in _text_cache:
                full_text, source = _text_cache[pid]
            else:
                full_text, source = fetch_full_text(paper)
                if pid and full_text:
                    _text_cache[pid] = (full_text, source)

            if not full_text:
                full_text = paper.get("abstract") or ""
                source    = "Abstract only (full text unavailable)"

            content    = select_relevant_chunks(full_text, question) if full_text else "No content available."
            sys_prompt = build_system_prompt(paper, content, source=source)

            messages = [{"role": "system", "content": sys_prompt}]
            for turn in req.history[-6:]:
                role = turn.get("role", "user")
                if role in ("user", "assistant") and turn.get("content"):
                    messages.append({"role": role, "content": turn["content"]})
            messages.append({"role": "user", "content": question})

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
    _text_cache.clear()
    return {"status": "cleared"}
