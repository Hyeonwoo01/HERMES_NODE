"""Compare the rule-based and LLM extractors on the labelled synthetic notes.

    python scripts/compare_extractors.py            # rule-based only (offline)
    python scripts/compare_extractors.py --llm      # also the LLM extractor (needs an API key)

The LLM run reads LLM_PROVIDER, ANTHROPIC_API_KEY / CLAUDE_MODEL or OPENAI_API_KEY /
OPENAI_MODEL from the environment. Every note is synthetic. Writes
results/extractor_comparison.json and .md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from synapse_h.intake import RuleBasedExtractor  # noqa: E402
from synapse_h.intake_eval import load_notes, score  # noqa: E402
from synapse_h.llm import LLMClient, LLMConfig  # noqa: E402
from synapse_h.llm_intake import LLMExtractor  # noqa: E402


def pct(x):
    return "—" if x is None else f"{x:.1%}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "results"))
    args = ap.parse_args()

    data = load_notes()
    subsets = {
        "all": None,
        "written with the rules (n01–n30)": {n["id"] for n in data["notes"][:30]},
        "varied phrasing (n31–n40)": {n["id"] for n in data["notes"][30:]},
    }
    extractors = {"rule-based": RuleBasedExtractor()}
    model = None
    if args.llm:
        cfg = LLMConfig.from_mapping()
        if cfg.missing:
            sys.exit("LLM not configured: " + ", ".join(cfg.missing))
        client = LLMClient(cfg)
        model = client.model
        extractors[f"LLM + rule cross-check ({cfg.provider})"] = LLMExtractor(client)

    results = {name: {s: score(ex, data, ids) for s, ids in subsets.items()} for name, ex in extractors.items()}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    record = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "llm_model": model, "dataset": "evals/intake_notes.json", "results": results}
    (out / "extractor_comparison.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Intake extractor comparison (synthetic notes)", "",
             f"{len(data['notes'])} invented referral notes × {len(data['fields'])} required fields. "
             "*Unsafe* = a value proposed as extracted that differs from the label; *missed* = left for the "
             "clinician although the note states it. Every proposal still goes through clinician confirmation.", ""]
    if not args.llm:
        lines += ["LLM extractor: not measured in this run (no API key). Run with `--llm` to add it.", ""]
    for s in subsets:
        lines += [f"## {s}", "", "| Extractor | Correct | Unsafe | Missed |", "|---|---|---|---|"]
        for name in extractors:
            r = results[name][s]
            lines.append(f"| {name} | {pct(r['accuracy'])} ({r['correct']}/{r['fields']}) | "
                         f"{r['unsafe']} | {r['missed']} |")
        lines.append("")
    (out / "extractor_comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
