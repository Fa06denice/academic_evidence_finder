# Evaluation Harness

This folder contains a small local evaluation harness for the backend API.

It is designed for:
- quick smoke tests before demos
- repeatable claim-verifier checks
- grounded `Paper Chat` checks without using the frontend
- generating JSON / CSV artefacts for slides or reporting

The scripts call the backend directly, so the frontend is not involved.

## Prerequisite

Run the backend first, locally or remotely.

Local example:

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Claim Verifier evaluation

Starter dataset:

```bash
python3 eval/run_claim_eval.py \
  --dataset eval/datasets/claim_verifier_sample.json \
  --base-url http://127.0.0.1:8000 \
  --workers 3
```

Outputs:
- `eval/results/claim_eval_<timestamp>.json`
- `eval/results/claim_eval_<timestamp>.csv`

Useful fields:
- `overall_verdict`
- `overall_confidence`
- `analysed_papers`
- `relevant_papers`
- `checks`

Broader benchmark:

```bash
python3 eval/run_claim_eval.py \
  --dataset eval/datasets/claim_verifier_benchmark.json \
  --base-url https://academicevidencefinder-production.up.railway.app \
  --workers 2
```

## Paper Chat evaluation

Starter dataset:

```bash
python3 eval/run_paper_chat_eval.py \
  --dataset eval/datasets/paper_chat_sample.json \
  --base-url http://127.0.0.1:8000 \
  --workers 2
```

Outputs:
- `eval/results/paper_chat_eval_<timestamp>.json`
- `eval/results/paper_chat_eval_<timestamp>.csv`

Useful fields:
- `source_type`
- `citation_count`
- `source_card_count`
- `answer_preview`
- `checks`

Broader benchmark:

```bash
python3 eval/run_paper_chat_eval.py \
  --dataset eval/datasets/paper_chat_benchmark.json \
  --base-url https://academicevidencefinder-production.up.railway.app \
  --workers 1
```

## Datasets

Two kinds of datasets are provided:

- `*_sample.json`
  - starter cases for smoke / demo-level validation
  - acceptable for development, not enough for final academic evaluation

- `*_template.json`
  - schema templates for your own gold dataset
  - recommended for final grading

- `*_benchmark.json`
  - broader, presentation-ready benchmark datasets
  - stronger than the smoke sets but still small enough to run live

## Recommended next step

Before final presentation, replace the sample datasets with:
- `10–20` annotated claim-verifier cases
- `5–10` annotated paper-chat questions on known papers

That gives you a defensible evaluation section covering:
- retrieval quality
- verdict stability
- grounded answering
- citation presence
- hallucination reduction
