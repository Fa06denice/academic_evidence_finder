import time
import logging
import requests
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

_SEARCH_FIELDS = (
    "paperId,title,abstract,year,authors,citationCount,"
    "tldr,externalIds,isOpenAccess,openAccessPdf,publicationTypes,journal"
)

class SemanticScholarClient:
    """
    Thin wrapper around the Semantic Scholar Graph API v1.
    Abstract-only — no PDF fetching, no Unpaywall.
    """

    BASE         = "https://api.semanticscholar.org/graph/v1"
    MIN_INTERVAL = 1.1
    RETRY_WAIT   = 6.0

    def __init__(self, api_key: Optional[str] = None):
        self._last_call = 0.0
        self._session   = requests.Session()
        self._session.headers.update({"User-Agent": "AcademicEvidenceFinder/1.0"})
        if api_key:
            self._session.headers.update({"x-api-key": api_key})

    def _throttle(self):
        wait = self.MIN_INTERVAL - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _get(self, path: str, params: dict, retries: int = 3) -> dict:
        self._throttle()
        try:
            r = self._session.get(f"{self.BASE}/{path}", params=params, timeout=20)
            if r.status_code == 429:
                if retries > 0:
                    logger.warning("429 — waiting %.1fs", self.RETRY_WAIT)
                    time.sleep(self.RETRY_WAIT)
                    return self._get(path, params, retries - 1)
                return {"data": [], "error": "Rate limited"}
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as exc:
            logger.error("API error [%s]: %s", path, exc)
            return {"data": [], "error": str(exc)}

    def search(
        self,
        query: str,
        limit: int = 10,
        year: Optional[str] = None,
    ) -> List[Dict]:
        params: dict = {"query": query, "limit": limit, "fields": _SEARCH_FIELDS}
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
