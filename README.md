# 🔬 Academic Evidence Finder

An AI-powered research assistant that retrieves real scientific papers from
Semantic Scholar and extracts grounded evidence for or against any claim.

USE COLLABORATE.TXT for prompting your fav AI about this project

## Setup

```bash
git clone <repo>
cd academic-evidence-finder
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your API keys
streamlit run app.py
```

## API Keys

| Key | Where to get it | Required? |
|-----|----------------|-----------|
| `GROQ_API_KEY` | _________ | ✅ Yes |
| `SEMANTIC_SCHOLAR_API_KEY` | [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api) | ✅ Yes |

## Features

| Mode | What it does |
|------|-------------|
| 🔍 Evidence Finder | Finds papers supporting or contradicting a claim, with direct evidence quotes |
| 📚 Literature Review | Generates a structured literature review on any topic |
| 📄 Paper Summarizer | Searches for and summarizes a specific paper |

## How it works

1. **Query transformation** — your input is turned into 1–3 academic search queries via LLM
2. **Semantic Scholar search** — papers are retrieved with full metadata and abstracts
3. **Evidence analysis** — each paper's abstract is analysed by the LLM for relevance and stance
4. **Overall verdict** — a synthesized verdict is produced across all papers
5. **Caching** — all results are saved locally; repeated queries are instant

## Anti-hallucination guarantees

- The LLM is strictly instructed to quote from the abstract only
- Papers with no abstract are flagged as `INSUFFICIENT_DATA`
- No general knowledge answers are generated — only retrieved content is used
- Every result links back to the original paper on Semantic Scholar
