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


def month_bounds(label: str):
    """``'2026-08'`` -> ``(date(2026, 8, 1), date(2026, 9, 1))``, else None.

    Half-open on purpose: the end is the first day of the next month, so no
    caller has to know how long a month is.
    """
    try:
        year, month = (int(part) for part in label.split('-', 1))
        start = date(year, month, 1)
    except (AttributeError, TypeError, ValueError):
        return None
    index = _month_index(start) + 1
    return start, date(index // 12, index % 12 + 1, 1)


def monthly_spending(user, months: int = 12, mode: str = 'normalized') -> dict:
    base_currency = user.profile.base_currency
    today = date.today()
    end_index = _month_index(today)
    start_index = end_index - months + 1
    window_start = date(start_index // 12, start_index % 12 + 1, 1)

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

    return {
        'mode': mode,
        'base_currency': base_currency,
        'categories': [
            name for name, _total
            in sorted(category_totals.items(), key=lambda kv: kv[1], reverse=True)
        ],
        'months': [
            {
                'month': _month_label(i),
                'income': to_float(buckets[i]['income']),
                'expenses': to_float(buckets[i]['expenses']),
                'net': to_float(buckets[i]['income'] - buckets[i]['expenses']),
                'by_category': {
                    name: to_float(value)
                    for name, value in sorted(
                        buckets[i]['by_category'].items(), key=lambda kv: kv[1], reverse=True,
                    )
                },
            }
            for i in range(start_index, end_index + 1)
        ],
    }
