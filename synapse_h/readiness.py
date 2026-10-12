"""Readiness Engine: freshness-aware acceptance forecast with uncertainty.

An interpretable logistic baseline predicts whether a destination will accept
and initiate the pathway within a short operational horizon. Stale feeds are
shrunk toward an uninformative prior and widen the interval rather than being
silently trusted.
"""

from __future__ import annotations

import math

from .models import Hospital, Readiness

STALE_THRESHOLD_MIN = 15.0  # feeds older than this are flagged and down-weighted
UNVERIFIABLE_MIN = 60.0  # feeds older than this are excluded until phone-verified
PRIOR_ACCEPT = 0.5

# Logistic coefficients (synthetic baseline; to be refit on partner data).
COEF = {
    "intercept": -0.6,
    "hist_accept_rate": 4.0,
    "load": -2.8,
    "night": -0.5,
    "last_bed": -0.3,
    "pending_cases": -0.35,
}


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def freshness_weight(feed_age_min: float) -> float:
    """1.0 while fresh, linear decay to 0 between the stale and unverifiable thresholds."""
    if feed_age_min <= STALE_THRESHOLD_MIN:
        return 1.0
    span = UNVERIFIABLE_MIN - STALE_THRESHOLD_MIN
    return max(0.0, 1.0 - (feed_age_min - STALE_THRESHOLD_MIN) / span)


def is_night(hour: int) -> bool:
    return hour < 7 or hour >= 22


def predict_readiness(h: Hospital, hour: int = 14, pending_cases: int = 0) -> Readiness:
    z = (COEF["intercept"]
         + COEF["hist_accept_rate"] * h.hist_accept_rate
         + COEF["load"] * h.load
         + COEF["night"] * is_night(hour)
         + COEF["last_bed"] * (h.beds_available == 1)
         + COEF["pending_cases"] * pending_cases)
    p_raw = _sigmoid(z)

    w = freshness_weight(h.feed_age_min)
    p = w * p_raw + (1 - w) * PRIOR_ACCEPT

    uncertainty = 0.10 + 0.40 * (1 - w) + 0.06 * (h.load > 0.85) + 0.04 * is_night(hour)
    uncertainty = min(1.0, uncertainty)
    half = 0.05 + 0.5 * uncertainty
    if uncertainty < 0.15:
        conf = "high"
    elif uncertainty < 0.30:
        conf = "moderate"
    else:
        conf = "low"
    return Readiness(
        accept_prob=p,
        low=max(0.0, p - half),
        high=min(1.0, p + half),
        uncertainty=uncertainty,
        confidence=conf,
        stale=h.feed_age_min > STALE_THRESHOLD_MIN,
        freshness_weight=w,
    )


CONFIDENCE_KO = {"high": "높음", "moderate": "보통", "low": "낮음"}
