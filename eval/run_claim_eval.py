import argparse
from pathlib import Path

from common import dump_csv, dump_json, ensure_dir, event_error, extract_answer_text, load_json, now_stamp, run_parallel, stream_sse_json


def evaluate_case(base_url: str, case: dict) -> dict:
    payload = {
        "claim": case["claim"],
        "max_papers": int(case.get("max_papers", 7)),
    }
    if case.get("year_filter"):
        payload["year_filter"] = case["year_filter"]

    events = stream_sse_json(base_url, "/api/verify", payload, timeout=int(case.get("timeout", 420)))
    error = event_error(events)
    analyses = [event for event in events if event.get("type") == "analysis"]
    warnings = [event.get("message", "") for event in events if event.get("type") == "warning"]
    verdict_event = next((event for event in events if event.get("type") == "verdict"), None)
    verdict = (verdict_event or {}).get("data") or {}
    overall_verdict = verdict.get("overall_verdict", "")

    expected_verdicts = case.get("expected_verdicts") or []
    min_analysed = int(case.get("min_analysed_papers", 0))
    min_relevant = int(case.get("min_relevant_papers", 0))
    relevant_count = sum(
        1 for event in analyses
        if int((event.get("analysis") or {}).get("relevance_score", 0)) >= int(case.get("relevance_threshold", 3))
    )

    checks = {
        "no_error": not error,
        "has_verdict": bool(overall_verdict),
        "analysed_enough": len(analyses) >= min_analysed,
        "relevant_enough": relevant_count >= min_relevant,
        "verdict_matches": (not expected_verdicts) or overall_verdict in expected_verdicts,
    }
    passed = all(checks.values())

    return {
        "id": case["id"],
        "claim": case["claim"],
        "status": "passed" if passed else "failed",
        "error": error,
        "overall_verdict": overall_verdict,
        "overall_confidence": verdict.get("overall_confidence", ""),
        "analysed_papers": len(analyses),
        "relevant_papers": relevant_count,
        "supporting_count": verdict.get("supporting_count", ""),
        "contradicting_count": verdict.get("contradicting_count", ""),
        "neutral_count": verdict.get("neutral_count", ""),
        "warning_count": len([message for message in warnings if message]),
        "expected_verdicts": ", ".join(expected_verdicts),
        "checks": checks,
        "verdict_explanation": verdict.get("verdict_explanation", ""),
        "notes": case.get("notes", ""),
        "raw_events": events,
    }


def main():
    parser = argparse.ArgumentParser(description="Parallel evaluator for /api/verify")
    parser.add_argument("--dataset", default="eval/datasets/claim_verifier_sample.json")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--workers", type=int, default=3)
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
    base_name = f"claim_eval_{stamp}"
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

    print(f"Claim evaluation completed: {summary['passed']}/{summary['total_cases']} passed")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")


if __name__ == "__main__":
    main()
