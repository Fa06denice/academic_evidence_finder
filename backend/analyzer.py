import json
import logging
import os
import re
import time
import itertools
import threading
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple
from openai import OpenAI

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

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
- ANCHOR RULE — CRITICAL: Every single query MUST include BOTH:
    (1) the intervention / subject of the claim (e.g. "caffeine", "coffee", "vitamin D")
    (2) the outcome / object of the claim (e.g. "sleep", "depression", "mortality")
  Never query the outcome alone without the intervention, and never query the
  intervention alone without the outcome. A query like "sleep quality" or "caffeine"
  in isolation is FORBIDDEN when the claim is about "coffee and sleep".
  EXAMPLE: claim = "coffee is beneficial for sleep"
    GOOD: "caffeine sleep quality RCT", "coffee sleep latency humans", "caffeine sleep deprivation"
    BAD:  "sleep quality adults", "caffeine cognitive function", "melatonin sleep" (wrong intervention)
- If the claim contains a comparison (e.g. "no more than", "better than", "compared to",
  "versus"), ALWAYS include the comparator explicitly in at least one query.
- If the claim is a comparative (A vs B), generate queries for BOTH sides of the comparison
  so that papers supporting either direction are retrieved.

Return ONLY a valid JSON array of exactly {n_queries} strings.
"""

_PAPER_ANALYSIS = """\
You are a rigorous academic evidence analyst. Your task is to assess whether a \
scientific paper SUPPORTS, CONTRADICTS, or is UNRELATED to a specific claim.

CLAIM: {claim}

PAPER:
  Title:    {title}
  Year:     {year}
  Authors:  {authors}
  Abstract: {abstract}
  TL;DR:    {tldr}

━━━ MANDATORY PRE-ANALYSIS: CLAIM DECOMPOSITION ━━━

Before choosing a verdict, explicitly answer these three questions in your head:

  Q1. DIRECTION: What does the claim assert? Identify:
      - The subject/intervention (A), the outcome/object (B), and the direction
      - Does the claim say A improves B, A causes B, A prevents B, A > B, etc.?
      Example: "Coffee is beneficial for sleep"
        → Intervention=Coffee/caffeine, Outcome=sleep quality/duration, Direction=coffee improves sleep

  Q2. PAPER FINDING: What does THIS paper actually measure and conclude?
      - Does the paper MEASURE the same outcome (B) as the claim?
      - If the paper does NOT measure outcome B at all → go to Q3 with "outcome not measured".
      - CRITICAL — NEGATION INVERSION: Does the paper study the ABSENCE or WITHDRAWAL of A
        (e.g. "abstinence from caffeine", "caffeine-free", "without X", "X withdrawal") and
        find that outcome B WORSENS? If yes, by logical inversion this SUPPORTS "A improves B".
        Always resolve the double negation before comparing to the claim:
          "absence of A → worse B"  ≡  "A → better B"  → compare THAT to the claim.
          "absence of A → better B" ≡  "A → worse B"   → compare THAT to the claim.
      - If it does measure B directly: does it show A improves B, A worsens B, or no effect?

  Q3. ALIGNMENT:
      - If the paper does NOT measure the claim's outcome → NEUTRAL (outcome mismatch)
      - If the resolved finding shows A improves B (same direction as claim) → SUPPORTS or PARTIALLY_SUPPORTS
      - If the resolved finding shows A worsens B or A has no effect on B → CONTRADICTS or PARTIALLY_SUPPORTS
      - If the paper is about A vs B but doesn't quantify the direction → NEUTRAL

━━━ ANALYSIS PROTOCOL ━━━

STEP 1 — RELEVANCE CHECK
Does this paper study the same population, intervention, condition, or phenomenon \
as the claim? If completely off-topic, assign NEUTRAL with relevance_score <= 2.

STEP 2 — EVIDENCE EXTRACTION
Find the single most informative sentence in the abstract that relates to the claim. \
Use it verbatim as your "evidence" field. If no single sentence is perfect, \
use the closest paraphrase in quotes.

STEP 3 — VERDICT (choose the MOST ACCURATE — do not default to safe options)
  SUPPORTS           → The paper EXPLICITLY measures the claim's outcome AND confirms the
                       claim in the SAME direction, same population. This includes papers
                       that study the ABSENCE/WITHDRAWAL of A and find outcome B WORSENS
                       (logical double-negation inversion: "no A → worse B" = "A → better B").
  PARTIALLY_SUPPORTS → Related evidence with caveats: different population or subgroup,
                       indirect measure, small sample, animal/in vitro model, or partial
                       confirmation. Double-negation studies in subgroups (e.g. one sex only)
                       should be PARTIALLY_SUPPORTS, not SUPPORTS.
  CONTRADICTS        → The paper EXPLICITLY measures the claim's outcome AND opposes the
                       claim IN THE SAME population/context.
                       CRITICAL: CONTRADICTS requires that the paper measures the SAME outcome
                       as the claim. A paper measuring cognitive function does NOT contradict
                       a claim about sleep — assign NEUTRAL instead.
  NEUTRAL            → (a) The paper is on the same broad topic but does not directly test
                       the claim's assertion, OR
                       (b) The paper measures a DIFFERENT outcome than the one in the claim
                       (outcome mismatch), OR
                       (c) The paper discusses context, policy, or related factors only.
  INSUFFICIENT_DATA  → LAST RESORT ONLY. Use ONLY when the abstract has fewer than 60 words
                       OR is completely unreadable/missing. Do NOT use as a safe default.

━━━ CRITICAL DIRECTION RULES (read carefully) ━━━

▶ OUTCOME MISMATCH — THE MOST IMPORTANT RULE:
  CONTRADICTS requires that the paper actually measures the SAME outcome as the claim.
  - Claim: "coffee is beneficial for SLEEP"
    Paper studies coffee → cognitive function only → NEUTRAL (does not measure sleep)
    Paper studies coffee → sleep latency → can be CONTRADICTS or SUPPORTS
  - Claim: "X reduces DEPRESSION"
    Paper studies X → blood pressure only → NEUTRAL (does not measure depression)
  - A paper can only CONTRADICT a claim if it measures what the claim asserts.
    "No evidence of effect" on a DIFFERENT outcome = NEUTRAL, never CONTRADICTS.

▶ NEGATION INVERSION — DOUBLE NEGATION TRAP:
  A paper that studies the ABSENCE, WITHDRAWAL, or ABSTINENCE of A and finds that
  outcome B WORSENS is LOGICALLY EQUIVALENT to saying "A improves B".
  You MUST resolve the double negation BEFORE comparing to the claim.

  CANONICAL EXAMPLES:
    Claim: "Coffee (caffeine) is beneficial for sleep"
    Paper: "Caffeine ABSTINENCE was associated with MORE sleep disturbances"
      Step 1 — resolve: abstinence (no caffeine) → more disturbances (worse sleep)
      Step 2 — invert:  caffeine present → fewer disturbances (better sleep)
      Step 3 — compare: "caffeine → better sleep" SUPPORTS "coffee is beneficial for sleep"
      Verdict: SUPPORTS (or PARTIALLY_SUPPORTS if the effect is only in a subgroup)

    Claim: "Exercise improves mood"
    Paper: "Exercise deprivation led to significant mood deterioration"
      Resolved: no exercise → worse mood → exercise → better mood → SUPPORTS

    Claim: "Vitamin D supplementation reduces depression"
    Paper: "Vitamin D deficiency was associated with higher depression rates"
      Resolved: no vitamin D → more depression → vitamin D → less depression → SUPPORTS

  SUBGROUP CAVEAT: If the double-negation effect is only in a subgroup (e.g. only in
  females, only in the elderly), assign PARTIALLY_SUPPORTS, not SUPPORTS.

▶ COMPARATIVE CLAIMS — direction is everything:
  - "A is better than B" vs "B is better than A" are OPPOSITE claims.
  - A paper that shows B > A CONTRADICTS "A > B" even if both deal with the same topic.
  - A paper that shows A > B SUPPORTS "A > B" even if the paper's authors favor B.
  EXAMPLE:
    Claim: "Traditional CS is more efficient than Quantum CS"
    Paper finds: classical simulation on laptop is faster than quantum hardware → SUPPORTS
    Paper finds: quantum processor outperforms best classical approximation → CONTRADICTS

▶ NEGATION TRAPS — absence of effect ON THE CLAIMED OUTCOME:
  - "No significant difference", "no association", "no effect", "did not improve"
    on the SAME outcome → CONTRADICTS (same population) or PARTIALLY_SUPPORTS against
    (different population).
  - These rules apply ONLY when the paper measures the same outcome as the claim.
    If the paper measures a different outcome: NEUTRAL regardless.

▶ SCOPE TRAPS — partial or conditional findings:
  - If the paper shows an effect only under specific conditions but the claim is general,
    use PARTIALLY_SUPPORTS.
  - Absolute claims ("always", "in general") → PARTIALLY_SUPPORTS if only partial confirmation.

▶ TITLE/TOPIC TRAP — do not infer verdict from the paper's subject:
  - A paper about caffeine/coffee does NOT automatically CONTRADICT a claim about
    coffee and sleep. Only what the paper MEASURES and FINDS matters.
  - A paper's title alone never determines the verdict.

━━━ ANTI-HALLUCINATION RULES ━━━
- Base analysis SOLELY on the abstract and TL;DR provided. Nothing else.
- Do NOT add knowledge from outside the abstract.
- Do NOT invent quotes. If quoting, it must appear verbatim in the abstract above.
- If uncertain between NEUTRAL and PARTIALLY_SUPPORTS: does the abstract contain
  a finding that even indirectly supports or weakens the SAME outcome as the claim?
  If yes → PARTIALLY_SUPPORTS. If the outcome differs → NEUTRAL.
- Mechanistic studies (in vitro, cell culture, animal models): PARTIALLY_SUPPORTS at most
  with LOW confidence, unless the paper explicitly establishes human causation.
- Population mismatch rule: if the claim specifies a population and the paper studies a
  DIFFERENT population, cap the verdict at PARTIALLY_SUPPORTS (MEDIUM or LOW confidence).
  Never assign CONTRADICTS HIGH across a population gap.

━━━ CONFIDENCE ━━━
  HIGH   → The abstract directly and explicitly addresses the claim's outcome in the same
            direction, same population. The verdict is unambiguous.
  MEDIUM → Indirect evidence, different (but related) population, conditional findings,
            or requires some interpretation.
  LOW    → The link is weak, speculative, different population, or the abstract is very short.

━━━ OUTPUT FORMAT ━━━
Return ONLY a raw JSON object. No markdown. No code fences. No text outside the JSON.
Required keys:
  "verdict"        : one of SUPPORTS | PARTIALLY_SUPPORTS | CONTRADICTS | NEUTRAL | INSUFFICIENT_DATA
  "confidence"     : one of HIGH | MEDIUM | LOW
  "relevance_score": integer 0-10 (rate how directly this paper tests the claim's specific outcome)
  "evidence"       : exact quote or tight paraphrase from the abstract (max 2 sentences)
  "explanation"    : 1-2 sentences explaining WHY this verdict was chosen, referencing the outcome
  "key_finding"    : the single most important result of the paper in one sentence
"""

_OVERALL_VERDICT = """\
You are a senior scientist synthesizing evidence from multiple peer-reviewed papers \
to issue a final verdict on a scientific claim.

CLAIM: {claim}

INDIVIDUAL PAPER ANALYSES:
{analyses_text}

━━━ YOUR TASK ━━━
Think step by step before concluding:

1. CLAIM DIRECTION — first, identify what the claim asserts:
   - Intervention/subject, outcome/object, and direction (A improves B? A causes B? A > B?)
   - This is your reference frame for the entire synthesis.

2. FILTER by relevance first:
   - Separate papers with relevance_score >= 4 ("relevant papers") from those with score < 4.
   - Base your verdict and confidence ONLY on relevant papers (score >= 4).
   - Papers with relevance_score < 4 are background noise — do NOT let them drive the verdict.
   - If fewer than 2 papers have relevance_score >= 4, set overall_confidence to LOW
     and strongly consider INSUFFICIENT_EVIDENCE.

3. Among RELEVANT papers (score >= 4), count by verdict:
   - Supporting (SUPPORTS + PARTIALLY_SUPPORTS): how many?
   - Contradicting (CONTRADICTS): how many?
   - Neutral/Unclear (NEUTRAL + INSUFFICIENT_DATA): how many?

4. Weigh evidence quality, not just quantity:
   - HIGH confidence papers count more than LOW confidence.
   - One strong contradicting paper (HIGH conf, high relevance) can outweigh several weak supports.
   - PARTIALLY_SUPPORTS papers from different populations carry less weight.
   - DOUBLE-NEGATION CHECK: before counting a paper as CONTRADICTS, verify that its
     key_finding actually opposes the claim direction. A finding like "abstinence from A
     worsens B" logically SUPPORTS "A improves B" — recount it as SUPPORTS if mislabeled.

5. Apply these verdict rules in order (based ONLY on relevant papers):
   SUPPORTED            → Clear majority of relevant papers confirm the claim in the SAME
                          direction. Evidence is direct and from the same population.
   PARTIALLY_SUPPORTED  → More support than contradiction, but evidence has caveats, population
                          differences, or limited scope. When uncertain, prefer this over SUPPORTED.
   CONTRADICTED         → Majority of RELEVANT papers oppose the claim in the same direction,
                          or key high-quality relevant papers directly refute it.
   MIXED                → Roughly equal evidence on both sides among relevant papers;
                          genuine scientific debate.
   INSUFFICIENT_EVIDENCE→ Use when fewer than 2 relevant papers (score >= 4) have a concrete
                          verdict (SUPPORTS / PARTIALLY_SUPPORTS / CONTRADICTS). If most papers
                          are off-topic (low relevance_score), this is likely the right choice.

6. Confidence calibration:
   HIGH   → ≥3 relevant HIGH-confidence papers agree; little contradiction among relevant papers.
   MEDIUM → 2 relevant papers, or mixed quality, or partially-relevant populations.
   LOW    → Fewer than 2 relevant papers, or evidence is highly mixed among relevant papers.
   → IMPORTANT: If the verdict is based on ≤2 relevant papers out of many total papers,
     the confidence MUST be LOW or MEDIUM, never HIGH.

7. Note in verdict_explanation how many relevant papers (score >= 4) vs total papers were found.
   Example: "Only 2 of 10 papers had relevance_score ≥ 4 and directly tested the claim."
8. Translate non-English claims before evaluating.
9. Specific numbers/dosages not confirmed by any relevant paper → CONTRADICTED or PARTIALLY_SUPPORTED.

━━━ OUTPUT FORMAT ━━━
Return ONLY a raw JSON object. No markdown. No code fences.
Required keys:
  "overall_verdict"     : one of SUPPORTED | PARTIALLY_SUPPORTED | CONTRADICTED | MIXED | INSUFFICIENT_EVIDENCE
  "overall_confidence"  : one of HIGH | MEDIUM | LOW
  "verdict_explanation" : 3 sentences — synthesize the evidence, mention relevant paper count vs total,
                          cite 1-2 paper titles by name
  "supporting_count"    : integer (relevant papers only, score >= 4)
  "contradicting_count" : integer (relevant papers only, score >= 4)
  "neutral_count"       : integer (all papers with score < 4 or NEUTRAL/INSUFFICIENT_DATA verdict)
"""

_LITERATURE_REVIEW = """\
You are a senior academic researcher writing a rigorous literature review for a \
peer-reviewed journal. Use ONLY the papers provided below. Do not cite or invent \
any other sources.

TOPIC: {topic}

PAPERS:
{papers_text}

━━━ STRUCTURE (follow exactly) ━━━

**1. Introduction** (1 paragraph)
Introduce the research area, explain why it is scientifically and/or clinically \
important, and state the scope of this review.

**2. Main Findings** (2-3 paragraphs)
Group papers thematically. Highlight points of consensus and disagreement. \
For each key claim, cite the relevant papers. Note sample sizes or effect sizes if mentioned.

**3. Methodological Considerations** (1 paragraph)
Discuss study designs used (RCT, observational, meta-analysis, etc.), \
populations studied, and key limitations mentioned by the authors.

**4. State of Evidence & Open Questions** (1 paragraph)
Summarize the overall strength of evidence. Identify gaps, contradictions, \
and the most important unanswered questions for future research.

━━━ STYLE RULES ━━━
- Cite as [First Author et al., Year] inline.
- Formal academic register. No bullet points in the review body.
- Every sentence must add information — no padding.
- Minimum 400 words.
"""

_SUMMARIZE = """\
You are an expert academic research assistant. Produce a thorough, structured summary \
of the paper below, based STRICTLY on the provided abstract. \
Do NOT add external knowledge or invent details not present in the abstract.

Title:    {title}
Year:     {year}
Authors:  {authors}
Abstract: {abstract}

━━━ REQUIRED STRUCTURE ━━━

**🎯 Objective**
What specific question or hypothesis does this study address? \
What gap in the literature does it aim to fill?

**🔬 Methodology**
Study design (RCT, cohort, meta-analysis, etc.), population or sample, \
intervention or exposure, and outcome measures. Include numbers if stated.

**📊 Key Findings**
The main results. Quote exact numbers, percentages, p-values, or effect sizes \
if present in the abstract. What did the authors conclude?

**⚠️ Limitations**
Any limitations explicitly mentioned in the abstract. \
If none are stated: write "Not reported in abstract."

**💡 Why It Matters**
Scientific significance, practical implications, and who should care about these results.

━━━ RULES ━━━
- Stay strictly within what the abstract says.
- Never use vague phrases like "the study found interesting results."
- If the abstract is short, extract maximum value from what is there.
"""

_TOPIC_QUERIES = """\
You are a senior academic librarian with expertise in systematic literature search.
Your task: generate {n_queries} DISTINCT, high-yield Semantic Scholar search queries for the topic below.

TOPIC: {topic}

STRATEGY:
- Query 1: the core concept and main keywords (most specific to the topic).
- Query 2: a specific subtopic, mechanism, or clinical application directly within this field.
- Query 3: the broader scientific or clinical context — still within the field, not adjacent.
- Query 4+ (if requested): alternative angles, specific populations, or methodological variations
  that would surface papers from a different research community on the SAME topic.

RULES:
- All queries in English. 3 to 7 keywords each. No stopwords.
- Queries must be meaningfully different from each other.
- Every query must remain TIGHTLY scoped to the topic. Do NOT drift into adjacent fields.
  Example for "Large language models clinical decision support":
  GOOD: "LLM clinical decision support accuracy", "GPT medical diagnosis benchmark"
  BAD:  "AI ethics higher education", "machine learning genomics" (too distant)

Return ONLY a valid JSON array of exactly {n_queries} strings.
"""

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

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
    logger.error("_extract_content FAILED — raw: %s", str(resp)[:300])
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

# ══════════════════════════════════════════════════════════════════════════════
#  KEY POOL — Kimi-only, round-robin thread-safe
#  Reads LLM_API_KEY, LLM_API_KEY_2 … LLM_API_KEY_10 from env
# ══════════════════════════════════════════════════════════════════════════════

def _load_key_pool() -> list:
    """Return all Groq API keys found in env, in declaration order."""
    keys = []
    # Primary key
    primary = os.getenv("LLM_API_KEY", "")
    if primary:
        keys.append(primary)
    # Extra keys: LLM_API_KEY_2 … LLM_API_KEY_10
    for i in range(2, 11):
        k = os.getenv(f"LLM_API_KEY_{i}", "")
        if k:
            keys.append(k)
    if not keys:
        raise ValueError("No Groq API key found. Set LLM_API_KEY in your environment.")
    logger.info("Kimi key pool loaded: %d key(s)", len(keys))
    return keys

class _KeyPool:
    """Thread-safe round-robin pool of Groq clients, all pointing to Kimi."""

    MODEL = "moonshotai/kimi-k2-instruct"
    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, keys: list):
        self._clients = [
            OpenAI(api_key=k, base_url=self.BASE_URL)
            for k in keys
        ]
        self._cycle = itertools.cycle(range(len(self._clients)))
        self._lock  = threading.Lock()
        self._n     = len(self._clients)
        logger.info("KeyPool initialised with %d Kimi client(s)", self._n)

    def next_client(self) -> OpenAI:
        with self._lock:
            idx = next(self._cycle)
        return self._clients[idx]

    def call(self, messages: list, temperature: float = 0.1,
             max_tokens: int = 1000, retries: int = 6) -> str:
        """
        Call Kimi with automatic retry + key rotation on 429.
        Exponential back-off with jitter: 0.4s, 0.8s, 1.6s, 3.2s, 6.4s, 12.8s
        With 10 keys in round-robin, consecutive calls hit different keys so
        most 429s resolve immediately on the next client.
        """
        last_exc = None
        for attempt in range(retries):
            client = self.next_client()
            try:
                resp = client.chat.completions.create(
                    model=self.MODEL,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = _extract_content(resp)
                if content:
                    return content.strip()
                # Empty response — retry without sleeping
                logger.warning("Empty content on attempt %d, retrying…", attempt + 1)
            except Exception as e:
                last_exc = e
                err = str(e)
                is_rate = "429" in err or "rate_limit" in err.lower() or "ratelimitexceeded" in err.lower()
                if is_rate:
                    wait = (0.4 * (2 ** attempt)) + random.uniform(0, 0.2)
                    logger.warning("429 on attempt %d/%d — sleeping %.2fs then rotating key",
                                   attempt + 1, retries, wait)
                    time.sleep(wait)
                else:
                    # Non-rate error: log and retry immediately on next key
                    logger.error("LLM error attempt %d/%d: %s", attempt + 1, retries, err[:200])

        raise ValueError(
            f"All {retries} Kimi attempts failed. Last error: {last_exc}"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  PAPER ANALYZER
# ══════════════════════════════════════════════════════════════════════════════

class PaperAnalyzer:
    VALID_VERDICTS = {"SUPPORTS", "PARTIALLY_SUPPORTS", "CONTRADICTS", "NEUTRAL", "INSUFFICIENT_DATA"}
    VALID_OVERALL  = {"SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "MIXED", "INSUFFICIENT_EVIDENCE"}
    VALID_CONF     = {"HIGH", "MEDIUM", "LOW"}

    def __init__(self, api_key: str, provider: str = "groq", model: str = None, extra_keys: list = None):
        # Collect all keys: constructor arg + extra_keys list + env vars
        all_keys = []
        if api_key:
            all_keys.append(api_key)
        for k in (extra_keys or []):
            if k and k not in all_keys:
                all_keys.append(k)

        # Always top-up from env so that Railway/Render env vars are picked up
        for k in _load_key_pool():
            if k not in all_keys:
                all_keys.append(k)

        self._pool    = _KeyPool(all_keys)
        self.provider = "groq"

    @property
    def current_model(self) -> str:
        return f"groq/{_KeyPool.MODEL} [{self._pool._n} key(s)]"

    # ── low-level LLM call ────────────────────────────────────────────────────

    def _llm(self, prompt: str, temperature: float = 0.1, max_tokens: int = 1000) -> str:
        return self._pool.call(
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ── validation helpers ────────────────────────────────────────────────────

    def validate_claim(self, claim: str) -> Optional[dict]:
        claim = claim.strip()
        if not claim:
            return self._norm_overall({
                "overall_verdict": "INSUFFICIENT_EVIDENCE",
                "overall_confidence": "LOW",
                "verdict_explanation": "No claim was provided.",
                "supporting_count": 0, "contradicting_count": 0, "neutral_count": 0,
            })
        if _is_vague_claim(claim):
            return self._norm_overall({
                "overall_verdict": "INSUFFICIENT_EVIDENCE",
                "overall_confidence": "LOW",
                "verdict_explanation": (
                    f'The input "{claim}" is too vague to evaluate scientifically. '
                    "Please enter a full sentence with subject + verb + specific assertion. "
                    'Example: "Vitamin D supplementation reduces depression symptoms."'
                ),
                "supporting_count": 0, "contradicting_count": 0, "neutral_count": 0,
            })
        return None

    # ── JSON helpers ──────────────────────────────────────────────────────────

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
            "evidence":        str(d.get("evidence")    or "No evidence found."),
            "explanation":     str(d.get("explanation") or ""),
            "key_finding":     str(d.get("key_finding") or "N/A"),
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

    # ── public API ────────────────────────────────────────────────────────────

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
        abstract = (paper.get("abstract") or "").strip()
        if len(abstract) < 80:
            return self._norm_analysis({
                "verdict": "INSUFFICIENT_DATA", "confidence": "LOW", "relevance_score": 0,
                "evidence": "Abstract too short or unavailable.",
                "explanation": "Not enough content to evaluate this paper.", "key_finding": "N/A",
            })
        tldr_obj  = paper.get("tldr") or {}
        tldr_text = tldr_obj.get("text", "Not available") if isinstance(tldr_obj, dict) else "Not available"
        prompt = _PAPER_ANALYSIS.format(
            claim=claim,
            title=paper.get("title", "Unknown"),
            year=paper.get("year", "Unknown"),
            authors=_author_str(paper),
            abstract=abstract[:3000],
            tldr=tldr_text,
        )
        fallback = {
            "verdict": "INSUFFICIENT_DATA", "confidence": "LOW", "relevance_score": 1,
            "evidence": "Analysis could not be completed.",
            "explanation": "LLM analysis failed.", "key_finding": "N/A",
        }
        return self._norm_analysis(self._parse(self._llm(prompt, temperature=0.1), fallback))

    def analyze_papers_parallel(self, papers: list, claim: str, max_workers: int = 5) -> list:
        """
        Analyse une liste de papers en parallèle via ThreadPoolExecutor.
        Retourne une liste de (paper, analysis) dans le même ordre que `papers`.
        max_workers est automatiquement plafonné au nombre de clés disponibles.
        """
        workers = min(max_workers, self._pool._n, len(papers))
        results = [None] * len(papers)

        def _task(idx: int, paper: dict):
            return idx, self.analyze_paper(paper, claim)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_task, i, p): i for i, p in enumerate(papers)}
            for future in as_completed(futures):
                idx, analysis = future.result()
                results[idx] = (papers[idx], analysis)

        return results

    def overall_verdict(self, claim: str, results: List[Tuple[dict, dict]]) -> dict:
        if not results:
            return self._norm_overall({
                "overall_verdict": "INSUFFICIENT_EVIDENCE",
                "overall_confidence": "LOW",
                "verdict_explanation": "No papers with sufficient content were retrieved.",
                "supporting_count": 0, "contradicting_count": 0, "neutral_count": 0,
            })
        lines = []
        for paper, analysis in results:
            lines.append(
                "Paper: " + paper.get("title", "Unknown") + "\n"
                "  Verdict: "         + analysis.get("verdict",         "N/A") + "\n"
                "  Confidence: "      + analysis.get("confidence",      "N/A") + "\n"
                "  Relevance Score: " + str(analysis.get("relevance_score", 0)) + "/10\n"
                "  Key Finding: "     + analysis.get("key_finding",     "N/A") + "\n"
                "  Evidence: "        + analysis.get("evidence",        "N/A") + "\n"
                "  Explanation: "     + analysis.get("explanation",     "N/A")
            )
        fallback = {
            "overall_verdict": "MIXED",
            "overall_confidence": "LOW",
            "verdict_explanation": "Could not synthesize automatically.",
            "supporting_count":    sum(1 for _, a in results if a.get("verdict") in {"SUPPORTS", "PARTIALLY_SUPPORTS"} and _safe_int(a.get("relevance_score")) >= 4),
            "contradicting_count": sum(1 for _, a in results if a.get("verdict") == "CONTRADICTS" and _safe_int(a.get("relevance_score")) >= 4),
            "neutral_count":       sum(1 for _, a in results if a.get("verdict") in {"NEUTRAL", "INSUFFICIENT_DATA"} or _safe_int(a.get("relevance_score")) < 4),
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
            return self._llm(
                _LITERATURE_REVIEW.format(topic=topic, papers_text=papers_text),
                temperature=0.3, max_tokens=2000,
            )
        except Exception as exc:
            return "Literature review generation failed: " + str(exc)

    def summarize(self, paper: dict) -> str:
        abstract = (paper.get("abstract") or "").strip()
        if not abstract:
            return "No abstract available — cannot summarize."
        try:
            return self._llm(
                _SUMMARIZE.format(
                    title=paper.get("title", "Unknown"),
                    year=paper.get("year", "N/A"),
                    authors=_author_str(paper, max_authors=5),
                    abstract=abstract[:3000],
                ),
                temperature=0.2, max_tokens=900,
            )
        except Exception as exc:
            return "Summarization failed: " + str(exc)
