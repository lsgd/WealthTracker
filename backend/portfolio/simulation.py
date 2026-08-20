"""Monte Carlo wealth projection.

Simulates total wealth forward with monthly geometric-Brownian-motion steps plus a
monthly contribution, and reports percentile bands per year. Everything runs in REAL
terms (today's purchasing power): the drift is the nominal expected return minus
inflation, and the contribution stays constant — which is exactly "contributions grow
with inflation" viewed in today's money.

Defaults are derived from the user's data and echoed back so the clients can show
what was assumed vs. what the user overrode:

- start_wealth: sum of the latest snapshots in base currency (same rule as the
  wealth summary).
- monthly_contribution: median monthly net (income - expenses, normalized) over the
  last year. Median, not mean — a truncated transaction feed or a one-off month
  should not skew the default.
- expected_return / volatility: blended from the current holdings' asset-class
  weights using the assumption table below; a documented 60/40-ish default when no
  positions exist.

Pure Python by design: the default 2,000 paths x 30 years is ~720k gauss draws,
well under a second — not worth a numpy dependency.
"""
import math
import random
from decimal import Decimal

# Long-run REAL-return-plus-inflation building blocks, per asset class:
# (nominal expected return, annual volatility). Deliberately unheroic numbers.
ASSET_CLASS_ASSUMPTIONS = {
    'equity': (0.070, 0.15),
    'fixed_income': (0.025, 0.06),
    'cash': (0.005, 0.005),
    'real_estate': (0.050, 0.12),
    'commodity': (0.040, 0.16),
    'crypto': (0.100, 0.60),
    'other': (0.040, 0.10),
}
# Used when no holdings exist to blend from: a conventional 60/40 portfolio.
DEFAULT_RETURN = 0.052
DEFAULT_VOLATILITY = 0.114
DEFAULT_INFLATION = 0.02

MAX_PATHS = 10_000
MIN_PATHS = 100
MAX_YEARS = 50

PERCENTILES = (5, 25, 50, 75, 95)


def _percentile(sorted_values, pct):
    """Linear-interpolation percentile of an already-sorted list."""
    if not sorted_values:
        return 0.0
    rank = (len(sorted_values) - 1) * pct / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[low]
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (rank - low)


def derive_start_wealth(user) -> float:
    """Sum of the latest snapshots in base currency — same rule as the summary view."""
    from exchange_rates.models import ExchangeRate

    from .models import FinancialAccount

    base_currency = user.profile.base_currency
    total = Decimal('0')
    for account in FinancialAccount.objects.filter(user=user):
        snapshot = account.latest_snapshot
        if not snapshot:
            continue
        if snapshot.balance_base_currency:
            total += snapshot.balance_base_currency
        elif snapshot.currency == base_currency:
            total += snapshot.balance
        else:
            rate = ExchangeRate.get_rate(
                snapshot.currency, base_currency, snapshot.snapshot_date,
            )
            if rate:
                total += snapshot.balance * rate
    return float(total)


def derive_monthly_contribution(user) -> float:
    """Median monthly net over the last 12 months, ignoring empty months.

    Empty months are almost always missing data (an account connected recently,
    a feed that reaches back only so far) rather than months where genuinely
    nothing happened — including them would drag the median toward zero.
    """
    from .spending import monthly_spending

    report = monthly_spending(user, months=12, mode='normalized')
    nets = [
        m['net'] for m in report['months']
        if m['income'] or m['expenses']
    ]
    if not nets:
        return 0.0
    nets.sort()
    mid = len(nets) // 2
    if len(nets) % 2:
        return float(nets[mid])
    return float((nets[mid - 1] + nets[mid]) / 2)


def derive_market_assumptions(user):
    """(expected_return, volatility) blended from current holdings, plus the weights.

    Weights come from each account's most recent snapshot that carries positions.
    Volatility blends linearly (correlation 1 between classes) — an upper bound,
    so the projection errs on the wide side rather than feigning precision.
    Returns (DEFAULT_RETURN, DEFAULT_VOLATILITY, {}) when there are no positions.
    """
    from .models import AccountSnapshot, FinancialAccount

    totals = {}
    for account in FinancialAccount.objects.filter(user=user):
        snapshot = (
            AccountSnapshot.objects
            .filter(account=account, positions__isnull=False)
            .distinct()
            .order_by('-snapshot_date', '-created_at', '-id')
            .first()
        )
        if snapshot is None:
            continue
        for pos in snapshot.positions.all():
            # Class weights only need relative sizes; currency conversion would
            # move every class by roughly the same factor, so skip it here.
            totals[pos.asset_class] = totals.get(pos.asset_class, Decimal('0')) \
                + pos.market_value

    grand_total = sum(totals.values(), Decimal('0'))
    if not grand_total:
        return DEFAULT_RETURN, DEFAULT_VOLATILITY, {}

    weights = {name: float(value / grand_total) for name, value in totals.items()}
    expected_return = sum(
        w * ASSET_CLASS_ASSUMPTIONS.get(name, ASSET_CLASS_ASSUMPTIONS['other'])[0]
        for name, w in weights.items()
    )
    volatility = sum(
        w * ASSET_CLASS_ASSUMPTIONS.get(name, ASSET_CLASS_ASSUMPTIONS['other'])[1]
        for name, w in weights.items()
    )
    return round(expected_return, 4), round(volatility, 4), weights


def run_simulation(
    *,
    start_wealth: float,
    monthly_contribution: float,
    expected_return: float,
    volatility: float,
    inflation: float,
    years: int,
    paths: int,
    target_amount: float = None,
    seed: int = None,
) -> dict:
    """Run the Monte Carlo projection and aggregate to per-year percentile bands.

    All amounts in and out are in today's purchasing power (see module docstring).
    Wealth is floored at 0: debt dynamics (interest on a negative balance) are a
    different model, and a "bankrupt" path staying at zero is the honest readout.
    """
    years = max(1, min(int(years), MAX_YEARS))
    paths = max(MIN_PATHS, min(int(paths), MAX_PATHS))
    volatility = max(0.0, volatility)
    rng = random.Random(seed)

    real_return = expected_return - inflation
    months = years * 12
    dt = 1 / 12
    # GBM per month on the real return; ito correction keeps the arithmetic
    # expectation at exp(real_return * t).
    drift = (real_return - volatility ** 2 / 2) * dt
    diffusion = volatility * math.sqrt(dt)

    # wealth_by_year[y] collects every path's value at the end of year y.
    wealth_by_year = [[] for _ in range(years + 1)]
    end_values = []

    for _ in range(paths):
        wealth = start_wealth
        wealth_by_year[0].append(wealth)
        for month in range(1, months + 1):
            growth = math.exp(drift + diffusion * rng.gauss(0, 1))
            wealth = max(0.0, wealth * growth + monthly_contribution)
            if month % 12 == 0:
                wealth_by_year[month // 12].append(wealth)
        end_values.append(wealth)

    bands = []
    for year, values in enumerate(wealth_by_year):
        values.sort()
        bands.append({
            'year': year,
            **{f'p{pct}': round(_percentile(values, pct), 2) for pct in PERCENTILES},
        })

    result = {'years': years, 'paths': paths, 'bands': bands}

    if target_amount is not None:
        reached = sum(1 for v in end_values if v >= target_amount)
        result['target'] = {
            'amount': target_amount,
            'probability': round(reached / paths, 4),
            # First year whose median clears the target — None if it never does.
            'median_reached_year': next(
                (b['year'] for b in bands if b['p50'] >= target_amount), None,
            ),
        }

    return result
