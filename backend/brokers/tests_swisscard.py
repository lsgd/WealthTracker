"""Swisscard integration: flow logic with the browser layer stubbed out.

The real login needs a phone, so the browser is replaced by a fake page that
answers the SPA's REST calls. What is verified here is the part that can break
silently: which call happens when, that the SMS is not re-sent while the user
holds a code, and how the portal's numbers map onto the app's model.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from brokers.integrations.swisscard import (
    ACCOUNTS_PATH,
    OTP_PATH,
    PASSWORD_PATH,
    SwisscardIntegration,
)

_ACCOUNTS = [{
    'id': '40007155878',
    'currency': 'CHF',
    'baseProduct': {'shortName': 'Cashback AMEX'},
    'cycleBalance': {
        'postedBalance': {'value': 2560.85, 'currency': 'CHF'},
        'pendingBalance': {'value': 0.0, 'currency': 'CHF'},
    },
}]

_CSV = (
    'Transaction date,Description,Merchant,Card number,Currency,Amount,'
    'Foreign Currency,Amount in foreign currency,Debit/Credit,Status,'
    'Merchant Category,Registered Category\n'
    '23.08.2026,TEST SHOP,TEST SHOP,3776 60**** *0001,CHF,42.50,,,'
    'Debit,Posted,Groceries,\n'
    '20.08.2026,IHRE ZAHLUNG,,3776 60**** *0001,CHF,-1200.00,,,'
    'Credit,Posted,Payment,\n'
)


class FakePage:
    """Answers the SPA's REST calls and records what was asked."""

    def __init__(self, password_status=200, otp_status=200, next_step='MTAN_OTP_REQUIRED'):
        self.calls = []
        self.password_status = password_status
        self.otp_status = otp_status
        self.next_step = next_step

    # -- playwright surface used by the integration --------------------
    def goto(self, url, **kwargs):
        self.calls.append(('goto', url))

    def on(self, event, handler):
        # Pretend Anomaly Shield signed the probe so the transport is settled.
        class _Req:
            method = 'POST'
            headers = {'x-42': 'signed'}
        self._handler = handler
        handler(_Req())

    def remove_listener(self, event, handler):
        pass

    def evaluate(self, script, args):
        method, path, body, _headers = args
        self.calls.append((method, path, body))
        if path.endswith('/access'):
            return {'status': 401, 'text': '{}'}
        if path == PASSWORD_PATH:
            return {'status': self.password_status, 'text':
                    '{"data": {"attributes": {"nextAuthStep": "%s", '
                    '"phoneNumber": "+41 79 ***"}}}' % self.next_step}
        if path == OTP_PATH:
            return {'status': self.otp_status, 'text': '{"data": {"id": "x"}}'}
        if path == ACCOUNTS_PATH:
            import json as jsonlib
            return {'status': 200, 'text': jsonlib.dumps(_ACCOUNTS)}
        if path.endswith('/transactions/csv'):
            return {'status': 200, 'text': _CSV}
        return {'status': 404, 'text': ''}


class FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def set_default_timeout(self, ms):
        pass

    def storage_state(self):
        return {'cookies': [{'name': 'ncs-S', 'value': 'x'}]}

    def close(self):
        self.closed = True


class SwisscardFlowTests(TestCase):
    def _integration(self, page, **creds):
        integration = SwisscardIntegration(
            {'username': 'u', 'password': 'p', **creds})
        context = FakeContext(page)

        class _Browser:
            def close(self_inner):
                pass

        def fake_open(playwright, storage_state=None, url=None):
            return _Browser(), context, page

        integration._playwright = lambda: _NullPlaywright()
        integration._open = fake_open
        integration._context = context
        return integration

    def test_password_step_asks_for_the_sms_code(self):
        page = FakePage()
        integration = self._integration(page)
        result = integration.authenticate()
        self.assertFalse(result.success)
        self.assertTrue(result.requires_2fa)
        self.assertEqual(result.two_fa_type, 'sms')
        # The cookies of the half-finished flow travel to the second step.
        self.assertIn('storage_state', result.session_data)
        self.assertIn('+41 79 ***', result.challenge_data['message'])
        # The password was posted exactly once — one SMS, not two.
        self.assertEqual(
            [c for c in page.calls if c[1] == PASSWORD_PATH].__len__(), 1)

    def test_wrong_password_reports_instead_of_asking_for_a_code(self):
        integration = self._integration(FakePage(password_status=401))
        result = integration.authenticate()
        self.assertFalse(result.success)
        self.assertFalse(result.requires_2fa)

    def test_missing_credentials_do_not_open_a_browser(self):
        integration = SwisscardIntegration({'username': '', 'password': ''})
        integration._playwright = lambda: self.fail('browser must not start')
        result = integration.authenticate()
        self.assertFalse(result.success)
        self.assertIn('username', result.error_message)

    def test_otp_step_completes_and_pulls_the_data(self):
        page = FakePage()
        integration = self._integration(page)
        result = integration.complete_2fa('123456', {
            'storage_state': {'cookies': []}, 'transport': 'fetch'})
        self.assertTrue(result.success, result.error_message)
        # Accounts and the CSV export were fetched inside the same session.
        paths = [c[1] for c in page.calls]
        self.assertIn(ACCOUNTS_PATH, paths)
        self.assertTrue(any(p.endswith('/transactions/csv') for p in paths))
        # The password step was NOT repeated (that would send a second SMS).
        self.assertNotIn(PASSWORD_PATH, paths)

    def test_rejected_code_is_reported(self):
        integration = self._integration(FakePage(otp_status=400))
        result = integration.complete_2fa('000000', {
            'storage_state': {'cookies': []}})
        self.assertFalse(result.success)
        self.assertIn('code', result.error_message.lower())

    def test_empty_code_is_refused_before_opening_a_browser(self):
        integration = SwisscardIntegration({'username': 'u', 'password': 'p'})
        integration._playwright = lambda: self.fail('browser must not start')
        result = integration.complete_2fa('', {'storage_state': {}})
        self.assertFalse(result.success)

    def test_card_balance_is_carried_as_a_liability(self):
        page = FakePage()
        integration = self._integration(page)
        integration.complete_2fa('123456', {'storage_state': {'cookies': []}})
        balance = integration.get_balance('40007155878')
        # The portal reports 2560.85 owed; net worth must see it as negative.
        self.assertEqual(balance.balance, Decimal('-2560.85'))
        self.assertEqual(balance.currency, 'CHF')

    def test_transactions_are_parsed_with_the_swisscard_signs(self):
        page = FakePage()
        integration = self._integration(page)
        integration.complete_2fa('123456', {'storage_state': {'cookies': []}})
        rows = integration.get_transactions(
            '40007155878', date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(len(rows), 2)
        by_date = {r.booking_date: r for r in rows}
        self.assertEqual(by_date[date(2026, 8, 23)].amount, Decimal('-42.50'))
        self.assertEqual(by_date[date(2026, 8, 20)].amount, Decimal('1200.00'))
        # Outside the fetched range nothing is invented.
        self.assertEqual(
            integration.get_transactions(
                '40007155878', date(2025, 1, 1), date(2025, 2, 1)),
            [])

    def test_does_not_reauthenticate_before_the_code_step(self):
        self.assertFalse(
            SwisscardIntegration({}).requires_reauth_before_2fa())

    def test_accounts_are_exposed_for_discovery(self):
        page = FakePage()
        integration = self._integration(page)
        integration.complete_2fa('123456', {'storage_state': {'cookies': []}})
        accounts = integration.get_accounts()
        self.assertEqual(accounts[0].identifier, '40007155878')
        self.assertEqual(accounts[0].account_type, 'credit_card')


class _NullPlaywright:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SwisscardFactoryTests(TestCase):
    def test_factory_returns_the_integration(self):
        from brokers.integrations import get_broker_integration
        from brokers.models import Broker
        broker = Broker.objects.create(
            code='swisscard', name='Swisscard', integration_type='rest')
        integration = get_broker_integration(
            broker, {'username': 'u', 'password': 'p'}, account_id=1)
        self.assertIsInstance(integration, SwisscardIntegration)
        self.assertTrue(integration.supports_transactions())


class SwisscardViewFlowTests(TestCase):
    """The auth view must not restart the login before submitting the code."""

    @patch('brokers.integrations.swisscard.SwisscardIntegration.authenticate')
    def test_view_skips_reauth_for_interactive_brokers(self, m_auth):
        integration = SwisscardIntegration({'username': 'u', 'password': 'p'})
        # Mirrors AccountAuthView's branch.
        if integration.requires_reauth_before_2fa():
            integration.authenticate()
        m_auth.assert_not_called()
