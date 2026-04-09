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


class ResearchState(TypedDict, total=False):
    subject: str
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
    abort: bool
    decision: str
    overall: dict
    review: str


def langgraph_verify_available() -> bool:
    return bool(StateGraph and get_stream_writer and START is not None and END is not None)


def _workflow_definition(kind: Literal["claim_verifier", "literature_review"]) -> dict:
    if kind == "claim_verifier":
        final_node = "finalize_verdict"
        final_label = "Synthesize Verdict"
        warning_label = "Warn: limited evidence"
    else:
        final_node = "finalize_review"
        final_label = "Write Literature Review"
        warning_label = "Warn: limited relevant papers"

    return {
        "kind": kind,
        "nodes": {
            "generate_queries": "Generate Queries",
            "search_candidates": "Search Candidates",
            "analyze_candidates": "Analyze Candidates",
            "critique_results": "Critique Results",
            "refine_queries": "Refine Queries",
            "warning_then_finalize": warning_label,
            final_node: final_label,
        },
        "start": "generate_queries",
        "edges": [
            ("generate_queries", "search_candidates"),
            ("search_candidates", "analyze_candidates"),
            ("analyze_candidates", "critique_results"),
            ("refine_queries", "search_candidates"),
            ("warning_then_finalize", final_node),
            (final_node, "__end__"),
        ],
        "conditional_edges": {
            "critique_results": {
                "enough evidence": final_node,
                "need refinement": "refine_queries",
                "stop with limited evidence": "warning_then_finalize",
            }
        },
        "final_node": final_node,
    }


def _mermaid_id(node_name: str) -> str:
    return {
        "__start__": "START",
        "__end__": "END",
        "warning_then_finalize": "WARN",
    }.get(node_name, node_name.upper())


def _mermaid_node(node_name: str, label: str) -> str:
    node_id = _mermaid_id(node_name)
    if node_name == "__start__":
        return f'    {node_id}([Start])'
    if node_name == "__end__":
        return f'    {node_id}([End])'
    if node_name == "critique_results":
        return f'    {node_id}{{{label}}}'
    return f'    {node_id}[{label}]'


def _workflow_mermaid(definition: dict) -> str:
    lines = ["flowchart TD"]
    lines.append(_mermaid_node("__start__", "Start"))
    for node_name, label in definition["nodes"].items():
        lines.append(_mermaid_node(node_name, label))
    lines.append(_mermaid_node("__end__", "End"))

    lines.append(f"    {_mermaid_id('__start__')} --> {_mermaid_id(definition['start'])}")
    for source, target in definition["edges"]:
        lines.append(f"    {_mermaid_id(source)} --> {_mermaid_id(target)}")
    for source, transitions in definition["conditional_edges"].items():
        for label, target in transitions.items():
            lines.append(f"    {_mermaid_id(source)} -->|{label}| {_mermaid_id(target)}")
    return "\n".join(lines)


def workflow_graphs() -> dict:
    return {
        "claim_verifier": {
            "available": langgraph_verify_available(),
            "nodes": list(_workflow_definition("claim_verifier")["nodes"].keys()),
            "mermaid": _workflow_mermaid(_workflow_definition("claim_verifier")),
        },
        "literature_review": {
            "available": langgraph_verify_available(),
            "nodes": list(_workflow_definition("literature_review")["nodes"].keys()),
            "mermaid": _workflow_mermaid(_workflow_definition("literature_review")),
        },
    }


def _tuple_results(state: ResearchState) -> list[tuple[dict, dict]]:
    return [
        (item["paper"], item["analysis"])
        for item in (state.get("all_results") or [])
        if isinstance(item, dict) and item.get("paper") and item.get("analysis")
    ]


def _stream_research_graph(
    *,
    subject: str,
    max_papers: int,
    year_filter: Optional[str],
    analyzer,
    cache,
    fetch_papers: Callable,
    enrich_queries: Callable,
    run_with_heartbeat: Callable,
    topic_mode: bool,
    total_steps: int,
    search_step: int,
    analysis_step: int,
    final_step: int,
    final_message: str,
    final_event_type: Literal["verdict", "review"],
    final_builder: Callable[[ResearchState], tuple[Callable, tuple]],
    insufficiency_warning: Callable[[ResearchState], str],
) -> Iterable[dict]:
    if not langgraph_verify_available():
        raise RuntimeError("LangGraph is not installed")

    definition = _workflow_definition("claim_verifier" if final_event_type == "verdict" else "literature_review")

    def emit(event_type: str, **payload):
        writer = get_stream_writer()
        writer({"type": event_type, **payload})

    def generate_queries(state: ResearchState) -> dict:
        emit("progress", message="Generating search queries…", step=1, total=total_steps)
        queries = None
        for update in run_with_heartbeat(
            analyzer.transform_query,
            state["subject"],
            topic_mode=topic_mode,
            max_papers=state["max_papers"],
            message="Generating search queries…",
            step=1,
            total=total_steps,
        ):
            if update["kind"] == "heartbeat":
                emit("progress", **update["value"])
            else:
                queries = update["value"]

        safe_queries = queries or [state["subject"]]
        return {
            "base_queries": safe_queries,
            "current_queries": safe_queries,
            "retry_round": 0,
            "pending_papers": [],
            "all_results": [],
            "seen_ids": [],
            "relevant_count": 0,
            "search_error": None,
            "abort": False,
            "decision": "",
        }

    def search_candidates(state: ResearchState) -> dict:
        current_queries = state.get("current_queries") or state.get("base_queries") or [state["subject"]]
        retry_round = state.get("retry_round", 0)
        seen_ids = set(state.get("seen_ids") or [])
        relevant_count = int(state.get("relevant_count") or 0)

        if retry_round == 0:
            emit("progress", message="Searching literature…", step=search_step, total=total_steps)
            requested = state["max_papers"]
            heartbeat_message = "Searching literature…"
        else:
            requested = max(1, state["max_papers"] - relevant_count)
            emit(
                "progress",
                message=f"Only {relevant_count} relevant papers found — searching deeper…",
                step=analysis_step,
                total=total_steps,
            )
            heartbeat_message = "Searching deeper…"

        papers = None
        search_error = None
        for update in run_with_heartbeat(
            fetch_papers,
            current_queries,
            requested,
            state.get("year_filter"),
            exclude_ids=seen_ids if seen_ids else None,
            message=heartbeat_message,
            step=search_step if retry_round == 0 else analysis_step,
            total=total_steps,
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

    def analyze_candidates(state: ResearchState) -> dict:
        papers = state.get("pending_papers") or []
        if not papers:
            return {}

        subject_text = state["subject"]
        all_results = list(state.get("all_results") or [])
        seen_ids = set(state.get("seen_ids") or [])
        relevant_count = int(state.get("relevant_count") or 0)
        base_index = len(all_results)
        total = base_index + len(papers)

        emit("progress", message=f"Analysing {len(papers)} papers…", step=analysis_step, total=total_steps)

        for offset, paper in enumerate(papers):
            pid = paper.get("paperId", "")
            seen_ids.add(pid)

            cached = cache.get_analysis(pid, subject_text) if pid else None
            analysis = cached
            if not analysis:
                for update in run_with_heartbeat(
                    analyzer.analyze_paper,
                    paper,
                    subject_text,
                    message=f"Analysing paper {base_index + offset + 1} / {total}…",
                    step=analysis_step,
                    total=total_steps,
                ):
                    if update["kind"] == "heartbeat":
                        emit("progress", **update["value"])
                    else:
                        analysis = update["value"]

            if not cached and pid:
                cache.set_analysis(pid, subject_text, analysis)

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

    def critique_results(state: ResearchState) -> dict:
        all_results = state.get("all_results") or []
        relevant_count = int(state.get("relevant_count") or 0)
        retry_round = int(state.get("retry_round") or 0)
        pending_papers = state.get("pending_papers") or []

        if state.get("abort") and not all_results:
            return {"decision": "end"}

        if relevant_count >= state["max_papers"]:
            return {"decision": "enough_evidence"}

        if retry_round < MAX_RETRIES and (pending_papers or all_results):
            return {
                "decision": "need_refinement",
                "retry_round": retry_round + 1,
                "current_queries": enrich_queries(state.get("base_queries") or [state["subject"]], retry_round),
            }

        if relevant_count < state["max_papers"]:
            return {"decision": "limited_evidence"}
        return {"decision": "enough_evidence"}

    def refine_queries(state: ResearchState) -> dict:
        emit("progress", message="Refining search strategy…", step=analysis_step, total=total_steps)
        return {"pending_papers": [], "abort": False}

    def warning_then_finalize(state: ResearchState) -> dict:
        emit("warning", message=insufficiency_warning(state))
        return {}

    def finalize_output(state: ResearchState) -> dict:
        fn, args = final_builder(state)
        emit("progress", message=final_message, step=final_step, total=total_steps)
        payload = None
        for update in run_with_heartbeat(
            fn,
            *args,
            message=final_message,
            step=final_step,
            total=total_steps,
        ):
            if update["kind"] == "heartbeat":
                emit("progress", **update["value"])
            else:
                payload = update["value"]

        emit(final_event_type, data=payload)
        return {"overall" if final_event_type == "verdict" else "review": payload}

    def route_after_critique(state: ResearchState):
        decision = state.get("decision")
        if decision == "need_refinement":
            return definition["conditional_edges"]["critique_results"]["need refinement"]
        if decision == "limited_evidence":
            return definition["conditional_edges"]["critique_results"]["stop with limited evidence"]
        if decision == "enough_evidence":
            return definition["conditional_edges"]["critique_results"]["enough evidence"]
        return END

    graph = StateGraph(ResearchState)
    graph.add_node("generate_queries", generate_queries)
    graph.add_node("search_candidates", search_candidates)
    graph.add_node("analyze_candidates", analyze_candidates)
    graph.add_node("critique_results", critique_results)
    graph.add_node("refine_queries", refine_queries)
    graph.add_node("warning_then_finalize", warning_then_finalize)
    graph.add_node(definition["final_node"], finalize_output)

    graph.add_edge(START, definition["start"])
    for source, target in definition["edges"]:
        if target == "__end__":
            continue
        graph.add_edge(source, target)
    graph.add_conditional_edges(
        "critique_results",
        route_after_critique,
        [
            definition["conditional_edges"]["critique_results"]["need refinement"],
            definition["conditional_edges"]["critique_results"]["stop with limited evidence"],
            definition["final_node"],
            END,
        ],
    )
    graph.add_edge(definition["final_node"], END)

    compiled = graph.compile()
    initial_state: ResearchState = {
        "subject": subject,
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
    def final_builder(state: ResearchState) -> tuple[Callable, tuple]:
        return analyzer.overall_verdict, (state["subject"], _tuple_results(state))

    def insufficiency_warning(state: ResearchState) -> str:
        relevant_count = int(state.get("relevant_count") or 0)
        return (
            f"Only {relevant_count} of the {state['max_papers']} requested papers had sufficient "
            "relevance to the claim after the available search rounds. "
            "The verdict is based on available evidence."
        )

    return _stream_research_graph(
        subject=claim,
        max_papers=max_papers,
        year_filter=year_filter,
        analyzer=analyzer,
        cache=cache,
        fetch_papers=fetch_papers,
        enrich_queries=enrich_queries,
        run_with_heartbeat=run_with_heartbeat,
        topic_mode=False,
        total_steps=4,
        search_step=2,
        analysis_step=3,
        final_step=4,
        final_message="Synthesizing verdict…",
        final_event_type="verdict",
        final_builder=final_builder,
        insufficiency_warning=insufficiency_warning,
    )


def stream_literature_review_graph(
    *,
    topic: str,
    max_papers: int,
    year_filter: Optional[str],
    analyzer,
    cache,
    fetch_papers: Callable,
    enrich_queries: Callable,
    run_with_heartbeat: Callable,
) -> Iterable[dict]:
    def final_builder(state: ResearchState) -> tuple[Callable, tuple]:
        return analyzer.literature_review, (state["subject"], _tuple_results(state))

    def insufficiency_warning(state: ResearchState) -> str:
        relevant_count = int(state.get("relevant_count") or 0)
        return (
            f"Only {relevant_count} of the {state['max_papers']} requested papers were sufficiently "
            "relevant to the topic after the available search rounds."
        )

    return _stream_research_graph(
        subject=topic,
        max_papers=max_papers,
        year_filter=year_filter,
        analyzer=analyzer,
        cache=cache,
        fetch_papers=fetch_papers,
        enrich_queries=enrich_queries,
        run_with_heartbeat=run_with_heartbeat,
        topic_mode=True,
        total_steps=3,
        search_step=2,
        analysis_step=2,
        final_step=3,
        final_message="Writing literature review…",
        final_event_type="review",
        final_builder=final_builder,
        insufficiency_warning=insufficiency_warning,
    )
