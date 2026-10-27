"""Synthetic digital twin (proposal §4.2, Appendix A).

Compares a nearest-appropriate policy with the Synapse-H policy over paired
synthetic episodes. Both policies face the *same* latent acceptance draw per
hospital, so every difference comes from the contact order alone.

The Synapse-H policy only uses what the app could observe (historical
acceptance and a reported, possibly stale load) through the app's own
readiness baseline; it never sees the latent acceptance, the regional shock
or the unexplained variation.

This tests computational plausibility only. It contains no patient data,
does not reproduce Korean hospital behaviour and does not estimate mortality.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

import numpy as np
import pandas as pd

from .capabilities import PATHWAYS
from .data import HANDOVER_MIN, ROAD_FACTOR, SPEED_KMH, default_network
from .readiness import COEF, PRIOR_ACCEPT

CONDITIONS = ("stroke", "trauma", "stemi", "pediatric", "gi_bleed")
CONDITION_MIX = (0.25, 0.20, 0.20, 0.15, 0.20)
TRAVEL_SURFACES = {"urban": 1.0, "mixed": 1.4, "rural": 2.0}
REGION_BOX = (4.0, 24.0, 4.0, 20.0)
STALE_SHRINK = 0.6  # stale estimates are pulled toward the prior, as in synapse_h.readiness


@dataclass(frozen=True)
class TwinParams:
    n_episodes: int = 20_000
    seed: int = 2026
    model_error: float = 0.3  # extra logit-scale misspecification of the readiness baseline
    report_sd: float = 0.05  # error in a fresh reported load
    stale_report_sd: float = 0.20  # error in a stale reported load (older value)
    stale_prob: float = 0.15  # chance a hospital feed is stale in an episode
    first_contact_min: float = 3.0
    failed_contact_min: float = 6.0
    escalation_min: float = 10.0  # extra delay when every candidate refuses
    travel_surface: str = "urban"
    congestion_mean: float = 0.0
    congestion_sd: float = 0.5
    latent_noise: float = 0.6  # hospital-episode variation no observable feature explains
    w_travel: float = 1.0
    w_rejection: float = 1.0
    w_load: float = 0.5
    w_uncertainty: float = 1.0
    retry_penalty_min: float = 12.0


@dataclass
class TwinResult:
    params: TwinParams
    episodes: pd.DataFrame  # one row per episode, both policies
    summary: pd.DataFrame  # metric × policy table


def _policy_outcome(order_key, eligible, accepted, travel, p):
    n = order_key.shape[0]
    rows = np.arange(n)
    order = np.argsort(order_key, axis=1, kind="stable")
    acc_ord = np.take_along_axis(accepted & eligible, order, axis=1)
    n_elig = eligible.sum(axis=1)
    has = acc_ord.any(axis=1)
    k = np.argmax(acc_ord, axis=1)  # index of first acceptance in contact order
    chosen = order[rows, k]
    attempts = np.where(has, k + 1, n_elig)
    conf = np.where(has, p.first_contact_min + p.failed_contact_min * k,
                    p.first_contact_min + p.failed_contact_min * n_elig + p.escalation_min)
    nearest = np.argmin(np.where(eligible, travel, np.inf), axis=1)
    dest = np.where(has, chosen, nearest)  # medical control forces the nearest capable site
    return {
        "first_accept": acc_ord[:, 0],
        "attempts": attempts,
        "confirmation": conf,
        "travel": travel[rows, dest],
        "escalated": ~has,
        "dest": dest,
    }


def simulate(params: TwinParams | None = None) -> TwinResult:
    p = params or TwinParams()
    rng = np.random.default_rng(p.seed)
    hospitals = default_network()
    m, n = len(hospitals), p.n_episodes

    hx = np.array([h.x for h in hospitals])
    hy = np.array([h.y for h in hospitals])
    hist = np.array([h.hist_accept_rate for h in hospitals])
    base_load = np.array([h.load for h in hospitals])
    caps = [h.capabilities for h in hospitals]

    # 1. Patient condition, acuity and origin-specific travel times.
    cond = rng.choice(len(CONDITIONS), size=n, p=CONDITION_MIX)
    high_acuity = rng.random(n) < 0.4
    ox = rng.uniform(REGION_BOX[0], REGION_BOX[1], n)
    oy = rng.uniform(REGION_BOX[2], REGION_BOX[3], n)
    dist = np.hypot(ox[:, None] - hx[None, :], oy[:, None] - hy[None, :])
    travel = (HANDOVER_MIN + dist * ROAD_FACTOR / SPEED_KMH * 60) * TRAVEL_SURFACES[p.travel_surface]
    travel = np.maximum(2.0, travel + rng.normal(0, 1.5, (n, m)))

    # 2. Hard capability constraints.
    elig_by_cond = np.array([[PATHWAYS[c].required <= caps[j] for j in range(m)] for c in CONDITIONS])
    eligible = elig_by_cond[cond]

    # 3. Correlated regional congestion and local load.
    g = rng.normal(p.congestion_mean, p.congestion_sd, n)
    load = np.clip(base_load[None, :] + 0.15 * g[:, None] + rng.normal(0, 0.12, (n, m)), 0, 1)

    # 4. Latent acceptance. The policy never sees z_true, the regional shock g or the latent term.
    z_true = -0.6 + 4.0 * hist[None, :] - 2.8 * load - 0.6 * g[:, None] + rng.normal(0, p.latent_noise, (n, m))
    p_true = 1 / (1 + np.exp(-z_true))
    # Observable state, as the app sees it: historical acceptance and a *reported* load that is
    # older and noisier when the feed is stale. The estimate is the app's own logistic baseline.
    stale = rng.random((n, m)) < p.stale_prob
    load_obs = np.clip(load + rng.normal(0, 1, (n, m)) * np.where(stale, p.stale_report_sd, p.report_sd), 0, 1)
    z_hat = (COEF["intercept"] + COEF["hist_accept_rate"] * hist[None, :] + COEF["load"] * load_obs
             + rng.normal(0, p.model_error, (n, m)))
    p_hat = 1 / (1 + np.exp(-z_hat))
    p_hat = np.where(stale, STALE_SHRINK * p_hat + (1 - STALE_SHRINK) * PRIOR_ACCEPT, p_hat)
    uncertainty = np.where(stale, 0.4, 0.1)

    # 6. Shared acceptance draws: both policies face the same episode.
    accepted = rng.random((n, m)) < p_true

    # 5. Rank by nearest-compatible and by Synapse-H expected-cost score.
    near_key = np.where(eligible, travel, np.inf)
    syn_score = (p.w_travel * travel
                 + p.w_rejection * (1 - p_hat) * p.retry_penalty_min
                 + p.w_load * load_obs * 10
                 + p.w_uncertainty * uncertainty * 10)
    syn_key = np.where(eligible, syn_score, np.inf)

    out = {}
    for name, key in (("nearest", near_key), ("synapse", syn_key)):
        r = _policy_outcome(key, eligible, accepted, travel, p)
        total = r["confirmation"] + r["travel"]
        r["conf_plus_travel"] = total
        r["risk_adjusted"] = total * (1 + 0.15 * high_acuity)  # stylized; explicitly not mortality
        out[name] = r

    episodes = pd.DataFrame({"condition": np.array(CONDITIONS)[cond], "high_acuity": high_acuity})
    for name, r in out.items():
        for k, v in r.items():
            episodes[f"{name}_{k}"] = v

    # 7. Aggregate paired metrics.
    return TwinResult(p, episodes, summarize(episodes))


METRICS = [
    ("first_accept", "First-choice acceptance (1순위 수용률)", "pct"),
    ("attempts", "Mean contact attempts (평균 연락 횟수)", "mean"),
    ("confirmation", "Mean confirmation time (평균 승인 시간, 분)", "mean"),
    ("confirmation_p90", "P90 confirmation time (P90 승인 시간, 분)", "p90"),
    ("travel", "Mean travel time (평균 이송 시간, 분)", "mean"),
    ("conf_plus_travel", "Mean confirmation + travel (승인+이송, 분)", "mean"),
    ("risk_adjusted", "Risk-adjusted delay proxy (위험보정 지연 지표, 분)", "mean"),
    ("escalated", "Escalation rate (의료지도 에스컬레이션)", "pct"),
]


def summarize(ep: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, label, kind in METRICS:
        col = "confirmation" if key == "confirmation_p90" else key
        a, b = ep[f"nearest_{col}"], ep[f"synapse_{col}"]
        if kind == "p90":
            va, vb = float(np.percentile(a, 90)), float(np.percentile(b, 90))
        else:
            va, vb = float(a.mean()), float(b.mean())
        if kind == "pct":
            change = f"{(vb - va) * 100:+.1f} %p"
        elif kind == "p90":
            change = f"{vb - va:+.1f} 분"
        else:
            change = f"{(vb - va) / va * 100:+.1f}%" if va else "—"
        rows.append({"metric": key, "지표": label, "Nearest appropriate": va, "Synapse-H": vb,
                     "Paired change": change, "kind": kind})
    return pd.DataFrame(rows)


SENSITIVITY_VARIABLES = {
    "model_error": ("모델 오차 (logit SD)", [0.0, 0.3, 0.6, 1.0, 1.5, 2.0]),
    "latent_noise": ("관측 불가 변동 (logit SD)", [0.0, 0.3, 0.6, 1.0, 1.5]),
    "failed_contact_min": ("실패 연락 비용 (분)", [3, 6, 9, 12]),
    "congestion_mean": ("지역 혼잡도 (평균 shock)", [-0.5, 0.0, 0.5, 1.0, 1.5]),
    "stale_prob": ("피드 지연 확률", [0.0, 0.15, 0.3, 0.5]),
    "travel_surface": ("이동 표면", list(TRAVEL_SURFACES)),
}


def sensitivity(variable: str, base: TwinParams | None = None, n_episodes: int = 8_000) -> pd.DataFrame:
    base = replace(base or TwinParams(), n_episodes=n_episodes)
    rows = []
    for v in SENSITIVITY_VARIABLES[variable][1]:
        res = simulate(replace(base, **{variable: v}))
        s = res.summary.set_index("metric")
        rows.append({
            variable: v,
            "first_accept_gain_pp": (s.loc["first_accept", "Synapse-H"] - s.loc["first_accept", "Nearest appropriate"]) * 100,
            "confirmation_change_min": s.loc["confirmation", "Synapse-H"] - s.loc["confirmation", "Nearest appropriate"],
            "travel_change_min": s.loc["travel", "Synapse-H"] - s.loc["travel", "Nearest appropriate"],
            "total_change_min": s.loc["conf_plus_travel", "Synapse-H"] - s.loc["conf_plus_travel", "Nearest appropriate"],
        })
    return pd.DataFrame(rows)


def params_dict(p: TwinParams) -> dict:
    return asdict(p)


KEY_METRICS = ("first_accept", "attempts", "confirmation", "travel", "conf_plus_travel")


def replicate(params: TwinParams | None = None, n_reps: int = 10) -> pd.DataFrame:
    """Paired Synapse-H minus nearest differences for independent seeds."""
    base = params or TwinParams()
    rows = []
    for i in range(n_reps):
        s = simulate(replace(base, seed=base.seed + i)).summary.set_index("metric")
        row = {"seed": base.seed + i}
        for k in KEY_METRICS:
            row[k] = s.loc[k, "Synapse-H"] - s.loc[k, "Nearest appropriate"]
        rows.append(row)
    return pd.DataFrame(rows)


def replicate_summary(reps: pd.DataFrame, level: float = 0.95) -> pd.DataFrame:
    """Mean paired difference with a t-based confidence interval across seeds."""
    from scipy import stats

    n = len(reps)
    t = stats.t.ppf(0.5 + level / 2, n - 1) if n > 1 else float("nan")
    out = []
    for k in KEY_METRICS:
        x = reps[k]
        half = t * x.std(ddof=1) / np.sqrt(n) if n > 1 else float("nan")
        out.append({"metric": k, "mean_diff": x.mean(), "ci_low": x.mean() - half, "ci_high": x.mean() + half,
                    "n_seeds": n})
    return pd.DataFrame(out)
