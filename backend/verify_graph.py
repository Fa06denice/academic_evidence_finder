import logging
from typing import Callable, Iterable, Optional
from typing_extensions import Literal, TypedDict

try:  # pragma: no cover - runtime dependency
    from langgraph.config import get_stream_writer
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover - graceful fallback if dependency missing
    get_stream_writer = None
    StateGraph = None
    START = None
    END = None

logger = logging.getLogger(__name__)

MIN_RELEVANCE_SCORE = 3
MAX_RETRIES = 1


class VerifyState(TypedDict, total=False):
    claim: str
    max_papers: int
    year_filter: Optional[str]
    base_queries: list[str]
    current_queries: list[str]
    pending_papers: list[dict]
    all_results: list[dict]
    seen_ids: list[str]
    retry_round: int
    relevant_count: int
    search_error: Optional[str]
    overall: dict
    abort: bool
    decision: str


def langgraph_verify_available() -> bool:
    return bool(StateGraph and get_stream_writer and START is not None and END is not None)


def stream_verify_claim_graph(
    *,
    claim: str,
    max_papers: int,
    year_filter: Optional[str],
    analyzer,
    cache,
    fetch_papers: Callable,
    enrich_queries: Callable,
    run_with_heartbeat: Callable,
) -> Iterable[dict]:
    if not langgraph_verify_available():
        raise RuntimeError("LangGraph is not installed")

    def emit(event_type: str, **payload):
        writer = get_stream_writer()
        writer({"type": event_type, **payload})

    def generate_queries(state: VerifyState) -> dict:
        emit("progress", message="Generating search queries…", step=1, total=4)
        queries = None
        for update in run_with_heartbeat(
            analyzer.transform_query,
            state["claim"],
            topic_mode=False,
            max_papers=state["max_papers"],
            message="Generating search queries…",
            step=1,
            total=4,
        ):
            if update["kind"] == "heartbeat":
                emit("progress", **update["value"])
            else:
                queries = update["value"]

        return {
            "base_queries": queries or [state["claim"]],
            "current_queries": queries or [state["claim"]],
            "retry_round": 0,
            "pending_papers": [],
            "all_results": [],
            "seen_ids": [],
            "relevant_count": 0,
            "search_error": None,
            "abort": False,
        }

    def search_candidates(state: VerifyState) -> dict:
        current_queries = state.get("current_queries") or state.get("base_queries") or [state["claim"]]
        retry_round = state.get("retry_round", 0)
        seen_ids = set(state.get("seen_ids") or [])
        all_results = state.get("all_results") or []
        relevant_count = int(state.get("relevant_count") or 0)

        if retry_round == 0:
            emit("progress", message="Searching literature…", step=2, total=4)
            requested = state["max_papers"]
        else:
            requested = max(1, state["max_papers"] - relevant_count)
            emit(
                "progress",
                message=f"Only {relevant_count} relevant papers found — searching deeper…",
                step=3,
                total=4,
            )

        papers = None
        search_error = None
        for update in run_with_heartbeat(
            fetch_papers,
            current_queries,
            requested,
            state.get("year_filter"),
            exclude_ids=seen_ids if seen_ids else None,
            message="Searching literature…" if retry_round == 0 else "Searching deeper…",
            step=2 if retry_round == 0 else 3,
            total=4,
        ):
            if update["kind"] == "heartbeat":
                emit("progress", **update["value"])
            else:
                papers, search_error = update["value"]

        papers = papers or []

        if retry_round == 0 and not papers:
            emit("error", message=search_error or "No papers found. Try rephrasing.")
            return {
                "pending_papers": [],
                "search_error": search_error,
                "abort": True,
            }

        if retry_round == 0 and papers:
            emit("papers", data=papers)

        if retry_round > 0 and not papers and search_error:
            emit("warning", message=search_error)

        return {
            "pending_papers": papers,
            "search_error": search_error,
            "abort": False,
        }

    def analyze_candidates(state: VerifyState) -> dict:
        papers = state.get("pending_papers") or []
        if not papers:
            return {}

        claim_text = state["claim"]
        all_results = list(state.get("all_results") or [])
        seen_ids = set(state.get("seen_ids") or [])
        relevant_count = int(state.get("relevant_count") or 0)
        base_index = len(all_results)
        total = base_index + len(papers)

        emit("progress", message=f"Analysing {len(papers)} papers…", step=3, total=4)

        for offset, paper in enumerate(papers):
            pid = paper.get("paperId", "")
            seen_ids.add(pid)

            cached = cache.get_analysis(pid, claim_text) if pid else None
            analysis = cached
            if not analysis:
                for update in run_with_heartbeat(
                    analyzer.analyze_paper,
                    paper,
                    claim_text,
                    message=f"Analysing paper {base_index + offset + 1} / {total}…",
                    step=3,
                    total=4,
                ):
                    if update["kind"] == "heartbeat":
                        emit("progress", **update["value"])
                    else:
                        analysis = update["value"]

            if not cached and pid:
                cache.set_analysis(pid, claim_text, analysis)

            emit(
                "analysis",
                index=base_index + offset,
                total=total,
                paper_id=pid,
                paper=paper,
                analysis=analysis,
            )
            all_results.append({"paper": paper, "analysis": analysis})
            if analysis.get("relevance_score", 0) >= MIN_RELEVANCE_SCORE:
                relevant_count += 1

        return {
            "all_results": all_results,
            "seen_ids": list(seen_ids),
            "relevant_count": relevant_count,
            "pending_papers": [],
        }

    def critique_results(state: VerifyState) -> dict:
        all_results = state.get("all_results") or []
        relevant_count = int(state.get("relevant_count") or 0)
        retry_round = int(state.get("retry_round") or 0)
        pending_papers = state.get("pending_papers") or []

        if state.get("abort") and not all_results:
            return {"decision": "end"}

        if relevant_count >= state["max_papers"]:
            return {"decision": "synthesize"}

        if retry_round < MAX_RETRIES and (pending_papers or all_results):
            next_retry = retry_round + 1
            next_queries = enrich_queries(state.get("base_queries") or [state["claim"]], retry_round)
            return {
                "decision": "refine",
                "retry_round": next_retry,
                "current_queries": next_queries,
            }

        if relevant_count < state["max_papers"]:
            emit(
                "warning",
                message=(
                    f"Only {relevant_count} of the {state['max_papers']} requested papers had sufficient "
                    "relevance to the claim after the available search rounds. "
                    "The verdict is based on available evidence."
                ),
            )
        return {"decision": "synthesize"}

    def refine_queries(state: VerifyState) -> dict:
        emit("progress", message="Refining search strategy…", step=3, total=4)
        return {
            "pending_papers": [],
            "abort": False,
        }

    def synthesize_verdict(state: VerifyState) -> dict:
        tuple_results = [
            (item["paper"], item["analysis"])
            for item in (state.get("all_results") or [])
            if isinstance(item, dict) and item.get("paper") and item.get("analysis")
        ]

        emit("progress", message="Synthesizing verdict…", step=4, total=4)
        overall = None
        for update in run_with_heartbeat(
            analyzer.overall_verdict,
            state["claim"],
            tuple_results,
            message="Synthesizing verdict…",
            step=4,
            total=4,
        ):
            if update["kind"] == "heartbeat":
                emit("progress", **update["value"])
            else:
                overall = update["value"]

        emit("verdict", data=overall)
        return {"overall": overall}

    def route_after_critique(state: VerifyState) -> Literal["refine_queries", "synthesize_verdict", END]:
        decision = state.get("decision")
        if decision == "refine":
            return "refine_queries"
        if decision == "synthesize":
            return "synthesize_verdict"
        return END

    graph = StateGraph(VerifyState)
    graph.add_node("generate_queries", generate_queries)
    graph.add_node("search_candidates", search_candidates)
    graph.add_node("analyze_candidates", analyze_candidates)
    graph.add_node("critique_results", critique_results)
    graph.add_node("refine_queries", refine_queries)
    graph.add_node("synthesize_verdict", synthesize_verdict)

    graph.add_edge(START, "generate_queries")
    graph.add_edge("generate_queries", "search_candidates")
    graph.add_edge("search_candidates", "analyze_candidates")
    graph.add_edge("analyze_candidates", "critique_results")
    graph.add_conditional_edges(
        "critique_results",
        route_after_critique,
        ["refine_queries", "synthesize_verdict", END],
    )
    graph.add_edge("refine_queries", "search_candidates")
    graph.add_edge("synthesize_verdict", END)

    compiled = graph.compile()
    initial_state: VerifyState = {
        "claim": claim,
        "max_papers": max_papers,
        "year_filter": year_filter,
    }

    for chunk in compiled.stream(initial_state, stream_mode="custom"):
        if isinstance(chunk, dict) and chunk.get("type") == "custom":
            data = chunk.get("data")
            if isinstance(data, dict):
                yield data
            continue
        if isinstance(chunk, dict) and chunk.get("type"):
            yield chunk
