"""Remove transactions that the same account received twice through two feeds.

The importer keys entries by the bank's reference when there is one and by a
content hash otherwise. One payment can therefore end up stored twice when it
arrives through two paths whose wording differs — a ZKB EBICS sync says
"Debit TWINT: …" where the account's CSV export says "Belastung TWINT: …" —
and at least one side carries no reference. The two feeds sometimes even date
the same payment a day apart.

Candidates share an account, an amount and a currency. A row is only removed
when a KEPT row from ANOTHER source reads like the same payment (similar
booking text, no conflicting contract/card numbers) and lies within a few
days. Everything else is left alone: two Riester contracts debiting 10 EUR on
the same day are two payments, not a duplicate pair.

Dry run by default; pass --apply to delete. Hand-entered rows (source
'manual') are never deleted and never count as a feed. Among imported rows,
ones the user classified by hand (category_manual / transfer_manual) are kept
in preference to untouched ones, as are rows carrying a bank reference.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand

from portfolio.models import Transaction
from portfolio.transaction_importer import (
    DUPLICATE_WINDOW_DAYS,
    looks_like_same_entry,
)


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
    def _split(rows):
        """(survivors, doomed) for one (account, amount, currency) group.

        Rows arrive in preference order. A row is dropped only when a kept row
        from another source is the same payment in that feed's wording; of
        several such rows it claims the closest-dated one, so two same-amount
        payments on neighbouring days each pair with their own counterpart. A
        kept row absorbs at most one row per other source, so two genuinely
        identical payments reported twice by both feeds keep both.
        """
        window = timedelta(days=DUPLICATE_WINDOW_DAYS)
        survivors, doomed = [], []
        claims = {}  # id(survivor) -> sources already matched to it
        for row in rows:
            twins = [
                s for s in survivors
                if s.source != row.source
                and row.source not in claims.get(id(s), set())
                and abs(s.booking_date - row.booking_date) <= window
                and looks_like_same_entry(
                    s.counterparty, s.description,
                    row.counterparty, row.description)
            ]
            if not twins:
                survivors.append(row)
                continue
            twin = min(twins, key=lambda s: abs(s.booking_date - row.booking_date))
            claims.setdefault(id(twin), set()).add(row.source)
            doomed.append(row)
        return survivors, doomed

    def handle(self, *args, **options):
        transactions = Transaction.objects.select_related('account')
        if options['user']:
            transactions = transactions.filter(account__user__username=options['user'])

        groups = {}
        for row in transactions.order_by('booking_date', 'id'):
            if row.source == 'manual':
                continue  # the user's own record; never a candidate
            groups.setdefault(
                (row.account_id, row.amount, row.currency), []).append(row)

        removed = kept = 0
        for rows in groups.values():
            if len({row.source for row in rows}) < 2:
                kept += len(rows)
                continue  # one feed's own repeats are real payments
            # Prefer rows the user touched, then rows with a bank reference,
            # then the oldest id (the first import).
            rows.sort(key=lambda t: (
                not (t.category_manual or t.transfer_manual),
                not t.dedup_key.startswith('ref:'),
                t.id,
            ))
            survivors, doomed = self._split(rows)
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
