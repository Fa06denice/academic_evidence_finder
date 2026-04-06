"""paper_chat.py — PDF fetch, parse, HTML full-text, and chat logic."""
import io
import logging
import os
import re
from typing import Optional

import httpx
import fitz  # PyMuPDF
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "AcademicEvidenceFinder/1.0 (research tool; contact: research@example.com)"
}
_CHUNK_SIZE   = 800
_MAX_CHUNKS   = 6
_TIMEOUT      = 15

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


# ── Source 1 : Semantic Scholar openAccessPdf ─────────────────────────────────

def _try_fetch_pdf(url: str) -> Optional[bytes]:
    if not url:
        return None
    r = _get(url)
    if r and "pdf" in r.headers.get("content-type", "").lower():
        return r.content
    return None


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
