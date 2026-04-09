import argparse

from common import (
    cited_source_ids,
    contains_all,
    contains_any,
    dump_csv,
    dump_json,
    ensure_dir,
    event_error,
    extract_answer_text,
    extract_sources,
    load_json,
    now_stamp,
    post_json,
    run_parallel,
    stream_sse_json,
)


def evaluate_case(base_url: str, case: dict) -> dict:
    paper = case["paper"]
    question = case["question"]

    fetch_payload = post_json(base_url, "/api/paper/fetch", {"paper": paper}, timeout=int(case.get("fetch_timeout", 240)))
    events = stream_sse_json(
        base_url,
        "/api/paper/chat",
        {"paper": paper, "question": question, "history": case.get("history", [])},
        timeout=int(case.get("chat_timeout", 300)),
    )

    error = event_error(events)
    answer = extract_answer_text(events)
    sources = extract_sources(events)
    source_ids = cited_source_ids(answer)
    source_excerpt_text = "\n".join(source.get("excerpt", "") for source in sources)

    must_include_any = case.get("must_include_any") or []
    must_include_all = case.get("must_include_all") or []
    must_not_include = case.get("must_not_include") or []
    required_citations = int(case.get("required_citations", 1))
    require_full_text = bool(case.get("require_full_text", False))

    checks = {
        "no_error": not error,
        "has_answer": bool(answer),
        "has_citations": len(source_ids) >= required_citations,
        "matches_any": (not must_include_any) or contains_any(answer, must_include_any) or contains_any(source_excerpt_text, must_include_any),
        "matches_all": (not must_include_all) or contains_all(answer, must_include_all) or contains_all(source_excerpt_text, must_include_all),
        "avoids_forbidden": not must_not_include or not contains_any(answer, must_not_include),
        "full_text_available": (not require_full_text) or bool(fetch_payload.get("available")),
    }
    passed = all(checks.values())

    return {
        "id": case["id"],
        "question": question,
        "paper_title": paper.get("title", ""),
        "status": "passed" if passed else "failed",
        "error": error,
        "source_type": fetch_payload.get("source", ""),
        "full_text_available": bool(fetch_payload.get("available")),
        "citation_count": len(source_ids),
        "source_card_count": len(sources),
        "must_include_any": ", ".join(must_include_any),
        "must_include_all": ", ".join(must_include_all),
        "checks": checks,
        "answer_preview": answer[:500],
        "notes": case.get("notes", ""),
        "raw_events": events,
    }


def main():
    parser = argparse.ArgumentParser(description="Parallel evaluator for /api/paper/chat")
    parser.add_argument("--dataset", default="eval/datasets/paper_chat_sample.json")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--out-dir", default="eval/results")
    args = parser.parse_args()

    dataset = load_json(args.dataset)
    cases = dataset.get("cases", [])
    results = run_parallel(
        cases,
        lambda case: evaluate_case(args.base_url, case),
        workers=args.workers,
    )

    summary = {
        "dataset": str(args.dataset),
        "base_url": args.base_url,
        "workers": args.workers,
        "total_cases": len(results),
        "passed": sum(1 for result in results if result.get("status") == "passed"),
        "failed": sum(1 for result in results if result.get("status") == "failed"),
        "errored": sum(1 for result in results if result.get("status") == "error"),
        "results": results,
    }

    out_dir = ensure_dir(args.out_dir)
    stamp = now_stamp()
    base_name = f"paper_chat_eval_{stamp}"
    json_path = out_dir / f"{base_name}.json"
    csv_path = out_dir / f"{base_name}.csv"

    dump_json(json_path, summary)
    dump_csv(
        csv_path,
        [
            {
                key: value
                for key, value in result.items()
                if key not in {"raw_events", "checks"}
            }
            | {"checks": "; ".join(f"{name}={state}" for name, state in result.get("checks", {}).items())}
            for result in results
        ],
    )

    print(f"Paper chat evaluation completed: {summary['passed']}/{summary['total_cases']} passed")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")


if __name__ == "__main__":
    main()
