# cache_manager.py
import json
import hashlib
import os
import logging
from datetime import datetime
from typing import Optional


logger = logging.getLogger(__name__)


class CacheManager:
    """
    Persistent JSON cache for Semantic Scholar results and LLM analyses.
    Prevents redundant API calls and re-analyses for the same paper/claim pair.
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
                logger.warning("Cache file unreadable (%s) — starting fresh.", exc)
                return {}
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


    # ── Search results ────────────────────────────────────────────────────────


    def get_search(self, query: str) -> Optional[list]:
        entry = self.cache.get(f"search_{self._key(query)}")
        return entry.get("data") if isinstance(entry, dict) else None

    def set_search(self, query: str, results: list):
        self.cache[f"search_{self._key(query)}"] = {
            "data": results,
            "ts":   datetime.now().isoformat(),
        }
        self._save()


    # ── Paper details ─────────────────────────────────────────────────────────


    def get_paper(self, paper_id: str) -> Optional[dict]:
        entry = self.cache.get(f"paper_{paper_id}")
        return entry.get("data") if isinstance(entry, dict) else None

    def set_paper(self, paper_id: str, data: dict):
        self.cache[f"paper_{paper_id}"] = {
            "data": data,
            "ts":   datetime.now().isoformat(),
        }
        self._save()


    # ── Full text ─────────────────────────────────────────────────────────────


    def get_fulltext(self, paper_id: str) -> Optional[str]:
        entry = self.cache.get(f"fulltext_{paper_id}")
        return entry.get("data") if isinstance(entry, dict) else None

    def set_fulltext(self, paper_id: str, text: str):
        self.cache[f"fulltext_{paper_id}"] = {
            "data": text,
            "ts":   datetime.now().isoformat(),
        }
        self._save()


    # ── LLM analyses ──────────────────────────────────────────────────────────


    def get_analysis(self, paper_id: str, claim: str) -> Optional[dict]:
        entry = self.cache.get(f"analysis_{self._key(paper_id, claim)}")
        return entry.get("data") if isinstance(entry, dict) else None

    def set_analysis(self, paper_id: str, claim: str, analysis: dict):
        self.cache[f"analysis_{self._key(paper_id, claim)}"] = {
            "data": analysis,
            "ts":   datetime.now().isoformat(),
        }
        self._save()


    # ── Summaries ─────────────────────────────────────────────────────────────


    def get_summary(self, paper_id: str) -> Optional[str]:
        entry = self.cache.get(f"summary_{paper_id}")
        return entry.get("data") if isinstance(entry, dict) else None

    def set_summary(self, paper_id: str, summary: str):
        self.cache[f"summary_{paper_id}"] = {
            "data": summary,
            "ts":   datetime.now().isoformat(),
        }
        self._save()


    # ── Utilities ─────────────────────────────────────────────────────────────


    def stats(self) -> dict:
        return {
            "searches":  sum(1 for k in self.cache if k.startswith("search_")),
            "papers":    sum(1 for k in self.cache if k.startswith("paper_")),
            "analyses":  sum(1 for k in self.cache if k.startswith("analysis_")),
            "summaries": sum(1 for k in self.cache if k.startswith("summary_")),
            "fulltexts": sum(1 for k in self.cache if k.startswith("fulltext_")),
            "total":     len(self.cache),
        }

    def clear(self):
        self.cache = {}
        try:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
        except OSError as exc:
            logger.error("Could not delete cache file: %s", exc)