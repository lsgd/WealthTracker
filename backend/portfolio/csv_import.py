"""CSV transaction import (web-only backfill).

Parses per-account CSV exports from the banks' online banking — currently ZKB
("with details" export) and DKB — into the shared ``TransactionInfo`` shape and
stores them through the same idempotent importer as the sync paths.

Format notes (structure learned from real exports; test fixtures are synthetic):

- **ZKB**: semicolon-separated, one header row. Debit and credit live in
  separate columns whose headers carry the account currency ("Debit CHF" /
  "Credit CHF"). The "ZKB reference" is the bank-side unique reference (the
  same value camt.053 reports as ``AcctSvcrRef``), so imported rows dedup
  exactly against EBICS-synced entries via the ``ref:`` key.
- **DKB**: preamble lines (account, period, balance) before the header row.
  German number format ("-1.234,56"), dates as DD.MM.YY, currency taken from
  the "Betrag (€)" header. Only "Gebucht" rows are imported — pending entries
  change on booking and would come back as duplicates. The "Kundenreferenz" is
  not a guaranteed-unique bank reference, so DKB entries use the importer's
  order-stable content-hash dedup instead of a ``ref:`` key.
- **Swisscard** (credit card): COMMA-separated, header in row one. Amounts are
  unsigned-by-column: a purchase is a positive "Amount" with
  "Debit/Credit" = Debit, a refund or the monthly settlement is negative with
  Credit — the opposite of the sign convention everywhere else, so the sign is
  taken from that column. One file can cover several cards of the same
  account ("Card number"). The monthly settlement appears as a Credit row
  ("IHRE ZAHLUNG – BESTEN DANK"), which pairs with the debit on the paying
  bank account through the normal transfer detection.
- **Commerzbank**: header in row one ("Buchungstag;…"), German number format,
  currency in its own column, and the account's OWN IBAN per row ("IBAN
  Kontoinhaber") — used for account auto-matching. Counterparty name comes
  from Sender (credits) / Empfänger (debits); the counterparty IBAN is only
  embedded in the booking text and gets extracted so transfer auto-detection
  can pair entries. No unique bank reference → content-hash dedup.
"""
import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from brokers.integrations.base import TransactionInfo

_IBAN_RE = re.compile(r'^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$')


class CsvImportError(Exception):
    """CSV could not be parsed; the message is safe to show to the user."""


# Column aliases: the export language follows the user's e-banking language.
_ZKB_DATE = ('date', 'datum')
_ZKB_TEXT = ('booking text', 'buchungstext')
_ZKB_REFERENCE = ('zkb reference', 'zkb-referenz')
_ZKB_DEBIT = ('debit', 'belastung')
_ZKB_CREDIT = ('credit', 'gutschrift')
_ZKB_VALUE_DATE = ('value date', 'valuta')
_ZKB_PURPOSE = ('payment purpose', 'zahlungszweck')
_ZKB_DETAILS = ('details',)

_DKB_HEADER_FIRST = 'buchungsdatum'
_COMMERZBANK_HEADER_FIRST = 'buchungstag'
_SWISSCARD_HEADER_START = ['transaction date', 'description']


def _decode(content: bytes) -> str:
    """Bank CSVs are UTF-8 (sometimes with BOM) or cp1252 — never anything else."""
    try:
        return content.decode('utf-8-sig')
    except UnicodeDecodeError:
        return content.decode('cp1252', errors='replace')


def _find_column(header, aliases, prefix=False):
    """Index of the first header cell matching one of ``aliases``, else None."""
    for index, cell in enumerate(header):
        name = cell.strip().lower()
        for alias in aliases:
            if (prefix and name.startswith(alias)) or (not prefix and name == alias):
                return index
    return None


def _parse_date(text, formats):
    for fmt in formats:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(text: str, german: bool) -> Decimal:
    cleaned = text.strip().replace('−', '-').replace("'", '')
    if german:
        cleaned = cleaned.replace('.', '').replace(',', '.')
    else:
        cleaned = cleaned.replace(',', '')
    return Decimal(cleaned)


def parse_transactions_csv(content: bytes, fallback_currency: str):
    """Parse a ZKB, DKB, Commerzbank or Swisscard export.

    Returns (format_name, currency, infos, skipped, account_iban) —
    ``account_iban`` is the account the file itself claims to belong to (DKB
    puts its IBAN in the preamble; ZKB and Swisscard exports carry no
    identifier → None). ``skipped`` counts rows without a parseable date or
    amount (detail continuation rows, pending entries). Raises CsvImportError
    when the file matches no known format.
    """
    text = _decode(content)

    # Swisscard is the only comma-separated format; sniff it before the
    # semicolon parse, which would read the whole line as one cell.
    comma_header = next(iter(csv.reader(io.StringIO(text))), [])
    if [c.strip().lower() for c in comma_header[:2]] == _SWISSCARD_HEADER_START:
        return _parse_swisscard(
            list(csv.reader(io.StringIO(text))), fallback_currency) + (None,)

    rows = list(csv.reader(io.StringIO(text), delimiter=';'))
    if not rows:
        raise CsvImportError('The file is empty.')

    header = [cell.strip().lower() for cell in rows[0]]
    if _find_column(header, _ZKB_REFERENCE) is not None:
        return _parse_zkb(rows, fallback_currency) + (None,)
    if header and header[0] == _COMMERZBANK_HEADER_FIRST:
        return _parse_commerzbank(rows, fallback_currency)
    for index, row in enumerate(rows):
        if row and row[0].strip().lower() == _DKB_HEADER_FIRST:
            iban = _preamble_iban(rows[:index])
            return _parse_dkb(rows, index, fallback_currency) + (iban,)
    raise CsvImportError(
        'Unrecognized CSV format. Supported: ZKB account export ("with details"), '
        'DKB, and Commerzbank account exports.'
    )


def _preamble_iban(preamble_rows):
    """The account IBAN a DKB export names in its preamble, or None."""
    for row in preamble_rows:
        for cell in row:
            candidate = cell.strip().replace(' ', '').upper()
            if _IBAN_RE.match(candidate):
                return candidate
    return None


def _parse_zkb(rows, fallback_currency):
    header = rows[0]
    date_col = _find_column(header, _ZKB_DATE)
    text_col = _find_column(header, _ZKB_TEXT)
    ref_col = _find_column(header, _ZKB_REFERENCE)
    debit_col = _find_column(header, _ZKB_DEBIT, prefix=True)
    credit_col = _find_column(header, _ZKB_CREDIT, prefix=True)
    value_col = _find_column(header, _ZKB_VALUE_DATE)
    purpose_col = _find_column(header, _ZKB_PURPOSE)
    details_col = _find_column(header, _ZKB_DETAILS)
    if None in (date_col, text_col, debit_col, credit_col):
        raise CsvImportError('ZKB export is missing expected columns.')

    # "Debit CHF" / "Belastung CHF": the header names the account currency.
    currency_token = header[debit_col].strip().split()[-1].upper()
    currency = currency_token if len(currency_token) == 3 else fallback_currency

    def cell(row, col):
        return row[col].strip() if col is not None and col < len(row) else ''

    infos, skipped = [], 0
    for row in rows[1:]:
        booking_date = _parse_date(cell(row, date_col), ('%d.%m.%Y',))
        debit, credit = cell(row, debit_col), cell(row, credit_col)
        if booking_date is None or (not debit and not credit):
            skipped += 1  # detail continuation rows carry no date/amount
            continue
        try:
            amount = -_parse_amount(debit, german=False) if debit \
                else _parse_amount(credit, german=False)
        except InvalidOperation:
            skipped += 1
            continue
        description = cell(row, text_col)
        purpose = cell(row, purpose_col)
        if purpose:
            description = f'{description} — {purpose}' if description else purpose
        infos.append(TransactionInfo(
            booking_date=booking_date,
            amount=amount,
            currency=currency,
            value_date=_parse_date(cell(row, value_col), ('%d.%m.%Y',)),
            counterparty=cell(row, details_col),
            description=description,
            external_id=cell(row, ref_col) or None,
        ))
    return 'zkb', currency, infos, skipped


def _parse_swisscard(rows, fallback_currency):
    """Swisscard credit-card export (comma-separated, unsigned amounts)."""
    columns = {cell.strip().lower(): i for i, cell in enumerate(rows[0])}

    def col(name):
        return columns.get(name)

    date_col = col('transaction date')
    description_col = col('description')
    merchant_col = col('merchant')
    card_col = col('card number')
    currency_col = col('currency')
    amount_col = col('amount')
    direction_col = col('debit/credit')
    status_col = col('status')
    category_col = col('merchant category')
    if None in (date_col, amount_col, direction_col):
        raise CsvImportError('Swisscard export is missing expected columns.')

    def cell(row, c):
        return row[c].strip() if c is not None and c < len(row) else ''

    currency = fallback_currency
    infos, skipped = [], 0
    for row in rows[1:]:
        booking_date = _parse_date(cell(row, date_col), ('%d.%m.%Y',))
        if booking_date is None:
            skipped += 1
            continue
        status = cell(row, status_col)
        if status and status.lower() != 'posted':
            skipped += 1  # pending entries change on posting and would duplicate
            continue
        try:
            value = _parse_amount(cell(row, amount_col), german=False)
        except InvalidOperation:
            skipped += 1
            continue
        # The file states the direction in its own column and writes purchases
        # POSITIVE — the opposite of every other format, so the sign is taken
        # from the direction, not from the number.
        amount = -abs(value) if cell(row, direction_col).lower().startswith('d') \
            else abs(value)
        currency = cell(row, currency_col).upper() or currency
        description = cell(row, description_col)
        category = cell(row, category_col)
        card = cell(row, card_col)
        # One file can cover several cards of the same account — naming the
        # card keeps a shared account's entries apart in the list.
        details = ' · '.join(p for p in (category, card) if p)
        infos.append(TransactionInfo(
            booking_date=booking_date,
            amount=amount,
            currency=currency,
            value_date=None,
            counterparty=cell(row, merchant_col) or description,
            description=f'{description} ({details})' if details else description,
            # No bank reference in the export → content-hash dedup.
            external_id=None,
        ))
    return 'swisscard', currency, infos, skipped


def _parse_commerzbank(rows, fallback_currency):
    """Returns the full 5-tuple: the file names its own IBAN per row."""
    columns = {cell.strip().lower(): i for i, cell in enumerate(rows[0])}

    def col(name):
        return columns.get(name)

    date_col = col('buchungstag')
    value_col = col('wertstellung')
    text_col = col('buchungstext')
    amount_col = col('betrag')
    currency_col = col('währung')
    own_iban_col = col('iban kontoinhaber')
    sender_col = col('sender')
    recipient_col = col('empfänger')
    purpose_col = col('verwendungszweck')
    if None in (date_col, amount_col):
        raise CsvImportError('Commerzbank export is missing expected columns.')

    def cell(row, c):
        return row[c].strip() if c is not None and c < len(row) else ''

    account_iban = None
    currency = fallback_currency
    infos, skipped = [], 0
    for row in rows[1:]:
        booking_date = _parse_date(cell(row, date_col), ('%d.%m.%Y',))
        if booking_date is None:
            skipped += 1
            continue
        try:
            amount = _parse_amount(cell(row, amount_col), german=True)
        except InvalidOperation:
            skipped += 1
            continue
        account_iban = account_iban or cell(row, own_iban_col).replace(' ', '').upper() or None
        currency = cell(row, currency_col).upper() or currency
        counterparty = cell(row, recipient_col) if amount < 0 else cell(row, sender_col)
        text = cell(row, text_col)
        # The counterparty IBAN only appears inside the booking text — pull it
        # out (skipping the account's own) so transfer detection can pair.
        counterparty_account = next(
            (t for t in text.replace(' ', ' ').split()
             if _IBAN_RE.match(t.upper()) and t.upper() != account_iban),
            '',
        )
        purpose = cell(row, purpose_col)
        infos.append(TransactionInfo(
            booking_date=booking_date,
            amount=amount,
            currency=currency,
            value_date=_parse_date(cell(row, value_col), ('%d.%m.%Y',)),
            counterparty=counterparty,
            counterparty_account=counterparty_account.upper(),
            description=purpose or text,
            # End-to-end refs are mostly NOTPROVIDED → content-hash dedup.
            external_id=None,
        ))
    return 'commerzbank', currency, infos, skipped, account_iban


def _parse_dkb(rows, header_index, fallback_currency):
    header = rows[header_index]
    columns = {cell.strip().lower(): i for i, cell in enumerate(header)}

    def col(name, prefix=False):
        if prefix:
            return next((i for n, i in columns.items() if n.startswith(name)), None)
        return columns.get(name)

    date_col = col('buchungsdatum')
    value_col = col('wertstellung')
    status_col = col('status')
    payer_col = col('zahlungspflichtige', prefix=True)
    payee_col = col('zahlungsempfänger', prefix=True)
    purpose_col = col('verwendungszweck')
    iban_col = col('iban')
    amount_col = col('betrag', prefix=True)
    if None in (date_col, amount_col):
        raise CsvImportError('DKB export is missing expected columns.')

    # "Betrag (€)": currency symbol in the header.
    amount_header = header[amount_col]
    currency = 'EUR' if '€' in amount_header else (
        'USD' if '$' in amount_header else fallback_currency)

    def cell(row, c):
        return row[c].strip() if c is not None and c < len(row) else ''

    infos, skipped = [], 0
    for row in rows[header_index + 1:]:
        booking_date = _parse_date(cell(row, date_col), ('%d.%m.%y', '%d.%m.%Y'))
        if booking_date is None:
            skipped += 1
            continue
        status = cell(row, status_col)
        if status and status.lower() != 'gebucht':
            skipped += 1  # pending rows change on booking and would duplicate
            continue
        try:
            amount = _parse_amount(cell(row, amount_col), german=True)
        except InvalidOperation:
            skipped += 1
            continue
        counterparty = cell(row, payee_col) if amount < 0 else cell(row, payer_col)
        infos.append(TransactionInfo(
            booking_date=booking_date,
            amount=amount,
            currency=currency,
            value_date=_parse_date(cell(row, value_col), ('%d.%m.%y', '%d.%m.%Y')),
            counterparty=counterparty,
            counterparty_account=cell(row, iban_col),
            description=cell(row, purpose_col),
            # Kundenreferenz is NOT a guaranteed-unique bank reference — no
            # external_id, so the importer's content-hash dedup applies.
            external_id=None,
        ))
    return 'dkb', currency, infos, skipped
