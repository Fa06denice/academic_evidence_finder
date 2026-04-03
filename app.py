import os
import streamlit as st
import streamlit.components.v1 as components
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

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* ═══════════════════════════════════════════════
   CHROME
═══════════════════════════════════════════════ */
#MainMenu { visibility: hidden !important; }
footer { visibility: hidden !important; }
[data-testid="stDecoration"] { display: none !important; }
.stDeployButton { display: none !important; }
[data-testid="stToolbarActionButtonIcon"] { display: none !important; }
[data-testid="stAppDeployButton"] { display: none !important; }

header[data-testid="stHeader"] {
    background: transparent !important;
    border: none !important;
}

[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapsedControl"] button,
button[data-testid="stBaseButton-headerNoPadding"],
button[data-testid="stBaseButton-header"] {
    display: flex !important;
    visibility: visible !important;
    opacity: 1 !important;
    background: #6366f1 !important;
    color: #ffffff !important;
    border-radius: 0 8px 8px 0 !important;
    min-width: 28px !important;
    min-height: 40px !important;
    z-index: 99999 !important;
    border: none !important;
    position: fixed !important;
    left: 0 !important;
    top: 0.75rem !important;
    transform: none !important;
}
button[data-testid="stBaseButton-headerNoPadding"] svg,
button[data-testid="stBaseButton-header"] svg {
    stroke: #ffffff !important;
    fill: #ffffff !important;
}

/* ═══════════════════════════════════════════════
   FOND GLOBAL
═══════════════════════════════════════════════ */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="block-container"] {
    background: #0d0f14 !important;
}

[data-testid="stMain"] {
    background:
        radial-gradient(ellipse 60% 40% at 0% 0%, rgba(99,102,241,0.09), transparent),
        #0d0f14 !important;
}

[data-testid="block-container"] {
    max-width: 1100px;
    padding-top: 2rem;
}

/* ═══════════════════════════════════════════════
   TYPOGRAPHIE
═══════════════════════════════════════════════ */
h1 {
    font-size: 1.7rem !important;
    font-weight: 700 !important;
    color: #f1f0ee !important;
    letter-spacing: -0.03em;
    margin-bottom: 4px;
}
h2, h3, h4 {
    color: #e2e4ea !important;
    letter-spacing: -0.02em;
}
p, li {
    color: #9ca3af;
}

/* ═══════════════════════════════════════════════
   SIDEBAR
═══════════════════════════════════════════════ */
section[data-testid="stSidebar"] {
    background: #13151d !important;
    border-right: 1px solid rgba(255,255,255,0.07) !important;
}
section[data-testid="stSidebar"] * {
    color: #c9ccd4 !important;
}
section[data-testid="stSidebar"] strong,
section[data-testid="stSidebar"] b {
    color: #f1f0ee !important;
}
.sidebar-logo {
    font-size: 1rem;
    font-weight: 700;
    color: #f1f0ee !important;
    padding: 4px 0 16px 0;
}
.sidebar-model-box {
    background: rgba(99,102,241,0.1);
    border: 1px solid rgba(99,102,241,0.25);
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 0.8rem;
    color: #a5b4fc !important;
    font-weight: 500;
    word-break: break-all;
    margin: 6px 0 10px 0;
}
.sidebar-cache-box {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 0.8rem;
    color: #6b7280 !important;
    margin-top: 4px;
}

/* ═══════════════════════════════════════════════
   TABS
═══════════════════════════════════════════════ */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: #151820;
    border-radius: 10px;
    padding: 4px;
    border: 1px solid rgba(255,255,255,0.06);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    font-size: 0.88rem;
    font-weight: 500;
    padding: 8px 20px;
    color: #6b7280 !important;
    background: transparent !important;
}
.stTabs [aria-selected="true"] {
    background: #252836 !important;
    color: #f1f0ee !important;
    font-weight: 600 !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}

/* ═══════════════════════════════════════════════
   INPUTS
═══════════════════════════════════════════════ */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    border-radius: 10px !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    background: #171a22 !important;
    color: #f3f4f6 !important;
    font-size: 0.95rem !important;
}
.stTextInput > div > div > input::placeholder,
.stTextArea > div > div > textarea::placeholder {
    color: #4b5263 !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.15) !important;
}

/* ═══════════════════════════════════════════════
   BOUTONS
═══════════════════════════════════════════════ */
.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    transition: all 0.15s ease !important;
}
.stButton > button[data-testid="baseButton-primary"] {
    background: linear-gradient(180deg, #6366f1 0%, #4f46e5 100%) !important;
    color: #ffffff !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    box-shadow: 0 8px 20px rgba(79,70,229,0.3) !important;
}
.stButton > button[data-testid="baseButton-primary"]:hover {
    transform: translateY(-1px);
    box-shadow: 0 12px 28px rgba(79,70,229,0.38) !important;
}
.stButton > button[data-testid="baseButton-secondary"] {
    background: #1a1d26 !important;
    color: #e2e4ea !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
}
.stButton > button[data-testid="baseButton-secondary"]:hover {
    border-color: rgba(255,255,255,0.16) !important;
    background: #1e2130 !important;
}

/* ═══════════════════════════════════════════════
   EXPANDERS
═══════════════════════════════════════════════ */
div[data-testid="stExpander"] {
    background: #151820;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 12px;
    margin-bottom: 10px;
    overflow: hidden;
}
div[data-testid="stExpander"] summary {
    background: #151820;
    color: #c9ccd4 !important;
    font-size: 0.9rem;
    font-weight: 500;
    padding: 12px 16px;
}
div[data-testid="stExpander"] summary:hover {
    background: #1c2030;
}
div[data-testid="stExpander"] > div[data-testid="stExpanderDetails"] {
    background: #151820;
    padding: 4px 16px 16px 16px;
}

/* ═══════════════════════════════════════════════
   VERDICT BANNERS
═══════════════════════════════════════════════ */
.ob-supported, .ob-contradicted, .ob-partial, .ob-neutral {
    border-radius: 12px;
    padding: 22px 28px;
    margin: 20px 0 24px 0;
    border: 1px solid transparent;
    border-left-width: 5px;
    border-left-style: solid;
}
.ob-supported    { background: rgba(22,163,74,0.08);   border-color: rgba(22,163,74,0.2);   border-left-color: #22c55e; }
.ob-contradicted { background: rgba(220,38,38,0.08);   border-color: rgba(220,38,38,0.2);   border-left-color: #ef4444; }
.ob-partial      { background: rgba(217,119,6,0.08);   border-color: rgba(217,119,6,0.2);   border-left-color: #f59e0b; }
.ob-neutral      { background: rgba(99,102,241,0.05);  border-color: rgba(99,102,241,0.15); border-left-color: #6366f1; }

.ob-title { font-size: 1rem; font-weight: 700; letter-spacing: 0.03em; margin-bottom: 10px; }
.ob-supported .ob-title    { color: #4ade80; }
.ob-contradicted .ob-title { color: #f87171; }
.ob-partial .ob-title      { color: #fbbf24; }
.ob-neutral .ob-title      { color: #a5b4fc; }

.ob-explanation {
    font-size: 0.93rem;
    line-height: 1.7;
    color: #9ca3af;
    margin-bottom: 14px;
}
.ob-counts {
    display: flex;
    gap: 20px;
    font-size: 0.82rem;
    font-weight: 500;
    color: #6b7280;
    flex-wrap: wrap;
}
.ob-counts span { display: flex; align-items: center; gap: 5px; }

/* ═══════════════════════════════════════════════
   PAPER BADGES
═══════════════════════════════════════════════ */
.v-supported, .v-partial, .v-contradicted, .v-neutral {
    display: inline-block;
    border-radius: 20px;
    padding: 3px 13px;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.01em;
    border: 1px solid transparent;
}
.v-supported    { background: rgba(22,163,74,0.12);  color: #4ade80; border-color: rgba(22,163,74,0.25); }
.v-partial      { background: rgba(245,158,11,0.12); color: #fbbf24; border-color: rgba(245,158,11,0.25); }
.v-contradicted { background: rgba(239,68,68,0.12);  color: #f87171; border-color: rgba(239,68,68,0.25); }
.v-neutral      { background: rgba(99,102,241,0.08); color: #a5b4fc; border-color: rgba(99,102,241,0.2); }

/* ═══════════════════════════════════════════════
   CHIPS
═══════════════════════════════════════════════ */
.chip {
    display: inline-block;
    background: rgba(255,255,255,0.05);
    color: #8890a4;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 20px;
    padding: 2px 11px;
    font-size: 0.77rem;
    font-weight: 500;
    margin-right: 6px;
}
.chip-blue  { background: rgba(99,102,241,0.1); color: #a5b4fc; border-color: rgba(99,102,241,0.2); }
.chip-green { background: rgba(22,163,74,0.1);  color: #6ee7b7; border-color: rgba(22,163,74,0.2); }

/* ═══════════════════════════════════════════════
   BLOCS CONTENU
═══════════════════════════════════════════════ */
.evidence-block {
    background: rgba(99,102,241,0.07);
    border-left: 3px solid #6366f1;
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    font-size: 0.88rem;
    font-style: italic;
    color: #a5b4fc;
    margin: 10px 0;
    line-height: 1.65;
}
.explanation-block {
    background: rgba(255,255,255,0.03);
    border-left: 3px solid rgba(255,255,255,0.12);
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    font-size: 0.88rem;
    color: #9ca3af;
    margin: 10px 0;
    line-height: 1.65;
}
.finding-block {
    background: rgba(22,163,74,0.08);
    border-left: 3px solid #22c55e;
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    font-size: 0.88rem;
    color: #6ee7b7;
    margin: 10px 0;
    line-height: 1.65;
}

/* ═══════════════════════════════════════════════
   SECTION HEADER
═══════════════════════════════════════════════ */
.section-header {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #3d4454;
    margin: 22px 0 6px 0;
}

/* ═══════════════════════════════════════════════
   PROGRESS + SLIDER
═══════════════════════════════════════════════ */
.stProgress > div > div > div {
    background: #6366f1 !important;
    border-radius: 4px;
}
[data-baseweb="slider"] [data-testid="stSliderThumb"],
.stSlider [role="slider"] {
    background: #6366f1 !important;
    border-color: #6366f1 !important;
}

/* ═══════════════════════════════════════════════
   EMPTY STATE
═══════════════════════════════════════════════ */
.empty-state {
    text-align: center;
    padding: 60px 20px;
    color: #3d4454;
}
.empty-state h3 {
    font-size: 1rem;
    font-weight: 600;
    color: #6b7280;
    margin-bottom: 8px;
}
.empty-state p {
    font-size: 0.88rem;
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
    "SUPPORTED":            ("v-supported",    "ob-supported"),
    "PARTIALLY_SUPPORTED":  ("v-partial",      "ob-partial"),
    "CONTRADICTED":         ("v-contradicted", "ob-contradicted"),
    "MIXED":                ("v-partial",      "ob-partial"),
    "INSUFFICIENT_EVIDENCE":("v-neutral",      "ob-neutral"),
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
        st.markdown(
            '<div class="sidebar-logo">🔬 Academic Evidence Finder</div>',
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.markdown("**⚙️ Search settings**")
        max_papers  = st.slider("Max papers to analyse", 3, 15, 7)
        year_filter = st.text_input("Year filter (e.g. 2018-2024)", "")
        st.markdown("---")
        st.markdown("**🤖 Active model**")
        model_ph = st.empty()
        _refresh_sidebar(cache, model_ph)
        st.markdown("---")
        if st.button("🗑️ Clear cache", use_container_width=True):
            cache.clear()
            st.success("Cache cleared!")
            st.rerun()
    return max_papers, year_filter, model_ph


def _refresh_sidebar(cache: CacheManager, model_ph):
    stats   = cache.stats()
    current = st.session_state.get("current_model", "—")
    model_ph.markdown(
        '<div class="sidebar-model-box">⚡ ' + current + '</div>'
        '<div class="sidebar-cache-box">'
        '📦 ' + str(stats.get("searches", 0)) + ' searches &nbsp;·&nbsp; '
        + str(stats.get("analyses", 0)) + ' analyses cached'
        '</div>',
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
    cites    = paper.get("citationCount")
    verdict  = analysis.get("verdict", "INSUFFICIENT_DATA")
    icon     = VERDICT_ICON.get(verdict, "⚫")
    css      = VERDICT_CSS.get(verdict, "v-neutral")
    label    = PAPER_VERDICT_LABEL.get(verdict, verdict)
    score    = int(analysis.get("relevance_score") or 0)
    conf     = analysis.get("confidence", "LOW")
    evidence = analysis.get("evidence", "No evidence found.")
    explain  = analysis.get("explanation", "")
    finding  = analysis.get("key_finding", "")
    doi      = (paper.get("externalIds") or {}).get("DOI", "")
    url      = paper.get("url") or ("https://doi.org/" + doi if doi else "")
    abstract = (paper.get("abstract") or "").strip()

    expander_label = icon + " [" + str(idx + 1) + "] " + title + "  (" + str(year) + ")"
    with st.expander(expander_label, expanded=expanded):
        chips_html = (
            '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px;">'
            '<span class="' + css + '">' + label + '</span>'
        )
        if cites is not None:
            chips_html += '<span class="chip">📚 ' + str(cites) + ' citations</span>'
        chips_html += '<span class="chip chip-blue">🎯 ' + str(score) + '/10</span>'
        chips_html += '<span class="chip">🔒 ' + conf + '</span>'
        chips_html += '</div>'
        st.markdown(chips_html, unsafe_allow_html=True)

        meta = "👤 " + (author_s or "Unknown")
        if url:
            meta += "  ·  🔗 [DOI / Link](" + url + ")"
        st.caption(meta)

        st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

        if evidence and evidence not in ("No evidence found.", "Analysis could not be completed."):
            st.markdown('<div class="section-header">📌 Evidence</div>', unsafe_allow_html=True)
            st.markdown('<div class="evidence-block">' + evidence + '</div>', unsafe_allow_html=True)

        if explain:
            st.markdown('<div class="section-header">🧠 Explanation</div>', unsafe_allow_html=True)
            st.markdown('<div class="explanation-block">' + explain + '</div>', unsafe_allow_html=True)

        if finding and finding not in ("N/A", ""):
            st.markdown('<div class="section-header">🔑 Key Finding</div>', unsafe_allow_html=True)
            st.markdown('<div class="finding-block">' + finding + '</div>', unsafe_allow_html=True)

        if abstract:
            with st.expander("📄 Abstract"):
                st.write(abstract)

        st.markdown('<div style="height:4px;"></div>', unsafe_allow_html=True)
        skey = "sum_" + str(idx)
        if st.button("🔍 Summarize this paper", key="sbtn_" + str(idx)):
            with st.spinner("Generating summary…"):
                st.session_state[skey] = analyzer.summarize(paper)
        if skey in st.session_state:
            st.markdown(st.session_state[skey])


# ══════════════════════════════════════════════════════════════════════════════
#  FETCH + DEDUP
# ══════════════════════════════════════════════════════════════════════════════
def fetch_papers(queries, scholar, cache, max_papers, year_filter, status_ph):
    seen, papers = set(), []
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

    early = analyzer.validate_claim(claim)
    if early:
        ov_key                = early.get("overall_verdict", "INSUFFICIENT_EVIDENCE")
        badge_css, banner_css = OVERALL_CSS.get(ov_key, ("v-neutral", "ob-neutral"))
        lbl                   = OVERALL_LABEL.get(ov_key, ov_key)
        st.markdown(
            '<div class="' + banner_css + '">'
            '<div class="ob-title">' + lbl + '</div>'
            '<div class="ob-explanation">' + early.get("verdict_explanation", "") + '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    status.info("🔍 Generating search queries…")
    queries = analyzer.transform_query(claim, topic_mode=False, max_papers=max_papers)
    st.session_state["current_model"] = analyzer.current_model
    _refresh_sidebar(cache, model_ph)

    papers = fetch_papers(queries, scholar, cache, max_papers, year_filter, status)
    if not papers:
        status.empty()
        st.markdown(
            '<div class="empty-state">'
            '<h3>No papers found</h3>'
            '<p>Try rephrasing your claim or adjusting the year filter.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    status.info("🧠 Analysing " + str(len(papers)) + " papers…")

    results, low_rel = [], []
    prog = st.progress(0, text="Analysing papers…")
    for i, paper in enumerate(papers):
        pid = paper.get("paperId", "")
        cached_analysis = cache.get_analysis(pid, claim)
        if cached_analysis:
            analysis = cached_analysis
        else:
            analysis = analyzer.analyze_paper(paper, claim)
            if pid:
                cache.set_analysis(pid, claim, analysis)
        st.session_state["current_model"] = analyzer.current_model
        _refresh_sidebar(cache, model_ph)
        prog.progress((i + 1) / len(papers), text="Analysing paper " + str(i + 1) + "/" + str(len(papers)) + "…")
        if analysis.get("relevance_score", 0) >= 5:
            results.append((paper, analysis))
        else:
            low_rel.append((paper, analysis))

    prog.empty()

    status.info("⚖️ Synthesizing verdict from " + str(len(results)) + " relevant papers…")
    overall = analyzer.overall_verdict(claim, results)
    st.session_state["current_model"] = analyzer.current_model
    _refresh_sidebar(cache, model_ph)
    status.empty()

    ov_key                = overall.get("overall_verdict", "INSUFFICIENT_EVIDENCE")
    badge_css, banner_css = OVERALL_CSS.get(ov_key, ("v-neutral", "ob-neutral"))
    lbl                   = OVERALL_LABEL.get(ov_key, ov_key)
    explanation           = overall.get("verdict_explanation", "")
    sup                   = overall.get("supporting_count", 0)
    con                   = overall.get("contradicting_count", 0)
    neu                   = overall.get("neutral_count", 0)

    st.markdown(
        '<div class="' + banner_css + '">'
        '<div class="ob-title">' + lbl + '</div>'
        '<div class="ob-explanation">' + explanation + '</div>'
        '<div class="ob-counts">'
        '<span>🟢 Supporting: ' + str(sup) + '</span>'
        '<span>🔴 Contradicting: ' + str(con) + '</span>'
        '<span>⚪ Neutral/Unclear: ' + str(neu) + '</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    if results:
        st.markdown(
            '<div class="section-header">📄 ' + str(len(results)) + ' Directly Relevant Papers</div>',
            unsafe_allow_html=True,
        )
        for i, (paper, analysis) in enumerate(results):
            render_paper_card(paper, analysis, i, analyzer)

    if low_rel:
        with st.expander("🔘 " + str(len(low_rel)) + " Low-relevance papers (excluded from verdict)"):
            for i, (paper, analysis) in enumerate(low_rel):
                render_paper_card(paper, analysis, len(results) + i, analyzer)

    if results:
        st.markdown("---")
        if st.button("📝 Generate Literature Review from these papers", use_container_width=True):
            with st.spinner("Writing literature review…"):
                review = analyzer.literature_review(claim, results)
            st.markdown(review)


# ══════════════════════════════════════════════════════════════════════════════
#  MODE 2 — LITERATURE REVIEW
# ══════════════════════════════════════════════════════════════════════════════
def run_literature_review(topic, scholar, analyzer, cache, max_papers, year_filter, model_ph):
    status = st.empty()

    status.info("🔍 Generating search queries…")
    queries = analyzer.transform_query(topic, topic_mode=True, max_papers=max_papers)
    st.session_state["current_model"] = analyzer.current_model
    _refresh_sidebar(cache, model_ph)

    papers = fetch_papers(queries, scholar, cache, max_papers, year_filter, status)
    if not papers:
        status.empty()
        st.markdown(
            '<div class="empty-state">'
            '<h3>No papers found</h3>'
            '<p>Try rephrasing the topic or adjusting the year filter.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    status.info("🧠 Analysing " + str(len(papers)) + " papers…")
    results = []
    prog    = st.progress(0, text="Analysing papers…")
    for i, paper in enumerate(papers):
        pid = paper.get("paperId", "")
        cached_analysis = cache.get_analysis(pid, topic)
        if cached_analysis:
            analysis = cached_analysis
        else:
            analysis = analyzer.analyze_paper(paper, topic)
            if pid:
                cache.set_analysis(pid, topic, analysis)
        st.session_state["current_model"] = analyzer.current_model
        _refresh_sidebar(cache, model_ph)
        prog.progress((i + 1) / len(papers), text="Analysing paper " + str(i + 1) + "/" + str(len(papers)) + "…")
        results.append((paper, analysis))

    prog.empty()
    status.info("✍️ Writing literature review…")
    review = analyzer.literature_review(topic, results)
    st.session_state["current_model"] = analyzer.current_model
    _refresh_sidebar(cache, model_ph)
    status.empty()

    st.markdown(review)
    st.markdown("---")
    st.markdown(
        '<div class="section-header">📄 Papers used in this review</div>',
        unsafe_allow_html=True,
    )
    for i, (paper, analysis) in enumerate(results):
        render_paper_card(paper, analysis, i, analyzer)


# ══════════════════════════════════════════════════════════════════════════════
#  MODE 3 — PAPER SUMMARIZER
# ══════════════════════════════════════════════════════════════════════════════
def run_summarizer(topic, scholar, analyzer, cache, max_papers, year_filter, model_ph):
    status = st.empty()

    status.info("🔍 Generating search queries…")
    queries = analyzer.transform_query(topic, topic_mode=True, max_papers=max_papers)
    st.session_state["current_model"] = analyzer.current_model
    _refresh_sidebar(cache, model_ph)

    papers = fetch_papers(queries, scholar, cache, max_papers, year_filter, status)
    if not papers:
        status.empty()
        st.markdown(
            '<div class="empty-state">'
            '<h3>No papers found</h3>'
            '<p>Try rephrasing your search topic.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    status.empty()
    st.markdown(
        '<div class="section-header">📄 ' + str(len(papers)) + ' Papers found</div>',
        unsafe_allow_html=True,
    )

    for i, paper in enumerate(papers):
        pid   = paper.get("paperId", "")
        title = paper.get("title", "Unknown Title")
        year  = paper.get("year", "N/A")
        with st.expander("📄 [" + str(i + 1) + "] " + title + " (" + str(year) + ")"):
            skey = "sum_topic_" + str(i)
            if st.button("🔍 Summarize", key="sum_btn_" + str(i)):
                with st.spinner("Generating summary…"):
                    cached = cache.get_summary(pid)
                    if cached:
                        st.session_state[skey] = cached
                    else:
                        summary = analyzer.summarize(paper)
                        if pid:
                            cache.set_summary(pid, summary)
                        st.session_state[skey] = summary
                st.session_state["current_model"] = analyzer.current_model
                _refresh_sidebar(cache, model_ph)
            if skey in st.session_state:
                st.markdown(st.session_state[skey])


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    scholar, analyzer, cache = get_clients()
    model_ph = st.empty()

    if scholar is None:
        st.error("⚠️ No API key found. Set `LLM_API_KEY` in your `.env` file.")
        st.stop()

    max_papers, year_filter, model_ph = render_sidebar(cache, model_ph)

    # JS sidebar auto-open — une seule fois par session
    if not st.session_state.get("_sidebar_js_done"):
        st.session_state["_sidebar_js_done"] = True
        components.html("""
<script>
(function() {
    function tryOpen() {
        var doc = window.parent.document;
        var selectors = [
            '[data-testid="stSidebarCollapsedControl"] button',
            'button[data-testid="stBaseButton-headerNoPadding"]',
            'button[data-testid="stBaseButton-header"]'
        ];
        for (var i = 0; i < selectors.length; i++) {
            var btn = doc.querySelector(selectors[i]);
            if (btn) { btn.click(); return; }
        }
        setTimeout(tryOpen, 300);
    }
    setTimeout(tryOpen, 500);
})();
</script>
""", height=0)

    st.markdown(
        '<h1 style="font-size:1.7rem;font-weight:700;color:#f1f0ee;margin-bottom:4px;">'
        '🔬 Academic Evidence Finder</h1>'
        '<p style="color:#6b7280;font-size:0.92rem;margin-bottom:24px;">'
        'Verify scientific claims and explore academic literature with AI-powered analysis.</p>',
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs(["🧪 Claim Verifier", "📚 Literature Review", "📄 Paper Summarizer"])

    with tab1:
        st.markdown(
            '<p style="color:#6b7280;font-size:0.88rem;margin-bottom:12px;">'
            'Enter a scientific claim and get a verdict backed by peer-reviewed papers.</p>',
            unsafe_allow_html=True,
        )
        claim = st.text_input(
            "Scientific claim",
            placeholder="e.g. Intermittent fasting improves insulin sensitivity in type 2 diabetics",
            label_visibility="collapsed",
        )
        if st.button("🔍 Verify claim", type="primary", use_container_width=True, key="btn_claim"):
            if claim.strip():
                run_claim_verifier(claim.strip(), scholar, analyzer, cache, max_papers, year_filter, model_ph)
            else:
                st.warning("Please enter a claim to verify.")

    with tab2:
        st.markdown(
            '<p style="color:#6b7280;font-size:0.88rem;margin-bottom:12px;">'
            'Enter a research topic and get a structured academic literature review.</p>',
            unsafe_allow_html=True,
        )
        topic_review = st.text_input(
            "Research topic",
            placeholder="e.g. Gut microbiome and mental health",
            label_visibility="collapsed",
            key="inp_review",
        )
        if st.button("📚 Generate review", type="primary", use_container_width=True, key="btn_review"):
            if topic_review.strip():
                run_literature_review(topic_review.strip(), scholar, analyzer, cache, max_papers, year_filter, model_ph)
            else:
                st.warning("Please enter a research topic.")

    with tab3:
        st.markdown(
            '<p style="color:#6b7280;font-size:0.88rem;margin-bottom:12px;">'
            'Search papers by topic and summarize individual ones on demand.</p>',
            unsafe_allow_html=True,
        )
        topic_sum = st.text_input(
            "Search topic",
            placeholder="e.g. CRISPR base editing cancer therapy",
            label_visibility="collapsed",
            key="inp_sum",
        )
        if st.button("🔎 Search papers", type="primary", use_container_width=True, key="btn_sum"):
            if topic_sum.strip():
                run_summarizer(topic_sum.strip(), scholar, analyzer, cache, max_papers, year_filter, model_ph)
            else:
                st.warning("Please enter a search topic.")


if __name__ == "__main__":
    main()
