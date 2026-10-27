# Digital twin baseline (synthetic)

`python scripts/run_twin_experiment.py` · 20,000 paired episodes · seed 2026 · 10 seeds for the confidence intervals · Python 3.13.16, numpy 2.5.4, pandas 3.0.6, scipy 1.18.1.

## Single run (seed 2026)

| Metric | Nearest appropriate | Synapse-H | Paired change |
|---|---|---|---|
| First-choice acceptance (1순위 수용률) | 64.1% | 69.9% | +5.8 %p |
| Mean contact attempts (평균 연락 횟수) | 1.50 | 1.43 | -5.1% |
| Mean confirmation time (평균 승인 시간, 분) | 6.77 | 6.31 | -6.8% |
| P90 confirmation time (P90 승인 시간, 분) | 15.00 | 15.00 | +0.0 분 |
| Mean travel time (평균 이송 시간, 분) | 16.50 | 16.82 | +1.9% |
| Mean confirmation + travel (승인+이송, 분) | 23.27 | 23.13 | -0.6% |
| Risk-adjusted delay proxy (위험보정 지연 지표, 분) | 24.69 | 24.54 | -0.6% |
| Escalation rate (의료지도 에스컬레이션) | 4.6% | 4.6% | +0.0 %p |

## Paired difference across 10 seeds (Synapse-H − nearest, 95% CI)

| Metric | Mean difference | 95% CI |
|---|---|---|
| First-choice acceptance (1순위 수용률) | +5.49 pp | [+5.31, +5.66] pp |
| Mean contact attempts (평균 연락 횟수) | -0.07 | [-0.08, -0.07] |
| Mean confirmation time (평균 승인 시간, 분) | -0.45 | [-0.46, -0.43] |
| Mean travel time (평균 이송 시간, 분) | +0.31 | [+0.31, +0.31] |
| Mean confirmation + travel (승인+이송, 분) | -0.14 | [-0.15, -0.12] |

The confidence interval reflects simulation randomness only, not whether the model assumptions are right. See `synapse_h/twin.py` for every assumption.
