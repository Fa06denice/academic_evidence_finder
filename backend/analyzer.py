import json
import logging
import os
import re
import time
from typing import List, Optional, Tuple
from openai import OpenAI

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
#  PROMPTS — V5 (2-pass chain-of-thought architecture)
# ═══════════════════════════════════════════════════════════════════════════════

# ---------------------------------------------------------------------------
# PASS 1 — Factual extraction (no judgment)
# Goal : lock down WHAT the paper says before any claim comparison.
# ~350 tokens of instructions. Short, focused, no examples needed.
# ---------------------------------------------------------------------------
_PAPER_EXTRACT = """\
You are a scientific fact extractor. Read the abstract below and return a \
JSON object with four fields. Do NOT evaluate any claim. Do NOT express any opinion. \
Only report what the abstract explicitly states.

PAPER:
  Title:    {title}
  Year:     {year}
  Authors:  {authors}
  Abstract: {abstract}
  TL;DR:    {tldr}

Required JSON fields:

  "main_finding" : The single most important empirical result of this paper, \
in one sentence. Quote verbatim if possible, otherwise paraphrase tightly. \
Do NOT include author opinions or implications — only the measured result.

  "direction"    : The comparative direction the data shows. Choose exactly one:
    "A_beats_B"    → the paper’s primary subject outperforms the comparison.
    "B_beats_A"    → the comparison outperforms the primary subject.
    "no_difference"→ the paper shows no significant difference, no speedup,
                      no advantage, comparable results, or failed to find an effect.
    "no_comparison"→ the paper does not directly compare two systems/groups.

  "conditions"   : Any scope limitations on the result (specific task, hardware,
 population, circuit type, time window, dose). Write "none" if the result is general.

  "evidence_quote": The single most informative sentence from the abstract \
that best supports the main_finding. Copy verbatim.

Return ONLY a raw JSON object. No markdown, no code fences, no extra text.
"""

# ---------------------------------------------------------------------------
# PASS 2 — Verdict (judgment only, extraction already done)
# Goal : compare the locked finding against the claim. Short, sharp rules.
# ~400 tokens of instructions.
# ---------------------------------------------------------------------------
_PAPER_VERDICT = """\
You are an academic evidence analyst. A factual extraction has already been done \
for a scientific paper. Your only job is to decide whether that finding \
SUPPORTS, CONTRADICTS, or is UNRELATED to the claim below.

CLAIM: {claim}

EXTRACTED FINDING:
  main_finding   : {main_finding}
  direction      : {direction}
  conditions     : {conditions}
  evidence_quote : {evidence_quote}

━━━ DECISION RULES ━━━

First, identify the claim’s direction:
  Subject A = the entity the claim favours.
  Object  B = the entity the claim says is worse/less/ineffective.
  Direction = A > B, A causes B, A prevents B, etc.

Then apply these rules IN ORDER — stop at the first that matches:

1. OFF-TOPIC
   The paper does not study the same phenomenon as the claim.
   → NEUTRAL, relevance_score ≤ 2.

2. NO ADVANTAGE FOR B (direction = "no_difference" or "no_comparison" without B winning)
   The paper failed to show B outperforms A, or found no significant difference.
   When claim says A > B:
   → SUPPORTS if no conditions, or PARTIALLY_SUPPORTS if narrow conditions.
   CRITICAL: This is NOT CONTRADICTS. Absence of B’s advantage = support for A’s claim.

3. B GENUINELY BEATS A (direction = "B_beats_A")
   The paper’s data shows B > A.
   When claim says A > B:
   → CONTRADICTS if same general context.
   → PARTIALLY_SUPPORTS if conditions are very narrow (single task type, specific hardware,
     limited population) and the claim is general.

4. A GENUINELY BEATS B (direction = "A_beats_B")
   When claim says A > B:
   → SUPPORTS if no major conditions, PARTIALLY_SUPPORTS if narrow conditions.

5. NO COMPARISON / INDIRECT
   Paper discusses the topic but makes no direct A vs B comparison.
   → NEUTRAL.

CONFIDENCE:
  HIGH   → finding directly and unambiguously addresses the claim, same context.
  MEDIUM → finding is indirect, conditional, or partially relevant.
  LOW    → weak link, very narrow scope, or finding is speculative.

COHERENCE CHECK (before writing JSON):
  Re-read your explanation. Your "verdict" field MUST match what your
  explanation concludes. Fix the verdict if there is any conflict.

━━━ OUTPUT ━━━

Return ONLY a raw JSON object. No markdown. No code fences.
Required keys:
  "verdict"        : SUPPORTS | PARTIALLY_SUPPORTS | CONTRADICTS | NEUTRAL | INSUFFICIENT_DATA
  "confidence"     : HIGH | MEDIUM | LOW
  "relevance_score": integer 0-10
  "explanation"    : 2 sentences — (1) state the paper’s direction explicitly,
                     (2) explain whether that matches or opposes the claim direction.
"""

# ---------------------------------------------------------------------------
# Other prompts (unchanged from V4)
# ---------------------------------------------------------------------------

_QUERY_TRANSFORM = """\
You are a senior academic librarian with expertise in systematic literature search.
Your task: convert a scientific claim into {n_queries} DISTINCT, high-yield Semantic Scholar queries.

CLAIM: {user_input}

STRATEGY:
- Query 1: direct translation of the claim into keywords (most specific).
- Query 2: the core mechanism, variable, or intervention being tested.
- Query 3: the broader epidemiological / clinical / scientific context.
- Query 4+ (if requested): alternative phrasings, related outcomes, or methodological angles
  that would surface papers a different audience might have published.

HARD RULES:
- All queries in English regardless of claim language.
- Preserve exact medical/scientific terms — never paraphrase or generalize.
- 3 to 7 words per query. No stopwords, no punctuation.
- All queries must be meaningfully different from each other.
- If the claim contains a comparison (e.g. "no more than", "better than", "compared to",
  "versus"), ALWAYS include the comparator explicitly in at least one query.
- If the claim is a comparative (A vs B), generate queries for BOTH sides.
  Example: "Quantum computing outperforms classical computing"
  → "quantum advantage classical simulation comparison"
  → "classical algorithms competitive quantum circuits benchmark"

Return ONLY a valid JSON array of exactly {n_queries} strings.
"""

_OVERALL_VERDICT = """\
You are a senior scientist synthesizing evidence from multiple peer-reviewed papers \
to issue a final verdict on a scientific claim.

CLAIM: {claim}

INDIVIDUAL PAPER ANALYSES:
{analyses_text}

━━━ TASK ━━━

1. CLAIM DIRECTION: identify Subject A, Object B, and direction (A > B? A causes B?).

2. CONSISTENCY CHECK — for each paper, verify verdict matches its explanation:
   - explanation says "no B advantage" + claim is "A > B" → should be SUPPORTS, not CONTRADICTS.
   - explanation says "B beats A" + claim is "A > B" → should be CONTRADICTS, not SUPPORTS.
   - Fix mislabelled verdicts before counting.

3. Count by CORRECTED verdict:
   Supporting   = SUPPORTS + PARTIALLY_SUPPORTS
   Contradicting= CONTRADICTS
   Neutral      = NEUTRAL + INSUFFICIENT_DATA

4. Weigh quality: HIGH confidence > LOW; high relevance_score counts more.
   One strong direct CONTRADICTS can outweigh several weak PARTIALLY_SUPPORTS.

5. Verdict rules (apply in order):
   SUPPORTED            → clear majority confirm claim, direct evidence, same context.
   PARTIALLY_SUPPORTED  → more support than contradiction but with caveats or scope limits.
   CONTRADICTED         → majority or key high-quality papers oppose the claim.
   MIXED                → roughly equal on both sides — genuine scientific debate.
   INSUFFICIENT_EVIDENCE→ LAST RESORT: fewer than 2 papers have a concrete verdict.

6. Overall confidence:
   HIGH   → multiple HIGH papers agree, little contradiction.
   MEDIUM → mostly indirect or partially relevant.
   LOW    → very few relevant papers or highly mixed.

━━━ OUTPUT ━━━

Return ONLY a raw JSON object. No markdown. No code fences.
Required keys:
  "overall_verdict"     : SUPPORTED | PARTIALLY_SUPPORTED | CONTRADICTED | MIXED | INSUFFICIENT_EVIDENCE
  "overall_confidence"  : HIGH | MEDIUM | LOW
  "verdict_explanation" : 3 sentences — synthesize evidence, cite 2-3 paper titles by name
  "supporting_count"    : integer (after corrections)
  "contradicting_count" : integer (after corrections)
  "neutral_count"       : integer
"""

_LITERATURE_REVIEW = """\
You are a senior academic researcher writing a rigorous literature review for a \
peer-reviewed journal. Use ONLY the papers provided below. Do not cite or invent \
any other sources.

TOPIC: {topic}

PAPERS:
{papers_text}

━━━ STRUCTURE ━━━

**1. Introduction** (1 paragraph)
Introduce the research area, explain why it matters, state the scope.

**2. Main Findings** (2-3 paragraphs)
Group papers thematically. Highlight consensus and disagreement.
Cite relevant papers. Note sample sizes or effect sizes if mentioned.

**3. Methodological Considerations** (1 paragraph)
Study designs, populations, key limitations.

**4. State of Evidence & Open Questions** (1 paragraph)
Overall evidence strength, gaps, and most important unanswered questions.

━━━ STYLE ━━━
- Cite as [First Author et al., Year] inline.
- Formal academic register. No bullet points.
- Minimum 400 words.
"""

_SUMMARIZE = """\
You are an expert academic research assistant. Produce a thorough, structured summary \
of the paper below, based STRICTLY on the provided abstract. \
Do NOT add external knowledge or invent details.

Title:    {title}
Year:     {year}
Authors:  {authors}
Abstract: {abstract}

━━━ REQUIRED STRUCTURE ━━━

**🎯 Objective** — What question does this study address? What gap does it fill?

**🔬 Methodology** — Study design, population, intervention, outcome measures. Include numbers.

**📊 Key Findings** — Main results with exact numbers, p-values, effect sizes if present.

**⚠️ Limitations** — Explicitly mentioned limitations, or "Not reported in abstract."

**💡 Why It Matters** — Scientific significance and practical implications.

━━━ RULES ━━━
- Stay strictly within what the abstract says.
- Never use vague phrases like "the study found interesting results."
"""

_TOPIC_QUERIES = """\
You are a senior academic librarian with expertise in systematic literature search.
Your task: generate {n_queries} DISTINCT, high-yield Semantic Scholar search queries for the topic below.

TOPIC: {topic}

STRATEGY:
- Query 1: core concept and main keywords (most specific).
- Query 2: specific subtopic, mechanism, or clinical application.
- Query 3: broader scientific or clinical context — still within the field.
- Query 4+: alternative angles, populations, or methodological variations.

RULES:
- English only. 3–7 keywords each. No stopwords.
- Queries must be meaningfully different from each other.
- Stay TIGHTLY scoped to the topic. No adjacent fields.

Return ONLY a valid JSON array of exactly {n_queries} strings.
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'```[a-zA-Z]*\n?', '', raw).strip()
    raw = raw.rstrip('`').strip()
    for open_c, close_c in [('{', '}'), ('[', ']')]:
        start = raw.find(open_c)
        end   = raw.rfind(close_c)
        if start != -1 and end != -1 and end > start:
            return raw[start:end + 1]
    return raw

def _author_str(paper: dict, max_authors: int = 3) -> str:
    authors = paper.get("authors", [])
    names   = [a.get("name", "") for a in authors[:max_authors]]
    result  = ", ".join(n for n in names if n)
    if len(authors) > max_authors:
        result += " et al."
    return result or "Unknown"

def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _extract_content(resp) -> Optional[str]:
    try:
        content = resp.choices[0].message.content
        if content is not None:
            return content
    except Exception:
        pass
    try:
        data  = resp.model_dump()
        first = (data.get("choices") or [{}])[0]
        if isinstance(first, dict):
            return first.get("message", {}).get("content")
    except Exception:
        pass
    logger.warning("_extract_content returned None — resp type: %s, raw: %s", type(resp).__name__, str(resp)[:400])
    return None

_VERB_RE = re.compile(
    r"\b(is|are|was|were|be|been|being|has|have|had|do|does|did|will|would|shall|should|"
    r"may|might|must|can|could|cause[sd]?|reduce[sd]?|increase[sd]?|improve[sd]?|affect[sd]?|"
    r"prevent[sd]?|treat[sd]?|lead[sd]?|show[sn]?|suggest[sd]?|support[sd]?|outperform[sd]?|"
    r"surpass|enhance[sd]?|decrease[sd]?|induce[sd]?|inhibit[sd]?|promote[sd]?|link[sd]?|"
    r"associat|correlat|est|sont|ont|peut|peuvent|cause|reduit|augmente|ameliore|provoque)\b",
    re.IGNORECASE,
)

def _is_vague_claim(claim: str) -> bool:
    if len(claim.strip().split()) >= 4:
        return False
    return not bool(_VERB_RE.search(claim))

# ═══════════════════════════════════════════════════════════════════════════════
#  MODEL ROTATOR
# ═══════════════════════════════════════════════════════════════════════════════

class ModelRotator:
    GROQ_FALLBACKS = [
        "qwen/qwen3-32b",
        "llama-3.3-70b-versatile",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ]

    def __init__(self, pool: list):
        self.pool        = pool
        self.index       = 0
        self.fail_counts = [0] * len(pool)

    @property
    def current(self) -> tuple:
        return self.pool[self.index]

    @property
    def current_label(self) -> str:
        return self.pool[self.index][2]

    def rotate(self):
        self.fail_counts[self.index] += 1
        original = self.index
        for _ in range(len(self.pool)):
            self.index = (self.index + 1) % len(self.pool)
            if self.fail_counts[self.index] < 3:
                logger.info("Rotated to: %s", self.pool[self.index][2])
                return
        logger.warning("All models hit limits — resetting.")
        self.fail_counts = [0] * len(self.pool)
        self.index       = (original + 1) % len(self.pool)

    def success(self):
        self.fail_counts[self.index] = 0

# ═══════════════════════════════════════════════════════════════════════════════
#  PAPER ANALYZER
# ═══════════════════════════════════════════════════════════════════════════════

class PaperAnalyzer:
    PROVIDERS = {
        "openai": {"base_url": None,                                                        "default_model": "gpt-4o-mini"},
        "groq":   {"base_url": "https://api.groq.com/openai/v1",                           "default_model": "moonshotai/kimi-k2-instruct"},
        "ollama": {"base_url": "http://localhost:11434/v1",                                 "default_model": "llama3.2"},
        "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "default_model": "gemini-2.0-flash"},
    }
    VALID_VERDICTS = {"SUPPORTS", "PARTIALLY_SUPPORTS", "CONTRADICTS", "NEUTRAL", "INSUFFICIENT_DATA"}
    VALID_OVERALL  = {"SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "MIXED", "INSUFFICIENT_EVIDENCE"}
    VALID_CONF     = {"HIGH", "MEDIUM", "LOW"}
    VALID_DIRECTIONS = {"A_beats_B", "B_beats_A", "no_difference", "no_comparison"}

    def __init__(self, api_key: str, provider: str = "groq", model: str = None, extra_keys: list = None):
        cfg        = self.PROVIDERS.get(provider, self.PROVIDERS["groq"])
        base_url   = cfg["base_url"]
        base_model = model or os.getenv("LLM_MODEL") or cfg["default_model"]

        def _make(key, mdl, label):
            kw = {"api_key": key or "ollama"}
            if base_url:
                kw["base_url"] = base_url
            return (OpenAI(**kw), mdl, label)

        pool = [_make(api_key, base_model, provider + "/" + base_model + " [primary]")]
        if provider == "groq":
            for alt in ModelRotator.GROQ_FALLBACKS:
                if alt != base_model:
                    pool.append(_make(api_key, alt, "groq/" + alt))
        for i, k in enumerate(extra_keys or []):
            if k:
                pool.append(_make(k, base_model, provider + "/" + base_model + " [key" + str(i+1) + "]"))

        self.rotator  = ModelRotator(pool)
        self.provider = provider

    @property
    def current_model(self) -> str:
        return self.rotator.current_label

    def validate_claim(self, claim: str) -> Optional[dict]:
        claim = claim.strip()
        if not claim:
            return self._norm_overall({"overall_verdict": "INSUFFICIENT_EVIDENCE",
                                       "overall_confidence": "LOW",
                                       "verdict_explanation": "No claim was provided.",
                                       "supporting_count": 0, "contradicting_count": 0, "neutral_count": 0})
        if _is_vague_claim(claim):
            return self._norm_overall({
                "overall_verdict": "INSUFFICIENT_EVIDENCE",
                "overall_confidence": "LOW",
                "verdict_explanation": (
                    'The input "' + claim + '" is too vague to evaluate scientifically. '
                    "Please enter a full sentence with subject + verb + specific assertion. "
                    'Example: "Vitamin D supplementation reduces depression symptoms."'
                ),
                "supporting_count": 0, "contradicting_count": 0, "neutral_count": 0})
        return None

    def _llm(self, prompt: str, temperature: float = 0.1, max_tokens: int = 1000) -> str:
        attempts = len(self.rotator.pool) * 2
        for i in range(attempts):
            client, model, label = self.rotator.current
            try:
                resp    = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = _extract_content(resp)
                if content:
                    self.rotator.success()
                    return content.strip()
                logger.warning("Empty content from %s — rotating.", label)
                self.rotator.rotate()
            except Exception as e:
                err     = str(e)
                is_rate = "429" in err or "rate_limit" in err.lower() or "ratelimitexceeded" in err.lower()
                logger.error("Attempt %d/%d %s rate=%s %s", i+1, attempts, label, is_rate, err[:200])
                self.rotator.rotate()
                if is_rate:
                    time.sleep(2)
        raise ValueError("All models exhausted after " + str(attempts) + " attempts.")

    def _parse(self, raw: str, fallback: dict) -> dict:
        try:
            return json.loads(_clean_json(raw))
        except json.JSONDecodeError:
            logger.error("JSON parse failed. Raw: %s", raw[:300])
            return fallback

    def _norm_analysis(self, d: dict) -> dict:
        return {
            "verdict":         d.get("verdict",       "INSUFFICIENT_DATA") if d.get("verdict")   in self.VALID_VERDICTS else "INSUFFICIENT_DATA",
            "confidence":      d.get("confidence",    "LOW")               if d.get("confidence") in self.VALID_CONF     else "LOW",
            "relevance_score": _safe_int(d.get("relevance_score"), 0),
            "evidence":        str(d.get("evidence")    or d.get("evidence_quote") or "No evidence found."),
            "explanation":     str(d.get("explanation") or ""),
            "key_finding":     str(d.get("key_finding") or d.get("main_finding") or "N/A"),
        }

    def _norm_overall(self, d: dict) -> dict:
        return {
            "overall_verdict":     d.get("overall_verdict", "INSUFFICIENT_EVIDENCE") if d.get("overall_verdict") in self.VALID_OVERALL else "INSUFFICIENT_EVIDENCE",
            "overall_confidence":  d.get("overall_confidence", "LOW") if d.get("overall_confidence") in self.VALID_CONF else "LOW",
            "verdict_explanation": str(d.get("verdict_explanation") or ""),
            "supporting_count":    _safe_int(d.get("supporting_count"),    0),
            "contradicting_count": _safe_int(d.get("contradicting_count"), 0),
            "neutral_count":       _safe_int(d.get("neutral_count"),       0),
        }

    def transform_query(self, user_input: str, topic_mode: bool = False, max_papers: int = 7) -> List[str]:
        if max_papers <= 6:
            n_queries = 3
        elif max_papers <= 10:
            n_queries = 4
        else:
            n_queries = 5

        template = _TOPIC_QUERIES if topic_mode else _QUERY_TRANSFORM
        key      = "topic" if topic_mode else "user_input"
        try:
            raw     = self._llm(template.format(**{key: user_input, "n_queries": n_queries}), temperature=0.2)
            queries = json.loads(_clean_json(raw))
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                return [q.strip() for q in queries[:n_queries] if q.strip()]
        except Exception as exc:
            logger.warning("Query transform failed: %s", exc)
        return [user_input]

    def analyze_paper(self, paper: dict, claim: str) -> dict:
        """2-pass chain-of-thought: extract finding first, then judge against claim."""
        abstract = (paper.get("abstract") or "").strip()
        if len(abstract) < 80:
            return self._norm_analysis({
                "verdict": "INSUFFICIENT_DATA", "confidence": "LOW", "relevance_score": 0,
                "evidence": "Abstract too short or unavailable.",
                "explanation": "Not enough content to evaluate this paper.",
                "key_finding": "N/A",
            })

        tldr_obj  = paper.get("tldr") or {}
        tldr_text = tldr_obj.get("text", "Not available") if isinstance(tldr_obj, dict) else "Not available"
        common = dict(
            title   = paper.get("title", "Unknown"),
            year    = paper.get("year", "Unknown"),
            authors = _author_str(paper),
            abstract= abstract[:2500],
            tldr    = tldr_text,
        )

        extract_fallback = {
            "main_finding":   "Could not extract finding.",
            "direction":      "no_comparison",
            "conditions":     "unknown",
            "evidence_quote": "",
        }
        verdict_fallback = {
            "verdict": "INSUFFICIENT_DATA", "confidence": "LOW",
            "relevance_score": 1, "explanation": "LLM analysis failed.",
        }

        # --- Pass 1: factual extraction ---
        try:
            raw1       = self._llm(_PAPER_EXTRACT.format(**common), temperature=0.1, max_tokens=400)
            extraction = self._parse(raw1, extract_fallback)
        except Exception as exc:
            logger.error("Pass 1 failed for '%s': %s", common["title"], exc)
            extraction = extract_fallback

        # Sanitise direction field
        if extraction.get("direction") not in self.VALID_DIRECTIONS:
            extraction["direction"] = "no_comparison"

        # --- Pass 2: verdict ---
        try:
            raw2   = self._llm(
                _PAPER_VERDICT.format(
                    claim         = claim,
                    main_finding  = extraction.get("main_finding",   "N/A"),
                    direction     = extraction.get("direction",       "no_comparison"),
                    conditions    = extraction.get("conditions",      "none"),
                    evidence_quote= extraction.get("evidence_quote",  ""),
                ),
                temperature=0.1, max_tokens=500,
            )
            verdict_data = self._parse(raw2, verdict_fallback)
        except Exception as exc:
            logger.error("Pass 2 failed for '%s': %s", common["title"], exc)
            verdict_data = verdict_fallback

        # Merge extraction fields into final result for display
        merged = {
            **verdict_data,
            "evidence":    extraction.get("evidence_quote") or "No evidence found.",
            "key_finding": extraction.get("main_finding")   or "N/A",
        }
        return self._norm_analysis(merged)

    def overall_verdict(self, claim: str, results: List[Tuple[dict, dict]]) -> dict:
        if not results:
            return self._norm_overall({"overall_verdict": "INSUFFICIENT_EVIDENCE",
                                       "overall_confidence": "LOW",
                                       "verdict_explanation": "No papers with sufficient content were retrieved.",
                                       "supporting_count": 0, "contradicting_count": 0, "neutral_count": 0})
        lines = []
        for paper, analysis in results:
            lines.append(
                "Paper: " + paper.get("title", "Unknown") + "\n"
                "  Verdict: "     + analysis.get("verdict",     "N/A") + "\n"
                "  Confidence: "  + analysis.get("confidence",  "N/A") + "\n"
                "  Key Finding: " + analysis.get("key_finding", "N/A") + "\n"
                "  Evidence: "    + analysis.get("evidence",    "N/A") + "\n"
                "  Explanation: " + analysis.get("explanation", "N/A")
            )
        fallback = {
            "overall_verdict": "MIXED",
            "overall_confidence": "LOW",
            "verdict_explanation": "Could not synthesize automatically.",
            "supporting_count":    sum(1 for _, a in results if a.get("verdict") in {"SUPPORTS", "PARTIALLY_SUPPORTS"}),
            "contradicting_count": sum(1 for _, a in results if a.get("verdict") == "CONTRADICTS"),
            "neutral_count":       sum(1 for _, a in results if a.get("verdict") in {"NEUTRAL", "INSUFFICIENT_DATA"}),
        }
        prompt = _OVERALL_VERDICT.format(claim=claim, analyses_text="\n\n".join(lines))
        return self._norm_overall(self._parse(self._llm(prompt, temperature=0.1), fallback))

    def literature_review(self, topic: str, results: List[Tuple[dict, dict]]) -> str:
        papers_text = ""
        for paper, analysis in results:
            papers_text += (
                "\n---\n"
                "Title:    " + paper.get("title", "Unknown") + "\n"
                "Authors:  " + _author_str(paper) + "\n"
                "Year:     " + str(paper.get("year", "N/A")) + "\n"
                "Abstract: " + (paper.get("abstract") or "")[:800] + "\n"
                "Key Finding: " + analysis.get("key_finding", "N/A") + "\n"
            )
        try:
            return self._llm(_LITERATURE_REVIEW.format(topic=topic, papers_text=papers_text),
                             temperature=0.3, max_tokens=2000)
        except Exception as exc:
            return "Literature review generation failed: " + str(exc)

    def summarize(self, paper: dict) -> str:
        abstract = (paper.get("abstract") or "").strip()
        if not abstract:
            return "No abstract available — cannot summarize."
        try:
            return self._llm(
                _SUMMARIZE.format(
                    title   = paper.get("title", "Unknown"),
                    year    = paper.get("year", "N/A"),
                    authors = _author_str(paper, max_authors=5),
                    abstract= abstract[:3000],
                ),
                temperature=0.2, max_tokens=900,
            )
        except Exception as exc:
            return "Summarization failed: " + str(exc)
