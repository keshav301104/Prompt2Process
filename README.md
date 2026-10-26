# Prompt2Process

> Turn a company's SOP — written in plain English — into a checked, running back-office process,
> operated by digital employees that earn autonomy only when they prove they are accurate.

Built at **Hacktoberfest Hack Day Amaravati × AIBPT Club, VIT-AP** (MLH, 26 Oct 2026),
problem statement **#19 — Natural-Language Workflow Builder**.

## Status
🚧 Building live during the hack day — follow the commit history.

## Stack
- **Gemma 4** (open-weights, via the Gemini API) — SOP → plan compiler, document reading (text + vision), multilingual drafting
- **LangGraph** — workflow runtime with checkpoints and human-in-the-loop
- **FastAPI** backend · **React + TypeScript** console
- **scikit-learn** — anomaly detection, learned categoriser, payment-risk model

## License
MIT