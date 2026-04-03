import os
import time
import streamlit as st
from dotenv import load_dotenv
from scholar_client import SemanticScholarClient
from analyzer import PaperAnalyzer
from cache_manager import CacheManager

load_dotenv()

st.set_page_config(
    page_title="Academic Evidence Finder",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════════════
#  CSS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
  /* ── Verdict badges ── */
  .vbadge {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 8px;
    font-weight: 700;
    font-size: 0.88em;
    letter-spacing: 0.02em;
  }
  .v-supported    { background:#1a4731; color:#6fcf97; }
  .v-partial      { background:#4a3800; color:#f2c94c; }
  .v-contradicted { background:#4a1020; color:#eb5757; }
  .v-neutral      { background:#2d2d2d; color:#bdbdbd; }

  /* ── Overall verdict banner ── */
  .overall-banner {
    padding: 18px 22px;
    border-radius: 12px;
    margin: 14px 0;
    border-left: 5px solid;
  }
  .ob-supported    { background:#0d2b1d; border-color:#6fcf97; color:#e0f5eb; }
  .ob-partial      { background:#2a2000; border-color:#f2c94c; color:#fdf3d0; }
  .ob-contradicted { background:#2a0810; border-color:#eb5757; color:#fde0e0; }
  .ob-neutral      { background:#1e1e1e; border-color:#bdbdbd; color:#e0e0e0; }

  /* ── Metric pills ── */
  .mpill {
    display: inline-block;
    background: #2a2a2a;
    color: #e0e0e0;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.82em;
    margin-right: 6px;
  }

  /* ── Mode tabs custom ── */
  div[data-testid="stRadio"] > label {
    font-size: 0.95em;
  }

  /* ── Model indicator ── */
  .model-tag {
    background: #1a1a2e;
    color: #a78bfa;
    border: 1px solid #3d2e6e;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 0.8em;
    font-family: monospace;
    margin-top: 8px;
    display: block;
  }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════
VERDICT_ICON = {
    "SUPPORTS": "🟢", "PARTIALLY_SUPPORTS": "🟡",
    "CONTRADICTS": "🔴", "NEUTRAL": "⚪", "INSUFFICIENT_DATA": "⚫",
}
VERDICT_CSS = {
    "SUPPORTS": "v-supported", "PARTIALLY_SUPPORTS": "v-partial",
    "CONTRADICTS": "v-contradicted", "NEUTRAL": "v-neutral",
    "INSUFFICIENT_DATA": "v-neutral",
}
OVERALL_CSS = {
    "SUPPORTED": ("v-supported", "ob-supported"),
    "PARTIALLY_SUPPORTED": ("v-partial", "ob-partial"),
    "CONTRADICTED": ("v-contradicted", "ob-contradicted"),
    "MIXED": ("v-partial", "ob-partial"),
    "INSUFFICIENT_EVIDENCE": ("v-neutral", "ob-neutral"),
}
OVERALL_LABEL = {
    "SUPPORTED":             "✅ SUPPORTED BY LITERATURE",
    "PARTIALLY_SUPPORTED":   "⚠️ PARTIALLY SUPPORTED",
    "CONTRADICTED":          "❌ CONTRADICTED BY LITERATURE",
    "MIXED":                 "🔀 MIXED EVIDENCE",
    "INSUFFICIENT_EVIDENCE": "❓ INSUFFICIENT EVIDENCE",
}
PAPER_VERDICT_LABEL = {
    "SUPPORTS":          "✅ Supports the claim",
    "PARTIALLY_SUPPORTS":"⚠️ Partially supports",
    "CONTRADICTS":       "❌ Contradicts the claim",
    "NEUTRAL":           "➖ Neutral",
    "INSUFFICIENT_DATA": "❓ Insufficient data",
}

# ══════════════════════════════════════════════════════════════════════════════
#  CLIENTS
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_resource
def get_clients():
    provider   = os.getenv("LLM_PROVIDER", "groq").lower()
    api_key    = os.getenv("LLM_API_KEY", "")
    ss_key     = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    extra_keys = [os.getenv("LLM_API_KEY_" + str(i), "")
                  for i in range(2, 10) if os.getenv("LLM_API_KEY_" + str(i), "")]
    if not api_key and provider != "ollama":
        return None, None, None
    return (
        SemanticScholarClient(api_key=ss_key or None),
        PaperAnalyzer(api_key=api_key, provider=provider, extra_keys=extra_keys),
        CacheManager(),
    )

# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
def render_sidebar(cache: CacheManager, model_ph):
    with st.sidebar:
        st.markdown("## 🔬 Academic Evidence Finder")
        st.markdown("---")

        st.markdown("### ⚙️ Settings")
        max_papers  = st.slider("Max papers to analyse", 3, 15, 7)
        year_filter = st.text_input("Year filter (e.g. 2018-2024)", "")

        st.markdown("---")
        st.markdown("### 🤖 Active model")
        model_ph = st.empty()
        _refresh_sidebar(cache, model_ph)

        st.markdown("---")
        if st.button("🗑️ Clear cache", use_container_width=True):
            cache.clear()
            st.success("Cache cleared!")
            st.rerun()

    return max_papers, year_filter, model_ph

def _refresh_sidebar(cache: CacheManager, model_ph):
    stats = cache.stats()
    current = st.session_state.get("current_model", "—")
    model_ph.markdown(
        '<span class="model-tag">⚡ ' + current + '</span>'
        '<br><small style="color:#888">📦 '
        + str(stats.get("searches", 0)) + ' searches &nbsp;|&nbsp; '
        + str(stats.get("analyses", 0)) + ' analyses in cache</small>',
        unsafe_allow_html=True,
    )

# ══════════════════════════════════════════════════════════════════════════════
#  PAPER CARD
# ══════════════════════════════════════════════════════════════════════════════
def render_paper_card(paper: dict, analysis: dict, idx: int, analyzer: PaperAnalyzer, expanded: bool = False):
    title    = paper.get("title", "Unknown Title")
    year     = paper.get("year", "N/A")
    authors  = [a.get("name", "") for a in paper.get("authors", [])[:4]]
    author_s = ", ".join(a for a in authors if a)
    if len(paper.get("authors", [])) > 4:
        author_s += " et al."

    cites   = paper.get("citationCount")
    verdict = analysis.get("verdict", "INSUFFICIENT_DATA")
    icon    = VERDICT_ICON.get(verdict, "⚫")
    css     = VERDICT_CSS.get(verdict, "v-neutral")
    label   = PAPER_VERDICT_LABEL.get(verdict, verdict)
    score   = int(analysis.get("relevance_score") or 0)
    conf    = analysis.get("confidence", "LOW")
    evidence    = analysis.get("evidence",    "No evidence found.")
    explain     = analysis.get("explanation", "")
    finding     = analysis.get("key_finding", "")
    doi         = (paper.get("externalIds") or {}).get("DOI", "")
    url         = paper.get("url") or ("https://doi.org/" + doi if doi else "")
    abstract    = (paper.get("abstract") or "").strip()

    with st.expander(icon + " [" + str(idx + 1) + "] " + title + " (" + str(year) + ")", expanded=expanded):
        c1, c2, c3 = st.columns([3, 1, 1])
        with c1:
            st.markdown('<span class="vbadge ' + css + '">' + label + '</span>', unsafe_allow_html=True)
        with c2:
            if cites is not None:
                st.markdown('<span class="mpill">📚 ' + str(cites) + ' citations</span>', unsafe_allow_html=True)
        with c3:
            st.markdown('<span class="mpill">🎯 ' + str(score) + '/10</span>', unsafe_allow_html=True)

        meta = "👤 " + (author_s or "Unknown")
        if url:
            meta += " &nbsp;|&nbsp; 🔗 [DOI / Link](" + url + ")"
        st.caption(meta)

        if evidence and evidence not in ("No evidence found.", "Analysis could not be completed."):
            st.markdown("**📌 Evidence**")
            st.info(evidence)

        if explain:
            st.markdown("**🧠 Explanation**")
            st.write(explain)

        if finding and finding not in ("N/A", ""):
            st.markdown("**🔑 Key Finding**")
            st.success(finding)

        st.caption("Confidence: **" + conf + "**")

        if abstract:
            with st.expander("📄 Abstract"):
                st.write(abstract)

        # Per-paper summarizer
        skey = "sum_" + str(idx)
        if st.button("🔍 Summarize this paper", key="sbtn_" + str(idx)):
            with st.spinner("Summarizing…"):
                st.session_state[skey] = analyzer.summarize(paper)
        if skey in st.session_state:
            st.markdown(st.session_state[skey])

# ══════════════════════════════════════════════════════════════════════════════
#  FETCH + DEDUP
# ══════════════════════════════════════════════════════════════════════════════
def fetch_papers(queries, scholar, cache, max_papers, year_filter, status_ph):
    seen   = set()
    papers = []
    for q in queries:
        cached = cache.get_search(q)
        if cached:
            batch = cached
        else:
            status_ph.info("📡 Searching: *" + q + "*")
            batch = scholar.search(q, limit=max_papers, year=year_filter or None)
            if batch:
                cache.set_search(q, batch)
        for p in batch:
            pid = p.get("paperId", "")
            if pid and pid not in seen:
                seen.add(pid)
                papers.append(p)
    papers = sorted(papers, key=lambda p: p.get("citationCount") or 0, reverse=True)
    return papers[:max_papers]

# ══════════════════════════════════════════════════════════════════════════════
#  MODE 1 — CLAIM VERIFIER
# ══════════════════════════════════════════════════════════════════════════════
def run_claim_verifier(claim, scholar, analyzer, cache, max_papers, year_filter, model_ph):
    status = st.empty()

    # Validate
    early = analyzer.validate_claim(claim)
    if early:
        ov_key = early.get("overall_verdict", "INSUFFICIENT_EVIDENCE")
        badge_css, banner_css = OVERALL_CSS.get(ov_key, ("v-neutral", "ob-neutral"))
        lbl = OVERALL_LABEL.get(ov_key, ov_key)
        st.markdown('<div class="overall-banner ' + banner_css + '">'
                    '<span class="vbadge ' + badge_css + '" style="font-size:1.1em;">' + lbl + '</span>'
                    '<p style="margin:10px 0 0 0;">' + early.get("verdict_explanation", "") + '</p>'
                    '</div>', unsafe_allow_html=True)
        return

    # Query transform
    status.info("🔄 Transforming query…")
    queries = analyzer.transform_query(claim, max_papers=max_papers)
    st.session_state["current_model"] = analyzer.current_model
    _refresh_sidebar(cache, model_ph)
    st.caption("🔍 Search queries: " + " | ".join(queries))

    # Fetch
    papers = fetch_papers(queries, scholar, cache, max_papers, year_filter, status)
    if not papers:
        status.error("No papers found. Try rephrasing your claim.")
        return

    status.info("📄 " + str(len(papers)) + " papers found — analysing…")

    # Analyse
    results = []
    prog    = st.progress(0)
    for i, paper in enumerate(papers):
        pid   = paper.get("paperId", "")
        title = (paper.get("title") or "")[:60]
        status.info("🧠 Analysing " + str(i+1) + "/" + str(len(papers)) + ": *" + title + "…*")
        cached_a = cache.get_analysis(pid, claim)
        if cached_a is not None:
            analysis = cached_a
        else:
            analysis = analyzer.analyze_paper(paper, claim)
            cache.set_analysis(pid, claim, analysis)
        results.append((paper, analysis))
        st.session_state["current_model"] = analyzer.current_model
        _refresh_sidebar(cache, model_ph)
        prog.progress((i + 1) / len(papers))

    # Retry with alternative queries if too few relevant papers found
    relevant_count = sum(
        1 for _, a in results
        if a.get("verdict") not in ("NEUTRAL", "INSUFFICIENT_DATA")
    )

    # Si moins de 2 papiers pertinents et qu'on n'a pas déjà retenté
    if relevant_count < 2 and not st.session_state.get("retried_" + claim[:30]):
        st.session_state["retried_" + claim[:30]] = True
        status.warning(
            "⚠️ Too few relevant papers found — retrying with alternative queries…"
        )
        # Forcer de nouvelles queries différentes
        alt_queries = analyzer.transform_query(
            claim + " randomized controlled trial meta-analysis review",
            max_papers=max_papers
        )
        extra_papers = fetch_papers(alt_queries, scholar, cache, max_papers, year_filter, status)
        # Fusionner en évitant les doublons
        existing_ids = {p.get("paperId") for p, _ in results}
        for paper in extra_papers:
            pid = paper.get("paperId", "")
            if pid and pid not in existing_ids:
                existing_ids.add(pid)
                analysis = analyzer.analyze_paper(paper, claim)
                cache.set_analysis(pid, claim, analysis)
                results.append((paper, analysis))

    prog.empty()
    status.info("⚖️ Synthesizing verdict from " + str(len(results)) + " papers… this can take 10-15s")
    
    # Overall verdict
    overall = analyzer.overall_verdict(claim, results)
    st.session_state["current_model"] = analyzer.current_model
    _refresh_sidebar(cache, model_ph)
    status.empty()

    ov_key = overall.get("overall_verdict", "INSUFFICIENT_EVIDENCE")
    badge_css, banner_css = OVERALL_CSS.get(ov_key, ("v-neutral", "ob-neutral"))
    lbl = OVERALL_LABEL.get(ov_key, ov_key)

    st.markdown("---")
    st.markdown(
        '<div class="overall-banner ' + banner_css + '">'
        '<span class="vbadge ' + badge_css + '" style="font-size:1.15em;">' + lbl + '</span>'
        '<p style="margin:12px 0 6px 0;">' + overall.get("verdict_explanation", "") + '</p>'
        '<span class="mpill">🟢 Supporting: ' + str(overall.get("supporting_count", 0)) + '</span>'
        '<span class="mpill">🔴 Contradicting: ' + str(overall.get("contradicting_count", 0)) + '</span>'
        '<span class="mpill">⚪ Neutral/Unclear: ' + str(overall.get("neutral_count", 0)) + '</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # Sépare pertinents et non-pertinents
    relevant_results = [
        (p, a) for p, a in results
        if a.get("verdict") not in ("NEUTRAL", "INSUFFICIENT_DATA")
        or a.get("relevance_score", 0) >= 5
    ]
    other_results = [
        (p, a) for p, a in results
        if (p, a) not in relevant_results
    ]

    # Affiche les pertinents en premier
    st.subheader("📄 " + str(len(relevant_results)) + " Directly Relevant Papers")
    for i, (paper, analysis) in enumerate(relevant_results):
        render_paper_card(paper, analysis, i, analyzer, expanded=(i == 0))

    # Les autres dans un expander collapsed
    if other_results:
        with st.expander(
            "🔘 " + str(len(other_results)) + " Low-relevance papers (excluded from verdict)"
        ):
            for i, (paper, analysis) in enumerate(other_results):
                render_paper_card(paper, analysis, len(relevant_results) + i, analyzer, expanded=False)

    # Literature review
    st.markdown("---")
    with st.expander("📝 Generate Literature Review from these papers"):
        if st.button("Generate literature review", key="litrev_btn"):
            with st.spinner("Writing literature review…"):
                review = analyzer.literature_review(claim, results)
            st.session_state["litrev"] = review
        if "litrev" in st.session_state:
            st.markdown(st.session_state["litrev"])

# ══════════════════════════════════════════════════════════════════════════════
#  MODE 2 — LITERATURE REVIEW
# ══════════════════════════════════════════════════════════════════════════════
def run_literature_review(topic, scholar, analyzer, cache, max_papers, year_filter, model_ph):
    status = st.empty()

    status.info("🔄 Building search strategy…")
    queries = analyzer.transform_query(topic, topic_mode=True, max_papers=max_papers)
    st.session_state["current_model"] = analyzer.current_model
    _refresh_sidebar(cache, model_ph)
    st.caption("🔍 Search queries: " + " | ".join(queries))

    papers = fetch_papers(queries, scholar, cache, max_papers, year_filter, status)
    if not papers:
        status.error("No papers found. Try a different topic.")
        return

    status.info("🧠 Analysing " + str(len(papers)) + " papers…")
    results = []
    prog    = st.progress(0)
    for i, paper in enumerate(papers):
        pid      = paper.get("paperId", "")
        cached_a = cache.get_analysis(pid, topic)
        if cached_a is not None:
            analysis = cached_a
        else:
            analysis = analyzer.analyze_paper(paper, topic)
            cache.set_analysis(pid, topic, analysis)
        results.append((paper, analysis))
        st.session_state["current_model"] = analyzer.current_model
        _refresh_sidebar(cache, model_ph)
        prog.progress((i + 1) / len(papers))

    prog.empty()
    status.info("✍️ Writing literature review…")
    review = analyzer.literature_review(topic, results)
    st.session_state["current_model"] = analyzer.current_model
    _refresh_sidebar(cache, model_ph)
    status.empty()

    st.markdown("---")
    st.subheader("📝 Literature Review: " + topic)
    st.markdown(review)

    st.markdown("---")
    st.subheader("📄 " + str(len(results)) + " Source Papers")
    for i, (paper, analysis) in enumerate(results):
        render_paper_card(paper, analysis, i, analyzer, expanded=False)

# ══════════════════════════════════════════════════════════════════════════════
#  MODE 3 — PAPER SUMMARIZER
# ══════════════════════════════════════════════════════════════════════════════
def run_paper_summarizer(topic, scholar, analyzer, cache, max_papers, year_filter, model_ph):
    status = st.empty()

    status.info("🔍 Searching papers…")
    queries = analyzer.transform_query(topic, topic_mode=True, max_papers=max_papers)
    st.session_state["current_model"] = analyzer.current_model
    _refresh_sidebar(cache, model_ph)
    st.caption("🔍 Search queries: " + " | ".join(queries))

    papers = fetch_papers(queries, scholar, cache, max_papers, year_filter, status)
    if not papers:
        status.error("No papers found.")
        return

    status.empty()
    st.subheader("📄 " + str(len(papers)) + " Papers on: " + topic)
    st.info("Click **Summarize** on any paper to generate a detailed summary.")

    for i, paper in enumerate(papers):
        title   = paper.get("title", "Unknown Title")
        year    = paper.get("year", "N/A")
        authors = [a.get("name", "") for a in paper.get("authors", [])[:3]]
        auth_s  = ", ".join(a for a in authors if a)
        if len(paper.get("authors", [])) > 3:
            auth_s += " et al."
        cites    = paper.get("citationCount")
        abstract = (paper.get("abstract") or "").strip()
        doi      = (paper.get("externalIds") or {}).get("DOI", "")
        url      = paper.get("url") or ("https://doi.org/" + doi if doi else "")

        with st.expander("📄 [" + str(i+1) + "] " + title + " (" + str(year) + ")", expanded=(i == 0)):
            meta = "👤 " + (auth_s or "Unknown")
            if cites is not None:
                meta += " &nbsp;|&nbsp; 📚 " + str(cites) + " citations"
            if url:
                meta += " &nbsp;|&nbsp; 🔗 [Link](" + url + ")"
            st.caption(meta)

            if abstract:
                with st.expander("📜 Abstract"):
                    st.write(abstract)

            skey = "psum_" + str(i)
            if st.button("🔍 Summarize", key="psbtn_" + str(i)):
                with st.spinner("Summarizing…"):
                    st.session_state[skey] = analyzer.summarize(paper)
                st.session_state["current_model"] = analyzer.current_model
                _refresh_sidebar(cache, model_ph)
            if skey in st.session_state:
                st.markdown(st.session_state[skey])

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    scholar, analyzer, cache = get_clients()

    if not scholar:
        st.error("⚠️ LLM_API_KEY not set. Add it to your .env file.")
        st.code("LLM_API_KEY=gsk_...\nLLM_PROVIDER=groq")
        st.stop()

    # Sidebar
    with st.sidebar:
        st.markdown("## 🔬 Academic Evidence Finder")
        st.markdown("---")
        st.markdown("### ⚙️ Settings")
        max_papers  = st.slider("Max papers to analyse", 3, 15, 7)
        year_filter = st.text_input("Year filter (e.g. 2018-2024)", "")
        st.markdown("---")
        st.markdown("### 🤖 Active model")
        model_ph = st.empty()
        _refresh_sidebar(cache, model_ph)
        st.markdown("---")
        if st.button("🗑️ Clear cache", use_container_width=True):
            cache.clear()
            st.success("Cache cleared!")
            st.rerun()

    # Header
    st.title("🔬 Academic Evidence Finder")
    st.markdown("*Verify claims, explore literature and summarize papers — powered by AI + Semantic Scholar*")
    st.markdown("---")

    # Mode selector
    mode = st.radio(
        "Select mode:",
        ["🔬 Claim Verifier", "📚 Literature Review", "📄 Paper Summarizer"],
        horizontal=True,
    )
    st.markdown("")

    if mode == "🔬 Claim Verifier":
        st.markdown("##### Enter a falsifiable scientific claim to verify against the literature")
        claim = st.text_input(
            "Claim:",
            placeholder="e.g. Coffee consumption reduces the risk of Parkinson's disease",
            label_visibility="collapsed",
        )
        col1, col2 = st.columns([1, 6])
        with col1:
            go = st.button("🔍 Analyse", type="primary", use_container_width=True)
        with col2:
            if claim:
                st.caption('Claim: *"' + claim + '"*')
        if go and claim.strip():
            run_claim_verifier(claim.strip(), scholar, analyzer, cache, max_papers, year_filter, model_ph)
        elif go:
            st.warning("Please enter a claim.")

    elif mode == "📚 Literature Review":
        st.markdown("##### Enter a research topic to generate an academic literature review")
        topic = st.text_input(
            "Topic:",
            placeholder="e.g. Gut microbiome and mental health",
            label_visibility="collapsed",
        )
        col1, col2 = st.columns([1, 6])
        with col1:
            go = st.button("📝 Generate Review", type="primary", use_container_width=True)
        with col2:
            if topic:
                st.caption('Topic: *"' + topic + '"*')
        if go and topic.strip():
            run_literature_review(topic.strip(), scholar, analyzer, cache, max_papers, year_filter, model_ph)
        elif go:
            st.warning("Please enter a topic.")

    elif mode == "📄 Paper Summarizer":
        st.markdown("##### Enter a topic or keywords to find and summarize relevant papers")
        topic = st.text_input(
            "Topic / Keywords:",
            placeholder="e.g. CRISPR gene editing cancer therapy",
            label_visibility="collapsed",
        )
        col1, col2 = st.columns([1, 6])
        with col1:
            go = st.button("🔎 Find Papers", type="primary", use_container_width=True)
        with col2:
            if topic:
                st.caption('Searching: *"' + topic + '"*')
        if go and topic.strip():
            run_paper_summarizer(topic.strip(), scholar, analyzer, cache, max_papers, year_filter, model_ph)
        elif go:
            st.warning("Please enter a topic.")

if __name__ == "__main__":
    main()
