"""Diagnostics for the Gemma 4 connection.  Run from backend/:   python -m app.llm.check

Prints: which Gemma models your key can see, the one Prompt2Process picked, a JSON test, a vision test, and the
SOP -> plan compiler result (attempts + checker errors). Paste the output to your teammate if anything fails."""

import time

from .. import (
    actions,  # noqa: F401
    config,
)
from ..core import checker
from .gemma import llm


def main() -> None:
    print("== Prompt2Process · Gemma check ==")
    print("key set:", bool(config.GEMINI_API_KEY), "| mode:", llm.mode, "| error:", llm.error or "-")
    if not llm.live:
        print("Offline: add GEMINI_API_KEY to the .env file in the repo root and run again.")
        return
    print("gemma models visible:", ", ".join(llm.list_models()) or "none")
    print("selected text model:", llm.model, "| vision model:", llm.vision_model)

    t0 = time.time()
    try:
        ans = llm.generate_json('Return {"ok": true, "model": "<your model family>"} as JSON.', purpose="check:json")
        print(f"JSON test: OK in {time.time() - t0:.1f}s ->", ans)
    except Exception as e:
        print("JSON test: FAILED ->", e)

    try:
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page(width=420, height=160)
        page.insert_text((20, 60), "INVOICE No: TEST/42   Total: Rs. 12,345.00", fontsize=14)
        png = page.get_pixmap(dpi=100).tobytes("png")
        t0 = time.time()
        ans = llm.generate_json(
            'Read the image. Return {"invoice_no": "...", "total": <number>}.', images=[png], purpose="check:vision"
        )
        print(f"Vision test: OK in {time.time() - t0:.1f}s ->", ans)
    except Exception as e:
        print("Vision test: FAILED ->", e)

    sop = config.DATA_DIR / "sops" / "accounts_payable_sop.md"
    if sop.exists():
        from ..workforce import compiler

        t0 = time.time()
        d = compiler.draft("Test", "ap", sop.read_text(encoding="utf-8"))
        print(f"Clarify ({d['method']}): {len(d['questions'])} questions in {time.time() - t0:.1f}s")
        for q in d["questions"]:
            print("   -", q["question"])
        t0 = time.time()
        res = compiler.compile_plan(d["draft_id"], {})
        print(
            f"Compile: {'OK' if res['check']['ok'] else 'FAILED'} in {time.time() - t0:.1f}s, {len(res['plan']['steps']) if res['plan'] else 0} steps"
        )
        for a in res["attempts"]:
            print(f"   attempt {a['attempt']} by {a['by']}: {'ok' if a['ok'] else 'errors'}")
            for msg in a["errors"][:6]:
                print("      ·", msg)
        report, _ = checker.check(res["plan"], "ap") if res["plan"] else ({"ok": False}, None)
        print("final plan passes checker:", report["ok"])
    print("total Gemma calls:", llm.total_calls)


if __name__ == "__main__":
    main()
