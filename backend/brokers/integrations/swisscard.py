"""Swisscard (credit card) — password plus an SMS one-time code.

Swisscard's portal runs Ergon Airlock IAM with a mandatory second factor and
issues nothing but session cookies: no device trust, no refresh token, no
storable long-lived credential. A sync therefore cannot run unattended; it is
user-initiated and completes only once the SMS code is entered:

1. :meth:`authenticate` submits username and password, which makes Airlock
   send the SMS, and returns ``requires_2fa`` together with the cookies of the
   half-finished flow.
2. :meth:`complete_2fa` restores those cookies, posts the code, and pulls
   accounts and transactions straight away — the session is short-lived, so
   everything is fetched in that one window and cached.

Everything runs inside a real browser page. The portal's ``42.js`` (Airlock
Anomaly Shield) signs each POST with an ``x-42`` header computed at runtime,
so requests are issued from the page rather than rebuilt from the outside. No
CSS selectors are involved — the SPA's own REST endpoints are called directly,
which survives redesigns of the login screen.
"""
import json
import logging
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .base import (
    AccountInfo,
    AuthResult,
    BalanceInfo,
    BrokerIntegrationBase,
    TransactionInfo,
)

logger = logging.getLogger(__name__)

ORIGIN = 'https://app.swisscard.ch'
FLOW = '2fa_cardholder'
LOGIN_PAGE = f'{ORIGIN}/auth/ui/app/auth/flow/{FLOW}/password'
APP_PAGE = f'{ORIGIN}/'

ACCESS_PATH = f'/auth/rest/public/authentication/applications/{FLOW}/access'
PASSWORD_PATH = '/auth/rest/public/authentication/password/check'
OTP_PATH = '/auth/rest/public/authentication/mtan/otp/check'
ACCOUNTS_PATH = '/api/v1/accounts'

# How much history one interactive login pulls. The session dies within
# minutes, so everything that may be asked for later is fetched up front.
FETCH_DAYS = 400

DEFAULT_TIMEOUT_MS = 60_000


class SwisscardLoginError(RuntimeError):
    """Login failed in a way the user can act on (wrong password, wrong code)."""


class SwisscardUnavailable(RuntimeError):
    """The browser stack needed for the login is missing."""


# Issue requests from the page so Anomaly Shield instruments them. Which
# transport it hooks (fetch or XMLHttpRequest) is a deployment detail, so the
# caller probes once with a harmless call and sticks to what worked.
_FETCH_JS = """
async ([method, path, body, headers]) => {
  const res = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: Object.assign(
      {'accept': 'application/json, text/plain, */*'},
      body ? {'content-type': 'application/json'} : {},
      headers || {}),
    body: body ? JSON.stringify(body) : undefined,
  });
  return {status: res.status, text: await res.text()};
}
"""

_XHR_JS = """
([method, path, body, headers]) => new Promise((resolve) => {
  const xhr = new XMLHttpRequest();
  xhr.open(method, path, true);
  xhr.withCredentials = true;
  xhr.setRequestHeader('accept', 'application/json, text/plain, */*');
  if (body) xhr.setRequestHeader('content-type', 'application/json');
  for (const [k, v] of Object.entries(headers || {})) xhr.setRequestHeader(k, v);
  xhr.onloadend = () => resolve({status: xhr.status, text: xhr.responseText});
  xhr.send(body ? JSON.stringify(body) : null);
})
"""


class SwisscardIntegration(BrokerIntegrationBase):
    """Interactive Swisscard sync (password + SMS code)."""

    def __init__(self, credentials: Dict[str, Any], account_id: Any = None):
        super().__init__(credentials)
        self.account_id = account_id
        self._accounts: Optional[List[Dict[str, Any]]] = None
        self._transactions: Optional[List[TransactionInfo]] = None
        self._fetched_from: Optional[date] = None

    # -- capabilities -----------------------------------------------------

    def requires_reauth_before_2fa(self) -> bool:
        """The SMS was already sent; re-running the password step sends another."""
        return False

    def supports_transactions(self) -> bool:
        return True

    # -- browser plumbing -------------------------------------------------

    def _playwright(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depends on deploy image
            raise SwisscardUnavailable(
                'Playwright is not installed. Add `playwright` to requirements '
                'and run `playwright install --with-deps chromium`.'
            ) from exc
        return sync_playwright()

    def _open(self, playwright, storage_state=None, url=LOGIN_PAGE):
        headless = os.environ.get('SWISSCARD_HEADLESS', '1') != '0'
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            storage_state=storage_state,
            locale='en-CH',
        )
        context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        page = context.new_page()
        # networkidle: 42.js must have run before anything is posted.
        page.goto(url, wait_until='networkidle')
        return browser, context, page

    def _pick_transport(self, page) -> str:
        """Return 'fetch' or 'xhr' — whichever Anomaly Shield signs.

        Probes with the SPA's own flow-start call, which answers 401 by design
        and changes no state.
        """
        for transport, script in (('fetch', _FETCH_JS), ('xhr', _XHR_JS)):
            signed = {'ok': False}

            def _watch(request, signed=signed):
                if request.method == 'POST' and 'x-42' in request.headers:
                    signed['ok'] = True

            page.on('request', _watch)
            try:
                page.evaluate(script, [
                    'POST', ACCESS_PATH, {}, {'x-same-domain': '1'},
                ])
            except Exception:  # pragma: no cover - transport simply unusable
                logger.debug('Swisscard: %s transport unusable', transport)
            finally:
                page.remove_listener('request', _watch)
            if signed['ok']:
                return transport
        # Nothing signed the probe; the header may not be enforced. Carry on
        # with fetch rather than failing before we have learned anything.
        logger.warning('Swisscard: no x-42 header observed on the probe call')
        return 'fetch'

    def _call(self, page, transport, method, path, body=None, headers=None):
        script = _FETCH_JS if transport == 'fetch' else _XHR_JS
        result = page.evaluate(script, [method, path, body, headers or {}])
        text = result.get('text') or ''
        payload = None
        if text:
            try:
                payload = json.loads(text)
            except ValueError:
                payload = None
        return result.get('status'), payload, text

    # -- authentication ---------------------------------------------------

    def authenticate(self) -> AuthResult:
        username = (self.credentials.get('username') or '').strip()
        password = self.credentials.get('password') or ''
        if not username or not password:
            return AuthResult(
                success=False,
                error_message='Swisscard needs a username and password.',
            )

        with self._playwright() as playwright:
            browser, context, page = self._open(playwright)
            try:
                transport = self._pick_transport(page)
                status, payload, _ = self._call(
                    page, transport, 'POST', PASSWORD_PATH,
                    {'username': username, 'password': password},
                    {'x-same-domain': '1', 'x-continue-flow': 'true'},
                )
                if status != 200:
                    return AuthResult(
                        success=False,
                        error_message=self._message(
                            payload, 'Swisscard rejected the username or password.'),
                    )
                meta = self._meta(payload)
                next_step = (meta.get('nextAuthStep') or '').upper()
                if 'MTAN' not in next_step and 'OTP' not in next_step:
                    # No SMS step (or the deployment changed): nothing to ask
                    # the user, so treat it as a failure rather than pretend.
                    return AuthResult(
                        success=False,
                        error_message=f'Unexpected authentication step "{next_step}".',
                    )
                # The cookies carry the half-finished flow; the OTP step
                # continues it in a fresh browser.
                state = context.storage_state()
                phone = meta.get('phoneNumber') or ''
                return AuthResult(
                    success=False,
                    requires_2fa=True,
                    two_fa_type='sms',
                    session_data={'storage_state': state, 'transport': transport},
                    challenge_data={
                        'message': f'Enter the code sent to {phone}' if phone
                                   else 'Enter the code sent by SMS',
                        'phone_number': phone,
                    },
                )
            finally:
                context.close()
                browser.close()

    def complete_2fa(self, auth_code: Optional[str],
                     session_data: Dict[str, Any]) -> AuthResult:
        code = (auth_code or '').strip()
        if not code:
            return AuthResult(success=False, error_message='Enter the SMS code.')
        state = (session_data or {}).get('storage_state')
        if not state:
            return AuthResult(
                success=False,
                error_message='The login session expired — start the sync again.',
            )

        with self._playwright() as playwright:
            browser, context, page = self._open(
                playwright, storage_state=state,
                url=f'{ORIGIN}/auth/ui/app/auth/flow/{FLOW}/mtan',
            )
            try:
                transport = (session_data.get('transport')
                             or self._pick_transport(page))
                status, payload, _ = self._call(
                    page, transport, 'POST', OTP_PATH, {'otp': code},
                    {'x-same-domain': '1', 'x-continue-flow': 'true'},
                )
                if status != 200:
                    return AuthResult(
                        success=False,
                        error_message=self._message(
                            payload, 'That SMS code was not accepted.'),
                    )
                # The session is live but short — pull everything now.
                page.goto(APP_PAGE, wait_until='networkidle')
                self._load_data(page, transport)
                return AuthResult(success=True)
            finally:
                context.close()
                browser.close()

    # -- data -------------------------------------------------------------

    def _load_data(self, page, transport) -> None:
        status, payload, _ = self._call(page, transport, 'GET', ACCOUNTS_PATH)
        if status != 200 or not isinstance(payload, list):
            raise SwisscardLoginError('Could not read the Swisscard accounts.')
        self._accounts = payload

        end = date.today()
        start = end - timedelta(days=FETCH_DAYS)
        self._transactions = []
        for account in payload:
            identifier = str(account.get('id') or '')
            if not identifier:
                continue
            self._transactions.extend(
                self._fetch_transactions(page, transport, identifier, start, end))
        self._fetched_from = start

    def _fetch_transactions(self, page, transport, identifier, start, end):
        from portfolio.csv_import import CsvImportError, parse_transactions_csv

        status, _, text = self._call(
            page, transport, 'POST',
            f'{ACCOUNTS_PATH}/{identifier}/transactions/csv',
            {'dateMin': start.isoformat(), 'dateMax': end.isoformat()},
        )
        if status != 200 or not text:
            logger.warning(
                'Swisscard: transaction export failed for %s (status %s)',
                identifier, status)
            return []
        try:
            _, _, infos, skipped, _ = parse_transactions_csv(
                text.encode('utf-8'), self._currency_of(identifier))
        except CsvImportError as exc:
            logger.warning('Swisscard: export not parseable: %s', exc)
            return []
        if skipped:
            logger.info('Swisscard: %d export rows skipped for %s',
                        skipped, identifier)
        for info in infos:
            info.raw_data = {'account': identifier}
        return infos

    def _account(self, identifier: str) -> Dict[str, Any]:
        for account in self._accounts or []:
            if str(account.get('id')) == str(identifier):
                return account
        raise SwisscardLoginError(f'Swisscard account {identifier} not found.')

    def _currency_of(self, identifier: str) -> str:
        for account in self._accounts or []:
            if str(account.get('id')) == str(identifier):
                return account.get('currency') or 'CHF'
        return 'CHF'

    def get_accounts(self) -> List[AccountInfo]:
        return [
            AccountInfo(
                identifier=str(a.get('id')),
                name=(a.get('baseProduct') or {}).get('shortName') or 'Swisscard',
                account_type='credit_card',
                currency=a.get('currency') or 'CHF',
            )
            for a in self._accounts or []
        ]

    def get_balance(self, account_identifier: str) -> BalanceInfo:
        account = self._account(account_identifier)
        posted = ((account.get('cycleBalance') or {}).get('postedBalance') or {})
        # The portal reports what is OWED as a positive number; as a balance in
        # a net-worth view a card is a liability, so it is carried negative.
        amount = Decimal(str(posted.get('value') or 0))
        return BalanceInfo(
            balance=-amount,
            currency=posted.get('currency') or account.get('currency') or 'CHF',
            balance_date=date.today(),
            raw_data={'posted_balance': str(amount)},
        )

    def get_transactions(self, account_identifier: str, start_date: date,
                         end_date: date) -> List[TransactionInfo]:
        if self._transactions is None:
            return []
        if self._fetched_from and start_date < self._fetched_from:
            logger.info(
                'Swisscard: %s requested but only %s onwards was fetched',
                start_date, self._fetched_from)
        return [
            info for info in self._transactions
            if (info.raw_data or {}).get('account') == str(account_identifier)
            and start_date <= info.booking_date <= end_date
        ]

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _meta(payload) -> Dict[str, Any]:
        """Airlock answers with a JSON:API document; the useful bits are flat."""
        if not isinstance(payload, dict):
            return {}
        found: Dict[str, Any] = {}

        def collect(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, (dict, list)):
                        collect(value)
                    elif key not in found:
                        found[key] = value
            elif isinstance(node, list):
                for item in node:
                    collect(item)

        collect(payload)
        return found

    @classmethod
    def _message(cls, payload, fallback: str) -> str:
        meta = cls._meta(payload)
        for key in ('detail', 'title', 'message', 'code'):
            value = meta.get(key)
            if isinstance(value, str) and value:
                return f'{fallback} ({value})'
        return fallback
