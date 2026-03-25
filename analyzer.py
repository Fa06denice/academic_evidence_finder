# analyzer.py
import json
import logging
import os
import re
import time
from typing import List, Optional, Tuple
from openai import OpenAI


logger = logging.getLogger(__name__)


# ── Prompts ───────────────────────────────────────────────────────────────────


_QUERY_TRANSFORM = """\
You are an expert academic librarian. Convert the user input into EXACTLY 3 concise \
Semantic Scholar search queries (keyword-focused, no filler words).

RULES:
- ALL queries MUST be in ENGLISH regardless of the input language.
- Keep the EXACT technical terms from the user input — do not paraphrase or generalize.
- Query 1: closest to the original phrasing, translated to English if needed.
- Query 2: key technical subtopic or method mentioned.
- Query 3: broader academic context of the topic.
- Each query must be 2-6 words maximum.
- Never use synonyms that change the technical meaning.

User input: {user_input}

Return ONLY a valid JSON array of exactly 3 strings. No markdown, no explanation.
Example: ["transformer attention mechanism NLP", "self-attention sequence models", "neural network language processing"]
"""


_PAPER_ANALYSIS = """\
You are a rigorous academic evidence analyst. Determine whether the paper below \
supports, contradicts, or is unrelated to the given CLAIM.

CLAIM: {claim}

PAPER:
Title: {title}
Year: {year}
Authors: {authors}
Abstract: {abstract}
TL;DR: {tldr}

Return a single valid JSON object with EXACTLY these keys:
{{
  "verdict": "SUPPORTS" | "PARTIALLY_SUPPORTS" | "CONTRADICTS" | "NEUTRAL" | "INSUFFICIENT_DATA",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "relevance_score": <integer 1-10>,
  "evidence": "<direct quote or close paraphrase from the abstract — not invented>",
  "explanation": "<1-2 sentence academic explanation of the verdict>",
  "key_finding": "<the most important result from this paper relevant to the claim>"
}}

RULES:
- Base analysis ONLY on the provided abstract and tldr.
- Use DIRECT QUOTES for the evidence field whenever possible.
- If the abstract is absent or too short to judge, use "INSUFFICIENT_DATA".
- Never invent facts. Never add information not in the abstract.
Return only the JSON object.
"""


_PAPER_ANALYSIS_FULLTEXT = """\
You are a rigorous academic evidence analyst. Determine whether the paper below \
supports, contradicts, or is unrelated to the given CLAIM.

CLAIM: {claim}

PAPER:
Title: {title}
Year: {year}
Authors: {authors}
Abstract: {abstract}
TL;DR: {tldr}

FULL TEXT EXCERPT:
{fulltext}

Return a single valid JSON object with EXACTLY these keys:
{{
  "verdict": "SUPPORTS" | "PARTIALLY_SUPPORTS" | "CONTRADICTS" | "NEUTRAL" | "INSUFFICIENT_DATA",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "relevance_score": <integer 1-10>,
  "evidence": "<direct quote from the abstract or full text — not invented>",
  "explanation": "<1-2 sentence academic explanation of the verdict>",
  "key_finding": "<the most important result from this paper relevant to the claim>"
}}

RULES:
- Prioritize the full text excerpt over the abstract for evidence and key findings.
- Use DIRECT QUOTES for the evidence field whenever possible.
- Never invent facts. Never add information not present in the provided text.
- If the full text contradicts the abstract, trust the full text.
Return only the JSON object.
"""


_OVERALL_VERDICT = """\
Given the analyses below, give an overall assessment of whether the scientific \
literature supports the claim.

CLAIM: {claim}

ANALYSES:
{analyses_text}

Return a single valid JSON object:
{{
  "overall_verdict": "SUPPORTED" | "PARTIALLY_SUPPORTED" | "CONTRADICTED" | "MIXED" | "INSUFFICIENT_EVIDENCE",
  "verdict_explanation": "<2-3 sentence synthesis — mention specific papers by title>",
  "supporting_count": <int>,
  "contradicting_count": <int>,
  "neutral_count": <int>
}}

STRICT VERDICT RULES — apply in this order:
1. SUPPORTED requires that a majority of papers DIRECTLY and EXPLICITLY confirm the specific claim as stated. \
   Papers that merely discuss the same topic without confirming the claim must NOT count as supporting. \
   When in doubt between SUPPORTED and PARTIALLY_SUPPORTED, always choose PARTIALLY_SUPPORTED.
2. If the claim is written in a language other than English, mentally translate it first, \
   then evaluate it with the same rigor as an English claim. Language must never lower the bar for evidence.
3. If the claim contains a specific quantitative value (a percentage, a ratio, a number, a dosage, etc.), \
   and no paper explicitly confirms that exact value, the verdict MUST be CONTRADICTED or PARTIALLY_SUPPORTED — \
   never SUPPORTED. If papers actively report a different value, use CONTRADICTED.
4. INSUFFICIENT_EVIDENCE is reserved for cases where fewer than 2 papers are relevant to the claim.

Base this ONLY on the provided analyses. Return only the JSON object.
"""


_LITERATURE_REVIEW = """\
Write a concise academic literature review (3-5 paragraphs) on the topic below, \
based ONLY on the provided papers. Do not reference any paper not listed here.
Cite as [First Author, Year].

TOPIC: {topic}

PAPERS:
{papers_text}

Be objective, highlight agreements and disagreements, and use academic register.
"""


_SUMMARIZE = """\
Summarize the following scientific paper for an academic reader.
Base your summary ONLY on the provided abstract. Do not invent details.

Title: {title}
Year: {year}
Authors: {authors}
Abstract: {abstract}

Provide this structure:
**Objective** — What the paper aims to do.
**Methodology** — How (brief).
**Key Findings** — What they found.
**Limitations** — Any limits mentioned in the abstract (or "Not stated").
**Why It Matters** — Relevance for researchers.
"""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    # 1. Strip markdown code fences en premier (```json, ```, etc.)
    raw = re.sub(r'^```[a-zA-Z]*', '', raw).strip()
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")].strip()
    # 2. Dé-échapper les \n littéraux
    raw = raw.replace("\\\\n", "\n").replace("\\n", "\n")
    # 3. Extraire le premier objet JSON valide
    match = re.search(r'(\{.*\}|\[.*\])', raw, re.DOTALL)
    if match:
        return match.group(0)
    return raw.strip()


def _author_str(paper: dict, max_authors: int = 3) -> str:
    authors = paper.get("authors", [])
    names = [a.get("name", "") for a in authors[:max_authors]]
    result = ", ".join(n for n in names if n)
    if len(authors) > max_authors:
        result += " et al."
    return result or "Unknown"


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_content(resp) -> str | None:
    """Extract text content — compatible Python 3.14 + openai SDK."""

    # Tentative 1 : accès direct avec unwrap récursif
    try:
        first = resp.choices
        while isinstance(first, list):
            first = first
        content = first.message.content
        if content is not None:
            return content
    except Exception as e:
        logger.warning("_extract_content attempt 1 failed: %s", e)

    # Tentative 2 : model_dump() avec unwrap récursif
    try:
        choices = resp.model_dump().get("choices") or []
        first = choices
        while isinstance(first, list):
            first = first
        if isinstance(first, dict):
            return first["message"]["content"]
    except Exception as e:
        logger.warning("_extract_content attempt 2 failed: %s", e)

    # Tentative 3 : repr() brut — fallback ultime
    try:
        raw = str(resp.choices)
        for marker in ["content='", 'content="']:
            if marker in raw:
                q = marker[-1]
                start = raw.index(marker) + len(marker)
                end = raw.index(q, start)
                return raw[start:end]
    except Exception as e:
        logger.warning("_extract_content attempt 3 failed: %s", e)

    logger.error("_extract_content FAILED — raw resp: %s", str(resp)[:300])
    return None


# ── Claim validation ──────────────────────────────────────────────────────────

_VERB_PATTERNS = re.compile(
    r"\b(is|are|was|were|be|been|being|has|have|had|do|does|did|will|would|shall|should|"
    r"may|might|must|can|could|cause[sd]?|reduce[sd]?|increase[sd]?|improve[sd]?|affect[sd]?|"
    r"prevent[sd]?|treat[sd]?|lead[sd]?|show[sn]?|suggest[sd]?|support[sd]?|outperform[sd]?|"
    r"surpass|enhance[sd]?|decrease[sd]?|induce[sd]?|inhibit[sd]?|promote[sd]?|"
    r"est|sont|a|ont|peut|peuvent|cause|réduit|augmente|améliore|provoque|empêche)\b",
    re.IGNORECASE,
)


def _is_vague_claim(claim: str) -> bool:
    words = claim.strip().split()
    if len(words) >= 4:
        return False
    has_verb = bool(_VERB_PATTERNS.search(claim))
    return not has_verb


# ── Model Rotator ─────────────────────────────────────────────────────────────


class ModelRotator:
    """
    Pool de modèles LLM qui rotate automatiquement sur rate limit (429).
    Supporte plusieurs modèles et/ou plusieurs clés API.
    """

    GROQ_FALLBACKS = [
        "llama-3.3-70b-versatile",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "llama-3.1-8b-instant",
        "qwen/qwen3-32b",
        "moonshotai/kimi-k2-instruct",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ]

    def __init__(self, pool: list):
        self.pool        = pool
        self.index       = 0
        self.fail_counts =  [0] * len(pool)

    @property
    def current(self) -> tuple:
        return self.pool[self.index]

    def rotate(self):
        self.fail_counts[self.index] += 1
        original = self.index
        for _ in range(len(self.pool)):
            self.index = (self.index + 1) % len(self.pool)
            if self.fail_counts[self.index] < 3:
                logger.info("Rotated to: %s", self.pool[self.index])[1]
                return
        logger.warning("All models hit limits — resetting fail counts.")
        self.fail_counts =  [0] * len(self.pool)
        self.index = (original + 1) % len(self.pool)

    def success(self):
        self.fail_counts[self.index] = 0


# ── Main class ────────────────────────────────────────────────────────────────


class PaperAnalyzer:
    """
    Supporte : OpenAI, Groq (gratuit), Ollama (local), Gemini.
    Rotation automatique entre modèles en cas de rate limit.
    """

    PROVIDERS = {
        "openai": {"base_url": None,                                                        "default_model": "gpt-4o-mini"},
        "groq":   {"base_url": "https://api.groq.com/openai/v1",                           "default_model": "llama-3.3-70b-versatile"},
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

        def _make_entry(key: str, mdl: str, label: str) -> tuple:
            kwargs = {"api_key": key or "ollama"}
            if base_url:
                kwargs["base_url"] = base_url
            return (OpenAI(**kwargs), mdl, label)

        pool = [_make_entry(api_key, base_model, f"{provider}/{base_model} [primary]")]

        if provider == "groq":
            for alt in ModelRotator.GROQ_FALLBACKS:
                if alt != base_model:
                    pool.append(_make_entry(api_key, alt, f"groq/{alt} [fallback]"))

        for i, extra_key in enumerate(extra_keys or []):
            if extra_key:
                pool.append(_make_entry(extra_key, base_model, f"{provider}/{base_model} [extra_key_{i + 1}]"))

        self.rotator = ModelRotator(pool)


    # ── Claim validation ──────────────────────────────────────────────────────


    def validate_claim(self, claim: str) -> Optional[dict]:
        claim = claim.strip()
        if not claim:
            return self._normalize_overall({
                "overall_verdict": "INSUFFICIENT_EVIDENCE",
                "verdict_explanation": "No claim was provided.",
                "supporting_count": 0, "contradicting_count": 0, "neutral_count": 0,
            })
        if _is_vague_claim(claim):
            return self._normalize_overall({
                "overall_verdict": "INSUFFICIENT_EVIDENCE",
                "verdict_explanation": (
                    f'The claim "{claim}" is too vague or incomplete to be evaluated against '
                    "scientific literature. A valid claim must contain a subject and a verb "
                    "expressing a specific, falsifiable assertion."
                ),
                "supporting_count": 0, "contradicting_count": 0, "neutral_count": 0,
            })
        return None


    # ── Core LLM call ─────────────────────────────────────────────────────────


    def _llm(self, prompt: str, temperature: float = 0.1, max_tokens: int = 900) -> str:
        """Send a prompt — rotates automatically on rate limit."""
        max_attempts = len(self.rotator.pool) * 2

        for attempt in range(max_attempts):
            client, model, label = self.rotator.current
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = _extract_content(resp)
                if content:
                    self.rotator.success()
                    return content.strip()
                # Contenu vide — on rotate vers le prochain modèle au lieu de retourner ""
                logger.warning("Empty content from %s (attempt %d) — rotating.", label, attempt + 1)
                self.rotator.rotate()

            except Exception as e:
                err = str(e)
                is_rate_limit = (
                    "429" in err
                    or "rate_limit" in err.lower()
                    or "tokens per day" in err.lower()
                    or "ratelimitexceeded" in err.lower()
                )
                logger.error(
                    "Attempt %d/%d — model=%s — rate_limit=%s — error: %s",
                    attempt + 1, max_attempts, label, is_rate_limit, err[:200],
                )
                self.rotator.rotate()
                if is_rate_limit:
                    time.sleep(2)

        raise ValueError(f"All {len(self.rotator.pool)} models exhausted after {max_attempts} attempts.")


    # ── JSON helpers ──────────────────────────────────────────────────────────


    def _parse_json(self, raw: str, fallback: dict) -> dict:
        try:
            return json.loads(_clean_json(raw))
        except json.JSONDecodeError:
            logger.error("JSON parse failed. Raw: %s", raw[:300])
            return fallback

    def _normalize_analysis(self, data: dict) -> dict:
        return {
            "verdict":         data.get("verdict", "INSUFFICIENT_DATA")
                               if data.get("verdict") in self.VALID_VERDICTS
                               else "INSUFFICIENT_DATA",
            "confidence":      data.get("confidence", "LOW")
                               if data.get("confidence") in self.VALID_CONF
                               else "LOW",
            "relevance_score": _safe_int(data.get("relevance_score"), 0),
            "evidence":        str(data.get("evidence") or "No evidence found."),
            "explanation":     str(data.get("explanation") or ""),
            "key_finding":     str(data.get("key_finding") or "N/A"),
        }

    def _normalize_overall(self, data: dict) -> dict:
        return {
            "overall_verdict":     data.get("overall_verdict", "INSUFFICIENT_EVIDENCE")
                                   if data.get("overall_verdict") in self.VALID_OVERALL
                                   else "INSUFFICIENT_EVIDENCE",
            "verdict_explanation": str(data.get("verdict_explanation") or ""),
            "supporting_count":    _safe_int(data.get("supporting_count"), 0),
            "contradicting_count": _safe_int(data.get("contradicting_count"), 0),
            "neutral_count":       _safe_int(data.get("neutral_count"), 0),
        }


    # ── Query transformation ──────────────────────────────────────────────────


    def transform_query(self, user_input: str) -> List[str]:
        try:
            raw = self._llm(_QUERY_TRANSFORM.format(user_input=user_input), temperature=0.2)
            if not raw:
                logger.warning("transform_query: empty response from LLM")
                return [user_input]
            queries = json.loads(_clean_json(raw))
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                return [q.strip() for q in queries[:3] if q.strip()]
        except Exception as exc:
            logger.warning("Query transform failed: %s", exc)
        return [user_input]


    # ── Paper analysis ────────────────────────────────────────────────────────


    def analyze_paper(self, paper: dict, claim: str, fulltext: Optional[str] = None) -> dict:
        abstract = (paper.get("abstract") or "").strip()
        if len(abstract) < 80:
            return self._normalize_analysis({
                "verdict": "INSUFFICIENT_DATA", "confidence": "LOW",
                "relevance_score": 0, "evidence": "Abstract too short or unavailable.",
                "explanation": "Not enough content to evaluate this paper.", "key_finding": "N/A",
            })

        tldr_obj  = paper.get("tldr") or {}
        tldr_text = tldr_obj.get("text", "Not available") if isinstance(tldr_obj, dict) else "Not available"

        # Utilise le prompt fulltext si on a du texte complet, sinon abstract seul
        if fulltext and len(fulltext) > 200:
            prompt = _PAPER_ANALYSIS_FULLTEXT.format(
                claim=claim,
                title=paper.get("title", "Unknown"),
                year=paper.get("year", "Unknown"),
                authors=_author_str(paper),
                abstract=abstract[:1000],
                tldr=tldr_text,
                fulltext=fulltext[:6000],
            )
            logger.info("analyze_paper: using full text for '%s'", paper.get("title", "")[:60])
        else:
            prompt = _PAPER_ANALYSIS.format(
                claim=claim,
                title=paper.get("title", "Unknown"),
                year=paper.get("year", "Unknown"),
                authors=_author_str(paper),
                abstract=abstract[:2500],
                tldr=tldr_text,
            )

        fallback = {
            "verdict": "INSUFFICIENT_DATA", "confidence": "LOW", "relevance_score": 1,
            "evidence": "Analysis could not be completed.",
            "explanation": "LLM analysis failed for this paper.", "key_finding": "N/A",
        }
        raw = self._llm(prompt, temperature=0.1)
        return self._normalize_analysis(self._parse_json(raw, fallback))


    # ── Overall verdict ───────────────────────────────────────────────────────


    def overall_verdict(self, claim: str, results: List[Tuple[dict, dict]]) -> dict:
        if not results:
            return self._normalize_overall({
                "overall_verdict": "INSUFFICIENT_EVIDENCE",
                "verdict_explanation": "No papers with sufficient content were retrieved.",
                "supporting_count": 0, "contradicting_count": 0, "neutral_count": 0,
            })

        lines = []
        for paper, analysis in results:
            lines.append(
                f"Paper: \"{paper.get('title', 'Unknown')}\"\n"
                f"  Verdict: {analysis.get('verdict')}\n"
                f"  Evidence: {analysis.get('evidence', 'N/A')}\n"
                f"  Explanation: {analysis.get('explanation', 'N/A')}"
            )

        prompt = _OVERALL_VERDICT.format(claim=claim, analyses_text="\n\n".join(lines))
        fallback = {
            "overall_verdict": "MIXED",
            "verdict_explanation": "Could not synthesize automatically.",
            "supporting_count":    sum(1 for _, a in results if a.get("verdict") in {"SUPPORTS", "PARTIALLY_SUPPORTS"}),
            "contradicting_count": sum(1 for _, a in results if a.get("verdict") == "CONTRADICTS"),
            "neutral_count":       sum(1 for _, a in results if a.get("verdict") in {"NEUTRAL", "INSUFFICIENT_DATA"}),
        }
        raw = self._llm(prompt, temperature=0.1)
        return self._normalize_overall(self._parse_json(raw, fallback))


    # ── Literature review ─────────────────────────────────────────────────────


    def literature_review(self, topic: str, results: List[Tuple[dict, dict]]) -> str:
        papers_text = ""
        for paper, analysis in results:
            papers_text += (
                f"\n---\n"
                f"Title: {paper.get('title', 'Unknown')}\n"
                f"Authors: {_author_str(paper)}\n"
                f"Year: {paper.get('year', 'N/A')}\n"
                f"Abstract (excerpt): {(paper.get('abstract') or '')[:600]}\n"
                f"Key Finding: {analysis.get('key_finding', 'N/A')}\n"
            )
        try:
            return self._llm(
                _LITERATURE_REVIEW.format(topic=topic, papers_text=papers_text),
                temperature=0.3,
                max_tokens=1600,
            )
        except Exception as exc:
            return f"Literature review generation failed: {exc}"


    # ── Paper summary ─────────────────────────────────────────────────────────


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
                    abstract=abstract[:2500],
                ),
                temperature=0.2,
                max_tokens=800,
            )
        except Exception as exc:
            return f"Summarization failed: {exc}"