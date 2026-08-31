"""Diagnostic: report what an IBKR Flex query actually returns.

Answers one question — does the Flex report carry per-instrument positions for
every day of the statement period, or only one set as of the period end? The
sync path currently ignores ``reportDate`` on ``OpenPosition`` and writes every
parsed position onto a single snapshot, so the answer decides whether daily
position history can be backfilled at all.

Read-only: it fetches a report and prints structure. Nothing is written to the
database. Delete this command once the question is settled.

Credentials, either:
    --token <flex_token> --query-id <id>
    --account <id> --kek <base64>        (unwraps the stored credentials)

Or skip the network entirely and re-analyze a saved report:
    --file /tmp/ibkr_flex_report.xml
"""
import base64
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError

# Attributes IBKR uses to date a row; checked in this order.
DATE_ATTRS = ('reportDate', 'date', 'tradeDate', 'settleDate', 'toDate', 'fromDate')

# Sections worth calling out explicitly in the summary.
NOTABLE = (
    'OpenPosition',
    'EquitySummaryByReportDateInBase',
    'MTMPerformanceSummaryInBase',
    'Trade',
    'CashTransaction',
    'CashReportCurrency',
    'ChangeInNAV',
)


class Command(BaseCommand):
    help = "Inspect an IBKR Flex report's sections and per-section date coverage"

    def add_arguments(self, parser):
        parser.add_argument('--token', help='Flex Web Service token')
        parser.add_argument('--query-id', help='Activity Flex Query ID')
        parser.add_argument('--account', type=int, help='FinancialAccount id to read credentials from')
        parser.add_argument('--kek', help='Base64 KEK, required with --account')
        parser.add_argument('--file', help='Analyze a saved XML report instead of fetching')
        parser.add_argument('--save', help='Write the fetched XML here for later runs')

    def handle(self, *args, **opts):
        xml = self._load_xml(opts)
        if opts.get('save'):
            with open(opts['save'], 'w') as fh:
                fh.write(xml)
            self.stdout.write(f"saved report to {opts['save']}\n")

        root = ET.fromstring(xml)
        self._report_period(root)
        tags = self._section_inventory(root)
        self._date_coverage(root, tags)
        self._open_position_verdict(root)
        self._sample_attributes(root)

    # ---------- input ----------

    def _load_xml(self, opts):
        if opts.get('file'):
            with open(opts['file']) as fh:
                return fh.read()

        creds = self._credentials(opts)
        # Reuse the integration's request flow so this reflects the real sync path.
        from brokers.integrations.ibkr_flex import IBKRFlexIntegration

        integration = IBKRFlexIntegration(creds)
        auth = integration.authenticate()
        if not auth.success:
            raise CommandError(auth.error_message)

        self.stdout.write('requesting report from IBKR (this can take a minute)...\n')
        ref = integration._send_request()
        return integration._get_statement(ref)

    def _credentials(self, opts):
        if opts.get('token') and opts.get('query_id'):
            return {'flex_token': opts['token'], 'query_id': opts['query_id']}

        if opts.get('account'):
            if not opts.get('kek'):
                raise CommandError('--account also needs --kek (the server cannot decrypt without it)')
            return self._credentials_from_db(opts['account'], opts['kek'])

        raise CommandError('Provide --token and --query-id, or --account and --kek, or --file')

    def _credentials_from_db(self, account_id, kek_b64):
        from core.user_encryption import (
            decrypt_credentials,
            decrypt_user_key,
            pad_kek_for_fernet,
        )
        from portfolio.models import FinancialAccount

        try:
            account = FinancialAccount.objects.select_related('user__profile').get(pk=account_id)
        except FinancialAccount.DoesNotExist:
            raise CommandError(f'No account with id {account_id}')
        if not account.encrypted_credentials:
            raise CommandError(f'Account {account_id} has no stored credentials')

        try:
            kek = pad_kek_for_fernet(base64.b64decode(kek_b64))
            user_key = decrypt_user_key(account.user.profile.encrypted_user_key, kek)
            return decrypt_credentials(account.encrypted_credentials, user_key)
        except Exception as exc:
            raise CommandError(f'Could not decrypt credentials: {exc}')

    # ---------- analysis ----------

    def _report_period(self, root):
        stmt = root.find('.//FlexStatement')
        self.stdout.write(self.style.MIGRATE_HEADING('\n== statement =='))
        if stmt is None:
            self.stdout.write('no FlexStatement element found; analyzing the whole document\n')
            return
        for key in ('fromDate', 'toDate', 'period', 'whenGenerated'):
            if stmt.get(key):
                self.stdout.write(f'  {key}: {stmt.get(key)}')

    def _section_inventory(self, root):
        tags = Counter(el.tag for el in root.iter())
        self.stdout.write(self.style.MIGRATE_HEADING('\n== sections =='))
        for tag, count in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0])):
            if count == 1 and tag not in NOTABLE:
                continue  # container elements, not data rows
            mark = ' <-' if tag in NOTABLE else ''
            self.stdout.write(f'  {tag:42} {count:>7}{mark}')

        missing = [t for t in NOTABLE if t not in tags]
        if missing:
            self.stdout.write(f"\n  not in this query: {', '.join(missing)}")
        return tags

    def _date_coverage(self, root, tags):
        """Per section: which date attribute it carries, and how many distinct values."""
        self.stdout.write(self.style.MIGRATE_HEADING('\n== date coverage per section =='))
        seen = defaultdict(lambda: defaultdict(set))
        for el in root.iter():
            for attr in DATE_ATTRS:
                value = el.get(attr)
                if value:
                    seen[el.tag][attr].add(value)

        if not seen:
            self.stdout.write('  no dated rows found')
            return

        for tag in sorted(seen, key=lambda t: -tags[t]):
            for attr, values in sorted(seen[tag].items()):
                dates = sorted(values)
                span = f'{dates[0]} .. {dates[-1]}' if len(dates) > 1 else dates[0]
                self.stdout.write(
                    f'  {tag:38} {attr:12} {len(dates):>5} distinct   {span}'
                )

    def _open_position_verdict(self, root):
        """The actual question: one set of positions, or one set per day?"""
        positions = root.findall('.//OpenPosition')
        self.stdout.write(self.style.MIGRATE_HEADING('\n== OpenPosition =='))
        if not positions:
            self.stdout.write('  none in this report — the query has no Open Positions section')
            return

        per_date = Counter(p.get('reportDate') or '(no reportDate)' for p in positions)
        symbols = {p.get('symbol') for p in positions}
        self.stdout.write(f'  rows: {len(positions)}   distinct symbols: {len(symbols)}')
        self.stdout.write(f'  distinct reportDates: {len(per_date)}')
        for day, count in sorted(per_date.items())[:10]:
            self.stdout.write(f'    {day}: {count} rows')
        if len(per_date) > 10:
            self.stdout.write(f'    ... and {len(per_date) - 10} more dates')

        self.stdout.write('')
        if len(per_date) > 1:
            self.stdout.write(self.style.SUCCESS(
                '  => daily positions ARE available. Backfilling per-day history is possible,\n'
                '     but the sync must bucket rows by reportDate: _parse_position drops it and\n'
                '     store_positions writes everything onto one snapshot.'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                '  => one set of positions only (period end). Per-instrument history cannot be\n'
                '     backfilled from this section; it accrues one sync at a time.'
            ))

    def _sample_attributes(self, root):
        """Field inventory for the sections that could carry performance data."""
        self.stdout.write(self.style.MIGRATE_HEADING('\n== available fields =='))
        for tag in ('OpenPosition', 'MTMPerformanceSummaryInBase', 'Trade', 'CashTransaction'):
            first = root.find(f'.//{tag}')
            if first is None:
                continue
            self.stdout.write(f'\n  {tag}:')
            for key in sorted(first.attrib):
                self.stdout.write(f'    {key} = {first.get(key)}')
