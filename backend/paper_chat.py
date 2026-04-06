"""paper_chat.py — PDF fetch, parse, and chat logic for feature/paper-chat."""
import io
import logging
import os
import re
from typing import Optional

import httpx
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "AcademicEvidenceFinder/1.0 (research tool; contact: research@example.com)"
}
_CHUNK_SIZE   = 800   # characters per chunk
_MAX_CHUNKS   = 6     # max chunks sent to LLM per turn
_TIMEOUT      = 15    # seconds for HTTP requests

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a precise academic paper assistant. You have been given the full text \
(or the best available excerpt) of the following paper:

Title:   {title}
Authors: {authors}
Year:    {year}
DOI:     {doi}

PAPER CONTENT:
{content}

━━━ STRICT RULES ━━━
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

# ── PDF fetching ──────────────────────────────────────────────────────────────

def _try_fetch_pdf(url: str) -> Optional[bytes]:
    """Attempt to download a PDF from a URL. Returns bytes or None."""
    if not url:
        return None
    try:
        r = httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT,
                      follow_redirects=True)
        if r.status_code == 200 and "pdf" in r.headers.get("content-type", "").lower():
            return r.content
    except Exception as exc:
        logger.warning("PDF fetch failed %s: %s", url, exc)
    return None


def _arxiv_pdf_url(paper: dict) -> Optional[str]:
    """Extract arXiv PDF URL from Semantic Scholar paper dict."""
    ext = paper.get("externalIds") or {}
    arxiv_id = ext.get("ArXiv") or ext.get("arxiv")
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return None


def _unpaywall_pdf_url(doi: str) -> Optional[str]:
    """Query Unpaywall for a free PDF URL given a DOI."""
    if not doi:
        return None
    email = os.getenv("UNPAYWALL_EMAIL", "research@example.com")
    try:
        r = httpx.get(
            f"https://api.unpaywall.org/v2/{doi}?email={email}",
            timeout=_TIMEOUT, headers=_HEADERS
        )
        if r.status_code == 200:
            data = r.json()
            best = data.get("best_oa_location") or {}
            url  = best.get("url_for_pdf") or best.get("url")
            if url:
                return url
    except Exception as exc:
        logger.warning("Unpaywall lookup failed for %s: %s", doi, exc)
    return None


def fetch_pdf_bytes(paper: dict) -> tuple[Optional[bytes], str]:
    """
    Try to fetch the PDF for a paper using multiple sources.
    Returns (pdf_bytes_or_None, source_label).
    """
    # 1. Semantic Scholar openAccessPdf
    oa = paper.get("openAccessPdf") or {}
    url = oa.get("url") if isinstance(oa, dict) else None
    if url:
        pdf = _try_fetch_pdf(url)
        if pdf:
            return pdf, "openAccessPdf"

    # 2. arXiv
    url = _arxiv_pdf_url(paper)
    if url:
        pdf = _try_fetch_pdf(url)
        if pdf:
            return pdf, "arXiv"

    # 3. Unpaywall
    doi = (paper.get("externalIds") or {}).get("DOI", "")
    url = _unpaywall_pdf_url(doi)
    if url:
        pdf = _try_fetch_pdf(url)
        if pdf:
            return pdf, "Unpaywall"

    return None, "unavailable"


# ── Text extraction ────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract full text from PDF bytes using PyMuPDF."""
    try:
        doc  = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text.strip()
    except Exception as exc:
        logger.error("PDF text extraction failed: %s", exc)
        return ""


# ── Chunk selection ────────────────────────────────────────────────────────────

def _split_chunks(text: str, size: int = _CHUNK_SIZE) -> list[str]:
    """Split text into overlapping chunks of ~size characters."""
    words  = text.split()
    chunks = []
    step   = max(1, size // 5)  # ~20 % overlap
    for i in range(0, len(words), step):
        chunk = " ".join(words[i:i + size // 5 * 5])
        if chunk.strip():
            chunks.append(chunk.strip())
    return chunks


def select_relevant_chunks(text: str, question: str,
                           max_chunks: int = _MAX_CHUNKS) -> str:
    """
    Keyword-based chunk selection — no embeddings needed.
    Returns concatenated best chunks as a single string.
    """
    # Always include abstract / first chunk for context
    chunks   = _split_chunks(text)
    if not chunks:
        return text[:_CHUNK_SIZE * max_chunks]

    keywords = set(re.findall(r"\b\w{4,}\b", question.lower()))
    # Common stop-words to ignore in matching
    keywords -= {"what", "does", "this", "paper", "study", "that", "with",
                 "from", "have", "been", "they", "about", "which", "there",
                 "their", "these", "when", "where", "also", "would", "could"}

    def score(chunk: str) -> int:
        lower = chunk.lower()
        return sum(1 for kw in keywords if kw in lower)

    scored   = sorted(enumerate(chunks), key=lambda t: score(t[1]), reverse=True)
    selected = [chunks[0]]  # always first chunk
    seen     = {0}
    for idx, chunk in scored:
        if len(selected) >= max_chunks:
            break
        if idx not in seen:
            selected.append(chunk)
            seen.add(idx)
    # Sort by original position for narrative coherence
    selected_with_idx = sorted(
        [(i, c) for i, c in enumerate(chunks) if c in selected],
        key=lambda t: t[0]
    )
    return "\n\n---\n\n".join(c for _, c in selected_with_idx)


# ── System prompt builder ──────────────────────────────────────────────────────

def build_system_prompt(paper: dict, content: str) -> str:
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
        content = content[:12000],  # hard cap to stay within context
    )
