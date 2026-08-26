"""Month-to-month spending report.

Aggregates booked transactions (transfers excluded) into calendar months in the
user's base currency. Two modes:

- ``actual``: every transaction counts fully in its booking month — raw cash flow.
- ``normalized``: a transaction with ``spread_months`` = N contributes amount/N to
  N consecutive months starting at its booking month. Yearly bills stop spiking
  their booking month and show up as a steady monthly cost instead.
"""
from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal

from exchange_rates.models import ExchangeRate

from .models import Transaction

# Normalized mode must see transactions booked before the report window whose
# spread still reaches into it. 13 months covers the largest common spread (12).
SPREAD_LOOKBACK_DAYS = 400


def _month_index(d: date) -> int:
    return d.year * 12 + (d.month - 1)


def _month_label(index: int) -> str:
    return f'{index // 12:04d}-{index % 12 + 1:02d}'


GRANULARITIES = ('month', 'quarter', 'year')

# Months per bucket, and the label each bucket carries.
_MONTHS_PER = {'month': 1, 'quarter': 3, 'year': 12}


def _first_month(index: int) -> date:
    return date(index // 12, index % 12 + 1, 1)


def period_label(month_index: int, granularity: str) -> str:
    """Label of the bucket a month falls into: 2026-08, 2026-Q3 or 2026."""
    year, month = month_index // 12, month_index % 12 + 1
    if granularity == 'year':
        return f'{year:04d}'
    if granularity == 'quarter':
        return f'{year:04d}-Q{(month - 1) // 3 + 1}'
    return f'{year:04d}-{month:02d}'


def period_bounds(label: str):
    """Half-open ``(start, end)`` of a period label, or None if unparseable.

    Accepts what :func:`period_label` produces — ``2026``, ``2026-Q3`` and
    ``2026-08``. Half-open on purpose: the end is the first day of the next
    period, so no caller has to know how long a month or quarter is.
    """
    if not isinstance(label, str):
        return None
    text = label.strip()
    try:
        if len(text) == 4:
            year = int(text)
            return date(year, 1, 1), date(year + 1, 1, 1)
        head, _, tail = text.partition('-')
        year = int(head)
        if tail[:1].upper() == 'Q':
            quarter = int(tail[1:])
            if not 1 <= quarter <= 4:
                return None
            start_month = (quarter - 1) * 3 + 1
            start = date(year, start_month, 1)
            return start, _first_month(_month_index(start) + 3)
        start = date(year, int(tail), 1)
    except (IndexError, TypeError, ValueError):
        return None
    return start, _first_month(_month_index(start) + 1)


def month_bounds(label: str):
    """Backwards-compatible alias — the month form of :func:`period_bounds`."""
    return period_bounds(label)


def monthly_spending(user, months: int = 12, mode: str = 'normalized',
                     granularity: str = 'month') -> dict:
    """Spending per period, newest last.

    ``months`` counts periods of the requested ``granularity`` — 12 quarters,
    3 years — and the window is aligned to period boundaries so a year bucket
    always starts in January. Buckets are always accumulated per month and
    folded afterwards: a spread transaction is defined in months, and folding a
    finished monthly series is exact.
    """
    base_currency = user.profile.base_currency
    today = date.today()
    if granularity not in GRANULARITIES:
        granularity = 'month'
    step = _MONTHS_PER[granularity]

    end_index = _month_index(today)
    # First month of the period today falls in: (end_index % 12) is the month
    # of the year, so its remainder over the step is the offset into the period.
    period_start = end_index - (end_index % 12) % step
    start_index = period_start - (months - 1) * step
    window_start = _first_month(start_index)

    fetch_start = window_start
    if mode == 'normalized':
        fetch_start = window_start - timedelta(days=SPREAD_LOOKBACK_DAYS)

    txs = (
        Transaction.objects
        .filter(
            account__user=user,
            is_transfer=False,
            booking_date__gte=fetch_start,
            booking_date__lte=today,
        )
        .select_related('category')
    )

    # Rate lookup is bulk-loaded: per-date ExchangeRateService.get_rate calls
    # cost 1-3 queries each (and a live frankfurter fetch for dates with no
    # stored rate at all) — hundreds of distinct booking dates made this
    # endpoint take seconds. One query per currency pair instead; per-date
    # resolution happens in memory with the same most-recent-before fallback.
    rate_series: dict = {}
    # order_by() clears the model's default ordering — it would leak into the
    # DISTINCT and yield one row per transaction instead of per currency.
    for cur in (
        txs.exclude(currency=base_currency)
        .order_by()
        .values_list('currency', flat=True)
        .distinct()
    ):
        rows = list(
            ExchangeRate.objects
            .filter(from_currency=cur, to_currency=base_currency, rate_date__lte=today)
            .order_by('rate_date')
            .values_list('rate_date', 'rate')
        )
        if not rows:
            rows = [
                (d, Decimal('1') / r) for d, r in
                ExchangeRate.objects
                .filter(from_currency=base_currency, to_currency=cur, rate_date__lte=today)
                .order_by('rate_date')
                .values_list('rate_date', 'rate')
                if r
            ]
        rate_series[cur] = ([d for d, _ in rows], [r for _, r in rows])

    def to_base(amount: Decimal, currency: str, on: date) -> Decimal:
        if currency == base_currency:
            return amount
        dates, rates = rate_series.get(currency) or ((), ())
        if not dates:
            return amount  # no rate known for the pair — same 1:1 fallback as before
        # Most recent rate on or before the booking date; dates older than the
        # first stored rate clamp to that first rate instead of hitting the
        # rate API mid-request.
        pos = bisect_right(dates, on)
        return amount * rates[pos - 1 if pos else 0]

    buckets = {
        i: {'income': Decimal('0'), 'expenses': Decimal('0'), 'by_category': {}}
        for i in range(start_index, end_index + 1)
    }
    category_totals: dict = {}

    for tx in txs:
        amount = to_base(tx.amount, tx.currency, tx.booking_date)
        tx_index = _month_index(tx.booking_date)
        if mode == 'normalized' and tx.spread_months > 1:
            slices = [
                (i, amount / tx.spread_months)
                for i in range(tx_index, tx_index + tx.spread_months)
            ]
        else:
            slices = [(tx_index, amount)]

        name = tx.category.name if tx.category else 'Uncategorized'
        for index, slice_amount in slices:
            bucket = buckets.get(index)
            if bucket is None:
                continue
            if slice_amount >= 0:
                bucket['income'] += slice_amount
            else:
                spent = -slice_amount
                bucket['expenses'] += spent
                bucket['by_category'][name] = bucket['by_category'].get(name, Decimal('0')) + spent
                category_totals[name] = category_totals.get(name, Decimal('0')) + spent

    def to_float(value: Decimal) -> float:
        return float(round(value, 2))

    # Fold the monthly buckets into the requested period, in order.
    periods: list = []
    by_label: dict = {}
    for i in range(start_index, end_index + 1):
        label = period_label(i, granularity)
        period = by_label.get(label)
        if period is None:
            period = {'income': Decimal('0'), 'expenses': Decimal('0'),
                      'by_category': {}}
            by_label[label] = period
            periods.append((label, period))
        period['income'] += buckets[i]['income']
        period['expenses'] += buckets[i]['expenses']
        for name, value in buckets[i]['by_category'].items():
            period['by_category'][name] = \
                period['by_category'].get(name, Decimal('0')) + value

    # Budgets are stored per month; scale them to whatever period is on screen
    # here rather than in each client, since the granularity lives here.
    budgets = {
        name: to_float(budget * step)
        for name, budget in user.transaction_categories
        .exclude(monthly_budget__isnull=True)
        .values_list('name', 'monthly_budget')
    }

    return {
        'mode': mode,
        'granularity': granularity,
        'base_currency': base_currency,
        # Per category, already scaled to one period of this granularity.
        'budgets': budgets,
        'categories': [
            name for name, _total
            in sorted(category_totals.items(), key=lambda kv: kv[1], reverse=True)
        ],
        # Named 'months' for the clients that predate the other granularities.
        'months': [
            {
                'month': label,
                'income': to_float(period['income']),
                'expenses': to_float(period['expenses']),
                'net': to_float(period['income'] - period['expenses']),
                'by_category': {
                    name: to_float(value)
                    for name, value in sorted(
                        period['by_category'].items(), key=lambda kv: kv[1], reverse=True,
                    )
                },
            }
            for label, period in periods
        ],
    }
