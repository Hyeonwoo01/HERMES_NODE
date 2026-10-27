"""Calibration checks and refitting for the acceptance score.

This is the pipeline to run once partner data exists: one row per transfer
contact with the features the app saw and whether the hospital accepted.

    hist_accept_rate, load, night, last_bed, pending_cases, accepted (0/1)
    optional: time (for a temporal split), hospital_id, pathway (for subgroups)

``evaluate`` reports how well a coefficient set is calibrated (Brier score,
log loss, calibration slope and intercept, expected calibration error and a
reliability table); ``fit_readiness`` refits the coefficients with
L2-regularised logistic regression. Until real data exists the script runs on
``synthetic_contacts`` and says so: the numbers then show only that the
pipeline works, not how the model performs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .readiness import COEF

FEATURES = ("hist_accept_rate", "load", "night", "last_bed", "pending_cases")
EPS = 1e-9


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-z))


def predict(coef: dict, df: pd.DataFrame) -> np.ndarray:
    z = coef["intercept"] + sum(coef[f] * df[f].to_numpy(float) for f in FEATURES)
    return _sigmoid(z)


def _irls(X: np.ndarray, y: np.ndarray, l2: float = 0.0, iters: int = 50) -> np.ndarray:
    """Logistic regression by Newton-Raphson; the first column (intercept) is not penalised."""
    w = np.zeros(X.shape[1])
    pen = np.full(X.shape[1], l2)
    pen[0] = 0.0
    for _ in range(iters):
        p = _sigmoid(X @ w)
        grad = X.T @ (y - p) - pen * w
        hess = (X * (p * (1 - p))[:, None]).T @ X + np.diag(pen)
        step = np.linalg.solve(hess + 1e-9 * np.eye(len(w)), grad)
        w += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w


def fit_readiness(df: pd.DataFrame, l2: float = 1.0) -> dict:
    X = np.column_stack([np.ones(len(df))] + [df[f].to_numpy(float) for f in FEATURES])
    w = _irls(X, df["accepted"].to_numpy(float), l2)
    return {"intercept": float(w[0]), **{f: float(v) for f, v in zip(FEATURES, w[1:])}}


def reliability_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if m.any():
            rows.append({"bin": f"{edges[b]:.1f}–{edges[b + 1]:.1f}", "n": int(m.sum()),
                         "mean_score": float(p[m].mean()), "observed_rate": float(y[m].mean())})
    return pd.DataFrame(rows)


def metrics(y: np.ndarray, p: np.ndarray, bins: int = 10) -> dict:
    y = np.asarray(y, float)
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    slope_fit = _irls(np.column_stack([np.ones(len(p)), _logit(p)]), y)
    # Calibration-in-the-large: intercept with the logit of the score as a fixed offset.
    offset = _logit(p)
    a = 0.0
    for _ in range(50):
        q = _sigmoid(a + offset)
        step = (y - q).sum() / max((q * (1 - q)).sum(), EPS)
        a += step
        if abs(step) < 1e-10:
            break
    rel = reliability_table(y, p, bins)
    ece = float((rel["n"] * (rel["mean_score"] - rel["observed_rate"]).abs()).sum() / len(y))
    return {
        "n": int(len(y)),
        "base_rate": float(y.mean()),
        "mean_score": float(p.mean()),
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
        "calibration_slope": float(slope_fit[1]),
        "calibration_intercept": float(a),
        "ece": ece,
    }


def temporal_split(df: pd.DataFrame, frac: float = 0.7, time_col: str = "time"):
    """Earlier rows for fitting, later rows for testing (no shuffling across time)."""
    d = df.sort_values(time_col) if time_col in df else df
    cut = int(len(d) * frac)
    return d.iloc[:cut], d.iloc[cut:]


def subgroup_metrics(df: pd.DataFrame, p: np.ndarray, by: str, min_n: int = 30) -> pd.DataFrame:
    rows = []
    for key, idx in df.groupby(by).indices.items():
        if len(idx) >= min_n:
            m = metrics(df["accepted"].to_numpy(float)[idx], p[idx])
            rows.append({by: key, **{k: m[k] for k in ("n", "base_rate", "mean_score", "brier",
                                                       "calibration_intercept")}})
    return pd.DataFrame(rows)


def synthetic_contacts(n: int = 6000, seed: int = 7) -> pd.DataFrame:
    """Invented contact records from a 'true' model that differs from the shipped coefficients."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "time": np.arange(n),
        "hospital_id": rng.choice([f"H{i}" for i in range(1, 9)], n),
        "pathway": rng.choice(["stroke", "trauma", "stemi", "pediatric", "gi_bleed"], n),
        "hist_accept_rate": rng.uniform(0.55, 0.95, n),
        "load": rng.beta(4, 3, n),
        "night": (rng.random(n) < 0.3).astype(int),
        "last_bed": (rng.random(n) < 0.2).astype(int),
        "pending_cases": rng.poisson(0.6, n),
    })
    true = {"intercept": -1.4, "hist_accept_rate": 3.2, "load": -1.9, "night": -0.9, "last_bed": -0.6,
            "pending_cases": -0.25}
    drift = np.where(df["time"] > n * 0.6, -0.3, 0.0)  # later period is busier
    p = _sigmoid(_logit(predict(true, df)) + drift)
    df["accepted"] = (rng.random(n) < p).astype(int)
    return df


def evaluate(df: pd.DataFrame, l2: float = 1.0) -> dict:
    """Shipped coefficients vs coefficients refit on the earlier part, both scored on the later part."""
    train, test = temporal_split(df)
    refit = fit_readiness(train, l2)
    y = test["accepted"].to_numpy(float)
    return {
        "train_n": len(train), "test_n": len(test),
        "shipped": metrics(y, predict(COEF, test)),
        "refit": metrics(y, predict(refit, test)),
        "refit_coef": refit,
        "reliability_shipped": reliability_table(y, predict(COEF, test)),
        "reliability_refit": reliability_table(y, predict(refit, test)),
    }
