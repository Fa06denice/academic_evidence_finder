# app.py
import json
import os
import streamlit as st
from dotenv import load_dotenv


from scholar_client import SemanticScholarClient
from analyzer import PaperAnalyzer
from cache_manager import CacheManager


load_dotenv()


# ── Page config ───────────────────────────────────────────────────────────────


st.set_page_config(
    page_title="Academic Evidence Finder",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown("""
<style>
  .verdict-supported    { background:#1a3a2a; border-left:4px solid #28a745; padding:12px 16px; border-radius:6px; margin:10px 0; color:#e8f5e9; }
  .verdict-partial      { background:#2a2a1a; border-left:4px solid #ffc107; padding:12px 16px; border-radius:6px; margin:10px 0; color:#fff8e1; }
  .verdict-contradicted { background:#3a1a1a; border-left:4px solid #dc3545; padding:12px 16px; border-radius:6px; margin:10px 0; color:#fce4ec; }
  .verdict-neutral      { background:#1e1e1e; border-left:4px solid #6c757d; padding:12px 16px; border-radius:6px; margin:10px 0; color:#e0e0e0; }
  .evidence-quote       { font-style:italic; border-left:3px solid #4a9eff; padding-left:12px; color:#b0c4de; margin:8px 0; }
  .paper-meta           { color:#aaa; font-size:0.9em; }
</style>
""", unsafe_allow_html=True)


# ── Constants ─────────────────────────────────────────────────────────────────


VERDICT_ICON = {
    "SUPPORTS":           "🟢",
    "PARTIALLY_SUPPORTS": "🟡",
    "CONTRADICTS":        "🔴",
    "NEUTRAL":            "⚪",
    "INSUFFICIENT_DATA":  "⚫",
}


VERDICT_CSS = {
    "SUPPORTS":           "verdict-supported",
    "PARTIALLY_SUPPORTS": "verdict-partial",
    "CONTRADICTS":        "verdict-contradicted",
    "NEUTRAL":            "verdict-neutral",
    "INSUFFICIENT_DATA":  "verdict-neutral",
}


OVERALL_CSS = {
    "SUPPORTED":             "verdict-supported",
    "PARTIALLY_SUPPORTED":   "verdict-partial",
    "CONTRADICTED":          "verdict-contradicted",
    "MIXED":                 "verdict-partial",
    "INSUFFICIENT_EVIDENCE": "verdict-neutral",
}


OVERALL_LABEL = {
    "SUPPORTED":             "✅ SUPPORTED BY LITERATURE",
    "PARTIALLY_SUPPORTED":   "⚠️ PARTIALLY SUPPORTED",
    "CONTRADICTED":          "❌ CONTRADICTED BY LITERATURE",
    "MIXED":                 "🔀 MIXED EVIDENCE",
    "INSUFFICIENT_EVIDENCE": "❓ INSUFFICIENT EVIDENCE",
}


PAPER_VERDICT_LABEL = {
    "SUPPORTS":           "✅ Supports the claim",
    "PARTIALLY_SUPPORTS": "⚠️ Partially supports",
    "CONTRADICTS":        "❌ Contradicts the claim",
    "NEUTRAL":            "➖ Neutral",
    "INSUFFICIENT_DATA":  "❓ Insufficient data",
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_llm_api_key() -> str:
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "openai":
        return os.getenv("OPENAI_API_KEY", "") or os.getenv("LLM_API_KEY", "")
    return os.getenv("LLM_API_KEY", "")


def _get_extra_keys() -> list:
    return [
        os.getenv(f"LLM_API_KEY_{i}", "")
        for i in range(2, 10)
        if os.getenv(f"LLM_API_KEY_{i}", "")
    ]


def get_clients():
    provider   = os.getenv("LLM_PROVIDER", "groq").lower()
    api_key    = _get_llm_api_key()
    ss_key     = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    extra_keys = _get_extra_keys()

    if not api_key and provider != "ollama":
        return None, None, None

    cache    = CacheManager()
    scholar  = SemanticScholarClient(api_key=ss_key or None)
    analyzer = PaperAnalyzer(
        api_key=api_key,
        provider=provider,
        extra_keys=extra_keys,
    )
    return scholar, analyzer, cache


def render_paper_card(paper: dict, analysis: dict, idx: int, expanded: bool = False):
    title    = paper.get("title", "Unknown Title")
    year     = paper.get("year", "N/A")
    authors  = [a.get("name", "") for a in paper.get("authors", [])[:4]]
    author_s = ", ".join(a for a in authors if a)
    if len(paper.get("authors", [])) > 4:
        author_s += " et al."
    cites    = paper.get("citationCount")
    verdict  = analysis.get("verdict", "INSUFFICIENT_DATA")
    icon     = VERDICT_ICON.get(verdict, "⚫")
    css      = VERDICT_CSS.get(verdict, "verdict-neutral")
    label    = PAPER_VERDICT_LABEL.get(verdict, verdict)
    score    = int(analysis.get("relevance_score") or 0)
    conf     = analysis.get("confidence", "LOW")
    evidence = analysis.get("evidence", "No evidence found.")
    explain  = analysis.get("explanation", "")
    finding  = analysis.get("key_finding", "")
    pid      = paper.get("paperId", "")
    doi      = (paper.get("externalIds") or {}).get("DOI", "")

    with st.expander(f"{icon} [{idx + 1}] {title} ({year})", expanded=expanded):
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.markdown(f'<span class="paper-meta">👤 {author_s or "Unknown"}</span>', unsafe_allow_html=True)
        with col2:
            if cites is not None:
                st.markdown(f'<span class="paper-meta">📎 {int(cites):,} citations</span>', unsafe_allow_html=True)
        with col3:
            st.markdown(f'<span class="paper-meta">⭐ Relevance: {score}/10</span>', unsafe_allow_html=True)

        st.markdown(
            f'<div class="{css}"><strong>{label}</strong>&nbsp;&nbsp;<small>(Confidence: {conf})</small></div>',
            unsafe_allow_html=True,
        )

        st.markdown("**📌 Evidence from abstract:**")
        st.markdown(f'<div class="evidence-quote">"{evidence}"</div>', unsafe_allow_html=True)

        if explain:
            st.markdown(f"**🔍 Analysis:** {explain}")
        if finding and finding != "N/A":
            st.markdown(f"**💡 Key finding:** {finding}")

        with st.expander("📄 Full abstract"):
            st.markdown(paper.get("abstract") or "*No abstract available.*")

        links = []
        if pid:
            links.append(f"[🔗 Semantic Scholar](https://www.semanticscholar.org/paper/{pid})")
        if doi:
            links.append(f"[📄 DOI](https://doi.org/{doi})")
        if links:
            st.markdown("  |  ".join(links))


def _render_overall_verdict(overall: dict):
    """Render the overall verdict block — reusable for both normal and early-exit cases."""
    ov     = overall.get("overall_verdict", "INSUFFICIENT_EVIDENCE")
    ov_css = OVERALL_CSS.get(ov, "verdict-neutral")
    ov_lbl = OVERALL_LABEL.get(ov, ov)
    st.markdown(
        f'<div class="{ov_css}">'
        f'<h3 style="margin:0">{ov_lbl}</h3>'
        f'<p style="margin:8px 0 4px 0">{overall.get("verdict_explanation", "")}</p>'
        f'<small>🟢 Supporting: {overall.get("supporting_count", 0)} &nbsp;|&nbsp; '
        f'🔴 Contradicting: {overall.get("contradicting_count", 0)} &nbsp;|&nbsp; '
        f'⚪ Neutral/Unclear: {overall.get("neutral_count", 0)}</small>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Search & analysis pipeline ────────────────────────────────────────────────


def run_search(
    claim: str,
    scholar: SemanticScholarClient,
    analyzer: PaperAnalyzer,
    cache: CacheManager,
    year_str: str = None,
) -> tuple:
    status = st.empty()

    # Step 1 — transform query
    status.info("🔄 Generating academic search queries…")
    queries = analyzer.transform_query(claim)
    st.sidebar.markdown("---\n**🔍 Queries sent to Semantic Scholar:**")
    for q in queries:
        st.sidebar.markdown(f"- `{q}`")

    # Step 2 — search (with cache)
    all_papers: dict = {}
    for i, q in enumerate(queries):
        status.info(f"🔍 Searching ({i + 1}/{len(queries)}): *{q}*…")
        cached = cache.get_search(q)
        if cached is not None:
            papers = cached
            st.sidebar.markdown("  ✅ Cache hit")
        else:
            papers = scholar.search(q, limit=10, year=year_str)
            cache.set_search(q, papers)
        for p in papers:
            pid = p.get("paperId")
            if pid and pid not in all_papers:
                if cache.get_paper(pid) is None:
                    cache.set_paper(pid, p)
                else:
                    cached_paper = cache.get_paper(pid)
                    for field in ("abstract", "tldr", "authors", "citationCount", "externalIds"):
                        if not p.get(field) and cached_paper.get(field):
                            p[field] = cached_paper[field]
                all_papers[pid] = p

    if not all_papers:
        status.empty()
        return [], {}

    # Sort by citation count and cap at 20
    sorted_papers = sorted(
        all_papers.values(),
        key=lambda p: int(p.get("citationCount") or 0),
        reverse=True,
    )[:20]

    # Step 3 — full texts fetched in background (non-bloquant)
    # Le pipeline principal utilise uniquement les abstracts
    # Les full texts arrivent en cache silencieusement pour les prochaines requêtes
    fulltext_map: dict = {}
    for p in sorted_papers:
        pid = p.get("paperId", "")
        cached_ft = cache.get_fulltext(pid)
        if cached_ft:
            fulltext_map[pid] = cached_ft  # déjà en cache → utilisé immédiatement

    # Step 4 — analyse each paper
    results = []
    for i, paper in enumerate(sorted_papers):
        pid   = paper.get("paperId", "")
        title = paper.get("title", "Unknown")[:65]
        status.info(f"🧠 Analysing paper {i + 1}/{len(sorted_papers)}: *{title}…*")

        cached_analysis = cache.get_analysis(pid, claim)
        if cached_analysis is not None:
            results.append((paper, cached_analysis))
        else:
            fulltext = fulltext_map.get(pid)
            analysis = analyzer.analyze_paper(paper, claim, fulltext=fulltext)
            cache.set_analysis(pid, claim, analysis)
            results.append((paper, analysis))

    # Filter irrelevant
    relevant = [(p, a) for p, a in results if int(a.get("relevance_score") or 0) >= 3]
    if not relevant:
        relevant = results
    relevant.sort(key=lambda x: int(x[1].get("relevance_score") or 0), reverse=True)

    # Step 5 — overall verdict
    status.info("📊 Computing overall verdict…")
    overall = analyzer.overall_verdict(claim, relevant)
    status.empty()
    return relevant, overall

# ── Sidebar ───────────────────────────────────────────────────────────────────


with st.sidebar:
    st.title("⚙️ Configuration")

    provider   = os.getenv("LLM_PROVIDER", "groq").lower()
    _api_key   = _get_llm_api_key()
    _ss_key    = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    _extra     = _get_extra_keys()
    _model     = os.getenv("LLM_MODEL", "")

    _provider_labels = {
        "groq":   "🟢 Groq (gratuit)",
        "openai": "🔵 OpenAI (payant)",
        "gemini": "🟡 Google Gemini (gratuit)",
        "ollama": "🟣 Ollama (local)",
    }

    st.markdown("**🔑 API Keys**")
    st.markdown(f"LLM : {_provider_labels.get(provider, provider)}&nbsp;&nbsp;{'✅' if _api_key else '❌'}")
    st.markdown(f"Semantic Scholar : {'✅ Actif' if _ss_key else '⚠️ Non configuré (optionnel)'}")

    total_keys = 1 + len(_extra) if _api_key else len(_extra)
    if provider == "groq":
        from analyzer import ModelRotator
        total_models = total_keys * len(ModelRotator.GROQ_FALLBACKS)
        st.markdown(f"🔄 Pool : **{total_keys} clé(s)** · **{total_models} modèles** en rotation")
    if _model:
        st.markdown(f"🤖 Modèle primaire : `{_model}`")

    if not _api_key and provider != "ollama":
        st.error(
            f"Clé LLM manquante. Ajoute dans ton `.env` :\n\n"
            f"`{'OPENAI_API_KEY' if provider == 'openai' else 'LLM_API_KEY'}=ta_clé`"
        )

    st.divider()

    use_year = st.checkbox("Filtrer par année de publication")
    year_str = None
    if use_year:
        c1, c2 = st.columns(2)
        y_from = c1.number_input("De", min_value=1900, max_value=2026, value=2018)
        y_to   = c2.number_input("À",  min_value=1900, max_value=2026, value=2026)
        if y_from > y_to:
            st.warning("⚠️ L'année de début doit être inférieure à l'année de fin.")
        else:
            year_str = f"{y_from}-{y_to}"

    st.divider()

    try:
        _cm = CacheManager()
        s = _cm.stats()
        st.markdown("**📦 Cache local**")
        col_a, col_b = st.columns(2)
        col_a.metric("Recherches", s["searches"])
        col_b.metric("Analyses",   s["analyses"])
        col_a.metric("Papiers",    s["papers"])
        col_b.metric("Résumés",    s["summaries"])
        col_a.metric("Full texts", s.get("fulltexts", 0))  # ← ajoute cette ligne
        if st.button("🗑️ Vider le cache", use_container_width=True):
            _cm.clear()
            st.success("Cache vidé.")
            st.rerun()
    except Exception:
        pass


# ── Auth guard ────────────────────────────────────────────────────────────────


if not _get_llm_api_key() and os.getenv("LLM_PROVIDER", "groq").lower() != "ollama":
    st.warning("⚠️ Clé LLM manquante. Configure ton `.env` avec `LLM_API_KEY=ta_clé`.")
    st.stop()


scholar, analyzer, cache = get_clients()


if scholar is None:
    st.error("❌ Impossible d'initialiser les clients. Vérifie ton fichier `.env`.")
    st.stop()


# ── Mode selector ─────────────────────────────────────────────────────────────


mode = st.radio(
    "Mode",
    ["🔍 Evidence Finder", "📚 Literature Review", "📄 Paper Summarizer"],
    horizontal=True,
    label_visibility="collapsed",
)
st.divider()


# ══════════════════════════════════════════════════════════════════════════════
# MODE 1 — Evidence Finder
# ══════════════════════════════════════════════════════════════════════════════


if mode == "🔍 Evidence Finder":
    st.markdown("### What is your claim, question, or topic?")
    st.markdown(
        "<small>Examples: *\"Transformer models outperform RNNs for NLP\"* · "
        "*\"What are the limits of graph neural networks?\"* · "
        "*\"CRISPR for genetic disease treatment\"*</small>",
        unsafe_allow_html=True,
    )

    examples = [
        "Quantum computing improves combinatorial optimization",
        "Social media use causes depression in teenagers",
        "Large language models can reason about mathematics",
        "Deep learning surpasses radiologists in medical imaging",
    ]
    st.markdown("**Quick examples:**")
    ex_cols = st.columns(len(examples))
    for col, ex in zip(ex_cols, examples):
        if col.button(ex, use_container_width=True):
            st.session_state["example_claim"] = ex
            st.rerun()

    col_in, col_btn = st.columns([5, 1])
    with col_in:
        user_input = st.text_input(
            "Claim",
            value=st.session_state.get("example_claim", ""),
            label_visibility="collapsed",
            placeholder="Enter a claim, question, or topic…",
        )
    with col_btn:
        go = st.button("Search 🔍", type="primary", use_container_width=True)

    if "example_claim" in st.session_state and user_input:
        del st.session_state["example_claim"]

    if go and user_input:

        # ── Claim validation (pre-flight) ─────────────────────────────────────
        early_exit = analyzer.validate_claim(user_input)
        if early_exit is not None:
            st.markdown("## 📊 Overall Verdict")
            _render_overall_verdict(early_exit)
            st.stop()

        # ── Normal pipeline ───────────────────────────────────────────────────
        results, overall = run_search(user_input, scholar, analyzer, cache, year_str)

        if not results:
            st.error("No relevant papers found. Try rephrasing your query.")
            st.stop()

        st.markdown("## 📊 Overall Verdict")
        _render_overall_verdict(overall)

        st.markdown(f"## 📚 {len(results)} Papers Analysed")
        for i, (paper, analysis) in enumerate(results):
            render_paper_card(paper, analysis, i, expanded=(i < 2))

        st.divider()
        export = {
            "claim": user_input,
            "overall_verdict": overall,
            "papers": [
                {
                    "title":    p.get("title"),
                    "year":     p.get("year"),
                    "authors":  [a.get("name") for a in p.get("authors", [])],
                    "abstract": (p.get("abstract") or "")[:500],
                    "url":      f"https://www.semanticscholar.org/paper/{p.get('paperId', '')}",
                    "analysis": a,
                }
                for p, a in results
            ],
        }
        st.download_button(
            "📥 Export results as JSON",
            data=json.dumps(export, indent=2, default=str),
            file_name=f"evidence_{user_input[:40].replace(' ', '_')}.json",
            mime="application/json",
        )


# ══════════════════════════════════════════════════════════════════════════════
# MODE 2 — Literature Review
# ══════════════════════════════════════════════════════════════════════════════


elif mode == "📚 Literature Review":
    st.markdown("### Generate a literature review from retrieved papers")

    col_in, col_btn = st.columns([5, 1])
    with col_in:
        topic_input = st.text_input(
            "Topic",
            label_visibility="collapsed",
            placeholder="e.g. AI in healthcare diagnosis, climate change and biodiversity…",
        )
    with col_btn:
        go_lr = st.button("Generate 📚", type="primary", use_container_width=True)

    if go_lr and topic_input:
        results, _ = run_search(topic_input, scholar, analyzer, cache, year_str)
        if not results:
            st.error("No papers found. Try a different topic.")
            st.stop()

        with st.spinner("✍️ Writing literature review…"):
            review = analyzer.literature_review(topic_input, results)

        st.markdown("### 📖 Literature Review")
        st.markdown(review)
        st.divider()
        st.markdown("### 📚 Papers used")
        for i, (paper, analysis) in enumerate(results):
            render_paper_card(paper, analysis, i)

        st.download_button(
            "📥 Export as Markdown",
            data=f"# Literature Review: {topic_input}\n\n{review}",
            file_name=f"litreview_{topic_input[:30].replace(' ', '_')}.md",
            mime="text/markdown",
        )


# ══════════════════════════════════════════════════════════════════════════════
# MODE 3 — Paper Summarizer
# ══════════════════════════════════════════════════════════════════════════════


elif mode == "📄 Paper Summarizer":
    st.markdown("### Find and summarize a specific paper")

    col_in, col_btn = st.columns([5, 1])
    with col_in:
        paper_query = st.text_input(
            "Paper title or topic",
            label_visibility="collapsed",
            placeholder='e.g. "Attention Is All You Need", "AlphaFold protein structure prediction"',
        )
    with col_btn:
        go_sum = st.button("Find 🔎", type="primary", use_container_width=True)

    if go_sum and paper_query:
        with st.spinner("Searching…"):
            cached = cache.get_search(f"__sum__{paper_query}")
            if cached is not None:
                papers = cached
            else:
                papers = scholar.search(paper_query, limit=6)
                cache.set_search(f"__sum__{paper_query}", papers)

        if not papers:
            st.error("No papers found.")
            st.stop()

        options = {
            f"{p.get('title', 'Unknown')} ({p.get('year', 'N/A')})": p
            for p in papers if p.get("abstract")
        }
        if not options:
            st.error("None of the found papers have abstracts available.")
            st.stop()

        chosen_title = st.selectbox("Select a paper:", list(options.keys()))
        chosen_paper = options[chosen_title]

        if st.button("Summarize ✨", type="primary"):
            pid = chosen_paper.get("paperId", "")
            cached_sum = cache.get_summary(pid)
            if cached_sum:
                summary = cached_sum
            else:
                with st.spinner("Summarizing…"):
                    summary = analyzer.summarize(chosen_paper)
                    cache.set_summary(pid, summary)

            authors = [a.get("name", "") for a in chosen_paper.get("authors", [])[:5]]
            cites   = chosen_paper.get("citationCount")

            st.markdown(f"### 📄 {chosen_paper.get('title')}")
            meta = f"**Year:** {chosen_paper.get('year', 'N/A')}"
            if cites:
                meta += f"&nbsp;&nbsp;|&nbsp;&nbsp;**Citations:** {int(cites):,}"
            meta += f"&nbsp;&nbsp;|&nbsp;&nbsp;**Authors:** {', '.join(a for a in authors if a)}"
            st.markdown(meta)
            if pid:
                st.markdown(f"[🔗 View on Semantic Scholar](https://www.semanticscholar.org/paper/{pid})")

            st.divider()
            st.markdown("### 📋 Summary")
            st.markdown(summary)

            with st.expander("📄 Full abstract"):
                st.markdown(chosen_paper.get("abstract") or "*Not available.*")