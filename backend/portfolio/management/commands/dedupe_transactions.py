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

Dry run by default; pass --apply to delete. Rows a user has classified by hand
(category_manual / transfer_manual) are kept in preference to untouched ones,
as are rows carrying a bank reference.
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
            survivors, doomed = rows[:keep_count], rows[keep_count:]
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
