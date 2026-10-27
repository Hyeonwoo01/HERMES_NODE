"""Write the FHIR bundles of the demo cases so the official HL7 validator can check them.

    python scripts/export_fhir_examples.py --out fhir-out

Writes fhir-out/r5/*.json (FHIR R5) and fhir-out/r4/*.json (FHIR R4 with KR Core
profiles). CI then runs:
    java -jar validator_cli.jar fhir-out/r5 -version 5.0.0
    java -jar validator_cli.jar fhir-out/r4 -version 4.0.1 -ig hl7.fhir.kr.core#1.0.2
All cases are synthetic.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from synapse_h.data import CONCURRENT_CASES, default_network  # noqa: E402
from synapse_h.fhir import case_bundle, kr_core_bundle, validate_bundle  # noqa: E402
from synapse_h.intake import build_case  # noqa: E402

FIXED_NOW = datetime(2026, 10, 27, 5, 30, tzinfo=timezone.utc)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="fhir-out")
    args = ap.parse_args()
    out = Path(args.out)
    (out / "r5").mkdir(parents=True, exist_ok=True)
    (out / "r4").mkdir(parents=True, exist_ok=True)
    net = default_network()
    n = 0
    for i, d in enumerate(CONCURRENT_CASES):
        values = dict(d, dbp=None if i % 3 == 0 else d["sbp"] - 50, rr=18 if i % 2 else None)
        case = build_case(d["case_id"], d["origin_id"], values, confirmed_by="synthetic reviewer",
                          red_flags=["기관삽관 상태"] if d.get("gcs") else [])
        dest = net[i % len(net)] if i % 2 == 0 else None
        for folder, fn in (("r5", case_bundle), ("r4", kr_core_bundle)):
            bundle = fn(case, dest, now=FIXED_NOW)
            problems = validate_bundle(bundle)
            if problems:
                sys.exit(f"{case.case_id} {folder}: {problems}")
            (out / folder / f"{case.case_id}.json").write_text(
                json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
            n += 1
    print(f"wrote {n} bundles to {out}")


if __name__ == "__main__":
    main()
