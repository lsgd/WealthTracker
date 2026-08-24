"""Remove transactions that the same account received twice through two feeds.

The importer keys entries by the bank's reference when there is one and by a
content hash otherwise. One payment can therefore end up stored twice when it
arrives through two paths whose wording differs — a ZKB EBICS sync says
"Debit TWINT: …" where the account's CSV export says "Belastung TWINT: …" —
and at least one side carries no reference.

Groups are (account, booking date, amount, currency). Only groups holding rows
from MORE THAN ONE source are touched, and only the surplus over the largest
per-source count is removed: if a day genuinely holds two identical payments,
each feed reports two and nothing is deleted.

Dry run by default; pass --apply to delete. Hand-entered rows (source
'manual') are never deleted and never count as a feed. Among imported rows,
ones the user classified by hand (category_manual / transfer_manual) are kept
in preference to untouched ones, as are rows carrying a bank reference.
"""
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Count

from portfolio.models import Transaction


class Command(BaseCommand):
    help = 'Remove cross-source duplicate transactions (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually delete the duplicates (default: only report them).',
        )
        parser.add_argument(
            '--user', help='Limit to one username.',
        )

    @staticmethod
    def _split(rows, keep_count):
        """(survivors, doomed) — one row per distinct payment before seconds.

        A day can hold several same-amount payments that are NOT copies of one
        another: two Riester contracts each debiting 10 EUR on the 1st. Taking
        simply the first ``keep_count`` rows could keep both copies of one
        contract and drop the other entirely, so distinct booking texts are
        served first; only then are remaining slots filled.
        """
        survivors, seen = [], set()
        for row in rows:
            identity = (row.counterparty, row.description)
            if identity not in seen and len(survivors) < keep_count:
                seen.add(identity)
                survivors.append(row)
        if len(survivors) < keep_count:
            for row in rows:
                if row not in survivors:
                    survivors.append(row)
                    if len(survivors) == keep_count:
                        break
        doomed = [row for row in rows if row not in survivors]
        return survivors, doomed

    def handle(self, *args, **options):
        transactions = Transaction.objects.select_related('account')
        if options['user']:
            transactions = transactions.filter(account__user__username=options['user'])

        # Only groups that actually hold several rows are candidates.
        duplicate_groups = (
            transactions
            .values('account_id', 'booking_date', 'amount', 'currency')
            .annotate(n=Count('id'))
            .filter(n__gt=1)
        )

        removed = kept = 0
        for group in duplicate_groups:
            rows = list(transactions.filter(
                account_id=group['account_id'],
                booking_date=group['booking_date'],
                amount=group['amount'],
                currency=group['currency'],
            ))
            # Hand-entered rows are the user's own record and cannot be
            # re-imported — never a deletion candidate, and never counted as
            # a feed that "also saw" the payment.
            manual = [row for row in rows if row.source == 'manual']
            rows = [row for row in rows if row.source != 'manual']
            by_source = defaultdict(list)
            for row in rows:
                by_source[row.source].append(row)
            if len(by_source) < 2:
                continue  # a single feed's own repeats are real payments

            # Each feed reports the payment once, so the true count is the
            # largest number any single source saw.
            keep_count = max(len(rows_of) for rows_of in by_source.values())
            # Prefer rows the user touched, then rows with a bank reference,
            # then the oldest id (the first import).
            rows.sort(key=lambda t: (
                not (t.category_manual or t.transfer_manual),
                not t.dedup_key.startswith('ref:'),
                t.id,
            ))
            kept += len(manual)
            survivors, doomed = self._split(rows, keep_count)
            kept += len(survivors)
            for row in doomed:
                self.stdout.write(
                    f'{"DELETE" if options["apply"] else "would delete"}: '
                    f'{row.account.name} {row.booking_date} {row.amount} '
                    f'{row.currency} [{row.source}] {row.description[:60]!r}'
                )
                if options['apply']:
                    row.delete()
                removed += 1

        if options['apply']:
            self.stdout.write(self.style.SUCCESS(
                f'Removed {removed} duplicates, kept {kept} originals.'))
        else:
            self.stdout.write(self.style.WARNING(
                f'{removed} duplicates found (kept {kept}). Re-run with --apply '
                'to delete them.'))
