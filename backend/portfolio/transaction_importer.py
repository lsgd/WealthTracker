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
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# How far back to ask on the first import of an account.
DEFAULT_LOOKBACK_DAYS = 365
# Re-request this many days before the newest imported transaction so late-booked
# entries around the boundary are not missed. Dedup makes the overlap free.
OVERLAP_DAYS = 5

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


def store_transactions(account, infos) -> int:
    """Persist a fetched batch idempotently. Returns the number of new rows."""
    from .models import Transaction

    source = _SOURCE_BY_INTEGRATION_TYPE.get(
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


def backfill_account_transactions(account, integration, start_date, end_date) -> int:
    """Fetch and store transactions for an explicit date range.

    Same idempotent storage as the incremental import — re-running an
    overlapping range creates nothing new. Also classifies what arrived.
    """
    if not integration.supports_transactions():
        return 0

    infos = integration.get_transactions(account.account_identifier, start_date, end_date)
    if not infos:
        return 0

    created_count = store_transactions(account, infos)
    if created_count:
        from .classification import apply_rules, detect_transfers
        apply_rules(account.user)
        detect_transfers(account.user)

    logger.info(
        'Backfilled %d new transactions for %s (%d fetched, %s to %s)',
        created_count, account.name, len(infos), start_date, end_date,
    )
    return created_count


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
