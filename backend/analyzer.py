import json
import logging
import os
import re
import time
from typing import List, Optional, Tuple
from openai import OpenAI

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
#  PROMPTS — V3 (all 10 logic traps patched)
# ═══════════════════════════════════════════════════════════════════════════════

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
  Example: "SSRIs no more effective than placebo for mild depression"
  → must produce a query like "SSRI placebo mild depression meta-analysis"
  → and another like "antidepressant efficacy mild depression randomized trial"
- If the claim is a comparative (A vs B), generate queries for BOTH sides of the comparison
  so that papers supporting either direction are retrieved.
  Example: "Quantum computing outperforms classical computing"
  → "quantum advantage classical simulation comparison"
  → "classical algorithms competitive quantum circuits benchmark"

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

━━━ STEP 1 — MANDATORY PRE-ANALYSIS ━━━

Before picking any verdict, answer these four questions explicitly in your reasoning:

  A. CLAIM DIRECTION
     What exactly does the claim assert?
     → Identify Subject (A), Object (B), and the direction: A > B? A causes B? A prevents B?
     → Example: "Traditional CS is more efficient than Quantum CS"
       Subject=Traditional CS, Object=Quantum CS, Direction=Traditional > Quantum

  B. PAPER FINDING
     What does THIS paper actually show in its data/results?
     → Quote or tightly paraphrase the key result sentence.
     → Do NOT infer from the title or topic — only from stated findings.
     → Ignore which side the authors favor; focus on what the data shows.

  C. DIRECTION MATCH
     Does the paper's finding go in the SAME direction as the claim, or the OPPOSITE direction?
     → Same direction (A > B and paper shows A > B) → leans SUPPORTS
     → Opposite direction (A > B but paper shows B > A) → leans CONTRADICTS
     → No quantified direction found → leans NEUTRAL

  D. TRAP CHECK — run through each of these before finalising:
     □ Negation trap:     Does the paper use "no effect", "did not", "failed to", "no association"?
                          If yes AND the claim asserts a positive effect → likely CONTRADICTS.
     □ Scope trap:        Is the result conditional (subgroup, dose, circuit type)?
                          If yes AND the claim is general → cap at PARTIALLY_SUPPORTS.
     □ Correlation trap:  Does the paper show correlation/association but the claim asserts causation?
                          If yes → cap at PARTIALLY_SUPPORTS.
     □ Model trap:        Is the evidence from animals, cell cultures, or in vitro only?
                          If yes AND claim is about humans → cap at PARTIALLY_SUPPORTS LOW.
     □ Population trap:   Does the paper study a DIFFERENT population than the claim specifies?
                          If yes → cap at PARTIALLY_SUPPORTS (never CONTRADICTS across pop gap).
     □ Magnitude trap:    Does the paper show an effect of a DIFFERENT size than the claim states?
                          If yes (e.g. claim says 50%, paper shows 5%) → CONTRADICTS or PARTIALLY_SUPPORTS.
     □ Timeframe trap:    Is the paper's effect short-term only but the claim is general/durable?
                          If yes → PARTIALLY_SUPPORTS at most.
     □ Reverse causality: Does the paper show Y predicts X but the claim says X causes Y?
                          If yes → NEUTRAL or PARTIALLY_SUPPORTS.
     □ Title trap:        Never infer verdict from title or topic alone — only from findings.

━━━ STEP 2 — RELEVANCE CHECK ━━━

Does this paper study the same population, intervention, condition, or phenomenon \
as the claim? If completely off-topic, assign NEUTRAL with relevance_score ≤ 2.

━━━ STEP 3 — VERDICT ━━━

Choose the SINGLE most accurate verdict. Do NOT default to safe options.

  SUPPORTS
    → The paper's findings EXPLICITLY confirm the claim IN THE SAME DIRECTION,
      same population, same context. No major caveats.
    → The direction of the paper's result MUST MATCH the direction of the claim.
    → SUPPORTS a "classical > quantum" claim means the paper shows classical IS better.
    → SUPPORTS a "quantum > classical" claim means the paper shows quantum IS better.
    → If the finding helps the claim but has caveats → use PARTIALLY_SUPPORTS instead.

  PARTIALLY_SUPPORTS
    → Related evidence that lends credibility to the claim, but with caveats:
      different population/subgroup, indirect measure, animal/in vitro model, correlation
      not causation, short-term only, conditional effect, or magnitude mismatch.

  CONTRADICTS
    → The paper's findings EXPLICITLY oppose the claim IN THE SAME DIRECTION,
      same population, same context.
    → "A > B" claim + paper shows "B > A" (or "A does NOT outperform B") → CONTRADICTS.
    → "X reduces Y" claim + paper shows "X did not reduce Y" (same pop) → CONTRADICTS.
    → If populations differ significantly → use PARTIALLY_SUPPORTS instead.

  NEUTRAL
    → Same broad topic but the paper does not directly test the claim's assertion.
      It discusses context, methods, policy, or tangential factors without quantifying
      the direction asserted by the claim.

  INSUFFICIENT_DATA
    → LAST RESORT ONLY. Use ONLY when the abstract has fewer than 60 words OR is
      completely unreadable. NEVER use as a safe default when a verdict is possible.

━━━ WORKED EXAMPLES (study these carefully) ━━━

EXAMPLE 1 — Direction inversion (most common mistake):
  Claim: "Traditional CS is more efficient than Quantum CS"
  Paper: "Classical simulation on a laptop matches the quantum processor output in 2 seconds"
  → Paper shows Classical ≥ Quantum → SAME direction as claim → SUPPORTS
  ✗ Wrong: CONTRADICTS (the paper is about quantum, so it must contradict a pro-classical claim)

EXAMPLE 2 — Direction inversion (other side):
  Claim: "Traditional CS is more efficient than Quantum CS"
  Paper: "Zuchongzhi completed a task in 200s that would take classical computers 5.9 billion years"
  → Paper shows Quantum >> Classical → OPPOSITE direction → CONTRADICTS
  ✓ Correct: CONTRADICTS

EXAMPLE 3 — Negation trap:
  Claim: "SSRIs improve depression symptoms"
  Paper: "SSRIs showed no significant improvement over placebo in this RCT"
  → "no significant improvement" = opposite of claim → CONTRADICTS (same population)
  ✗ Wrong: NEUTRAL

EXAMPLE 4 — Scope trap:
  Claim: "Quantum computing outperforms classical computing"
  Paper: "Quantum advantage observed only on random circuit sampling tasks of >50 qubits"
  → Effect is conditional on a narrow task type, claim is general → PARTIALLY_SUPPORTS
  ✗ Wrong: SUPPORTS

EXAMPLE 5 — Correlation ≠ Causation:
  Claim: "Social media use causes depression in teenagers"
  Paper: "Social media use was associated with depressive symptoms (r=0.3, p<0.01)"
  → Association ≠ causation asserted by claim → PARTIALLY_SUPPORTS
  ✗ Wrong: SUPPORTS

EXAMPLE 6 — Animal/in vitro model trap:
  Claim: "Compound X treats Alzheimer's disease"
  Paper: "In mice, Compound X reduced amyloid plaques by 40%"
  → Mouse model, no human data → PARTIALLY_SUPPORTS LOW
  ✗ Wrong: SUPPORTS

EXAMPLE 7 — Population mismatch:
  Claim: "Vitamin D reduces depression in healthy adults"
  Paper: "In type 2 diabetics, Vitamin D supplementation improved mood scores"
  → Different population (diabetics ≠ healthy adults) → PARTIALLY_SUPPORTS MEDIUM
  ✗ Wrong: CONTRADICTS (population gap — not grounds for CONTRADICTS)

EXAMPLE 8 — Magnitude trap:
  Claim: "Drug X reduces blood pressure by 30%"
  Paper: "Drug X reduced systolic BP by an average of 4 mmHg (≈3%)"
  → Effect confirmed but magnitude far smaller than claimed → CONTRADICTS or PARTIALLY_SUPPORTS
  ✗ Wrong: SUPPORTS

EXAMPLE 9 — Timeframe trap:
  Claim: "Mindfulness durably reduces anxiety"
  Paper: "Mindfulness reduced anxiety scores at 2-week follow-up; effect not assessed at 6 months"
  → Short-term effect only, durability unestablished → PARTIALLY_SUPPORTS
  ✗ Wrong: SUPPORTS

EXAMPLE 10 — Reverse causality:
  Claim: "Sleep deprivation causes cognitive decline"
  Paper: "Patients with early cognitive decline were observed to sleep fewer hours"
  → Cognitive decline → less sleep (reverse direction) → NEUTRAL or PARTIALLY_SUPPORTS
  ✗ Wrong: SUPPORTS

━━━ CONFIDENCE ━━━

  HIGH   → Abstract directly and explicitly addresses the claim in the same direction,
            same population. Verdict is unambiguous.
  MEDIUM → Indirect evidence, different (but related) population, conditional findings,
            or requires some interpretation.
  LOW    → Weak link, speculative, very different population, or abstract is very short.

━━━ OUTPUT ━━━

Return ONLY a raw JSON object. No markdown. No code fences. No text outside the JSON.
Required keys:
  "verdict"        : one of SUPPORTS | PARTIALLY_SUPPORTS | CONTRADICTS | NEUTRAL | INSUFFICIENT_DATA
  "confidence"     : one of HIGH | MEDIUM | LOW
  "relevance_score": integer 0-10
  "evidence"       : exact quote or tight paraphrase from the abstract (max 2 sentences)
  "explanation"    : 2 sentences — state the paper's finding direction, then explain why
                     that direction matches or opposes the claim's direction.
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
   - Subject, object, and direction (A > B? A causes B? A prevents B?)
   - This is your reference frame for the entire synthesis.

2. CONSISTENCY CHECK — for each paper's verdict, verify it is coherent:
   - Read the "key_finding" and "explanation" fields.
   - If a paper's explanation says "classical beats quantum" but its verdict says CONTRADICTS
     a "classical > quantum" claim → that is a mislabelled paper. Treat it as SUPPORTS.
   - If a paper's explanation says "quantum beats classical" but its verdict says SUPPORTS
     a "classical > quantum" claim → mislabelled. Treat it as CONTRADICTS.
   - Apply the same logic to any claim direction.

3. Count papers by corrected verdict category:
   - Supporting (SUPPORTS + PARTIALLY_SUPPORTS): how many?
   - Contradicting (CONTRADICTS): how many?
   - Neutral/Unclear (NEUTRAL + INSUFFICIENT_DATA): how many?

4. Weigh evidence quality, not just quantity:
   - HIGH confidence papers count more than LOW confidence.
   - High relevance_score papers count more.
   - One strong contradicting paper can outweigh several weak supports.
   - PARTIALLY_SUPPORTS papers from different populations carry less weight.

5. Apply these verdict rules in order:
   SUPPORTED            → Clear majority of relevant papers confirm the claim in the SAME
                          direction. Evidence is direct and from the same population.
   PARTIALLY_SUPPORTED  → More support than contradiction, but evidence has caveats,
                          population differences, or limited scope. When uncertain, prefer
                          this over SUPPORTED.
   CONTRADICTED         → Majority of relevant papers oppose the claim in the same direction,
                          or key high-quality papers directly refute it in the same population.
   MIXED                → Roughly equal evidence on both sides — genuine scientific debate.
   INSUFFICIENT_EVIDENCE→ LAST RESORT. Use ONLY if fewer than 2 papers have a concrete
                          verdict (SUPPORTS / PARTIALLY_SUPPORTS / CONTRADICTS).
                          NEUTRAL papers do NOT count as evidence.

6. When relevant papers are a small fraction of total papers analysed, note it in
   verdict_explanation. Adjust confidence accordingly.
7. Translate non-English claims before evaluating.
8. Specific numbers/dosages not confirmed by any paper → CONTRADICTED or PARTIALLY_SUPPORTED.

9. Overall confidence:
   HIGH   → Multiple HIGH-confidence direct papers agree; little contradiction.
   MEDIUM → Evidence mostly indirect, mixed quality, or from partially-relevant populations.
   LOW    → Very few relevant papers, most NEUTRAL/INSUFFICIENT, or evidence highly mixed.

━━━ OUTPUT ━━━

Return ONLY a raw JSON object. No markdown. No code fences.
Required keys:
  "overall_verdict"     : one of SUPPORTED | PARTIALLY_SUPPORTED | CONTRADICTED | MIXED | INSUFFICIENT_EVIDENCE
  "overall_confidence"  : one of HIGH | MEDIUM | LOW
  "verdict_explanation" : 3 sentences — synthesize the evidence, cite 2-3 paper titles by name
  "supporting_count"    : integer
  "contradicting_count" : integer
  "neutral_count"       : integer
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
        fallback = {"verdict": "INSUFFICIENT_DATA", "confidence": "LOW", "relevance_score": 1,
                    "evidence": "Analysis could not be completed.",
                    "explanation": "LLM analysis failed.", "key_finding": "N/A"}
        return self._norm_analysis(self._parse(self._llm(prompt, temperature=0.1), fallback))

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
                    title=paper.get("title", "Unknown"),
                    year=paper.get("year", "N/A"),
                    authors=_author_str(paper, max_authors=5),
                    abstract=abstract[:3000],
                ),
                temperature=0.2, max_tokens=900,
            )
        except Exception as exc:
            return "Summarization failed: " + str(exc)
