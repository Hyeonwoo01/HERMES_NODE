"""Business-plan arithmetic: revenue build-up and a monthly cash bridge.

All prices and drivers are planning assumptions from the business proposal,
not contracts. The point is to make the plan checkable: every yearly revenue
figure should be rebuildable from customers x price x recognised months, and
the first-year funding ask should be reconciled with the operating loss.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

YEARS = ("Y1", "Y2", "Y3", "Y4", "Y5")

# Proposal Table 18 (₩M): revenue, COGS, operating expense.
PLAN_REVENUE = (150, 720, 1950, 4750, 9200)
PLAN_COGS = (50, 180, 450, 1000, 1840)
PLAN_OPEX = (340, 720, 1280, 2480, 4220)


@dataclass
class Prices:  # ₩M per year (licenses) or per event (pilot, integration)
    regional: float = 250
    advanced: float = 60
    essential: float = 24
    pilot: float = 125
    integration: float = 15


@dataclass
class Drivers:
    """Customers active at each year end (licenses) and events within the year."""

    regions: tuple = (0, 1, 2, 5, 9)
    advanced: tuple = (0, 5, 15, 42, 90)
    essential: tuple = (0, 7, 10, 28, 60)
    pilots: tuple = (1, 0, 1, 1, 1)
    integrations: tuple = (2, 10, 13, 45, 80)
    new_fraction: float = 0.5  # share of the year a newly signed license is billed (0.5 = mid-year start)
    extra: dict = field(default_factory=dict)


def revenue_buildup(d: Drivers | None = None, p: Prices | None = None) -> pd.DataFrame:
    d, p = d or Drivers(), p or Prices()
    rows = []
    for i, y in enumerate(YEARS):
        row = {"연도": y}
        for key, price in (("regions", p.regional), ("advanced", p.advanced), ("essential", p.essential)):
            active = getattr(d, key)[i]
            prev = getattr(d, key)[i - 1] if i else 0
            new = max(0, active - prev)
            row[key] = (active - new) * price + new * price * d.new_fraction
        row["pilots"] = d.pilots[i] * p.pilot
        row["integrations"] = d.integrations[i] * p.integration
        row["build_up"] = sum(row[k] for k in ("regions", "advanced", "essential", "pilots", "integrations"))
        row["plan"] = PLAN_REVENUE[i]
        row["gap"] = row["build_up"] - row["plan"]
        rows.append(row)
    return pd.DataFrame(rows)


@dataclass
class CashResult:
    monthly: pd.DataFrame  # month, revenue_recognised, cash_in, cash_out, balance
    min_balance: float
    min_month: int
    funding_gap: float  # extra money needed to never go below zero


def cash_bridge(initial_cash: float, revenue=PLAN_REVENUE, cogs=PLAN_COGS, opex=PLAN_OPEX,
                collection_lag_months: int = 4) -> CashResult:
    """Spread each year evenly over 12 months; customers pay `collection_lag_months` after billing."""
    months = 12 * len(revenue)
    billed = [revenue[m // 12] / 12 for m in range(months)]
    out = [(cogs[m // 12] + opex[m // 12]) / 12 for m in range(months)]
    cash_in = [billed[m - collection_lag_months] if m >= collection_lag_months else 0.0 for m in range(months)]
    bal, rows = initial_cash, []
    for m in range(months):
        bal += cash_in[m] - out[m]
        rows.append({"month": m + 1, "billed": billed[m], "cash_in": cash_in[m], "cash_out": out[m], "balance": bal})
    df = pd.DataFrame(rows)
    i = int(df["balance"].idxmin())
    min_bal = float(df.loc[i, "balance"])
    return CashResult(df, min_bal, int(df.loc[i, "month"]), max(0.0, -min_bal))
