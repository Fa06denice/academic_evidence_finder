# Academic Evidence Finder

Academic Evidence Finder is a Vue + FastAPI application for retrieving academic
papers, analysing claims against the literature, and chatting with a paper
through a grounded RAG pipeline.

## Current Feature Set

- `Claim Verifier`
  - transforms a claim into academic search queries
  - retrieves papers from Semantic Scholar
  - analyses stance, confidence, and relevance per paper
  - produces an overall verdict
  - can generate a literature review from the selected evidence set
- `Paper Search`
  - retrieves papers for a topic or exact title
  - supports an `I know the exact title` mode to prioritize precise matches
- `Paper Chat`
  - fetches full text when available (`PDF`, `Europe PMC`, `PMC HTML`)
  - chunks the paper into anchored text blocks
  - uses embeddings + Chroma + lexical retrieval
  - answers with grounded citations and a full-text viewer linked to sources

## Architecture

### Frontend

- `Vue 3`
- `Vite`
- `Vue Router`
- location: `frontend/`

### Backend

- `FastAPI`
- `httpx`
- `PyMuPDF`
- `BeautifulSoup`
- `ChromaDB`
- location: `backend/`

### External Services

- `Semantic Scholar` for paper discovery
- `Groq / Kimi` for the main LLM workflows
- `OpenAI embeddings` for vector retrieval in `Paper Chat`

## Retrieval and RAG

The `Paper Chat` flow is currently:

1. fetch full text or fallback text
2. build structured text blocks and RAG chunks
3. embed chunks and persist them in Chroma
4. embed the user query
5. run hybrid retrieval:
   - vector search via Chroma
   - lexical scoring / BM25-like reranking
6. send grounded context to the LLM
7. return an answer with source tags and anchored excerpts

The backend also maintains a global paper index so previously seen papers can be
reused before falling back to Semantic Scholar.

## Repository Layout

```text
academic_evidence_finder/
├── backend/
│   ├── analyzer.py
│   ├── cache_manager.py
│   ├── main.py
│   ├── paper_chat.py
│   ├── paper_index.py
│   ├── scholar_client.py
│   ├── requirements.txt
│   ├── Procfile
│   └── railway.toml
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── api/
├── vercel.json
└── README.md
```

## Local Development

### Backend

Recommended Python version: `3.11` or `3.12`.

```bash
cd backend
python3.11 -m venv ../.venv
source ../.venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

### Backend

Required:

```env
LLM_PROVIDER=groq
LLM_API_KEY=...
SEMANTIC_SCHOLAR_API_KEY=...
```

Optional Groq key pool:

```env
LLM_API_KEY_2=...
LLM_API_KEY_3=...
LLM_API_KEY_4=...
```

Optional vector retrieval for `Paper Chat`:

```env
EMBEDDING_API_KEY=...
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
CHROMA_DIR=/data/chroma
```

Notes:

- If `EMBEDDING_API_KEY` is absent, the app falls back to lexical retrieval.
- On Railway, mount a persistent volume on `/data` and set
  `CHROMA_DIR=/data/chroma`.
- Without a volume, use `CHROMA_DIR=.chroma`.

### Frontend

```env
VITE_API_URL=https://academicevidencefinder-production.up.railway.app
```

If `VITE_API_URL` is omitted, the frontend can also use the `/api/*` rewrite
defined in `vercel.json`.

## Deployment

### Backend on Railway

- service root directory: `backend`
- start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

- recommended persistent volume mount: `/data`
- recommended variable: `CHROMA_DIR=/data/chroma`

### Frontend on Vercel

- build command comes from `vercel.json`
- current output directory: `frontend/dist`
- `/api/*` requests are rewritten to the Railway backend

## Health Check

The backend exposes:

```text
GET /api/health
```

It returns:

- active model configuration
- cache stats
- paper index status
- Chroma status and storage path

## Validation Commands

Backend:

```bash
python3 -m compileall backend
```

Frontend:

```bash
cd frontend
npm run build
```

## Known Constraints

- `Semantic Scholar` can return `429` or `500`, so the system uses caching and
  a local paper index to reduce external dependency pressure.
- `Paper Chat` quality depends on full-text availability and chunk quality.
- `Clear server cache` also clears Chroma collections, which forces reindexing.
