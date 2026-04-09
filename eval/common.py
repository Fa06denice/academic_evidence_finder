import csv
import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable


def now_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(path: str | Path) -> Path:
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def load_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(path: str | Path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def dump_csv(path: str | Path, rows: list[dict]):
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def post_json(base_url: str, path: str, payload: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def stream_sse_json(base_url: str, path: str, payload: dict, timeout: int = 300) -> list[dict]:
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    events: list[dict] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    events.append(json.loads(chunk))
                except json.JSONDecodeError:
                    continue
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    return events


def event_error(events: list[dict]) -> str:
    for event in events:
        if event.get("type") == "error":
            return str(event.get("message") or "unknown error")
    return ""


def extract_answer_text(events: list[dict]) -> str:
    return "".join(event.get("text", "") for event in events if event.get("type") == "token").strip()


def extract_sources(events: list[dict]) -> list[dict]:
    for event in events:
        if event.get("type") == "sources":
            data = event.get("data") or {}
            used = data.get("used")
            if isinstance(used, list):
                return used
            all_sources = data.get("all")
            if isinstance(all_sources, list):
                return all_sources
    return []


def cited_source_ids(answer_text: str) -> list[str]:
    return sorted(set(re.findall(r"S\d+", answer_text or "")), key=lambda item: int(item[1:]))


def contains_any(text: str, needles: list[str]) -> bool:
    haystack = (text or "").lower()
    return any(needle.lower() in haystack for needle in needles)


def contains_all(text: str, needles: list[str]) -> bool:
    haystack = (text or "").lower()
    return all(needle.lower() in haystack for needle in needles)


def run_parallel(cases: list[dict], worker_fn: Callable[[dict], dict], workers: int) -> list[dict]:
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(worker_fn, case): case for case in cases}
        for future in as_completed(futures):
            case = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({
                    "id": case.get("id", "unknown"),
                    "status": "error",
                    "error": str(exc),
                })
    return sorted(results, key=lambda item: item.get("id", ""))
