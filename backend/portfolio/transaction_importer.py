"""Shared transaction importer.

One place that turns broker ``TransactionInfo`` entries into ``Transaction`` rows,
idempotently. Used by the sync path after the balance snapshot, for every integration
that reports ``supports_transactions()``.

Dedup strategy (per account):
- Entries with a bank-side unique reference (camt.053 ``AcctSvcrRef``, a real MT940
  bank reference) get ``ref:<reference>`` as their key — exact, order-independent.
- Entries without one get a content hash over (booking date, amount, currency,
  counterparty, counterparty account, description) plus an *ordinal*: the occurrence
  index of that exact tuple within the fetched batch. Two identical coffee purchases
  on the same day therefore both survive, while re-importing an overlapping statement
  range maps them onto the same keys again. This relies on sources delivering whole
  booked days (camt.053 and MT940 statements do), so the ordinals are reproducible.
"""
import hashlib
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# How far back to ask on the first import of an account.
DEFAULT_LOOKBACK_DAYS = 365
# Re-request this many days before the newest imported transaction so late-booked
# entries around the boundary are not missed. Dedup makes the overlap free.
OVERLAP_DAYS = 5

# A backfill counts as truncated when the oldest entry the bank served is more than
# this many days after the requested start. Slack, because an account legitimately
# opened mid-window — or simply quiet over the new year — is not a truncation.
TRUNCATION_SLACK_DAYS = 31

# Broker integration_type -> Transaction.source
_SOURCE_BY_INTEGRATION_TYPE = {
    'ebics': 'camt053',
    'fints': 'fints',
}


def _content_hash(info, ordinal: int) -> str:
    payload = '|'.join([
        info.booking_date.isoformat(),
        str(info.amount),
        info.currency,
        info.counterparty,
        info.counterparty_account,
        info.description,
        str(ordinal),
    ])
    return 'h:' + hashlib.sha256(payload.encode()).hexdigest()[:40]


def _dedup_keys(infos):
    """Compute the per-entry dedup keys for one fetched batch, in order."""
    seen_counts = {}
    keys = []
    for info in infos:
        if info.external_id:
            keys.append(f'ref:{info.external_id}'[:128])
            continue
        tuple_key = (
            info.booking_date, str(info.amount), info.currency,
            info.counterparty, info.counterparty_account, info.description,
        )
        ordinal = seen_counts.get(tuple_key, 0)
        seen_counts[tuple_key] = ordinal + 1
        keys.append(_content_hash(info, ordinal))
    return keys


def store_transactions(account, infos, source=None) -> int:
    """Persist a fetched batch idempotently. Returns the number of new rows.

    ``source`` overrides the integration-derived provenance (the CSV import
    stores 'csv' — its rows did not come through the broker integration).
    """
    from .models import Transaction

    source = source or _SOURCE_BY_INTEGRATION_TYPE.get(
        getattr(account.broker, 'integration_type', '') or '', 'broker',
    )

    created_count = 0
    for info, dedup_key in zip(infos, _dedup_keys(infos)):
        _, created = Transaction.objects.get_or_create(
            account=account,
            dedup_key=dedup_key,
            defaults={
                'booking_date': info.booking_date,
                'value_date': info.value_date,
                'amount': info.amount,
                'currency': info.currency,
                'counterparty': info.counterparty[:255],
                'counterparty_account': info.counterparty_account[:64],
                'description': info.description,
                'source': source,
                'external_id': (info.external_id or '')[:128],
                'raw_data': info.raw_data,
            },
        )
        if created:
            created_count += 1
    return created_count


@dataclass
class BackfillResult:
    """Outcome of one dated backfill, including what the bank actually served.

    Banks routinely honour a dated request only partially — EBICS archives start at
    subscriber activation, FinTS usually caps at ~90 days. The importer cannot tell
    "you have no older transactions" from "the bank would not give them to me", so it
    reports the covered span and lets the caller say so out loud. Reporting only the
    imported count reads as "your 15 months are complete" when it was really 7 weeks.
    """

    imported: int = 0
    fetched: int = 0
    requested_start: Optional[date] = None
    requested_end: Optional[date] = None
    covered_start: Optional[date] = None
    covered_end: Optional[date] = None

    @property
    def is_truncated(self) -> bool:
        """True when the served span starts materially later than requested."""
        if self.covered_start is None or self.requested_start is None:
            return False
        return (self.covered_start - self.requested_start).days > TRUNCATION_SLACK_DAYS

    def describe(self) -> str:
        if not self.fetched:
            return (
                'No transactions were returned for that period. The bank may not '
                're-serve statements that far back.'
            )
        message = f'{self.imported} new transactions imported'
        if self.imported != self.fetched:
            message += f' ({self.fetched} fetched, the rest were already stored)'
        message += f'. The bank served {self.covered_start} to {self.covered_end}'
        if self.is_truncated:
            message += (
                f' — short of the requested {self.requested_start}, so the months '
                'before that stay empty in the spending report.'
            )
        else:
            message += '.'
        return message


def backfill_account_transactions(account, integration, start_date, end_date) -> BackfillResult:
    """Fetch and store transactions for an explicit date range.

    Same idempotent storage as the incremental import — re-running an
    overlapping range creates nothing new. Also classifies what arrived.
    """
    result = BackfillResult(requested_start=start_date, requested_end=end_date)
    if not integration.supports_transactions():
        return result

    # Not get_transactions(): backfill must query the period explicitly, which for
    # some feeds (EBICS) is a different request than the regular sync's.
    infos = integration.get_transactions_for_range(
        account.account_identifier, start_date, end_date,
    )
    if not infos:
        return result

    booking_dates = [info.booking_date for info in infos if info.booking_date]
    result.fetched = len(infos)
    result.covered_start = min(booking_dates) if booking_dates else None
    result.covered_end = max(booking_dates) if booking_dates else None
    result.imported = store_transactions(account, infos)

    if result.imported:
        from .classification import apply_rules, detect_transfers
        apply_rules(account.user)
        detect_transfers(account.user)

    logger.info(
        'Backfilled %d new transactions for %s (%d fetched, requested %s to %s, '
        'bank served %s to %s)',
        result.imported, account.name, result.fetched, start_date, end_date,
        result.covered_start, result.covered_end,
    )
    return result


def import_account_transactions(account, integration) -> int:
    """Fetch and store booked transactions for one account. Returns the created count.

    Never raises on a per-entry problem; a failure of the fetch itself propagates so
    the caller can decide (the sync views log it and keep the balance sync's result).
    """
    from .models import Transaction

    if not integration.supports_transactions():
        return 0

    end_date = date.today()
    latest = (
        Transaction.objects
        .filter(account=account)
        .exclude(source='manual')
        .order_by('-booking_date')
        .values_list('booking_date', flat=True)
        .first()
    )
    if latest:
        start_date = latest - timedelta(days=OVERLAP_DAYS)
    else:
        start_date = end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    infos = integration.get_transactions(account.account_identifier, start_date, end_date)
    if not infos:
        return 0

    created_count = store_transactions(account, infos)

    logger.info(
        'Imported %d new transactions for %s (%d fetched, %s to %s)',
        created_count, account.name, len(infos), start_date, end_date,
    )

    # Classify what just arrived: category rules + transfer pairing. Both are
    # idempotent and skip user-overridden rows.
    if created_count:
        from .classification import apply_rules, detect_transfers
        apply_rules(account.user)
        detect_transfers(account.user)

    return created_count
