import json
import hashlib
import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

class CacheManager:
    """
    Persistent JSON cache for search results and LLM analyses.
    Prevents redundant API calls for the same paper/claim pair.

    Search key includes the year_filter so that identical query strings
    with different year ranges never collide in the cache.
    """

    def __init__(self, cache_file: str = "paper_cache.json"):
        self.cache_file = cache_file
        self.cache = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, IOError) as exc:
                logger.warning("Cache unreadable (%s) — starting fresh.", exc)
        return {}

    def _save(self):
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, default=str, ensure_ascii=False)
        except (IOError, OSError) as exc:
            logger.error("Could not save cache: %s", exc)

    @staticmethod
    def _key(*args) -> str:
        combined = "|".join(str(a).lower().strip() for a in args)
        return hashlib.md5(combined.encode()).hexdigest()

    # ── Search results ─────────────────────────────────────────────────────────
    # Key includes year_filter so same query + different year range → different entry.

    def get_search(self, query: str, year_filter: Optional[str] = None) -> Optional[list]:
        entry = self.cache.get(f"search_{self._key(query, year_filter or '')}")
        return entry.get("data") if isinstance(entry, dict) else None

    def set_search(self, query: str, results: list, year_filter: Optional[str] = None):
        self.cache[f"search_{self._key(query, year_filter or '')}"] = {
            "data": results, "ts": datetime.now().isoformat()
        }
        self._save()

    # ── LLM analyses ───────────────────────────────────────────────────────────

    def get_analysis(self, paper_id: str, claim: str) -> Optional[dict]:
        entry = self.cache.get(f"analysis_{self._key(paper_id, claim)}")
        return entry.get("data") if isinstance(entry, dict) else None

    def set_analysis(self, paper_id: str, claim: str, analysis: dict):
        self.cache[f"analysis_{self._key(paper_id, claim)}"] = {
            "data": analysis, "ts": datetime.now().isoformat()
        }
        self._save()

    # ── Paper details ──────────────────────────────────────────────────────────

    def get_paper(self, paper_id: str) -> Optional[dict]:
        entry = self.cache.get(f"paper_{paper_id}")
        return entry.get("data") if isinstance(entry, dict) else None

    def set_paper(self, paper_id: str, data: dict):
        self.cache[f"paper_{paper_id}"] = {
            "data": data, "ts": datetime.now().isoformat()
        }
        self._save()

    # ── Utilities ──────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "searches": sum(1 for k in self.cache if k.startswith("search_")),
            "papers":   sum(1 for k in self.cache if k.startswith("paper_")),
            "analyses": sum(1 for k in self.cache if k.startswith("analysis_")),
            "total":    len(self.cache),
        }

    def clear(self):
        self.cache = {}
        try:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
        except OSError as exc:
            logger.error("Could not delete cache file: %s", exc)

    def get_summary(self, paper_id: str):
        return self.cache.get("summaries", {}).get(paper_id)

    def set_summary(self, paper_id: str, summary: str):
        if "summaries" not in self.cache:
            self.cache["summaries"] = {}
        self.cache["summaries"][paper_id] = summary
        self._save()
