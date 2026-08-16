"""ZKB (and other Swiss banks) via the EBICS 3.0 / H005 protocol.

Read-only: downloads camt.053 end-of-day statements and reports the closing
balance per IBAN. Uses the ``ebicsclient`` library.

Unlike the other integrations, the secret material (the RSA keyring) is not the
account's ``encrypted_credentials`` but a shared :class:`~brokers.models.EbicsCredential`.
The sync view decrypts that keyring and passes it in the ``credentials`` dict, so
this class stays stateless like its siblings. Expected keys:

    host_id, partner_id, user_id, url   — connection parameters
    bank_hash_auth, bank_hash_enc       — hex SHA-256 pinning hashes (optional)
    keyring_pem                         — base64 of the serialised ebicsclient keyring
    keyring_passphrase                  — passphrase for that keyring

The one-time key exchange (generate keys, INI/HIA, initialisation letter) lives in
the EBICS credential endpoints, not here — see brokers/views.py.
"""
import base64
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List

from .base import (
    AccountInfo,
    AuthResult,
    BalanceInfo,
    BrokerIntegrationBase,
    NoNewDataError,
    TransactionInfo,
)

logger = logging.getLogger(__name__)

# EBICS return code the bank sends when there is simply no statement to download
# (weekend/holiday, or a period whose camt.053 was already fetched — EBICS marks
# delivered data as received). It is a NORMAL empty result, never a failure.
_EBICS_NO_DOWNLOAD_DATA_AVAILABLE = '090005'

# When "Test connection" finds no pending statement (e.g. the backlog was already
# collected), look back this many days over a dated download so accounts can still be
# discovered from historical statements.
_DISCOVERY_FALLBACK_DAYS = 365


def _download_statements_or_empty(client, *, date_range=None, receipt_policy=None):
    """``client.download_statements(...)``, mapping "no data available" (090005) to ``[]``.

    Optional ``date_range`` requests a specific reporting period (dated download) and
    ``receipt_policy`` controls consumption (``ReceiptPolicy.KEEP`` = non-consuming peek).
    ebicsclient raises ``ReturnCodeError(code="090005")`` when nothing is waiting — routine,
    so we return an empty list. Any other return code (a genuine failure) propagates.
    """
    from ebicsclient import ReceiptPolicy, ReturnCodeError

    kwargs = {'receipt_policy': receipt_policy or ReceiptPolicy.ACKNOWLEDGE}
    if date_range is not None:
        kwargs['date_range'] = date_range
    try:
        return client.download_statements(**kwargs)
    except ReturnCodeError as e:
        if getattr(e, 'code', None) == _EBICS_NO_DOWNLOAD_DATA_AVAILABLE:
            logger.info('EBICS: no statement to download (090005) — treating as empty')
            return []
        raise


def _statement_to_balance(stmt, bal) -> BalanceInfo:
    """Map an ebicsclient Statement + closing Balance to a signed BalanceInfo.

    camt.053 reports the amount as a magnitude plus a CRDT/DBIT indicator; we fold
    that into a signed Decimal (debit balances are negative).
    """
    from ebicsclient import CreditDebit

    signed = bal.amount if bal.credit_debit == CreditDebit.CREDIT else -bal.amount
    return BalanceInfo(
        balance=Decimal(signed),
        currency=bal.currency,
        balance_date=bal.date,
        raw_data={
            'iban': stmt.iban,
            'balance_code': bal.code,
            'credit_debit': bal.credit_debit.value,
            'entries': len(stmt.entries),
            'source': 'ebics_camt053',
        },
    )


def _download_raw_or_none(client, *, date_range=None, receipt_policy=None):
    """``client.download(CAMT_053, ...)`` returning the raw order-data bytes, or ``None``
    when the bank reports "no data available" (090005 — a routine empty result).

    ``date_range`` requests a specific reporting period (dated download) instead of
    the not-yet-delivered data.
    """
    from ebicsclient import CAMT_053, ReceiptPolicy, ReturnCodeError

    kwargs = {'receipt_policy': receipt_policy or ReceiptPolicy.ACKNOWLEDGE}
    if date_range is not None:
        kwargs['date_range'] = date_range
    try:
        return client.download(CAMT_053, **kwargs)
    except ReturnCodeError as e:
        if getattr(e, 'code', None) == _EBICS_NO_DOWNLOAD_DATA_AVAILABLE:
            logger.info('EBICS: no statement to download (090005) — treating as empty')
            return None
        raise


# ---------------------------------------------------------------------------
# Rich camt.053 entry parsing.
#
# ebicsclient's Entry model stops at amount/dates/reference — no counterparty or
# remittance info, which transaction tracking needs. The raw camt.053 XML carries
# both (NtryDtls/TxDtls), so we keep the raw download and walk the Ntry elements
# ourselves, reusing the library's container/document helpers so ZIP handling and
# namespace adoption stay in one place.
# ---------------------------------------------------------------------------

def _xp(element, namespace, path):
    """First matching descendant element for a /-separated local-name path, or None."""
    ns = {'c': namespace}
    return next(iter(element.findall('/'.join(f'c:{p}' for p in path.split('/')), ns)), None)


def _xp_text(element, namespace, path):
    found = _xp(element, namespace, path)
    return found.text.strip() if found is not None and found.text else ''


def _parse_entry(ntry, namespace, iban) -> TransactionInfo:
    """Map one camt.053 ``Ntry`` element to a TransactionInfo."""
    from ebicsclient import CreditDebit

    amount_el = _xp(ntry, namespace, 'Amt')
    amount = Decimal(amount_el.text)
    currency = amount_el.get('Ccy', '')
    is_debit = _xp_text(ntry, namespace, 'CdtDbtInd') == CreditDebit.DEBIT.value
    if is_debit:
        amount = -amount

    # Sts is plain text in older camt.053 vintages, a <Cd> child in .001.08.
    status = _xp_text(ntry, namespace, 'Sts/Cd') or _xp_text(ntry, namespace, 'Sts') or 'BOOK'

    booking_date = _xp_text(ntry, namespace, 'BookgDt/Dt')
    value_date = _xp_text(ntry, namespace, 'ValDt/Dt')

    # Transaction details: counterparty and remittance info. A batch entry can carry
    # several TxDtls; only take the parties when the entry is a single transaction.
    ns = {'c': namespace}
    tx_details = ntry.findall('c:NtryDtls/c:TxDtls', ns)
    counterparty = ''
    counterparty_account = ''
    end_to_end_id = ''
    remittance_parts = []
    if len(tx_details) == 1:
        tx = tx_details[0]
        # The other party: creditor for money going out, debtor for money coming in.
        side = 'Cdtr' if is_debit else 'Dbtr'
        counterparty = (
            _xp_text(tx, namespace, f'RltdPties/{side}/Pty/Nm')  # .001.08
            or _xp_text(tx, namespace, f'RltdPties/{side}/Nm')  # older vintages
        )
        counterparty_account = _xp_text(tx, namespace, f'RltdPties/{side}Acct/Id/IBAN')
        end_to_end_id = _xp_text(tx, namespace, 'Refs/EndToEndId')
        remittance_parts = [
            el.text.strip()
            for el in tx.findall('c:RmtInf/c:Ustrd', ns)
            if el.text and el.text.strip()
        ]

    description = ' '.join(remittance_parts) or _xp_text(ntry, namespace, 'AddtlNtryInf')
    reference = _xp_text(ntry, namespace, 'AcctSvcrRef')

    return TransactionInfo(
        booking_date=date.fromisoformat(booking_date) if booking_date else None,
        value_date=date.fromisoformat(value_date) if value_date else None,
        amount=amount,
        currency=currency,
        counterparty=counterparty,
        counterparty_account=counterparty_account,
        description=description,
        external_id=reference or None,
        status=status,
        raw_data={
            'iban': iban,
            'source': 'ebics_camt053',
            'end_to_end_id': end_to_end_id or None,
            'tx_details_count': len(tx_details),
        },
    )


def parse_camt053_transactions(order_data: bytes) -> Dict[str, List[TransactionInfo]]:
    """Parse raw camt.053 order data into booked transactions, keyed by IBAN.

    Entries without a booking date and entries not in BOOK status are skipped —
    the importer needs a stable date and only ever records booked movements.
    """
    from ebicsclient.formats import camt
    from ebicsclient.formats.container import extract_documents

    out: Dict[str, List[TransactionInfo]] = {}
    for document in extract_documents(order_data):
        for stmt_el, namespace in camt.document_items(
            document, 'camt.053', 'BkToCstmrStmt', 'Stmt',
        ):
            iban = _xp_text(stmt_el, namespace, 'Acct/Id/IBAN')
            if not iban:
                continue
            ns = {'c': namespace}
            for ntry in stmt_el.findall('c:Ntry', ns):
                info = _parse_entry(ntry, namespace, iban)
                if info.booking_date is None or info.status != 'BOOK':
                    continue
                out.setdefault(iban, []).append(info)
    return out


class ZKBEbicsIntegration(BrokerIntegrationBase):
    """Download-only EBICS integration (camt.053 statements)."""

    def __init__(self, credentials: Dict[str, Any]):
        super().__init__(credentials)
        self._client = None
        self._statements = None  # cached list[Statement] for this instance
        self._raw = None  # raw camt.053 order data of the same download

    # ---- client construction -------------------------------------------------

    def _build_client(self):
        """Reconstruct the ebicsclient Client from the decrypted credentials."""
        from ebicsclient import Bank, Client, User, deserialize_keyring

        keyring_pem = self.credentials.get('keyring_pem')
        passphrase = self.credentials.get('keyring_passphrase')
        if not keyring_pem or not passphrase:
            raise ValueError('EBICS keyring is missing — the credential is not initialized')

        keyring = deserialize_keyring(base64.b64decode(keyring_pem), passphrase)
        bank = Bank(host_id=self.credentials['host_id'], url=self.credentials['url'])
        user = User(partner_id=self.credentials['partner_id'], user_id=self.credentials['user_id'])
        return Client(bank, user, keyring)

    def _pinned_hashes(self):
        """BankKeyHashes from the stored hex hashes, or None for trust-on-first-use."""
        from ebicsclient import BankKeyHashes

        auth = self.credentials.get('bank_hash_auth')
        enc = self.credentials.get('bank_hash_enc')
        if auth and enc:
            return BankKeyHashes(
                authentication=bytes.fromhex(auth.replace(' ', '')),
                encryption=bytes.fromhex(enc.replace(' ', '')),
            )
        return None

    def _get_statements(self):
        """HPB (verifying pinned bank keys) then download+parse camt.053, cached.

        The raw order data is kept alongside the parsed statements so
        ``get_transactions`` can extract the entry details (counterparty, remittance
        info) that ebicsclient's Entry model does not expose — same download, no
        extra network call.
        """
        if self._statements is not None:
            return self._statements
        from ebicsclient.formats import camt053

        if self._client is None:
            self._client = self._build_client()
        # Fetch and pin the bank's public keys, then pull the statements.
        self._client.hpb(pinned=self._pinned_hashes())
        self._raw = _download_raw_or_none(self._client)
        self._statements = camt053.parse(self._raw) if self._raw is not None else []
        return self._statements

    # ---- BrokerIntegrationBase ----------------------------------------------

    def authenticate(self) -> AuthResult:
        """EBICS has no interactive login: validate the keyring can be loaded.

        The actual network calls (HPB + download) happen lazily in get_accounts /
        get_balance so a construction problem surfaces as a clean error here.
        """
        try:
            self._client = self._build_client()
            return AuthResult(success=True)
        except Exception as e:
            logger.warning('EBICS client construction failed: %s', e)
            return AuthResult(success=False, error_message=str(e) or repr(e))

    def complete_2fa(self, auth_code, session_data) -> AuthResult:
        # Not applicable: EBICS access is granted out-of-band via the signed letter.
        return AuthResult(success=False, error_message='EBICS does not use interactive 2FA')

    def get_accounts(self) -> List[AccountInfo]:
        accounts = []
        for stmt in self._get_statements():
            if not stmt.iban:
                continue
            bal = stmt.closing_balance or (stmt.balances[0] if stmt.balances else None)
            accounts.append(AccountInfo(
                identifier=stmt.iban,
                name=stmt.iban,
                account_type='checking',
                currency=bal.currency if bal else 'CHF',
            ))
        return accounts

    def get_balance(self, account_identifier: str) -> BalanceInfo:
        statements = self._get_statements()

        # No statement delivered at all (EBICS 090005) is a routine "nothing new"
        # condition, not a failure — signal a benign no-op so the sync keeps the
        # account active and its last snapshot instead of marking it errored.
        if not statements:
            raise NoNewDataError(
                f'No EBICS statement available to download for {account_identifier}'
            )

        matches = [s for s in statements if s.iban == account_identifier]
        if not matches:
            available = ', '.join(sorted({s.iban for s in statements if s.iban})) or 'none'
            raise ValueError(
                f'No camt.053 statement for IBAN {account_identifier}. '
                f'Available in this delivery: {available}'
            )

        # Use the most recent statement for this IBAN by closing-balance date.
        stmt = max(
            matches,
            key=lambda s: s.closing_balance.date if s.closing_balance else date.min,
        )
        bal = stmt.closing_balance
        if bal is None:
            raise ValueError(f'Statement for IBAN {account_identifier} has no closing balance')

        return _statement_to_balance(stmt, bal)

    # ---- historical backfill --------------------------------------------------
    # A camt.053 delivery carries a run of daily end-of-day statements. Expose them
    # as historical balances so the sync worker snapshots EVERY delivered day (not
    # just the latest) — nothing gets thrown away. No network beyond the statements
    # already fetched for this sync.

    def supports_historical_data(self) -> bool:
        return True

    def historical_data_requires_extra_request(self) -> bool:
        # The daily statements come with the same camt.053 download — no extra call.
        return False

    def get_historical_balances(self, account_identifier, start_date, end_date):
        out = []
        for stmt in self._get_statements():
            if stmt.iban != account_identifier:
                continue
            bal = stmt.closing_balance
            if bal is None or not (start_date <= bal.date <= end_date):
                continue
            out.append(_statement_to_balance(stmt, bal))
        return out

    # ---- transactions ---------------------------------------------------------

    def supports_transactions(self) -> bool:
        return True

    def get_transactions(self, account_identifier, start_date, end_date):
        """Booked entries for the IBAN from the camt.053 data of this sync's download."""
        self._get_statements()  # ensure the raw order data is fetched (or confirmed empty)
        if self._raw is None:
            return []
        return self._entries_in_range(self._raw, account_identifier, start_date, end_date)

    def get_transactions_for_range(self, account_identifier, start_date, end_date):
        """Booked entries for a PAST period via a dated, non-consuming download.

        The regular sync reads whatever the bank has queued for delivery, which
        cannot reach further back than the current delivery — so history backfill
        must request the period explicitly. ``ReceiptPolicy.KEEP`` means this does
        not consume anything a later sync still needs. Whether the bank re-serves
        an already-delivered period is bank-specific (ZKB does).
        """
        from ebicsclient import DateRange, DateRangeMismatchError, ReceiptPolicy

        if self._client is None:
            self._client = self._build_client()
        self._client.hpb(pinned=self._pinned_hashes())
        try:
            raw = _download_raw_or_none(
                self._client,
                date_range=DateRange(start_date, end_date),
                receipt_policy=ReceiptPolicy.KEEP,
            )
        except DateRangeMismatchError:
            raise ValueError(
                'The bank ignored the requested period and returned other data — '
                'no transactions were imported. Try a shorter or more recent range.'
            )
        if raw is None:
            return []
        return self._entries_in_range(raw, account_identifier, start_date, end_date)

    @staticmethod
    def _entries_in_range(raw, account_identifier, start_date, end_date):
        by_iban = parse_camt053_transactions(raw)
        return [
            info for info in by_iban.get(account_identifier, [])
            if start_date <= info.booking_date <= end_date
        ]


# ---------------------------------------------------------------------------
# One-time key-exchange helpers (used by the EBICS credential endpoints).
# Kept here so all ebicsclient usage lives in one module.
# ---------------------------------------------------------------------------

def generate_keyring_blob() -> Dict[str, str]:
    """Generate a fresh EBICS keyring and return the storable secret blob.

    The blob (serialised keyring + its passphrase) is what gets Fernet-encrypted
    under the user's KEK. The passphrase is random and never leaves the blob.
    """
    import secrets

    from ebicsclient import generate_keyring, serialize_keyring

    passphrase = secrets.token_urlsafe(32)
    keyring = generate_keyring()
    pem = serialize_keyring(keyring, passphrase)
    return {
        'keyring_pem': base64.b64encode(pem).decode(),
        'keyring_passphrase': passphrase,
    }


def _client_for(cred, blob):
    """Build an ebicsclient Client for an EbicsCredential + decrypted keyring blob."""
    from ebicsclient import Bank, Client, User, deserialize_keyring

    keyring = deserialize_keyring(base64.b64decode(blob['keyring_pem']), blob['keyring_passphrase'])
    bank = Bank(host_id=cred.host_id, url=cred.url)
    # NB: the EBICS user id is `subscriber_id`, NOT `cred.user_id` — the latter is the
    # Django `user` FK's integer PK (a non-str), which crashed ebicsclient during INI.
    user = User(partner_id=cred.partner_id, user_id=cred.subscriber_id)
    return Client(bank, user, keyring)


def _pinned_for(cred):
    from ebicsclient import BankKeyHashes

    if cred.bank_hash_auth and cred.bank_hash_enc:
        return BankKeyHashes(
            authentication=bytes.fromhex(cred.bank_hash_auth.replace(' ', '')),
            encryption=bytes.fromhex(cred.bank_hash_enc.replace(' ', '')),
        )
    return None


class EbicsSubscriberBlockedError(Exception):
    """The bank rejected the key submission as already-initialised (EBICS 091002).

    Our freshly generated keys were NOT transmitted: the bank still holds an earlier
    initialisation for this subscriber, and that state blocks any new key delivery
    until the bank resets (deletes) the subscriber. Crucially the bank answers 091002
    for BOTH "you re-sent the same keys" and "you sent different keys we ignored", and
    the response carries no way to tell them apart — so a fresh keyring that comes back
    ALREADY_INITIALISED means our keys were silently dropped. Producing an
    initialisation letter here would be actively harmful: its key fingerprints would
    never match the keys the bank holds, so activation fails with a hash mismatch.
    """

    def __init__(self, ini_state, hia_state):
        self.ini_state = ini_state
        self.hia_state = hia_state
        super().__init__(
            'The bank rejected the key submission: this subscriber is already '
            'initialised on the bank side (EBICS 091002), so your new keys were NOT '
            'transmitted. Ask the bank to reset (delete) your EBICS subscriber '
            'initialisation, then submit keys again.'
        )


def submit_keys_and_letter(cred, blob):
    """Send INI + HIA, then render the initialisation letter for the delivered keys.

    Returns ``(ini_state, hia_state, letter)`` where letter is the ebicsclient Letter
    (``.media_type``, ``.content``).

    If the bank rejects the submission as already-initialised (EBICS 091002 ->
    ``InitializationState.ALREADY_INITIALISED``), the keys were NOT delivered — the
    bank still holds an earlier initialisation. We deliberately do NOT render a letter
    in that case (its fingerprints would never match the bank's keys) and raise
    ``EbicsSubscriberBlockedError`` so the caller can tell the user the bank must reset
    the subscriber before new keys can be submitted.
    """
    from ebicsclient import InitializationState, OutputFormat

    client = _client_for(cred, blob)
    ini_state = client.ini()
    hia_state = client.hia()
    if InitializationState.ALREADY_INITIALISED in (ini_state, hia_state):
        raise EbicsSubscriberBlockedError(ini_state, hia_state)
    letter = client.make_ini_letter(output_format=OutputFormat.PDF, branding='Wealth Tracker')
    return ini_state, hia_state, letter


def render_letter(cred, blob):
    """Re-render the initialisation letter as PDF (deterministic from the keys)."""
    from ebicsclient import OutputFormat

    return _client_for(cred, blob).make_ini_letter(
        output_format=OutputFormat.PDF, branding='Wealth Tracker',
    )


def fetch_bank_keys_and_statements(cred, blob):
    """HPB (pinning) + a NON-CONSUMING camt.053 peek. Returns ``(bank_key_hashes_hex, statements)``.

    ``bank_key_hashes_hex`` is ``{'auth': hex, 'enc': hex}`` computed from the keys the
    bank returned — for trust-on-first-use display/verification against the letter.

    The statement read uses ``ReceiptPolicy.KEEP`` (a negative receipt) so discovery /
    "Test connection" does NOT consume the pending data — it stays available for the
    first real sync to capture. Raises the underlying ebicsclient error if the bank has
    not activated the subscriber yet or the pinned hashes do not match.
    """
    from ebicsclient import DateRange, DateRangeMismatchError, ReceiptPolicy, bank_key_hashes

    client = _client_for(cred, blob)
    bank_keys = client.hpb(pinned=_pinned_for(cred))
    hashes = bank_key_hashes(bank_keys)
    statements = _download_statements_or_empty(client, receipt_policy=ReceiptPolicy.KEEP)

    if not statements:
        # Nothing pending (e.g. the backlog was already collected). Look back over a
        # window with a dated, non-consuming download so we can still discover the
        # accounts from historical statements. Whether the bank re-serves a past range
        # is bank-specific — an empty result here just means no accounts were found.
        end = date.today()
        start = end - timedelta(days=_DISCOVERY_FALLBACK_DAYS)
        try:
            statements = _download_statements_or_empty(
                client, date_range=DateRange(start, end), receipt_policy=ReceiptPolicy.KEEP,
            )
        except DateRangeMismatchError:
            logger.warning('EBICS discovery: bank ignored the fallback date range')

    return (
        {'auth': hashes.authentication.hex(), 'enc': hashes.encryption.hex()},
        statements,
    )


def fetch_statements_for_range(cred, blob, start, end):
    """HPB + a dated, NON-CONSUMING camt.053 download for the inclusive ``[start, end]``.

    Used for historical backfill: requests a specific reporting period via ``DateRange``
    and reads it with ``ReceiptPolicy.KEEP`` so nothing is consumed. Returns the parsed
    statements (``[]`` if the bank reports no data). ``DateRangeMismatchError`` propagates
    if the bank ignored the range (fail closed). Whether a bank re-serves already-delivered
    data for a past range is bank-specific.
    """
    from ebicsclient import DateRange, ReceiptPolicy

    client = _client_for(cred, blob)
    client.hpb(pinned=_pinned_for(cred))
    return _download_statements_or_empty(
        client, date_range=DateRange(start, end), receipt_policy=ReceiptPolicy.KEEP,
    )
