"""Check how well the acceptance score is calibrated, and refit it.

    python scripts/evaluate_calibration.py                 # synthetic contacts (pipeline check only)
    python scripts/evaluate_calibration.py --csv data.csv  # real de-identified contact records

CSV columns: hist_accept_rate, load, night, last_bed, pending_cases, accepted, and
optionally time, hospital_id, pathway. Earlier rows fit, later rows test.
Writes results/calibration_<name>.md. Never commit real data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from synapse_h.calibration import evaluate, predict, subgroup_metrics, synthetic_contacts, temporal_split  # noqa: E402


def md_table(df: pd.DataFrame) -> str:
    def cell(v):
        return f"{v:.3f}" if isinstance(v, float) else str(v)
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns)
    return head + "".join("\n| " + " | ".join(cell(v) for v in row) + " |" for row in df.itertuples(index=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--out", default=str(ROOT / "results"))
    args = ap.parse_args()
    df = pd.read_csv(args.csv) if args.csv else synthetic_contacts()
    name = Path(args.csv).stem if args.csv else "synthetic"
    r = evaluate(df)
    _, test = temporal_split(df)
    rows = [("Brier (낮을수록 좋음)", "brier"), ("Log loss", "log_loss"), ("보정 기울기 (1이 이상적)", "calibration_slope"),
            ("보정 절편 (0이 이상적)", "calibration_intercept"), ("ECE", "ece"), ("평균 점수", "mean_score"),
            ("실제 수용률", "base_rate")]
    lines = [f"# 수용 점수 보정 점검 — {name}", ""]
    if not args.csv:
        lines += ["**합성 데이터입니다.** 실제 수용 결과가 아니라 일부러 다른 '정답 모델'로 만든 가상 기록이며, "
                  "파이프라인이 작동하는지만 보여 줍니다. 모델 성능 근거로 쓰지 마세요.", ""]
    lines += [f"앞쪽 {r['train_n']}건으로 다시 맞추고 뒤쪽 {r['test_n']}건으로 평가했습니다 (시간 순서 유지).", "",
              "| 지표 | 현재 계수 (합성) | 다시 맞춘 계수 |", "|---|---|---|"]
    lines += [f"| {label} | {r['shipped'][k]:.3f} | {r['refit'][k]:.3f} |" for label, k in rows]
    lines += ["", "다시 맞춘 계수: " + ", ".join(f"{k}={v:+.2f}" for k, v in r["refit_coef"].items()), "",
              "## 신뢰도 표 (다시 맞춘 계수)", "", md_table(r["reliability_refit"])]
    if "pathway" in test:
        sub = subgroup_metrics(test.reset_index(drop=True), predict(r["refit_coef"], test), "pathway")
        lines += ["", "## 경로별", "", md_table(sub)]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"calibration_{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
