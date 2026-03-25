# scholar_client.py
import time
import logging
import requests
from typing import Optional, List, Dict


logger = logging.getLogger(__name__)


_SEARCH_FIELDS = (
    "paperId,title,abstract,year,authors,citationCount,"
    "tldr,externalIds,isOpenAccess,openAccessPdf,publicationTypes,journal"
)

_UNPAYWALL_EMAIL = "academic.evidence.finder@gmail.com"


class SemanticScholarClient:
    """
    Thin wrapper around the Semantic Scholar Graph API v1.

    Rate limiting: 1 req/s max. This client enforces a 1.1s minimum
    interval and retries automatically on 429 responses.
    """

    BASE              = "https://api.semanticscholar.org/graph/v1"
    UNPAYWALL_BASE    = "https://api.unpaywall.org/v2"
    MIN_INTERVAL      = 1.1
    RETRY_WAIT        = 6.0

    def __init__(self, api_key: Optional[str] = None):
        self._last_call = 0.0
        self._session   = requests.Session()
        self._session.headers.update({
            "User-Agent": "AcademicEvidenceFinder/1.0 (research tool)"
        })
        if api_key:
            self._session.headers.update({"x-api-key": api_key})

        # Session séparée pour Unpaywall — pas de clé, pas de throttle SS
        self._uw_session = requests.Session()
        self._uw_session.headers.update({
            "User-Agent": "AcademicEvidenceFinder/1.0 (research tool)"
        })


    # ── Rate limiter ──────────────────────────────────────────────────────────


    def _throttle(self):
        wait = self.MIN_INTERVAL - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()


    # ── Low-level GET (Semantic Scholar) ──────────────────────────────────────


    def _get(self, path: str, params: dict, retries: int = 3) -> dict:
        self._throttle()
        try:
            r = self._session.get(
                f"{self.BASE}/{path}", params=params, timeout=30
            )
            if r.status_code == 429:
                if retries > 0:
                    logger.warning("429 received — waiting %.1fs", self.RETRY_WAIT)
                    time.sleep(self.RETRY_WAIT)
                    return self._get(path, params, retries - 1)
                logger.error("Rate limit exhausted after retries.")
                return {"data": [], "error": "Rate limited"}
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as exc:
            logger.error("API error [%s]: %s", path, exc)
            return {"data": [], "error": str(exc)}


    # ── Unpaywall ─────────────────────────────────────────────────────────────


    def get_fulltext_url(self, doi: str) -> Optional[str]:
        """
        Query Unpaywall for an open-access PDF URL given a DOI.
        Returns the best OA URL or None if not available.
        """
        if not doi:
            return None
        try:
            r = self._uw_session.get(
                f"{self.UNPAYWALL_BASE}/{doi}",
                params={"email": _UNPAYWALL_EMAIL},
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()

            # Priorité : publisher PDF > best OA location
            best = data.get("best_oa_location") or {}
            url  = best.get("url_for_pdf") or best.get("url")

            # Fallback sur oa_locations si best_oa_location vide
            if not url:
                for loc in data.get("oa_locations") or []:
                    url = loc.get("url_for_pdf") or loc.get("url")
                    if url:
                        break

            if url:
                logger.info("Unpaywall found OA URL for DOI %s: %s", doi, url)
            return url or None

        except Exception as exc:
            logger.warning("Unpaywall error for DOI %s: %s", doi, exc)
            return None


    def fetch_fulltext(self, url: str, max_chars: int = 8000) -> Optional[str]:
        """
        Download and extract raw text from a PDF URL.
        Returns plain text (truncated to max_chars) or None on failure.
        Requires PyMuPDF (fitz) — install with: pip install pymupdf
        """
        if not url:
            return None
        try:
            import fitz  # PyMuPDF
            r = self._uw_session.get(url, timeout=20, stream=True)
            if r.status_code != 200:
                return None
            # Limite le download à 5MB pour éviter les PDFs géants
            content = b""
            for chunk in r.iter_content(chunk_size=65536):
                content += chunk
                if len(content) > 5 * 1024 * 1024:
                    break
            doc  = fitz.open(stream=content, filetype="pdf")
            text = ""
            for page in doc:
                text += page.get_text()
                if len(text) >= max_chars:
                    break
            doc.close()
            return text[:max_chars].strip() or None
        except ImportError:
            logger.warning("PyMuPDF not installed — pip install pymupdf")
            return None
        except Exception as exc:
            logger.warning("fetch_fulltext failed for %s: %s", url, exc)
            return None


    # ── Public methods ────────────────────────────────────────────────────────


    def search(
        self,
        query: str,
        limit: int = 10,
        year: Optional[str] = None,
    ) -> List[Dict]:
        params: dict = {
            "query":  query,
            "limit":  limit,
            "fields": _SEARCH_FIELDS,
        }
        if year:
            params["year"] = year

        result = self._get("paper/search", params)
        papers = result.get("data") or []

        return [
            p for p in papers
            if isinstance(p, dict)
            and p.get("abstract")
            and len(p["abstract"]) > 80
        ]


    def get_paper(self, paper_id: str) -> Optional[Dict]:
        if not paper_id:
            return None
        result = self._get(f"paper/{paper_id}", {"fields": _SEARCH_FIELDS})
        if "error" in result:
            logger.error("get_paper failed for %s: %s", paper_id, result["error"])
            return None
        return result