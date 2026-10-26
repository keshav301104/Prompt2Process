"""Central settings. Everything comes from environment variables (a .env file at the repo root works too)."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # the Prompt2Process/ repo folder
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "backend" / ".env")

DATA_DIR = Path(os.getenv("P2P_DATA_DIR", ROOT / "data")).resolve()  # synthetic company data (inputs)
STATE_DIR = Path(os.getenv("P2P_STATE_DIR", ROOT / "state")).resolve()  # database, checkpoints, outputs
FRONTEND_DIST = ROOT / "frontend" / "dist"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "")  # e.g. gemma-4-...  (auto-detected from the API when empty)
GEMMA_VISION_MODEL = os.getenv("GEMMA_VISION_MODEL", "")
GEMMA_DEEP_MODEL = os.getenv("GEMMA_DEEP_MODEL", "")  # model for the SOP compiler (hire:*); empty = GEMMA_MODEL
LLM_MODE = os.getenv("LLM_MODE", "auto")  # auto | live | offline
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "180"))
# Gemma 4 can "think" before answering. Routine steps (read, classify, draft) don't need it and get much faster
# without it; the SOP compiler (hire:*) keeps the model's default reasoning. Values: minimal | low | medium | high | ""
GEMMA_THINKING = os.getenv("GEMMA_THINKING", "minimal").strip().lower()
GEMMA_THINKING_DEEP = os.getenv("GEMMA_THINKING_DEEP", "").strip().lower()

DEFAULT_SETTINGS = {
    "chaos_mode": False,
    "chaos_rate": 0.25,
    "hourly_cost_inr": float(os.getenv("HOURLY_COST_INR", "300")),
    "minutes_per_invoice_manual": 12,
    "minutes_per_collection_manual": 15,
    "minutes_per_case_manual": 20,
    "extraction_mode": os.getenv("EXTRACTION_MODE", "template_first"),  # template_first | llm_first
}

# Autonomy promotion rules (earned trust)
PROMOTION = {
    1: {"min_backtest_accuracy": 0.85, "min_backtest_tasks": 20},
    2: {"min_backtest_accuracy": 0.90, "min_backtest_tasks": 20, "min_supervised_approvals": 5},
}

STATE_DIR.mkdir(parents=True, exist_ok=True)
