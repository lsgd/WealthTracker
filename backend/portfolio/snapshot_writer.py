"""Shared snapshot writer.

One place that turns a broker ``BalanceInfo`` into an ``AccountSnapshot`` for a given
day, including base-currency conversion. Used by the sync/backfill path today, and by
the EBICS dated-download backfill later — so gap-fill vs. overwrite semantics live here,
not scattered across callers.

``store_positions`` sits here for the same reason: a snapshot's holdings are part of
what that day's snapshot *is*, so they are written next to it rather than by callers.
"""
import logging
from decimal import Decimal

from exchange_rates.services import ExchangeRateService

from .models import AccountSnapshot, PortfolioPosition

logger = logging.getLogger(__name__)


def upsert_daily_snapshot(account, bal_info, base_currency, *, source='auto', overwrite=False):
    """Create or update the snapshot for ``(account, bal_info.balance_date)``.

    - ``overwrite=False`` (gap-fill): if a snapshot already exists for that date, leave
      it untouched and return ``(existing, False)``. This never clobbers a manual entry.
    - ``overwrite=True``: replace the existing snapshot's values with ``bal_info`` — the
      caller's source is authoritative for that day (e.g. EBICS end-of-day statements).

    Recomputes the base-currency conversion from scratch each time. Returns
    ``(snapshot, changed)`` where ``changed`` is False only for the skipped gap-fill case.
    """
    existing = (
        AccountSnapshot.objects
        .filter(account=account, snapshot_date=bal_info.balance_date)
        .order_by('-created_at', '-id')
        .first()
    )
    if existing and not overwrite:
        return existing, False

    snap = existing or AccountSnapshot(
        account=account, snapshot_date=bal_info.balance_date,
    )
    snap.balance = bal_info.balance
    snap.currency = bal_info.currency
    snap.snapshot_source = source
    snap.raw_data = bal_info.raw_data

    # Recompute base-currency fields (reset first so a stale conversion can't linger).
    snap.balance_base_currency = None
    snap.base_currency = ''
    snap.exchange_rate_used = None
    if bal_info.currency != base_currency:
        rate = ExchangeRateService.get_rate(
            bal_info.currency, base_currency, bal_info.balance_date,
        )
        if rate and rate != Decimal('1.0'):
            snap.balance_base_currency = bal_info.balance * rate
            snap.base_currency = base_currency
            snap.exchange_rate_used = rate
    else:
        snap.balance_base_currency = bal_info.balance
        snap.base_currency = base_currency

    snap.save()
    return snap, True


def store_positions(snapshot, position_infos) -> int:
    """Replace ``snapshot``'s holdings with ``position_infos``. Returns the row count.

    Wholesale replace rather than upsert: a broker's position list is a complete
    picture of the account at that moment, so a holding that disappeared from the
    feed must disappear here too. Merging would leave sold-out positions behind
    forever. Re-syncing the same day is therefore idempotent.

    An empty list is treated as "no position data" and leaves existing rows alone —
    a broker that reports nothing (an auth hiccup, a feed that went quiet) must not
    silently erase a snapshot's holdings.
    """
    if not position_infos:
        return 0

    PortfolioPosition.objects.filter(snapshot=snapshot).delete()
    PortfolioPosition.objects.bulk_create([
        PortfolioPosition(
            snapshot=snapshot,
            symbol=(info.symbol or '')[:20],
            isin=(info.isin or '')[:12],
            name=(info.name or '')[:200],
            quantity=info.quantity,
            price_per_unit=info.price_per_unit,
            market_value=info.market_value,
            currency=info.currency,
            cost_basis=info.cost_basis,
            asset_class=info.asset_class or 'other',
        )
        for info in position_infos
    ])
    return len(position_infos)
