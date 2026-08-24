"""Tests for portfolio models, serializers, and account/snapshot/sync endpoints."""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from brokers.integrations.base import AuthResult, BalanceInfo
from brokers.models import Broker
from core.kek_testing import make_kek_user
from core.user_encryption import decrypt_credentials
from exchange_rates.models import ExchangeRate
from portfolio.models import AccountSnapshot, FinancialAccount, PortfolioPosition
from portfolio.serializers import FinancialAccountSerializer


class ModelTests(TestCase):
    def setUp(self):
        self.user, _, _ = make_kek_user()
        self.broker = Broker.objects.create(code='viac', name='VIAC', integration_type='rest')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Pillar 3a', currency='CHF',
        )

    def test_latest_snapshot_returns_most_recent(self):
        AccountSnapshot.objects.create(
            account=self.account, balance=Decimal('100'), currency='CHF',
            snapshot_date=date(2026, 1, 1),
        )
        newest = AccountSnapshot.objects.create(
            account=self.account, balance=Decimal('200'), currency='CHF',
            snapshot_date=date(2026, 6, 1),
        )
        self.assertEqual(self.account.latest_snapshot, newest)

    def test_latest_snapshot_none_when_empty(self):
        self.assertIsNone(self.account.latest_snapshot)

    def test_account_str(self):
        self.assertIn('Pillar 3a', str(self.account))

    def test_position_relationship(self):
        snap = AccountSnapshot.objects.create(
            account=self.account, balance=Decimal('500'), currency='CHF',
            snapshot_date=date(2026, 6, 1),
        )
        pos = PortfolioPosition.objects.create(
            snapshot=snap, name='World ETF', quantity=Decimal('10'),
            price_per_unit=Decimal('50'), market_value=Decimal('500'),
            currency='CHF', asset_class='equity',
        )
        self.assertEqual(list(snap.positions.all()), [pos])


class SerializerTests(TestCase):
    def setUp(self):
        self.user, _, _ = make_kek_user()
        self.broker = Broker.objects.create(code='viac', name='VIAC', integration_type='rest')

    def test_financial_account_serializer_output(self):
        account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Acct', currency='CHF',
        )
        AccountSnapshot.objects.create(
            account=account, balance=Decimal('42'), currency='CHF',
            snapshot_date=date(2026, 6, 1),
        )
        data = FinancialAccountSerializer(account).data
        self.assertEqual(data['name'], 'Acct')
        self.assertEqual(data['broker']['code'], 'viac')
        self.assertEqual(data['latest_snapshot']['balance'], '42.0000')
        self.assertIsNone(data['ebics_credential'])
        # Encrypted credentials must never be exposed.
        self.assertNotIn('encrypted_credentials', data)


class AccountEndpointTests(APITestCase):
    def setUp(self):
        self.user, self.kek, self.user_key = make_kek_user()
        self.broker = Broker.objects.create(code='viac', name='VIAC', integration_type='rest')
        self.client.force_authenticate(user=self.user)

    def test_list_only_own_accounts(self):
        FinancialAccount.objects.create(user=self.user, broker=self.broker, name='Mine')
        other, _, _ = make_kek_user(username='bob')
        FinancialAccount.objects.create(user=other, broker=self.broker, name='Theirs')
        resp = self.client.get(reverse('account_list'))
        self.assertEqual(resp.status_code, 200)
        names = [a['name'] for a in resp.data['results']]
        self.assertEqual(names, ['Mine'])

    def test_create_manual_account(self):
        resp = self.client.post(reverse('account_list'), {
            'name': 'Cash', 'broker_code': 'viac', 'is_manual': True,
            'account_type': 'savings', 'currency': 'CHF',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        account = FinancialAccount.objects.get(name='Cash')
        self.assertTrue(account.is_manual)

    def test_create_account_with_credentials_encrypts_them(self):
        self.client.credentials(HTTP_X_KEK=self.kek)
        resp = self.client.post(reverse('account_list'), {
            'name': 'VIAC', 'broker_code': 'viac', 'currency': 'CHF',
            'credentials': {'username': 'me', 'password': 's3cr3t'},
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        account = FinancialAccount.objects.get(name='VIAC')
        self.assertIsNotNone(account.encrypted_credentials)
        # Stored ciphertext must decrypt back to the original credentials.
        self.assertEqual(
            decrypt_credentials(account.encrypted_credentials, self.user_key),
            {'username': 'me', 'password': 's3cr3t'},
        )

    def test_detail_delete(self):
        account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Del',
        )
        resp = self.client.delete(reverse('account_detail', args=[account.pk]))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(FinancialAccount.objects.filter(pk=account.pk).exists())

    def test_notes_are_editable(self):
        account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Cash', is_manual=True,
        )
        resp = self.client.patch(
            reverse('account_detail', args=[account.pk]),
            {'notes': 'IBAN CH..\nrainy-day fund'}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['notes'], 'IBAN CH..\nrainy-day fund')
        account.refresh_from_db()
        self.assertEqual(account.notes, 'IBAN CH..\nrainy-day fund')

    def test_cannot_access_other_users_account(self):
        other, _, _ = make_kek_user(username='bob')
        account = FinancialAccount.objects.create(
            user=other, broker=self.broker, name='Theirs',
        )
        resp = self.client.get(reverse('account_detail', args=[account.pk]))
        self.assertEqual(resp.status_code, 404)


class SnapshotEndpointTests(APITestCase):
    def setUp(self):
        self.user, _, _ = make_kek_user(base_currency='CHF')
        self.broker = Broker.objects.create(code='viac', name='VIAC', integration_type='rest')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Acct', currency='CHF',
        )
        self.client.force_authenticate(user=self.user)

    def test_create_manual_snapshot(self):
        resp = self.client.post(
            reverse('snapshot_list', args=[self.account.pk]),
            {'balance': '1000.00', 'currency': 'CHF', 'snapshot_date': '2026-06-01'},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        snap = AccountSnapshot.objects.get(account=self.account)
        self.assertEqual(snap.snapshot_source, 'manual')

    def test_duplicate_snapshot_rejected(self):
        payload = {'balance': '1000.00', 'currency': 'CHF', 'snapshot_date': '2026-06-01'}
        url = reverse('snapshot_list', args=[self.account.pk])
        self.assertEqual(self.client.post(url, payload, format='json').status_code, 201)
        dup = self.client.post(url, payload, format='json')
        self.assertEqual(dup.status_code, 400)

    def test_snapshot_converts_to_base_currency(self):
        ExchangeRate.objects.create(
            from_currency='USD', to_currency='CHF', rate=Decimal('0.9'),
            rate_date=date(2026, 6, 1),
        )
        resp = self.client.post(
            reverse('snapshot_list', args=[self.account.pk]),
            {'balance': '100.00', 'currency': 'USD', 'snapshot_date': '2026-06-01'},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        snap = AccountSnapshot.objects.get(account=self.account)
        self.assertEqual(snap.balance_base_currency, Decimal('90.0000'))
        self.assertEqual(snap.base_currency, 'CHF')


class WealthSummaryTests(APITestCase):
    def setUp(self):
        self.user, _, _ = make_kek_user(base_currency='CHF')
        self.broker = Broker.objects.create(code='viac', name='VIAC', integration_type='rest')
        self.client.force_authenticate(user=self.user)

    def test_summary_totals_latest_snapshots(self):
        for name, bal in [('A', '1000'), ('B', '500')]:
            account = FinancialAccount.objects.create(
                user=self.user, broker=self.broker, name=name, currency='CHF',
            )
            AccountSnapshot.objects.create(
                account=account, balance=Decimal(bal), currency='CHF',
                snapshot_date=date(2026, 6, 1),
            )
        resp = self.client.get(reverse('wealth_summary'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['total_wealth'], 1500.0)
        self.assertEqual(resp.data['base_currency'], 'CHF')
        self.assertEqual(resp.data['account_count'], 2)


class AccountSyncEndpointTests(APITestCase):
    def setUp(self):
        self.user, self.kek, self.user_key = make_kek_user(base_currency='CHF')
        self.broker = Broker.objects.create(code='viac', name='VIAC', integration_type='rest')
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_X_KEK=self.kek)

    def _account(self, **kwargs):
        from core.user_encryption import encrypt_credentials
        defaults = dict(
            user=self.user, broker=self.broker, name='VIAC', currency='CHF',
            account_identifier='ID1',
            encrypted_credentials=encrypt_credentials({'u': 'x'}, self.user_key),
        )
        defaults.update(kwargs)
        return FinancialAccount.objects.create(**defaults)

    def test_sync_manual_account_rejected(self):
        account = self._account(is_manual=True, encrypted_credentials=None)
        resp = self.client.post(reverse('account_sync', args=[account.pk]))
        self.assertEqual(resp.status_code, 400)

    def test_sync_without_credentials_rejected(self):
        account = self._account(encrypted_credentials=None)
        resp = self.client.post(reverse('account_sync', args=[account.pk]))
        self.assertEqual(resp.status_code, 400)

    def test_sync_enqueues_task(self):
        account = self._account()
        from portfolio.sync_queue import sync_queue
        with patch.object(sync_queue, 'has_pending_task', return_value=None), \
                patch.object(sync_queue, 'enqueue', return_value='task-xyz') as m_enqueue:
            resp = self.client.post(reverse('account_sync', args=[account.pk]))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['task_id'], 'task-xyz')
        # Credentials were decrypted on the request thread and handed to the queue.
        self.assertEqual(m_enqueue.call_args.kwargs['credentials'], {'u': 'x'})

    def test_sync_other_user_account_404(self):
        other, _, _ = make_kek_user(username='bob')
        account = FinancialAccount.objects.create(
            user=other, broker=self.broker, name='Theirs', account_identifier='X',
        )
        resp = self.client.post(reverse('account_sync', args=[account.pk]))
        self.assertEqual(resp.status_code, 404)


class SyncWorkerLogicTests(TestCase):
    """Exercise the sync worker body directly with a mocked broker integration."""

    def setUp(self):
        self.user, _, _ = make_kek_user(base_currency='CHF')
        self.broker = Broker.objects.create(code='viac', name='VIAC', integration_type='rest')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='VIAC', currency='CHF',
            account_identifier='ID1',
        )

    def _fake_integration(self, auth=True, balance=None):
        integ = MagicMock()
        integ.authenticate.return_value = AuthResult(success=auth) if auth else \
            AuthResult(success=False, error_message='bad creds')
        integ.get_balance.return_value = balance
        integ.supports_historical_data.return_value = False
        return integ

    @patch('django.db.connections.close_all')
    @patch('brokers.integrations.get_broker_integration')
    def test_sync_creates_snapshot(self, m_factory, _m_close):
        from portfolio.views import _sync_single_account
        m_factory.return_value = self._fake_integration(balance=BalanceInfo(
            balance=Decimal('1234.00'), currency='CHF', balance_date=date(2026, 6, 1),
            raw_data={'source': 'test'},
        ))
        result = _sync_single_account(
            account_id=self.account.id, credentials={'u': 'x'}, base_currency='CHF',
        )
        self.assertEqual(result['status'], 'success')
        snap = AccountSnapshot.objects.get(account=self.account)
        self.assertEqual(snap.balance, Decimal('1234.00'))
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, 'active')
        self.assertIsNotNone(self.account.last_sync_at)

    @patch('django.db.connections.close_all')
    @patch('brokers.integrations.get_broker_integration')
    def test_sync_auth_failure_marks_error(self, m_factory, _m_close):
        from portfolio.views import _sync_single_account
        m_factory.return_value = self._fake_integration(auth=False)
        result = _sync_single_account(
            account_id=self.account.id, credentials={'u': 'x'}, base_currency='CHF',
        )
        self.assertEqual(result['status'], 'error')
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, 'error')
        self.assertEqual(self.account.last_sync_error, 'bad creds')

    @patch('django.db.connections.close_all')
    @patch('brokers.integrations.get_broker_integration')
    def test_sync_no_new_data_is_noop_not_error(self, m_factory, _m_close):
        # A broker reporting "no new data" (e.g. EBICS 090005) must be a benign no-op:
        # keep the account active with its prior snapshot, record no error, no new snapshot.
        from brokers.integrations.base import NoNewDataError
        from portfolio.views import _sync_single_account
        AccountSnapshot.objects.create(
            account=self.account, balance=Decimal('50'), currency='CHF',
            snapshot_date=date(2026, 5, 1),
        )
        integ = self._fake_integration()
        integ.get_balance.side_effect = NoNewDataError('nothing new')
        m_factory.return_value = integ

        result = _sync_single_account(
            account_id=self.account.id, credentials={'u': 'x'}, base_currency='CHF',
        )
        self.assertEqual(result['status'], 'success')
        self.assertIsNone(result['snapshot'])
        # No new snapshot created; the prior one is preserved.
        self.assertEqual(AccountSnapshot.objects.filter(account=self.account).count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.status, 'active')
        self.assertEqual(self.account.last_sync_error, '')
        self.assertIsNotNone(self.account.last_sync_at)

    @patch('django.db.connections.close_all')
    @patch('brokers.integrations.get_broker_integration')
    def test_sync_all_backfills_every_delivered_day(self, m_factory, _m_close):
        # A broker that delivers multiple days (e.g. an EBICS camt.053 backlog) must
        # snapshot ALL of them on sync-all, not just the latest.
        from portfolio.views import _sync_all_accounts
        integ = self._fake_integration(balance=BalanceInfo(
            balance=Decimal('300'), currency='CHF', balance_date=date(2026, 6, 3), raw_data=None,
        ))
        integ.supports_historical_data.return_value = True
        integ.historical_data_requires_extra_request.return_value = False
        integ.get_historical_balances.return_value = [
            BalanceInfo(balance=Decimal('100'), currency='CHF', balance_date=date(2026, 6, 1), raw_data=None),
            BalanceInfo(balance=Decimal('200'), currency='CHF', balance_date=date(2026, 6, 2), raw_data=None),
            BalanceInfo(balance=Decimal('300'), currency='CHF', balance_date=date(2026, 6, 3), raw_data=None),
        ]
        m_factory.return_value = integ
        _sync_all_accounts(
            account_creds=[(self.account.id, {'u': 'x'})], base_currency='CHF',
        )
        dates = set(
            AccountSnapshot.objects.filter(account=self.account)
            .values_list('snapshot_date', flat=True)
        )
        self.assertEqual(dates, {date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)})

    @patch('django.db.connections.close_all')
    @patch('brokers.integrations.get_broker_integration')
    def test_sync_converts_to_base_currency(self, m_factory, _m_close):
        from portfolio.views import _sync_single_account
        ExchangeRate.objects.create(
            from_currency='USD', to_currency='CHF', rate=Decimal('0.9'),
            rate_date=date(2026, 6, 1),
        )
        m_factory.return_value = self._fake_integration(balance=BalanceInfo(
            balance=Decimal('100.00'), currency='USD', balance_date=date(2026, 6, 1),
            raw_data=None,
        ))
        _sync_single_account(
            account_id=self.account.id, credentials={'u': 'x'}, base_currency='CHF',
        )
        snap = AccountSnapshot.objects.get(account=self.account)
        self.assertEqual(snap.balance_base_currency, Decimal('90.00'))
        self.assertEqual(snap.exchange_rate_used, Decimal('0.9'))


class ExchangeRateModelTests(TestCase):
    def test_same_currency_returns_one(self):
        self.assertEqual(ExchangeRate.get_rate('CHF', 'CHF', date(2026, 6, 1)), Decimal('1.0'))

    def test_exact_date_match(self):
        ExchangeRate.objects.create(
            from_currency='USD', to_currency='CHF', rate=Decimal('0.9'),
            rate_date=date(2026, 6, 1),
        )
        self.assertEqual(
            ExchangeRate.get_rate('USD', 'CHF', date(2026, 6, 1)), Decimal('0.9'),
        )

    def test_falls_back_to_earlier_rate(self):
        ExchangeRate.objects.create(
            from_currency='USD', to_currency='CHF', rate=Decimal('0.85'),
            rate_date=date(2026, 5, 1),
        )
        self.assertEqual(
            ExchangeRate.get_rate('USD', 'CHF', date(2026, 6, 15)), Decimal('0.85'),
        )

    def test_inverse_rate(self):
        ExchangeRate.objects.create(
            from_currency='CHF', to_currency='USD', rate=Decimal('2'),
            rate_date=date(2026, 6, 1),
        )
        self.assertEqual(
            ExchangeRate.get_rate('USD', 'CHF', date(2026, 6, 1)), Decimal('0.5'),
        )

    def test_missing_rate_returns_none(self):
        self.assertIsNone(ExchangeRate.get_rate('JPY', 'CHF', date(2026, 6, 1)))


class SnapshotWriterTests(TestCase):
    """upsert_daily_snapshot: gap-fill by default, overwrite when the source is authoritative."""

    def setUp(self):
        self.user, _, _ = make_kek_user(base_currency='CHF')
        self.broker = Broker.objects.create(code='zkb', name='ZKB', integration_type='ebics')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='A', currency='CHF',
        )

    def _bal(self, amount, d, currency='CHF'):
        return BalanceInfo(
            balance=Decimal(amount), currency=currency, balance_date=d, raw_data={'s': 1},
        )

    def test_creates_when_absent(self):
        from portfolio.snapshot_writer import upsert_daily_snapshot
        snap, changed = upsert_daily_snapshot(self.account, self._bal('100', date(2026, 6, 1)), 'CHF')
        self.assertTrue(changed)
        self.assertEqual(snap.balance, Decimal('100'))

    def test_gap_fill_skips_existing(self):
        from portfolio.snapshot_writer import upsert_daily_snapshot
        AccountSnapshot.objects.create(
            account=self.account, balance=Decimal('50'), currency='CHF',
            snapshot_date=date(2026, 6, 1), snapshot_source='manual',
        )
        snap, changed = upsert_daily_snapshot(self.account, self._bal('100', date(2026, 6, 1)), 'CHF')
        self.assertFalse(changed)
        self.assertEqual(snap.balance, Decimal('50'))  # left untouched
        self.assertEqual(AccountSnapshot.objects.filter(account=self.account).count(), 1)

    def test_overwrite_replaces_in_place(self):
        from portfolio.snapshot_writer import upsert_daily_snapshot
        AccountSnapshot.objects.create(
            account=self.account, balance=Decimal('50'), currency='CHF',
            snapshot_date=date(2026, 6, 1), snapshot_source='manual',
        )
        snap, changed = upsert_daily_snapshot(
            self.account, self._bal('100', date(2026, 6, 1)), 'CHF', overwrite=True,
        )
        self.assertTrue(changed)
        snap.refresh_from_db()
        self.assertEqual(snap.balance, Decimal('100'))
        self.assertEqual(snap.snapshot_source, 'auto')
        self.assertEqual(AccountSnapshot.objects.filter(account=self.account).count(), 1)  # no dup

    def test_currency_conversion_applied(self):
        from portfolio.snapshot_writer import upsert_daily_snapshot
        ExchangeRate.objects.create(
            from_currency='USD', to_currency='CHF', rate=Decimal('0.9'), rate_date=date(2026, 6, 1),
        )
        snap, _ = upsert_daily_snapshot(
            self.account, self._bal('100', date(2026, 6, 1), 'USD'), 'CHF',
        )
        self.assertEqual(snap.balance_base_currency, Decimal('90.0'))
        self.assertEqual(snap.exchange_rate_used, Decimal('0.9'))


class EbicsAccountFallbackTests(APITestCase):
    """Until the bank activates the EBICS key exchange (credential state != 'active'),
    an EBICS-linked account must behave like a manual one: no auto-sync, surfaced in
    the app's manual "needs a snapshot" prompt."""

    def setUp(self):
        from brokers.models import EbicsCredential
        self.user, self.kek, self.user_key = make_kek_user(base_currency='CHF')
        self.broker = Broker.objects.create(
            code='zkb', name='ZKB', integration_type='ebics', supports_auto_sync=True,
        )
        self.cred = EbicsCredential.objects.create(
            user=self.user, broker=self.broker, label='ZKB',
            host_id='ZKBKCHZZ', partner_id='PARTNER1', subscriber_id='SUB1',
            url='https://ebicsweb.zkb.ch/ebicsweb', state='new',
        )
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='ZKB Giro', currency='CHF',
            account_identifier='CH00', ebics_credential=self.cred,
            sync_enabled=True, is_manual=False,
        )
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_X_KEK=self.kek)

    def _activate(self):
        self.cred.state = 'active'
        self.cred.save(update_fields=['state'])

    # --- serializer: effective sync_enabled drives the app's manual-vs-auto UX ---
    def test_serializer_reports_sync_disabled_while_credential_pending(self):
        for state in ('new', 'keys_sent'):
            self.cred.state = state
            self.cred.save(update_fields=['state'])
            data = FinancialAccountSerializer(self.account).data
            self.assertFalse(
                data['sync_enabled'],
                f'sync should be effectively off while credential is {state}',
            )
            self.assertEqual(data['ebics_credential']['state'], state)

    def test_serializer_reports_real_sync_enabled_when_active(self):
        self._activate()
        data = FinancialAccountSerializer(self.account).data
        self.assertTrue(data['sync_enabled'])

    def test_non_ebics_account_sync_flag_untouched(self):
        acct = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Plain',
            currency='CHF', sync_enabled=True,
        )
        data = FinancialAccountSerializer(acct).data
        self.assertTrue(data['sync_enabled'])
        self.assertIsNone(data['ebics_credential'])

    # --- single-account sync guard ---
    def test_single_sync_rejected_while_pending(self):
        resp = self.client.post(reverse('account_sync', args=[self.account.pk]))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('not active', resp.data['error'].lower())

    def test_single_sync_allowed_when_active(self):
        self._activate()
        from portfolio.sync_queue import sync_queue
        from portfolio.views import AccountSyncView
        with patch.object(AccountSyncView, 'decrypt_sync_credentials', return_value={'k': 1}), \
                patch.object(sync_queue, 'has_pending_task', return_value=None), \
                patch.object(sync_queue, 'enqueue', return_value='t1') as m_enqueue:
            resp = self.client.post(reverse('account_sync', args=[self.account.pk]))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(m_enqueue.called)

    # --- sync-all filter: pending EBICS accounts are skipped, not errored ---
    def test_sync_all_excludes_pending_ebics(self):
        resp = self.client.post(reverse('sync_all_accounts'))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['synced_count'], 0)
        self.assertIn('No accounts to sync', resp.data['message'])

    def test_sync_all_includes_active_ebics(self):
        self._activate()
        from portfolio.sync_queue import sync_queue
        from portfolio.views import SyncAllAccountsView
        with patch.object(SyncAllAccountsView, 'decrypt_sync_credentials', return_value={'k': 1}), \
                patch.object(sync_queue, 'has_pending_task', return_value=None), \
                patch.object(sync_queue, 'enqueue', return_value='t2') as m_enqueue:
            resp = self.client.post(reverse('sync_all_accounts'))
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(m_enqueue.called)
        account_ids = [aid for aid, _ in m_enqueue.call_args.kwargs['account_creds']]
        self.assertEqual(account_ids, [self.account.id])


class TransactionImporterTests(TestCase):
    """Dedup and window logic of the shared transaction importer."""

    def setUp(self):
        from brokers.integrations.base import TransactionInfo
        self.user, _, _ = make_kek_user()
        self.broker = Broker.objects.create(code='zkb', name='ZKB', integration_type='ebics')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Giro', currency='CHF',
            account_identifier='CH93',
        )
        self.TransactionInfo = TransactionInfo

    def _fake_integration(self, infos):
        calls = []

        class Fake:
            def supports_transactions(self):
                return True

            def get_transactions(self, identifier, start, end):
                calls.append((identifier, start, end))
                return infos

        fake = Fake()
        fake.calls = calls
        return fake

    def _info(self, **overrides):
        from decimal import Decimal as D
        defaults = dict(
            booking_date=date(2026, 8, 1), amount=D('-12.50'), currency='CHF',
            counterparty='Coop', description='Lunch',
        )
        defaults.update(overrides)
        return self.TransactionInfo(**defaults)

    def test_import_is_idempotent(self):
        from portfolio.models import Transaction
        from portfolio.transaction_importer import import_account_transactions
        infos = [self._info(external_id='R1'), self._info(external_id='R2')]
        integration = self._fake_integration(infos)
        self.assertEqual(import_account_transactions(self.account, integration), 2)
        self.assertEqual(import_account_transactions(self.account, integration), 0)
        self.assertEqual(Transaction.objects.filter(account=self.account).count(), 2)
        self.assertEqual(
            set(Transaction.objects.values_list('dedup_key', flat=True)),
            {'ref:R1', 'ref:R2'},
        )

    def test_same_entry_from_two_sources_is_not_duplicated(self):
        from decimal import Decimal as D
        from portfolio.models import Transaction
        from portfolio.transaction_importer import store_transactions
        # EBICS wording, no bank reference -> content hash.
        store_transactions(self.account, [self._info(
            amount=D('-30'), description='Debit TWINT: ALTERMATT, MANUEL',
        )], source='camt053')
        # The account's CSV export of the same payment: German wording, so the
        # content hash differs and the keys can never match.
        created = store_transactions(self.account, [self._info(
            amount=D('-30'), description='Belastung TWINT: ALTERMATT, MANUEL',
        )], source='csv')
        self.assertEqual(created, 0)
        self.assertEqual(Transaction.objects.filter(account=self.account).count(), 1)

    def test_genuinely_repeated_payment_survives_a_second_source(self):
        from decimal import Decimal as D
        from portfolio.models import Transaction
        from portfolio.transaction_importer import store_transactions
        # Two identical payments on one day, as the sync saw them.
        store_transactions(self.account, [
            self._info(amount=D('-30'), description='Debit TWINT: A'),
            self._info(amount=D('-30'), description='Debit TWINT: A'),
        ], source='camt053')
        # The CSV reports the same two — neither is new, none is lost.
        created = store_transactions(self.account, [
            self._info(amount=D('-30'), description='Belastung TWINT: A'),
            self._info(amount=D('-30'), description='Belastung TWINT: A'),
        ], source='csv')
        self.assertEqual(created, 0)
        self.assertEqual(Transaction.objects.filter(account=self.account).count(), 2)

    def test_third_payment_only_in_the_csv_is_still_imported(self):
        from decimal import Decimal as D
        from portfolio.models import Transaction
        from portfolio.transaction_importer import store_transactions
        store_transactions(self.account, [
            self._info(amount=D('-30'), description='Debit TWINT: A'),
        ], source='camt053')
        # The CSV covers the same day but holds one more such payment.
        created = store_transactions(self.account, [
            self._info(amount=D('-30'), description='Belastung TWINT: A'),
            self._info(amount=D('-30'), description='Belastung TWINT: A'),
        ], source='csv')
        self.assertEqual(created, 1)
        self.assertEqual(Transaction.objects.filter(account=self.account).count(), 2)

    def test_dedupe_command_removes_existing_cross_source_duplicates(self):
        from decimal import Decimal as D
        from io import StringIO
        from django.core.management import call_command
        from portfolio.models import Transaction
        common = dict(
            account=self.account, booking_date=date(2026, 8, 21),
            amount=D('-30'), currency='CHF',
        )
        Transaction.objects.create(
            **common, description='Debit TWINT: ALTERMATT',
            source='camt053', dedup_key='ref:ZKB-1',
        )
        Transaction.objects.create(
            **common, description='Belastung TWINT: ALTERMATT',
            source='csv', dedup_key='h:abc',
        )
        # Dry run reports but keeps both.
        out = StringIO()
        call_command('dedupe_transactions', stdout=out)
        self.assertIn('would delete', out.getvalue())
        self.assertEqual(Transaction.objects.count(), 2)

        call_command('dedupe_transactions', '--apply', stdout=StringIO())
        # The row with the bank reference survives.
        remaining = Transaction.objects.get()
        self.assertEqual(remaining.dedup_key, 'ref:ZKB-1')

    def test_dedupe_command_never_deletes_hand_entered_rows(self):
        from decimal import Decimal as D
        from io import StringIO
        from django.core.management import call_command
        from portfolio.models import Transaction
        common = dict(
            account=self.account, booking_date=date(2026, 8, 21),
            amount=D('-30'), currency='CHF',
        )
        Transaction.objects.create(
            **common, description='Noted by hand', source='manual',
            dedup_key='manual-1',
        )
        Transaction.objects.create(
            **common, description='Debit TWINT', source='camt053',
            dedup_key='ref:ZKB-1',
        )
        call_command('dedupe_transactions', '--apply', stdout=StringIO())
        # The user's own entry cannot be re-imported — it always survives, and
        # it does not count as a feed that also saw the payment.
        self.assertEqual(Transaction.objects.count(), 2)

    def test_dedupe_command_keeps_repeats_from_a_single_source(self):
        from decimal import Decimal as D
        from io import StringIO
        from django.core.management import call_command
        from portfolio.models import Transaction
        for i in range(2):
            Transaction.objects.create(
                account=self.account, booking_date=date(2026, 8, 21),
                amount=D('-30'), currency='CHF', description='Coffee',
                source='camt053', dedup_key=f'h:same-{i}',
            )
        call_command('dedupe_transactions', '--apply', stdout=StringIO())
        self.assertEqual(Transaction.objects.count(), 2)

    def test_identical_entries_without_reference_both_survive(self):
        from portfolio.models import Transaction
        from portfolio.transaction_importer import import_account_transactions
        # Two identical coffee purchases on the same day, no bank reference.
        infos = [self._info(), self._info()]
        integration = self._fake_integration(infos)
        self.assertEqual(import_account_transactions(self.account, integration), 2)
        # Redelivery of the same day maps onto the same ordinal-based keys.
        self.assertEqual(import_account_transactions(self.account, integration), 0)
        self.assertEqual(Transaction.objects.filter(account=self.account).count(), 2)

    def test_source_mapped_from_integration_type(self):
        from portfolio.models import Transaction
        from portfolio.transaction_importer import import_account_transactions
        import_account_transactions(self.account, self._fake_integration([self._info()]))
        self.assertEqual(Transaction.objects.get(account=self.account).source, 'camt053')

    def test_window_starts_before_latest_imported_transaction(self):
        from datetime import timedelta
        from portfolio.transaction_importer import (
            OVERLAP_DAYS, import_account_transactions,
        )
        integration = self._fake_integration([self._info(external_id='R1')])
        import_account_transactions(self.account, integration)
        import_account_transactions(self.account, integration)
        # Second run: start = newest imported booking_date - overlap.
        _, start, _ = integration.calls[1]
        self.assertEqual(start, date(2026, 8, 1) - timedelta(days=OVERLAP_DAYS))

    def test_unsupported_integration_is_noop(self):
        from portfolio.transaction_importer import import_account_transactions

        class NoTx:
            def supports_transactions(self):
                return False

        self.assertEqual(import_account_transactions(self.account, NoTx()), 0)


class TransactionEndpointTests(APITestCase):
    def setUp(self):
        from portfolio.models import Transaction
        self.user, _, _ = make_kek_user()
        self.broker = Broker.objects.create(code='zkb', name='ZKB', integration_type='ebics')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Giro', currency='CHF',
        )
        self.imported = Transaction.objects.create(
            account=self.account, booking_date=date(2026, 8, 1),
            amount=Decimal('-25.50'), currency='CHF', counterparty='Migros',
            source='camt053', dedup_key='ref:R1',
        )
        self.client.force_authenticate(user=self.user)

    def _list_url(self):
        return reverse('transaction_list', kwargs={'account_id': self.account.id})

    def test_list_transactions(self):
        resp = self.client.get(self._list_url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['results'][0]['counterparty'], 'Migros')

    def test_list_filters_by_date_range(self):
        resp = self.client.get(self._list_url(), {'start': '2026-08-02'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['results'], [])

    def test_global_list_spans_accounts_and_filters(self):
        from portfolio.models import Transaction, TransactionCategory
        other_account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Zweitkonto', currency='CHF',
        )
        category = TransactionCategory.objects.create(user=self.user, name='Food')
        Transaction.objects.create(
            account=other_account, booking_date=date(2026, 8, 10),
            amount=Decimal('-5'), currency='CHF', counterparty='Coop',
            source='camt053', dedup_key='ref:R2', category=category,
        )
        url = reverse('transaction_list_all')

        # All accounts, newest first.
        resp = self.client.get(url)
        self.assertEqual(resp.data['count'], 2)
        self.assertEqual(resp.data['results'][0]['counterparty'], 'Coop')

        # Restricted to one account.
        resp = self.client.get(url, {'account': self.account.id})
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['counterparty'], 'Migros')

        # Only uncategorized: the categorized Coop entry disappears.
        resp = self.client.get(url, {'uncategorized': '1'})
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['counterparty'], 'Migros')

        # Filtered to one category.
        resp = self.client.get(url, {'category': category.id})
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['counterparty'], 'Coop')

        # Transfers only.
        Transaction.objects.create(
            account=other_account, booking_date=date(2026, 8, 11),
            amount=Decimal('-99'), currency='CHF', counterparty='Broker',
            source='camt053', dedup_key='ref:R3', is_transfer=True,
        )
        resp = self.client.get(url, {'category': 'transfer'})
        self.assertEqual(resp.data['count'], 1)
        self.assertEqual(resp.data['results'][0]['counterparty'], 'Broker')

    def test_category_filter_does_not_leak_other_users_categories(self):
        from portfolio.models import TransactionCategory
        other, _, _ = make_kek_user(username='mallory')
        foreign = TransactionCategory.objects.create(user=other, name='Food')
        resp = self.client.get(
            reverse('transaction_list_all'), {'category': foreign.id})
        self.assertEqual(resp.data['count'], 0)

    def test_global_list_is_scoped_to_the_user(self):
        other, _, _ = make_kek_user(username='eve')
        self.client.force_authenticate(user=other)
        resp = self.client.get(reverse('transaction_list_all'))
        self.assertEqual(resp.data['count'], 0)

    def test_other_users_account_is_empty(self):
        other, _, _ = make_kek_user(username='bob')
        self.client.force_authenticate(user=other)
        resp = self.client.get(self._list_url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['results'], [])

    def test_create_manual_transaction_defaults_currency(self):
        from portfolio.models import Transaction
        resp = self.client.post(self._list_url(), {
            'booking_date': '2026-08-05', 'amount': '-9.90', 'description': 'Kiosk',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        tx = Transaction.objects.get(pk=resp.data['id'])
        self.assertEqual(tx.source, 'manual')
        self.assertEqual(tx.currency, 'CHF')
        self.assertTrue(tx.dedup_key.startswith('manual:'))

    def test_manual_transaction_can_be_deleted(self):
        resp = self.client.post(self._list_url(), {
            'booking_date': '2026-08-05', 'amount': '-1.00',
        }, format='json')
        detail = reverse('transaction_detail', kwargs={'pk': resp.data['id']})
        self.assertEqual(self.client.delete(detail).status_code, 204)

    def test_imported_transaction_financials_immutable_and_undeletable(self):
        # Classification PATCHes are allowed on imported rows; the bank's own
        # fields are read-only (silently ignored), and deletion is rejected.
        detail = reverse('transaction_detail', kwargs={'pk': self.imported.id})
        resp = self.client.patch(detail, {'description': 'x'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.imported.refresh_from_db()
        self.assertEqual(self.imported.description, '')
        self.assertEqual(self.client.delete(detail).status_code, 400)


class ClassificationTests(TestCase):
    """Category rules and transfer detection."""

    def setUp(self):
        from portfolio.models import CategoryRule, TransactionCategory
        self.user, _, _ = make_kek_user()
        self.broker = Broker.objects.create(code='zkb', name='ZKB', integration_type='ebics')
        self.checking = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Giro', currency='CHF',
            account_identifier='CH-GIRO',
        )
        self.savings = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Sparen', currency='CHF',
            account_identifier='CH-SPAR',
        )
        self.groceries = TransactionCategory.objects.create(user=self.user, name='Groceries')
        self.insurance = TransactionCategory.objects.create(user=self.user, name='Insurance')
        CategoryRule.objects.create(user=self.user, match_text='migros', category=self.groceries)
        CategoryRule.objects.create(
            user=self.user, match_text='axa', category=self.insurance, spread_months=12,
        )

    def _tx(self, account=None, **kwargs):
        from portfolio.models import Transaction
        defaults = dict(
            account=account or self.checking, booking_date=date(2026, 8, 1),
            amount=Decimal('-50'), currency='CHF', source='camt053',
        )
        defaults.update(kwargs)
        defaults.setdefault('dedup_key', f"t-{len(Transaction.objects.all())}-{kwargs}")
        return Transaction.objects.create(**defaults)

    def test_rules_match_case_insensitive_and_set_spread(self):
        from portfolio.classification import apply_rules
        grocery_tx = self._tx(counterparty='MIGROS Zuerich')
        insurance_tx = self._tx(description='AXA Jahresrechnung')
        self.assertEqual(apply_rules(self.user), 2)
        grocery_tx.refresh_from_db()
        insurance_tx.refresh_from_db()
        self.assertEqual(grocery_tx.category, self.groceries)
        self.assertEqual(grocery_tx.spread_months, 1)
        self.assertEqual(insurance_tx.category, self.insurance)
        self.assertEqual(insurance_tx.spread_months, 12)

    def test_rules_respect_manual_category(self):
        from portfolio.classification import apply_rules
        tx = self._tx(counterparty='Migros', category=self.insurance, category_manual=True)
        # Also uncategorized-but-manually-cleared rows stay untouched.
        cleared = self._tx(counterparty='Migros', category=None, category_manual=True)
        self.assertEqual(apply_rules(self.user), 0)
        tx.refresh_from_db()
        self.assertEqual(tx.category, self.insurance)
        cleared.refresh_from_db()
        self.assertIsNone(cleared.category)

    def test_transfer_pairing_across_accounts(self):
        from portfolio.classification import detect_transfers
        out_tx = self._tx(amount=Decimal('-500'), booking_date=date(2026, 8, 26))
        in_tx = self._tx(
            account=self.savings, amount=Decimal('500'), booking_date=date(2026, 8, 27),
        )
        unrelated = self._tx(amount=Decimal('-77'), counterparty='Shop')
        self.assertEqual(detect_transfers(self.user), 2)
        out_tx.refresh_from_db(); in_tx.refresh_from_db(); unrelated.refresh_from_db()
        self.assertTrue(out_tx.is_transfer)
        self.assertEqual(out_tx.transfer_peer_id, in_tx.id)
        self.assertTrue(in_tx.is_transfer)
        self.assertFalse(unrelated.is_transfer)

    def test_transfer_by_own_iban(self):
        from portfolio.classification import detect_transfers
        tx = self._tx(amount=Decimal('-300'), counterparty_account='CH-SPAR')
        self.assertEqual(detect_transfers(self.user), 1)
        tx.refresh_from_db()
        self.assertTrue(tx.is_transfer)

    def test_transfer_detection_respects_manual_flag(self):
        from portfolio.classification import detect_transfers
        self._tx(amount=Decimal('-500'), transfer_manual=True)
        self._tx(account=self.savings, amount=Decimal('500'))
        self.assertEqual(detect_transfers(self.user), 0)


class SpendingReportTests(TestCase):
    def setUp(self):
        from portfolio.models import TransactionCategory
        self.user, _, _ = make_kek_user()
        self.broker = Broker.objects.create(code='zkb', name='ZKB', integration_type='ebics')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Giro', currency='EUR',
        )
        self.user.profile.base_currency = 'EUR'
        self.user.profile.save()
        self.groceries = TransactionCategory.objects.create(user=self.user, name='Groceries')

    def _tx(self, **kwargs):
        from portfolio.models import Transaction
        defaults = dict(
            account=self.account, booking_date=date.today().replace(day=1),
            amount=Decimal('-100'), currency='EUR', source='camt053',
        )
        defaults.update(kwargs)
        defaults.setdefault('dedup_key', f"t-{Transaction.objects.count()}")
        return Transaction.objects.create(**defaults)

    def test_actual_vs_normalized_amortization(self):
        from portfolio.spending import monthly_spending
        self._tx(amount=Decimal('-1200'), spread_months=12, category=self.groceries)
        self._tx(amount=Decimal('1000'))

        actual = monthly_spending(self.user, months=1, mode='actual')
        self.assertEqual(actual['months'][-1]['expenses'], 1200.0)
        self.assertEqual(actual['months'][-1]['income'], 1000.0)

        normalized = monthly_spending(self.user, months=1, mode='normalized')
        self.assertEqual(normalized['months'][-1]['expenses'], 100.0)
        self.assertEqual(normalized['months'][-1]['by_category'], {'Groceries': 100.0})

    def test_transfers_are_excluded(self):
        from portfolio.spending import monthly_spending
        self._tx(amount=Decimal('-500'), is_transfer=True)
        self._tx(amount=Decimal('-40'))
        report = monthly_spending(self.user, months=1, mode='actual')
        self.assertEqual(report['months'][-1]['expenses'], 40.0)

    def test_uncategorized_bucket(self):
        from portfolio.spending import monthly_spending
        self._tx(amount=Decimal('-25'))
        report = monthly_spending(self.user, months=1, mode='actual')
        self.assertEqual(report['months'][-1]['by_category'], {'Uncategorized': 25.0})

    def test_foreign_currency_uses_most_recent_stored_rate(self):
        from portfolio.spending import monthly_spending
        booking = date.today().replace(day=1)
        # No rate on the booking date itself — the report must fall back to the
        # most recent earlier rate, without asking the rate API.
        ExchangeRate.objects.create(
            from_currency='CHF', to_currency='EUR',
            rate_date=booking - timedelta(days=3), rate=Decimal('1.05'),
        )
        self._tx(amount=Decimal('-100'), currency='CHF', booking_date=booking)
        report = monthly_spending(self.user, months=1, mode='actual')
        self.assertEqual(report['months'][-1]['expenses'], 105.0)

    def test_foreign_currency_inverse_pair(self):
        from portfolio.spending import monthly_spending
        # Only the opposite direction is stored (EUR->CHF); the report inverts
        # it. The rate is also dated today while the booking may be older —
        # bookings before the earliest stored rate clamp to that rate.
        ExchangeRate.objects.create(
            from_currency='EUR', to_currency='CHF',
            rate_date=date.today(), rate=Decimal('2'),
        )
        self._tx(amount=Decimal('-100'), currency='CHF',
                 booking_date=date.today().replace(day=1))
        report = monthly_spending(self.user, months=1, mode='actual')
        self.assertEqual(report['months'][-1]['expenses'], 50.0)

    def test_rate_lookup_is_bulk_not_per_transaction(self):
        from portfolio.spending import monthly_spending
        booking = date.today().replace(day=1)
        ExchangeRate.objects.create(
            from_currency='CHF', to_currency='EUR',
            rate_date=booking, rate=Decimal('1'),
        )
        for i in range(8):
            self._tx(amount=Decimal('-10'), currency='CHF', booking_date=booking)
        # transactions + distinct currencies + one rate-series fetch. Per-date
        # lookups would scale with the transaction count.
        with self.assertNumQueries(3):
            monthly_spending(self.user, months=1, mode='actual')


class ClassificationApiTests(APITestCase):
    def setUp(self):
        from portfolio.models import Transaction, TransactionCategory
        self.user, _, _ = make_kek_user()
        self.broker = Broker.objects.create(code='zkb', name='ZKB', integration_type='ebics')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Giro', currency='CHF',
        )
        self.category = TransactionCategory.objects.create(user=self.user, name='Groceries')
        self.imported = Transaction.objects.create(
            account=self.account, booking_date=date(2026, 8, 1),
            amount=Decimal('-25.50'), currency='CHF', counterparty='Migros',
            source='camt053', dedup_key='ref:R1',
        )
        self.client.force_authenticate(user=self.user)

    def test_classify_imported_transaction(self):
        detail = reverse('transaction_detail', kwargs={'pk': self.imported.id})
        resp = self.client.patch(detail, {'category': self.category.id}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['category_name'], 'Groceries')
        self.imported.refresh_from_db()
        self.assertTrue(self.imported.category_manual)

    def test_imported_financial_fields_stay_readonly(self):
        detail = reverse('transaction_detail', kwargs={'pk': self.imported.id})
        resp = self.client.patch(detail, {'amount': '-1.00'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.imported.refresh_from_db()
        self.assertEqual(self.imported.amount, Decimal('-25.50'))

    def test_cannot_use_other_users_category(self):
        from portfolio.models import TransactionCategory
        other, _, _ = make_kek_user(username='bob')
        foreign = TransactionCategory.objects.create(user=other, name='Theirs')
        detail = reverse('transaction_detail', kwargs={'pk': self.imported.id})
        resp = self.client.patch(detail, {'category': foreign.id}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_rule_create_applies_retroactively(self):
        resp = self.client.post(reverse('rule_list'), {
            'match_text': 'migros', 'category': self.category.id,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.imported.refresh_from_db()
        self.assertEqual(self.imported.category, self.category)

    def test_monthly_report_endpoint(self):
        resp = self.client.get(reverse('spending_monthly'), {'months': 2, 'mode': 'actual'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['months']), 2)
        self.assertEqual(resp.data['base_currency'], self.user.profile.base_currency)


class AiCategorizationClientTests(TestCase):
    """Gemini client: pricing lookup, model listing, suggestion parsing."""

    def test_price_prefix_matching_prefers_longest(self):
        from portfolio.ai_categorization import price_for_model
        self.assertEqual(price_for_model('gemini-3.5-flash-lite-001'), (0.30, 2.50))
        self.assertEqual(price_for_model('gemini-3.5-flash'), (1.50, 9.00))
        self.assertIsNone(price_for_model('gemini-unknown-model'))

    @patch('portfolio.ai_categorization.requests.get')
    def test_list_models_filters_and_prices(self, m_get):
        from portfolio.ai_categorization import list_models
        m_get.return_value = MagicMock(status_code=200, json=lambda: {'models': [
            {'name': 'models/gemini-3.6-flash', 'displayName': 'Gemini 3.6 Flash',
             'supportedGenerationMethods': ['generateContent']},
            {'name': 'models/gemini-embedding-001', 'displayName': 'Embedding',
             'supportedGenerationMethods': ['embedContent']},
            {'name': 'models/imagen-4', 'displayName': 'Imagen',
             'supportedGenerationMethods': ['generateContent']},
        ]})
        models = list_models('key')
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]['id'], 'gemini-3.6-flash')
        self.assertEqual(models[0]['input_price_per_1m'], 0.75)

    @patch('portfolio.ai_categorization.requests.get')
    def test_list_models_invalid_key_is_friendly(self, m_get):
        from portfolio.ai_categorization import GeminiError, list_models
        m_get.return_value = MagicMock(status_code=400, json=lambda: {
            'error': {'message': 'API key not valid. Please pass a valid API key.'}})
        with self.assertRaises(GeminiError) as ctx:
            list_models('bad')
        self.assertIn('not valid', str(ctx.exception))

    @patch('portfolio.ai_categorization.requests.post')
    def test_suggest_parses_assignments_rules_and_cost(self, m_post):
        import json as jsonlib
        from portfolio.ai_categorization import suggest_categories
        m_post.return_value = MagicMock(status_code=200, json=lambda: {
            'candidates': [{'content': {'parts': [{'text': jsonlib.dumps({
                'assignments': [{'id': 1, 'category': 'Health'}, {'bogus': True}],
                'rules': [{'match_text': 'apotheke', 'category': 'Health'}, {'match_text': ''}],
            })}]}}],
            'usageMetadata': {'promptTokenCount': 1000, 'candidatesTokenCount': 500},
        })
        result = suggest_categories(
            'key', 'gemini-3.6-flash',
            [{'id': 1, 'counterparty': 'Apotheke', 'description': '', 'amount': '-10', 'currency': 'EUR'}],
            ['Groceries'],
        )
        self.assertEqual(result['assignments'], [{'id': 1, 'category': 'Health'}])
        self.assertEqual(result['rules'], [{'match_text': 'apotheke', 'category': 'Health'}])
        self.assertAlmostEqual(result['usage']['estimated_cost_usd'], 0.002625)

    @patch('portfolio.ai_categorization.requests.post')
    def test_suggest_modes_use_separate_prompts(self, m_post):
        import json as jsonlib
        from portfolio.ai_categorization import suggest_categories
        m_post.return_value = MagicMock(status_code=200, json=lambda: {
            'candidates': [{'content': {'parts': [{'text': jsonlib.dumps({
                'assignments': [{'id': 1, 'category': 'Health'}],
                'rules': [{'match_text': 'apotheke', 'category': 'Health'}],
            })}]}}],
            'usageMetadata': {},
        })
        tx = [{'id': 1, 'counterparty': 'Apotheke', 'description': '',
               'amount': '-10', 'currency': 'EUR'}]

        suggest_categories('key', 'gemini-3.6-flash', tx, [], mode='items')
        items_prompt = m_post.call_args.kwargs['json']['contents'][0]['parts'][0]['text']
        self.assertIn('Do NOT propose', items_prompt)

        suggest_categories(
            'key', 'gemini-3.6-flash', tx, [], mode='rules',
            existing_rules=['rewe -> Groceries'],
        )
        rules_prompt = m_post.call_args.kwargs['json']['contents'][0]['parts'][0]['text']
        self.assertIn('rewe -> Groceries', rules_prompt)
        self.assertIn('Do NOT assign', rules_prompt)


class AiEndpointTests(APITestCase):
    def setUp(self):
        from portfolio.models import Transaction
        self.user, self.kek, _ = make_kek_user()
        self.broker = Broker.objects.create(code='zkb', name='ZKB', integration_type='ebics')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Giro', currency='EUR',
        )
        self.tx = Transaction.objects.create(
            account=self.account, booking_date=date(2026, 8, 1),
            amount=Decimal('-19.90'), currency='EUR', counterparty='Apotheke am Markt',
            source='camt053', dedup_key='ref:A1',
        )
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_X_KEK=self.kek)

    def test_config_roundtrip_stores_key_encrypted(self):
        resp = self.client.put(reverse('ai_config'), {
            'api_key': 'AIza-test', 'model': 'gemini-3.6-flash',
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.encrypted_gemini_key)
        self.assertNotIn(b'AIza-test', bytes(self.user.profile.encrypted_gemini_key))
        resp = self.client.get(reverse('ai_config'))
        self.assertTrue(resp.data['configured'])
        self.assertEqual(resp.data['model'], 'gemini-3.6-flash')
        self.assertTrue(resp.data['disclosed_fields'])

    def test_config_requires_kek(self):
        self.client.credentials()  # drop X-KEK
        resp = self.client.put(reverse('ai_config'), {'api_key': 'x'}, format='json')
        self.assertEqual(resp.status_code, 403)

    @patch('portfolio.ai_categorization.suggest_categories')
    def test_suggest_returns_disclosure_and_flags_new_categories(self, m_suggest):
        from portfolio.models import TransactionCategory
        TransactionCategory.objects.create(user=self.user, name='Groceries')
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        m_suggest.return_value = {
            'assignments': [
                {'id': self.tx.id, 'category': 'Health'},
                {'id': 999999, 'category': 'Ignored'},
            ],
            'rules': [{'match_text': 'apotheke', 'category': 'Health'}],
            'usage': {'input_tokens': 10, 'output_tokens': 5, 'estimated_cost_usd': 0.0001},
        }
        resp = self.client.post(reverse('ai_suggest'), {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(len(resp.data['suggestions']), 1)
        self.assertTrue(resp.data['suggestions'][0]['is_new_category'])
        self.assertEqual(resp.data['sent_count'], 1)
        self.assertTrue(resp.data['disclosed_fields'])
        # The suggestion is NOT persisted without confirmation.
        self.tx.refresh_from_db()
        self.assertIsNone(self.tx.category)

    @patch('portfolio.ai_categorization.suggest_categories')
    def test_suggest_rules_mode_passes_existing_rules(self, m_suggest):
        from portfolio.models import CategoryRule, TransactionCategory
        groceries = TransactionCategory.objects.create(user=self.user, name='Groceries')
        rewe = CategoryRule.objects.create(
            user=self.user, match_text='rewe', category=groceries, position=0)
        broker = CategoryRule.objects.create(
            user=self.user, match_text='broker top', is_transfer=True, position=1)
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        m_suggest.return_value = {
            'assignments': [],
            'rules': [{'match_text': 'apotheke', 'category': 'Health'}],
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'estimated_cost_usd': 0.0},
        }
        resp = self.client.post(reverse('ai_suggest'), {'mode': 'rules'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(m_suggest.call_args.kwargs['mode'], 'rules')
        self.assertEqual(
            m_suggest.call_args.kwargs['existing_rules'],
            [f'{rewe.id} | rewe | Groceries',
             f'{broker.id} | broker top | Transfer'],
        )
        self.assertEqual(resp.data['suggestions'], [])
        self.assertEqual(len(resp.data['rules']), 1)

    @patch('portfolio.ai_categorization.suggest_categories')
    def test_suggest_rules_mode_regex_replaces_and_transfer(self, m_suggest):
        from portfolio.models import CategoryRule, TransactionCategory
        subs = TransactionCategory.objects.create(user=self.user, name='Subscriptions')
        yt = CategoryRule.objects.create(
            user=self.user, match_text='youtubepremium', category=subs, position=0)
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        m_suggest.return_value = {
            'assignments': [],
            'rules': [
                # Variant-merging regex proposal, explicitly replacing a rule.
                {'match_text': 'dm[-.]drogerie', 'category': 'Groceries',
                 'is_regex': True, 'replaces': None},
                # Near-duplicate of an existing rule with no replaces set —
                # linked deterministically via normalization.
                {'match_text': 'youtube premium', 'category': 'Subscriptions'},
                # Exact duplicate — dropped as noise.
                {'match_text': 'youtubepremium', 'category': 'Subscriptions'},
                # Broken regex — dropped (it would silently match nothing).
                {'match_text': '(broker', 'category': 'X', 'is_regex': True},
                # Transfer rule: no category.
                {'match_text': 'broker top-up', 'transfer': True},
            ],
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'estimated_cost_usd': 0.0},
        }
        resp = self.client.post(reverse('ai_suggest'), {'mode': 'rules'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        rules = resp.data['rules']
        self.assertEqual(len(rules), 3)
        self.assertTrue(rules[0]['is_regex'])
        self.assertEqual(rules[1]['replaces_rule_id'], yt.id)
        self.assertEqual(rules[1]['replaced_match_text'], 'youtubepremium')
        self.assertTrue(rules[2]['is_transfer'])
        self.assertIsNone(rules[2]['category'])

    @patch('portfolio.ai_categorization.suggest_categories')
    def test_suggest_items_mode_can_flag_transfers(self, m_suggest):
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        m_suggest.return_value = {
            'assignments': [{'id': self.tx.id, 'transfer': True}],
            'rules': [],
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'estimated_cost_usd': 0.0},
        }
        resp = self.client.post(reverse('ai_suggest'), {'mode': 'items'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data['suggestions'][0]['is_transfer'])
        self.assertIsNone(resp.data['suggestions'][0]['category'])

    def test_apply_transfer_assignment_and_rule_replacement(self):
        from portfolio.models import CategoryRule, TransactionCategory
        subs = TransactionCategory.objects.create(user=self.user, name='Subscriptions')
        yt = CategoryRule.objects.create(
            user=self.user, match_text='youtubepremium', category=subs,
            position=0, spread_months=3)
        resp = self.client.post(reverse('ai_apply'), {
            'assignments': [
                {'transaction_id': self.tx.id, 'is_transfer': True},
            ],
            'rules': [
                {'match_text': 'youtube ?premium', 'category': 'Subscriptions',
                 'is_regex': True, 'replaces_rule_id': yt.id},
                {'match_text': 'broker top-up', 'is_transfer': True},
            ],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['assigned'], 1)
        self.assertEqual(resp.data['rules_updated'], 1)
        self.assertEqual(resp.data['rules_created'], 1)
        self.tx.refresh_from_db()
        self.assertTrue(self.tx.is_transfer)
        self.assertTrue(self.tx.transfer_manual)
        yt.refresh_from_db()
        # Updated in place: pattern and regex flag change, position and
        # spread survive, no duplicate rule appears.
        self.assertEqual(yt.match_text, 'youtube ?premium')
        self.assertTrue(yt.is_regex)
        self.assertEqual(yt.position, 0)
        self.assertEqual(yt.spread_months, 3)
        transfer_rule = CategoryRule.objects.get(
            user=self.user, match_text='broker top-up')
        self.assertTrue(transfer_rule.is_transfer)
        self.assertIsNone(transfer_rule.category)

    @patch('portfolio.ai_categorization.suggest_categories')
    def test_suggest_items_mode_sends_no_rules_context(self, m_suggest):
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        m_suggest.return_value = {
            'assignments': [{'id': self.tx.id, 'category': 'Health'}],
            'rules': [],
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'estimated_cost_usd': 0.0},
        }
        resp = self.client.post(reverse('ai_suggest'), {'mode': 'items'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(m_suggest.call_args.kwargs['mode'], 'items')
        self.assertIsNone(m_suggest.call_args.kwargs['existing_rules'])
        self.assertEqual(len(resp.data['suggestions']), 1)
        self.assertEqual(resp.data['rules'], [])

    def test_apply_confirmed_suggestions(self):
        from portfolio.models import CategoryRule, Transaction, TransactionCategory
        other = Transaction.objects.create(
            account=self.account, booking_date=date(2026, 8, 2),
            amount=Decimal('-5.00'), currency='EUR', counterparty='Apotheke Nord',
            source='camt053', dedup_key='ref:A2',
        )
        resp = self.client.post(reverse('ai_apply'), {
            'assignments': [{'transaction_id': self.tx.id, 'category': 'Health'}],
            'rules': [{'match_text': 'apotheke', 'category': 'Health'}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['assigned'], 1)
        self.assertEqual(resp.data['rules_created'], 1)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.category.name, 'Health')
        self.assertTrue(self.tx.category_manual)
        # The created rule immediately categorized the other apotheke transaction.
        other.refresh_from_db()
        self.assertEqual(other.category.name, 'Health')
        self.assertEqual(TransactionCategory.objects.filter(user=self.user).count(), 1)
        self.assertEqual(CategoryRule.objects.filter(user=self.user).count(), 1)

    @patch('portfolio.ai_categorization.relabel_similar')
    def test_relabel_proposes_similar_without_persisting(self, m_relabel):
        from portfolio.models import Transaction, TransactionCategory
        health = TransactionCategory.objects.create(user=self.user, name='Health')
        groceries = TransactionCategory.objects.create(user=self.user, name='Groceries')
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        # The corrected transaction: manually set to Health.
        self.tx.category = health
        self.tx.category_manual = True
        self.tx.save()
        # Mislabeled twin (rule/AI decision, not manual) and an unrelated entry.
        twin = Transaction.objects.create(
            account=self.account, booking_date=date(2026, 7, 15),
            amount=Decimal('-12.30'), currency='EUR', counterparty='Apotheke am Markt',
            category=groceries, source='camt053', dedup_key='ref:A2',
        )
        # No shared word — never reaches the candidate pool.
        Transaction.objects.create(
            account=self.account, booking_date=date(2026, 7, 1),
            amount=Decimal('-50.00'), currency='EUR', counterparty='Coop Pronto',
            category=groceries, source='camt053', dedup_key='ref:A3',
        )
        # Similar but already in the corrected category — nothing to fix.
        Transaction.objects.create(
            account=self.account, booking_date=date(2026, 6, 20),
            amount=Decimal('-8.00'), currency='EUR', counterparty='Apotheke am Markt',
            category=health, source='camt053', dedup_key='ref:A4',
        )
        m_relabel.return_value = {
            'ids': [twin.id, 999999],
            'rules': [{'match_text': 'apotheke', 'category': 'WrongName'}],
            'usage': {'input_tokens': 10, 'output_tokens': 5, 'estimated_cost_usd': 0.0001},
        }
        resp = self.client.post(reverse('ai_relabel'), {
            'transaction_id': self.tx.id,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        # Only the twin we sent; the hallucinated id is dropped.
        self.assertEqual(
            [s['transaction_id'] for s in resp.data['suggestions']], [twin.id])
        self.assertEqual(resp.data['suggestions'][0]['category'], 'Health')
        self.assertEqual(resp.data['suggestions'][0]['current_category'], 'Groceries')
        # The rule is pinned to the corrected category, whatever the model said.
        self.assertEqual(resp.data['rules'][0]['category'], 'Health')
        self.assertTrue(resp.data['disclosed_fields'])
        # Candidates: the twin only — same-category and the corrected tx excluded.
        self.assertEqual(resp.data['sent_count'], 1)
        # Nothing persisted without confirmation.
        twin.refresh_from_db()
        self.assertEqual(twin.category, groceries)

    @patch('portfolio.ai_categorization.relabel_similar')
    def test_relabel_skips_manual_and_uncategorized_candidates(self, m_relabel):
        from portfolio.models import Transaction, TransactionCategory
        health = TransactionCategory.objects.create(user=self.user, name='Health')
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        self.tx.category = health
        self.tx.category_manual = True
        self.tx.save()
        # A manual decision must never be proposed for overwriting…
        Transaction.objects.create(
            account=self.account, booking_date=date(2026, 7, 10),
            amount=Decimal('-9.99'), currency='EUR', counterparty='Apotheke Nord',
            category_manual=True, source='camt053', dedup_key='ref:M1',
        )
        # …but a similar UNCATEGORIZED transaction is a candidate.
        open_tx = Transaction.objects.create(
            account=self.account, booking_date=date(2026, 7, 5),
            amount=Decimal('-7.50'), currency='EUR', counterparty='Apotheke West',
            source='camt053', dedup_key='ref:U1',
        )
        m_relabel.return_value = {
            'ids': [open_tx.id], 'rules': [],
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'estimated_cost_usd': None},
        }
        resp = self.client.post(reverse('ai_relabel'), {
            'transaction_id': self.tx.id,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['sent_count'], 1)
        sent_candidates = m_relabel.call_args.args[3]
        self.assertEqual([c['id'] for c in sent_candidates], [open_tx.id])
        self.assertIsNone(resp.data['suggestions'][0]['current_category'])

    @patch('portfolio.ai_categorization.relabel_similar')
    def test_relabel_rule_is_placed_before_the_shadowing_rule(self, m_relabel):
        from portfolio.models import CategoryRule, Transaction, TransactionCategory
        health = TransactionCategory.objects.create(user=self.user, name='Health')
        groceries = TransactionCategory.objects.create(user=self.user, name='Groceries')
        # The broad rule that mislabeled the transaction ("Markt" matches).
        bad_rule = CategoryRule.objects.create(
            user=self.user, match_text='markt', category=groceries, position=0,
        )
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        self.tx.category = health
        self.tx.category_manual = True
        self.tx.save()
        Transaction.objects.create(
            account=self.account, booking_date=date(2026, 7, 15),
            amount=Decimal('-12.30'), currency='EUR', counterparty='Apotheke am Markt',
            category=groceries, source='camt053', dedup_key='ref:A2',
        )
        m_relabel.return_value = {
            'ids': [], 'rules': [{'match_text': 'apotheke', 'category': 'Health'}],
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'estimated_cost_usd': None},
        }
        resp = self.client.post(reverse('ai_relabel'), {
            'transaction_id': self.tx.id,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['rules'][0]['place_before_rule_id'], bad_rule.id)
        self.assertEqual(resp.data['rules'][0]['shadowed_match_text'], 'markt')

    @patch('portfolio.ai_categorization.relabel_similar')
    def test_relabel_drops_rule_when_first_match_is_already_correct(self, m_relabel):
        from portfolio.models import CategoryRule, Transaction, TransactionCategory
        health = TransactionCategory.objects.create(user=self.user, name='Health')
        CategoryRule.objects.create(
            user=self.user, match_text='apotheke', category=health, position=0,
        )
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        self.tx.category = health
        self.tx.category_manual = True
        self.tx.save()
        Transaction.objects.create(
            account=self.account, booking_date=date(2026, 7, 15),
            amount=Decimal('-12.30'), currency='EUR', counterparty='Apotheke am Markt',
            source='camt053', dedup_key='ref:A2',
        )
        m_relabel.return_value = {
            'ids': [], 'rules': [{'match_text': 'apotheke', 'category': 'Health'}],
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'estimated_cost_usd': None},
        }
        resp = self.client.post(reverse('ai_relabel'), {
            'transaction_id': self.tx.id,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        # Future entries already classify correctly — no rule proposal.
        self.assertEqual(resp.data['rules'], [])

    def test_apply_inserts_rule_before_the_named_rule(self):
        from portfolio.models import CategoryRule, TransactionCategory
        groceries = TransactionCategory.objects.create(user=self.user, name='Groceries')
        bad_rule = CategoryRule.objects.create(
            user=self.user, match_text='markt', category=groceries, position=0,
        )
        CategoryRule.objects.create(
            user=self.user, match_text='coop', category=groceries, position=1,
        )
        resp = self.client.post(reverse('ai_apply'), {
            'rules': [{
                'match_text': 'apotheke', 'category': 'Health',
                'place_before_rule_id': bad_rule.id,
            }],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        order = list(
            CategoryRule.objects.filter(user=self.user)
            .order_by('position', 'id').values_list('match_text', flat=True)
        )
        self.assertEqual(order, ['apotheke', 'markt', 'coop'])

    def test_regex_rule_creation_validation_and_matching(self):
        from portfolio.models import Transaction, TransactionCategory
        health = TransactionCategory.objects.create(user=self.user, name='Health')
        # Invalid pattern is rejected by the serializer.
        resp = self.client.post(reverse('rule_list'), {
            'match_text': 'apo(theke', 'category': health.id, 'is_regex': True,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        # Valid regex categorizes the uncategorized setUp transaction
        # ("Apotheke am Markt") retroactively on creation.
        resp = self.client.post(reverse('rule_list'), {
            'match_text': r'apotheke.*(markt|nord)', 'category': health.id,
            'is_regex': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data['is_regex'])
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.category, health)
        # A plain substring rule with regex metacharacters stays literal.
        other = Transaction.objects.create(
            account=self.account, booking_date=date(2026, 8, 3),
            amount=Decimal('-2.00'), currency='EUR', counterparty='Kiosk (Markt)',
            source='camt053', dedup_key='ref:L1',
        )
        self.client.post(reverse('rule_list'), {
            'match_text': '(markt)', 'category': health.id,
        }, format='json')
        other.refresh_from_db()
        self.assertEqual(other.category, health)  # literal "(markt)" matched

    def test_transfer_rule_marks_matches_as_transfers(self):
        from portfolio.models import Transaction, TransactionCategory
        health = TransactionCategory.objects.create(user=self.user, name='Health')
        # XOR validation: both targets, or neither, is invalid.
        resp = self.client.post(reverse('rule_list'), {
            'match_text': 'apotheke', 'category': health.id, 'is_transfer': True,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(reverse('rule_list'), {
            'match_text': 'apotheke',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        # A user's manual "not a transfer" decision outranks the rule, and the
        # entry falls through to later category rules.
        unmarked = Transaction.objects.create(
            account=self.account, booking_date=date(2026, 8, 2),
            amount=Decimal('-5.00'), currency='EUR', counterparty='Apotheke Nord',
            transfer_manual=True, source='camt053', dedup_key='ref:T1',
        )
        resp = self.client.post(reverse('rule_list'), {
            'match_text': 'apotheke', 'is_transfer': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertIsNone(resp.data['category'])
        self.client.post(reverse('rule_list'), {
            'match_text': 'nord', 'category': health.id,
        }, format='json')
        self.tx.refresh_from_db()
        self.assertTrue(self.tx.is_transfer)
        self.assertIsNone(self.tx.category)
        unmarked.refresh_from_db()
        self.assertFalse(unmarked.is_transfer)
        self.assertEqual(unmarked.category, health)  # later rule applied

    def test_rules_replace_accepts_transfer_rules(self):
        resp = self.client.post(reverse('rule_replace'), {
            'rules': [{'match_text': 'vorsorge', 'is_transfer': True}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        from portfolio.models import CategoryRule
        rule = CategoryRule.objects.get(user=self.user)
        self.assertTrue(rule.is_transfer)
        self.assertIsNone(rule.category)

    def test_rules_replace_validates_regex(self):
        from portfolio.models import TransactionCategory
        TransactionCategory.objects.create(user=self.user, name='Health')
        resp = self.client.post(reverse('rule_replace'), {
            'rules': [{'match_text': 'apo(theke', 'category': 'Health',
                       'is_regex': True}],
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(reverse('rule_replace'), {
            'rules': [{'match_text': r'apotheke|drogerie', 'category': 'Health',
                       'is_regex': True}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.category.name, 'Health')

    @patch('portfolio.ai_categorization.consolidate_rules')
    def test_consolidate_merges_and_drops_hallucinated_categories(self, m_consolidate):
        from portfolio.models import CategoryRule, TransactionCategory
        groceries = TransactionCategory.objects.create(user=self.user, name='Groceries')
        r1 = CategoryRule.objects.create(
            user=self.user, match_text='migros zurich', category=groceries, position=0)
        r2 = CategoryRule.objects.create(
            user=self.user, match_text='migros bern', category=groceries,
            spread_months=3, position=1)
        # A regex rule must pass through untouched and never reach Gemini.
        regex_rule = CategoryRule.objects.create(
            user=self.user, match_text=r'coop (city|pronto)', category=groceries,
            is_regex=True, position=2)
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        m_consolidate.return_value = {
            'rules': [
                {'match_text': 'migros', 'category': 'Groceries',
                 'spread_months': None, 'sources': [r1.id, r2.id]},
                {'match_text': 'ghost', 'category': 'InventedCategory', 'sources': []},
            ],
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'estimated_cost_usd': None},
        }
        resp = self.client.post(reverse('ai_consolidate'), {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['before_count'], 3)
        self.assertEqual(resp.data['after_count'], 2)
        rule = resp.data['rules'][0]
        self.assertEqual(rule['match_text'], 'migros')
        # Missing spread falls back to the largest source spread.
        self.assertEqual(rule['spread_months'], 3)
        self.assertEqual(rule['sources'], [r1.id, r2.id])
        # The regex rule passes through unchanged, in evaluation order.
        passthrough = resp.data['rules'][1]
        self.assertEqual(passthrough['match_text'], r'coop (city|pronto)')
        self.assertTrue(passthrough['is_regex'])
        self.assertEqual(passthrough['sources'], [regex_rule.id])
        # Match counts are computed and sent (self.tx does not contain
        # "migros"); the regex rule is never sent to Gemini.
        sent_rules = m_consolidate.call_args.args[2]
        self.assertEqual([r['matches'] for r in sent_rules], [0, 0])
        self.assertEqual([r['id'] for r in sent_rules], [r1.id, r2.id])
        # Nothing persisted: all original rules still there.
        self.assertEqual(CategoryRule.objects.filter(user=self.user).count(), 3)

    def test_rules_replace_swaps_the_set_and_reapplies(self):
        from portfolio.models import CategoryRule, Transaction, TransactionCategory
        groceries = TransactionCategory.objects.create(user=self.user, name='Groceries')
        health = TransactionCategory.objects.create(user=self.user, name='Health')
        CategoryRule.objects.create(
            user=self.user, match_text='migros zurich', category=groceries, position=0)
        CategoryRule.objects.create(
            user=self.user, match_text='migros bern', category=groceries, position=1)
        resp = self.client.post(reverse('rule_replace'), {
            'rules': [
                {'match_text': 'migros', 'category': 'Groceries', 'spread_months': 1},
                {'match_text': 'apotheke', 'category': 'Health', 'spread_months': 1},
            ],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['count'], 2)
        order = list(
            CategoryRule.objects.filter(user=self.user)
            .order_by('position', 'id').values_list('match_text', flat=True)
        )
        self.assertEqual(order, ['migros', 'apotheke'])
        # The replacement set was re-applied: the uncategorized Apotheke
        # transaction from setUp is now categorized.
        self.assertEqual(resp.data['rule_applied'], 1)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.category, health)

    def test_rules_replace_rejects_unknown_category_keeping_old_rules(self):
        from portfolio.models import CategoryRule, TransactionCategory
        groceries = TransactionCategory.objects.create(user=self.user, name='Groceries')
        CategoryRule.objects.create(
            user=self.user, match_text='migros', category=groceries, position=0)
        resp = self.client.post(reverse('rule_replace'), {
            'rules': [{'match_text': 'x', 'category': 'Nope', 'spread_months': 1}],
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            CategoryRule.objects.filter(user=self.user).count(), 1)

    @patch('portfolio.ai_categorization.relabel_similar')
    def test_relabel_leaves_old_labels_alone_but_offers_old_uncategorized(
            self, m_relabel):
        from portfolio.models import Transaction, TransactionCategory
        health = TransactionCategory.objects.create(user=self.user, name='Health')
        groceries = TransactionCategory.objects.create(user=self.user, name='Groceries')
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        self.tx.category = health
        self.tx.category_manual = True
        self.tx.save()
        # Mislabeled but >18 months old: settled history, not a candidate.
        Transaction.objects.create(
            account=self.account, booking_date=date(2024, 5, 1),
            amount=Decimal('-11.00'), currency='EUR', counterparty='Apotheke am Markt',
            category=groceries, source='camt053', dedup_key='ref:OLD1',
        )
        # Uncategorized of the same age: pure gain, still a candidate.
        old_open = Transaction.objects.create(
            account=self.account, booking_date=date(2024, 5, 2),
            amount=Decimal('-6.00'), currency='EUR', counterparty='Apotheke am Markt',
            source='camt053', dedup_key='ref:OLD2',
        )
        m_relabel.return_value = {
            'ids': [old_open.id], 'rules': [],
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'estimated_cost_usd': None},
        }
        resp = self.client.post(reverse('ai_relabel'), {
            'transaction_id': self.tx.id,
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        sent_candidates = m_relabel.call_args.args[3]
        self.assertEqual([c['id'] for c in sent_candidates], [old_open.id])

    def test_relabel_requires_categorized_transaction(self):
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash',
        }, format='json')
        resp = self.client.post(reverse('ai_relabel'), {
            'transaction_id': self.tx.id,
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(reverse('ai_relabel'), {
            'transaction_id': 999999,
        }, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_apply_cannot_touch_other_users_transactions(self):
        from portfolio.models import Transaction
        other_user, _, _ = make_kek_user(username='bob')
        foreign_account = FinancialAccount.objects.create(
            user=other_user, broker=self.broker, name='Foreign', currency='EUR',
        )
        foreign_tx = Transaction.objects.create(
            account=foreign_account, booking_date=date(2026, 8, 1),
            amount=Decimal('-1.00'), currency='EUR', source='camt053', dedup_key='x',
        )
        resp = self.client.post(reverse('ai_apply'), {
            'assignments': [{'transaction_id': foreign_tx.id, 'category': 'Hijack'}],
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['assigned'], 0)
        foreign_tx.refresh_from_db()
        self.assertIsNone(foreign_tx.category)


_ZKB_CSV = (
    '"Date";"Booking text";"Curr";"Amount details";"ZKB reference";'
    '"Reference number";"Debit CHF";"Credit CHF";"Value date";"Balance CHF";'
    '"Payment purpose";"Details"\n'
    '"23.08.2026";"Debit TWINT: TEST MERCHANT";"";"";"REF-AAA-1";"";"10.00";"";'
    '"23.08.2026";"1000.00";"";""\n'
    '"20.08.2026";"Credit originator: ACME CORP";"";"";"REF-BBB-2";"";"";"80.00";'
    '"20.08.2026";"1010.00";"PURPOSE TEXT";"ACME CORP, Somestreet 1, CH"\n'
    '"";"";"";"";"";"";"";"";"";"";"";"a detail continuation row"\n'
)

_DKB_CSV = (
    '"Girokonto";"DE00000000000000000000"\n'
    '"Zeitraum:";"01.01.2026 - 24.08.2026"\n'
    '"Kontostand vom 24.08.2026:";"1.000,00 €"\n'
    '""\n'
    '"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";'
    '"Zahlungsempfänger*in";"Verwendungszweck";"Umsatztyp";"IBAN";'
    '"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"\n'
    '"24.08.26";"24.08.26";"Gebucht";"ISSUER";"Test Shop";"Purchase 1";"Ausgang";'
    '"DE11111111111111111111";"-1.234,56";"";"";"KREF1"\n'
    '"20.08.26";"20.08.26";"Gebucht";"Employer AG";"Account Holder";"Salary";'
    '"Eingang";"DE22222222222222222222";"2.500,00";"";"";"KREF2"\n'
    '"25.08.26";"25.08.26";"Vorgemerkt";"ISSUER";"Pending Shop";"Pending";'
    '"Ausgang";"DE33333333333333333333";"-9,99";"";"";"KREF3"\n'
)


_COMMERZBANK_CSV = (
    'Buchungstag;Wertstellung;Umsatzart;Buchungstext;Betrag;Währung;'
    'IBAN Kontoinhaber;Kategorie;Sender;Empfänger;Verwendungszweck\n'
    '11.08.2026;11.08.2026;Überweisung;Alice Example Auffuellung '
    'End-to-End-Ref.: NOTPROVIDED;702;EUR;DE58000000000000000001;Einnahmen;'
    'Alice Example;;Auffuellung\n'
    '03.08.2026;03.08.2026;Dauerauftrag;BOB EXAMPLE BYLADEM1001 '
    'DE57000000000000000002 TOPUP End-to-End-Ref.: NOTPROVIDED Dauerauftrag;'
    '-1.702,50;EUR;DE58000000000000000001;Sonstige Ausgaben;;BOB EXAMPLE;TOPUP\n'
)


class CsvImportTests(APITestCase):
    """CSV transaction import (synthetic fixtures mimicking the bank formats)."""

    def setUp(self):
        self.user, self.kek, _ = make_kek_user()
        self.broker = Broker.objects.create(code='zkb', name='ZKB', integration_type='ebics')
        self.chf = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='ZKB Giro', currency='CHF',
        )
        self.eur = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='DKB Giro', currency='EUR',
        )
        self.client.force_authenticate(user=self.user)

    def _upload(self, account, text):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post(
            reverse('transaction_csv_import', kwargs={'pk': account.pk}),
            {'file': SimpleUploadedFile('export.csv', text.encode('utf-8'))},
            format='multipart',
        )

    def _upload_auto(self, text):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post(
            reverse('transaction_csv_import_auto'),
            {'file': SimpleUploadedFile('export.csv', text.encode('utf-8'))},
            format='multipart',
        )

    def test_auto_import_matches_dkb_account_by_preamble_iban(self):
        self.eur.account_identifier = 'DE00000000000000000000'
        self.eur.save()
        resp = self._upload_auto(_DKB_CSV)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['status'], 'success')
        self.assertEqual(resp.data['account_id'], self.eur.id)
        self.assertEqual(resp.data['imported'], 2)

    def test_commerzbank_auto_import_by_own_iban_column(self):
        from portfolio.models import Transaction
        self.eur.account_identifier = 'DE58000000000000000001'
        self.eur.save()
        resp = self._upload_auto(_COMMERZBANK_CSV)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['format'], 'commerzbank')
        self.assertEqual(resp.data['account_id'], self.eur.id)
        self.assertEqual(resp.data['imported'], 2)
        credit = Transaction.objects.get(account=self.eur, amount=Decimal('702'))
        self.assertEqual(credit.counterparty, 'Alice Example')  # sender on inflow
        self.assertEqual(credit.description, 'Auffuellung')
        debit = Transaction.objects.get(account=self.eur, amount=Decimal('-1702.50'))
        self.assertEqual(debit.counterparty, 'BOB EXAMPLE')  # recipient on outflow
        # The counterparty IBAN is embedded in the booking text — extracted so
        # transfer auto-detection can pair it (the own IBAN is skipped).
        self.assertEqual(debit.counterparty_account, 'DE57000000000000000002')
        self.assertEqual(debit.currency, 'EUR')

    def test_auto_import_rejects_unknown_iban(self):
        resp = self._upload_auto(_DKB_CSV)  # no account carries that IBAN
        self.assertEqual(resp.status_code, 400)
        self.assertIn('DE00000000000000000000', resp.data['error'])

    def test_auto_import_zkb_by_unique_currency(self):
        resp = self._upload_auto(_ZKB_CSV)  # exactly one CHF account
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['status'], 'success')
        self.assertEqual(resp.data['account_id'], self.chf.id)

    def test_auto_import_zkb_ambiguous_lists_candidates(self):
        other = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Second CHF', currency='CHF',
        )
        resp = self._upload_auto(_ZKB_CSV)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['status'], 'ambiguous')
        self.assertEqual(
            {a['id'] for a in resp.data['accounts']}, {self.chf.id, other.id})
        from portfolio.models import Transaction
        self.assertEqual(Transaction.objects.count(), 0)  # nothing imported

    def test_account_import_rejects_foreign_iban_file(self):
        self.chf.account_identifier = 'CH0000000000000000000'
        self.chf.save()
        resp = self._upload(self.chf, _DKB_CSV)  # file names a DE IBAN
        self.assertEqual(resp.status_code, 400)
        self.assertIn('DE00000000000000000000', resp.data['error'])

    def test_zkb_import_signs_refs_and_detail_rows(self):
        from portfolio.models import Transaction
        resp = self._upload(self.chf, _ZKB_CSV)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['format'], 'zkb')
        self.assertEqual(resp.data['imported'], 2)
        self.assertEqual(resp.data['skipped'], 1)  # the detail continuation row
        debit = Transaction.objects.get(account=self.chf, external_id='REF-AAA-1')
        self.assertEqual(debit.amount, Decimal('-10.00'))
        self.assertEqual(debit.currency, 'CHF')
        self.assertEqual(debit.source, 'csv')
        self.assertEqual(debit.dedup_key, 'ref:REF-AAA-1')
        credit = Transaction.objects.get(account=self.chf, external_id='REF-BBB-2')
        self.assertEqual(credit.amount, Decimal('80.00'))
        self.assertEqual(credit.counterparty, 'ACME CORP, Somestreet 1, CH')
        self.assertIn('PURPOSE TEXT', credit.description)
        self.assertEqual(str(credit.value_date), '2026-08-20')

    def test_zkb_import_dedups_against_ebics_synced_rows(self):
        from portfolio.models import Transaction
        # The same entry already arrived via EBICS: shared bank reference.
        Transaction.objects.create(
            account=self.chf, booking_date=date(2026, 8, 23),
            amount=Decimal('-10.00'), currency='CHF', source='camt053',
            external_id='REF-AAA-1', dedup_key='ref:REF-AAA-1',
        )
        resp = self._upload(self.chf, _ZKB_CSV)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['imported'], 1)  # only the credit is new
        self.assertEqual(Transaction.objects.filter(account=self.chf).count(), 2)

    def test_dkb_import_amounts_status_and_counterparty(self):
        from portfolio.models import Transaction
        resp = self._upload(self.eur, _DKB_CSV)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['format'], 'dkb')
        self.assertEqual(resp.data['imported'], 2)  # pending row skipped
        self.assertEqual(resp.data['skipped'], 1)
        out = Transaction.objects.get(account=self.eur, amount=Decimal('-1234.56'))
        self.assertEqual(out.counterparty, 'Test Shop')  # payee on outflow
        self.assertEqual(out.counterparty_account, 'DE11111111111111111111')
        self.assertEqual(out.currency, 'EUR')
        inc = Transaction.objects.get(account=self.eur, amount=Decimal('2500.00'))
        self.assertEqual(inc.counterparty, 'Employer AG')  # payer on inflow

    def test_reimport_is_idempotent(self):
        for account, text in ((self.chf, _ZKB_CSV), (self.eur, _DKB_CSV)):
            first = self._upload(account, text)
            second = self._upload(account, text)
            self.assertEqual(second.status_code, 200, second.data)
            self.assertEqual(second.data['imported'], 0)
            self.assertEqual(second.data['fetched'], first.data['fetched'])

    def test_currency_mismatch_is_refused(self):
        resp = self._upload(self.chf, _DKB_CSV)  # EUR file into CHF account
        self.assertEqual(resp.status_code, 400)
        self.assertIn('EUR', resp.data['error'])

    def test_unknown_format_and_foreign_account(self):
        resp = self._upload(self.chf, 'just;some;random\ncsv;file;here\n')
        self.assertEqual(resp.status_code, 400)
        other_user, _, _ = make_kek_user(username='bob')
        foreign = FinancialAccount.objects.create(
            user=other_user, broker=self.broker, name='Foreign', currency='CHF',
        )
        resp = self._upload(foreign, _ZKB_CSV)
        self.assertEqual(resp.status_code, 404)


class TransactionBackfillTests(APITestCase):
    """Dated transaction backfill (web-only feature)."""

    def setUp(self):
        self.user, self.kek, _ = make_kek_user()
        self.broker = Broker.objects.create(code='zkb', name='ZKB', integration_type='ebics')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Giro', currency='CHF',
            account_identifier='CH93', encrypted_credentials=b'x',
        )
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_X_KEK=self.kek)

    def _url(self):
        return reverse('transaction_backfill', kwargs={'pk': self.account.pk})

    @patch('portfolio.views.KEKAuthenticationMixin.decrypt_sync_credentials')
    @patch('portfolio.views.FinancialAccount.objects.get')
    def test_rejects_bad_dates(self, _m_get, m_creds):
        m_creds.return_value = {}
        _m_get.return_value = self.account
        resp = self.client.post(self._url(), {'start': 'nope'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('ISO dates', resp.data['error'])

        resp = self.client.post(
            self._url(), {'start': '2026-08-01', 'end': '2026-01-01'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('before end date', resp.data['error'])

    def test_manual_account_rejected(self):
        self.account.is_manual = True
        self.account.save()
        resp = self.client.post(self._url(), {'start': '2026-01-01'}, format='json')
        self.assertEqual(resp.status_code, 400)

    @patch('portfolio.views.KEKAuthenticationMixin.decrypt_sync_credentials')
    def test_enqueues_task(self, m_creds):
        m_creds.return_value = {'keyring_pem': 'x'}
        resp = self.client.post(
            self._url(), {'start': '2026-01-01', 'end': '2026-06-30'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['status'], 'queued')
        self.assertIn('task_id', resp.data)


class BackfillImporterTests(TestCase):
    def setUp(self):
        from brokers.integrations.base import TransactionInfo
        self.user, _, _ = make_kek_user()
        self.broker = Broker.objects.create(code='zkb', name='ZKB', integration_type='ebics')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Giro', currency='CHF',
            account_identifier='CH93',
        )
        self.TransactionInfo = TransactionInfo

    def _integration(self, infos):
        calls = []

        class Fake:
            def supports_transactions(self):
                return True

            # Backfill goes through get_transactions_for_range (dated request),
            # which defaults to get_transactions for range-querying feeds.
            def get_transactions_for_range(self, identifier, start, end):
                return self.get_transactions(identifier, start, end)

            def get_transactions(self, identifier, start, end):
                calls.append((start, end))
                return infos

        fake = Fake()
        fake.calls = calls
        return fake

    def test_backfill_uses_requested_range_and_is_idempotent(self):
        from portfolio.models import Transaction
        from portfolio.transaction_importer import backfill_account_transactions
        infos = [self.TransactionInfo(
            booking_date=date(2025, 3, 5), amount=Decimal('-20'), currency='CHF',
            counterparty='Old Shop', external_id='OLD1',
        )]
        integration = self._integration(infos)
        result = backfill_account_transactions(
            self.account, integration, date(2025, 1, 1), date(2025, 12, 31))
        self.assertEqual(result.imported, 1)
        self.assertEqual(integration.calls[0], (date(2025, 1, 1), date(2025, 12, 31)))
        # Re-running the same range imports nothing new.
        self.assertEqual(
            backfill_account_transactions(
                self.account, integration, date(2025, 1, 1), date(2025, 12, 31)).imported,
            0,
        )
        self.assertEqual(Transaction.objects.filter(account=self.account).count(), 1)

    def test_backfill_reports_the_span_the_bank_actually_served(self):
        """A bank that serves only the tail of the requested window must say so.

        ZKB's EBICS archive starts at subscriber activation, so a 15-month request
        can come back with 7 weeks. Reporting only the imported count made that look
        like a complete import of the requested period.
        """
        from portfolio.transaction_importer import backfill_account_transactions
        infos = [
            self.TransactionInfo(
                booking_date=date(2025, 11, 3), amount=Decimal('-20'), currency='CHF',
                counterparty='Shop', external_id='A1',
            ),
            self.TransactionInfo(
                booking_date=date(2025, 12, 20), amount=Decimal('-35'), currency='CHF',
                counterparty='Shop', external_id='A2',
            ),
        ]
        result = backfill_account_transactions(
            self.account, self._integration(infos), date(2025, 1, 1), date(2025, 12, 31))

        self.assertEqual(result.imported, 2)
        self.assertEqual(result.fetched, 2)
        self.assertEqual(result.covered_start, date(2025, 11, 3))
        self.assertEqual(result.covered_end, date(2025, 12, 20))
        self.assertTrue(result.is_truncated)
        self.assertIn('2025-11-03', result.describe())
        self.assertIn("short of the requested", result.describe())

    def test_backfill_covering_the_window_is_not_flagged_truncated(self):
        from portfolio.transaction_importer import backfill_account_transactions
        infos = [self.TransactionInfo(
            booking_date=date(2025, 1, 9), amount=Decimal('-20'), currency='CHF',
            counterparty='Shop', external_id='B1',
        )]
        result = backfill_account_transactions(
            self.account, self._integration(infos), date(2025, 1, 1), date(2025, 12, 31))
        self.assertFalse(result.is_truncated)
        self.assertNotIn('short of the requested', result.describe())

    def test_backfill_with_no_data_says_so(self):
        from portfolio.transaction_importer import backfill_account_transactions
        result = backfill_account_transactions(
            self.account, self._integration([]), date(2025, 1, 1), date(2025, 12, 31))
        self.assertEqual(result.imported, 0)
        self.assertFalse(result.is_truncated)
        self.assertIn('No transactions were returned', result.describe())


class StorePositionsTests(TestCase):
    def setUp(self):
        from brokers.integrations.base import PositionInfo
        self.user, _, _ = make_kek_user()
        broker = Broker.objects.create(code='ibkr', name='IBKR', integration_type='rest')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=broker, name='IBKR', currency='USD',
        )
        self.snapshot = AccountSnapshot.objects.create(
            account=self.account, balance=Decimal('1000'), currency='USD',
            snapshot_date=date(2026, 8, 1),
        )
        self.PositionInfo = PositionInfo

    def _info(self, symbol='VT', value='500', quantity='4'):
        return self.PositionInfo(
            symbol=symbol, name=f'{symbol} ETF', quantity=Decimal(quantity),
            price_per_unit=Decimal(value) / Decimal(quantity),
            market_value=Decimal(value), currency='USD',
            isin='US9220427424', asset_class='equity',
        )

    def test_store_positions_replaces_wholesale(self):
        from portfolio.snapshot_writer import store_positions
        store_positions(self.snapshot, [self._info('VT'), self._info('VXUS')])
        self.assertEqual(self.snapshot.positions.count(), 2)
        # A later sync where VXUS was sold must remove its row.
        store_positions(self.snapshot, [self._info('VT', value='600')])
        names = list(self.snapshot.positions.values_list('symbol', flat=True))
        self.assertEqual(names, ['VT'])
        self.assertEqual(self.snapshot.positions.get().market_value, Decimal('600'))

    def test_empty_list_does_not_erase_existing_positions(self):
        from portfolio.snapshot_writer import store_positions
        store_positions(self.snapshot, [self._info('VT')])
        self.assertEqual(store_positions(self.snapshot, []), 0)
        self.assertEqual(self.snapshot.positions.count(), 1)


class WealthHoldingsEndpointTests(APITestCase):
    def setUp(self):
        self.user, _, _ = make_kek_user()
        self.client.force_authenticate(user=self.user)
        broker = Broker.objects.create(code='ibkr', name='IBKR', integration_type='rest')
        self.acc_a = FinancialAccount.objects.create(
            user=self.user, broker=broker, name='IBKR', currency='CHF',
        )
        self.acc_b = FinancialAccount.objects.create(
            user=self.user, broker=broker, name='MS', currency='CHF',
        )

    def _snap_with_position(self, account, snapshot_date, *, isin, symbol, value, quantity):
        snap = AccountSnapshot.objects.create(
            account=account, balance=Decimal(value), currency='CHF',
            snapshot_date=snapshot_date,
        )
        PortfolioPosition.objects.create(
            snapshot=snap, symbol=symbol, isin=isin, name=f'{symbol} ETF',
            quantity=Decimal(quantity), price_per_unit=Decimal(value) / Decimal(quantity),
            market_value=Decimal(value), currency='CHF', asset_class='equity',
        )
        return snap

    def test_merges_same_isin_across_accounts(self):
        self._snap_with_position(
            self.acc_a, date(2026, 8, 1), isin='US9220427424', symbol='VT',
            value='500', quantity='4')
        self._snap_with_position(
            self.acc_b, date(2026, 8, 2), isin='US9220427424', symbol='VT',
            value='250', quantity='2')
        resp = self.client.get(reverse('wealth_holdings'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['holdings']), 1)
        holding = resp.data['holdings'][0]
        self.assertEqual(holding['quantity'], 6.0)
        self.assertEqual(holding['value_base_currency'], 750.0)
        self.assertEqual(sorted(holding['accounts']), ['IBKR', 'MS'])
        self.assertEqual(resp.data['as_of'], '2026-08-02')

    def test_uses_latest_snapshot_that_has_positions(self):
        self._snap_with_position(
            self.acc_a, date(2026, 8, 1), isin='US9220427424', symbol='VT',
            value='500', quantity='4')
        # A newer balance-only snapshot (e.g. from a balance-only sync) must not
        # hide the holdings that are still current.
        AccountSnapshot.objects.create(
            account=self.acc_a, balance=Decimal('510'), currency='CHF',
            snapshot_date=date(2026, 8, 5),
        )
        resp = self.client.get(reverse('wealth_holdings'))
        self.assertEqual(len(resp.data['holdings']), 1)

    def test_empty_when_no_positions_anywhere(self):
        resp = self.client.get(reverse('wealth_holdings'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['holdings'], [])
        self.assertIsNone(resp.data['as_of'])


class SimulationEngineTests(TestCase):
    def _run(self, **overrides):
        from portfolio.simulation import run_simulation
        params = dict(
            start_wealth=100_000, monthly_contribution=1_000,
            expected_return=0.05, volatility=0.12, inflation=0.02,
            years=10, paths=500, seed=42,
        )
        params.update(overrides)
        return run_simulation(**params)

    def test_seeded_run_is_deterministic(self):
        self.assertEqual(self._run(), self._run())

    def test_percentiles_are_monotonic(self):
        for band in self._run()['bands']:
            self.assertLessEqual(band['p5'], band['p25'])
            self.assertLessEqual(band['p25'], band['p50'])
            self.assertLessEqual(band['p50'], band['p75'])
            self.assertLessEqual(band['p75'], band['p95'])

    def test_zero_volatility_matches_compound_interest(self):
        import math
        result = self._run(volatility=0, years=10, paths=100)
        # With sigma=0 every path is the deterministic monthly compounding of the
        # real return (5% - 2% = 3%) plus contributions.
        rate = math.exp(0.03 / 12)
        wealth = 100_000.0
        for _ in range(120):
            wealth = wealth * rate + 1_000
        band = result['bands'][-1]
        self.assertAlmostEqual(band['p50'], wealth, delta=0.01)  # bands round to 2 dp
        self.assertEqual(band['p5'], band['p95'])

    def test_target_probability_and_median_year(self):
        result = self._run(target_amount=150_000)
        target = result['target']
        self.assertGreaterEqual(target['probability'], 0)
        self.assertLessEqual(target['probability'], 1)
        # 100k at 3% real + 12k/year reaches 150k comfortably within 10 years.
        self.assertIsNotNone(target['median_reached_year'])
        # An absurd target is (a) never reached by the median and (b) ~0 probability.
        result = self._run(target_amount=10**12)
        self.assertIsNone(result['target']['median_reached_year'])
        self.assertEqual(result['target']['probability'], 0)

    def test_wealth_is_floored_at_zero(self):
        result = self._run(
            start_wealth=1_000, monthly_contribution=-5_000, volatility=0,
            years=2, paths=100,
        )
        self.assertEqual(result['bands'][-1]['p50'], 0)

    def test_paths_and_years_are_clamped(self):
        result = self._run(years=500, paths=5)
        self.assertEqual(result['years'], 50)
        self.assertEqual(result['paths'], 100)


class SimulationDefaultsTests(TestCase):
    def setUp(self):
        self.user, _, _ = make_kek_user()
        self.broker = Broker.objects.create(code='ibkr', name='IBKR', integration_type='rest')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='IBKR', currency='CHF',
        )

    def test_market_assumptions_blend_from_holdings(self):
        from portfolio.simulation import ASSET_CLASS_ASSUMPTIONS, derive_market_assumptions
        snap = AccountSnapshot.objects.create(
            account=self.account, balance=Decimal('1000'), currency='CHF',
            snapshot_date=date(2026, 8, 1),
        )
        for asset_class, value in (('equity', '600'), ('fixed_income', '400')):
            PortfolioPosition.objects.create(
                snapshot=snap, name=asset_class, quantity=Decimal('1'),
                price_per_unit=Decimal(value), market_value=Decimal(value),
                currency='CHF', asset_class=asset_class,
            )
        expected_return, volatility, weights = derive_market_assumptions(self.user)
        eq = ASSET_CLASS_ASSUMPTIONS['equity']
        fi = ASSET_CLASS_ASSUMPTIONS['fixed_income']
        self.assertAlmostEqual(expected_return, 0.6 * eq[0] + 0.4 * fi[0], places=4)
        self.assertAlmostEqual(volatility, 0.6 * eq[1] + 0.4 * fi[1], places=4)
        self.assertAlmostEqual(weights['equity'], 0.6, places=4)

    def test_market_assumptions_fall_back_without_holdings(self):
        from portfolio.simulation import DEFAULT_RETURN, DEFAULT_VOLATILITY, derive_market_assumptions
        expected_return, volatility, weights = derive_market_assumptions(self.user)
        self.assertEqual(expected_return, DEFAULT_RETURN)
        self.assertEqual(volatility, DEFAULT_VOLATILITY)
        self.assertEqual(weights, {})

    def test_start_wealth_uses_latest_snapshots(self):
        from portfolio.simulation import derive_start_wealth
        AccountSnapshot.objects.create(
            account=self.account, balance=Decimal('500'), currency='CHF',
            snapshot_date=date(2026, 7, 1),
        )
        AccountSnapshot.objects.create(
            account=self.account, balance=Decimal('750'), currency='CHF',
            snapshot_date=date(2026, 8, 1),
        )
        self.assertEqual(derive_start_wealth(self.user), 750.0)


class SimulationEndpointTests(APITestCase):
    def setUp(self):
        self.user, _, _ = make_kek_user()
        self.client.force_authenticate(user=self.user)

    def test_simulation_endpoint_returns_bands_and_parameters(self):
        resp = self.client.get(reverse('wealth_simulation'), {'seed': 1, 'paths': 200})
        self.assertEqual(resp.status_code, 200)
        # Bands always cover the largest selectable horizon (30y) so clients can
        # switch horizons by slicing locally; 'years' is the selected horizon.
        self.assertEqual(resp.data['years'], 15)
        self.assertEqual(len(resp.data['bands']), 31)
        for name in ('start_wealth', 'monthly_contribution', 'expected_return',
                     'volatility', 'inflation'):
            self.assertIn(name, resp.data['parameters'])
        # Nothing supplied -> everything derived.
        self.assertTrue(resp.data['parameters']['start_wealth']['derived'])

    def test_supplied_parameters_are_echoed_as_not_derived(self):
        resp = self.client.get(reverse('wealth_simulation'), {
            'seed': 1, 'paths': 200, 'expected_return': '0.06', 'target_amount': '1000',
        })
        self.assertEqual(resp.data['parameters']['expected_return']['value'], 0.06)
        self.assertFalse(resp.data['parameters']['expected_return']['derived'])
        self.assertIn('target', resp.data)

    def test_target_probability_matches_selected_horizon(self):
        resp = self.client.get(reverse('wealth_simulation'), {
            'seed': 1, 'paths': 200, 'years': 5, 'target_amount': '1000',
            'monthly_contribution': '100', 'start_wealth': '0',
        })
        target = resp.data['target']
        self.assertEqual(len(target['probability_by_year']), 31)
        self.assertEqual(target['probability'], target['probability_by_year'][5])

    def test_invalid_parameter_is_a_400(self):
        resp = self.client.get(reverse('wealth_simulation'), {'years': 'soon'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('years', resp.data['error'])


class SimulationPersistenceTests(APITestCase):
    """Explicitly sent parameters persist as overrides; untouched ones re-derive."""

    def setUp(self):
        self.user, _, _ = make_kek_user()
        self.client.force_authenticate(user=self.user)
        self.url = reverse('wealth_simulation')

    def _profile(self):
        self.user.profile.refresh_from_db()
        return self.user.profile

    def test_sent_parameters_are_stored_and_reused(self):
        self.client.get(self.url, {'paths': 100, 'expected_return': '0.06', 'years': 20})
        stored = self._profile().simulation_params
        self.assertEqual(stored, {'expected_return': 0.06, 'years': 20})

        # A later bare request applies the stored overrides.
        resp = self.client.get(self.url, {'paths': 100})
        self.assertEqual(resp.data['years'], 20)
        parameter = resp.data['parameters']['expected_return']
        self.assertEqual(parameter['value'], 0.06)
        self.assertFalse(parameter['derived'])
        # Untouched parameters still count as derived.
        self.assertTrue(resp.data['parameters']['volatility']['derived'])

    def test_unsent_parameters_keep_rederiving(self):
        """A stored override must not freeze the others — esp. start_wealth."""
        broker = Broker.objects.create(code='viac', name='VIAC', integration_type='rest')
        account = FinancialAccount.objects.create(
            user=self.user, broker=broker, name='Acct', currency='CHF',
        )
        AccountSnapshot.objects.create(
            account=account, balance=Decimal('1000'), currency='CHF',
            snapshot_date=date(2026, 8, 1),
        )
        self.client.get(self.url, {'paths': 100, 'expected_return': '0.06'})
        # Wealth changes: a new snapshot arrives.
        AccountSnapshot.objects.create(
            account=account, balance=Decimal('2000'), currency='CHF',
            snapshot_date=date(2026, 8, 10),
        )
        resp = self.client.get(self.url, {'paths': 100})
        self.assertEqual(resp.data['parameters']['start_wealth']['value'], 2000.0)
        self.assertTrue(resp.data['parameters']['start_wealth']['derived'])

    def test_empty_parameter_clears_the_override(self):
        self.client.get(self.url, {'paths': 100, 'volatility': '0.3'})
        self.assertEqual(self._profile().simulation_params, {'volatility': 0.3})
        resp = self.client.get(self.url, {'paths': 100, 'volatility': ''})
        self.assertIsNone(self._profile().simulation_params)
        self.assertTrue(resp.data['parameters']['volatility']['derived'])

    def test_target_amount_persists_and_clears(self):
        self.client.get(self.url, {'paths': 100, 'target_amount': '500000'})
        resp = self.client.get(self.url, {'paths': 100})
        self.assertEqual(resp.data['target']['amount'], 500000.0)
        self.client.get(self.url, {'paths': 100, 'target_amount': ''})
        resp = self.client.get(self.url, {'paths': 100})
        self.assertNotIn('target', resp.data)

    def test_paths_and_seed_are_never_persisted(self):
        self.client.get(self.url, {'paths': 100, 'seed': 5})
        self.assertIsNone(self._profile().simulation_params)


class AiModelFilterTests(TestCase):
    """The model picker must only offer general-purpose text models."""

    def _list(self, ids_and_names):
        from portfolio.ai_categorization import list_models
        payload = {'models': [
            {'name': f'models/{mid}', 'displayName': name,
             'supportedGenerationMethods': ['generateContent']}
            for mid, name in ids_and_names
        ]}
        with patch('portfolio.ai_categorization.requests.get') as m_get:
            m_get.return_value = MagicMock(status_code=200, json=lambda: payload)
            return list_models('key')

    def test_excludes_image_speech_robotics_and_tool_variants(self):
        models = self._list([
            ('gemini-3.6-flash', 'Gemini 3.6 Flash'),
            ('gemini-2.5-flash-image', 'Nano Banana'),
            ('gemini-3-pro-image-preview', 'Nano Banana Pro'),
            ('gemini-2.5-flash-preview-tts', 'Gemini 2.5 Flash Preview TTS'),
            ('gemini-robotics-er-2-preview', 'Gemini Robotics-ER 2 Preview'),
            ('gemini-2.5-computer-use-preview-10-2025', 'Gemini 2.5 Computer Use'),
            ('gemini-2.5-flash-native-audio-dialog', 'Gemini Live'),
            ('gemini-embedding-001', 'Gemini Embedding'),
            ('gemini-3.1-pro-preview-custom-tools', 'Gemini 3.1 Pro Custom Tools'),
        ])
        self.assertEqual([m['id'] for m in models], ['gemini-3.6-flash'])

    def test_image_model_never_inherits_a_text_models_price(self):
        # 'gemini-2.5-flash-image' prefix-matches the 'gemini-2.5-flash' price row.
        from portfolio.ai_categorization import is_text_model
        self.assertFalse(is_text_model('gemini-2.5-flash-image'))
        self.assertEqual(self._list([('gemini-2.5-flash-image', 'Nano Banana')]), [])

    def test_keeps_current_text_models_including_previews_and_aliases(self):
        models = self._list([
            ('gemini-3.1-pro-preview', 'Gemini 3.1 Pro Preview'),
            ('gemini-3.5-flash-lite', 'Gemini 3.5 Flash Lite'),
            ('gemini-flash-latest', 'Gemini Flash Latest'),
        ])
        self.assertEqual(
            sorted(m['id'] for m in models),
            ['gemini-3.1-pro-preview', 'gemini-3.5-flash-lite', 'gemini-flash-latest'],
        )

    def test_deduplicates_aliases_of_the_same_model(self):
        models = self._list([
            ('gemini-3.6-flash', 'Gemini 3.6 Flash'),
            ('gemini-3.6-flash-001', 'Gemini 3.6 Flash'),
        ])
        self.assertEqual(len(models), 1)


class RuleOrderingTests(APITestCase):
    """Rules are first-match-wins, so their order is user-controlled."""

    def setUp(self):
        from portfolio.models import CategoryRule, TransactionCategory
        self.user, self.kek, _ = make_kek_user()
        self.broker = Broker.objects.create(code='zkb', name='ZKB', integration_type='ebics')
        self.account = FinancialAccount.objects.create(
            user=self.user, broker=self.broker, name='Giro', currency='EUR',
        )
        self.travel = TransactionCategory.objects.create(user=self.user, name='Travel')
        self.fuel = TransactionCategory.objects.create(user=self.user, name='Fuel')
        self.CategoryRule = CategoryRule
        self.client.force_authenticate(user=self.user)

    def _rule(self, match_text, category, position):
        return self.CategoryRule.objects.create(
            user=self.user, match_text=match_text, category=category, position=position,
        )

    def _tx(self, counterparty):
        from portfolio.models import Transaction
        return Transaction.objects.create(
            account=self.account, booking_date=date(2026, 8, 1), amount=Decimal('-60'),
            currency='EUR', counterparty=counterparty, source='camt053',
            dedup_key=f'k-{counterparty}',
        )

    def test_duplicate_match_text_is_rejected(self):
        url = reverse('rule_list')
        first = self.client.post(
            url, {'match_text': 'shell', 'category': self.fuel.id}, format='json')
        self.assertEqual(first.status_code, 201, first.data)
        # A second rule with the same text could never fire (first-match-wins).
        dupe = self.client.post(
            url, {'match_text': 'Shell', 'category': self.travel.id}, format='json')
        self.assertEqual(dupe.status_code, 400, dupe.data)
        self.assertEqual(self.CategoryRule.objects.filter(user=self.user).count(), 1)

    def test_transfer_rule_cannot_spread(self):
        resp = self.client.post(reverse('rule_list'), {
            'match_text': 'broker top-up', 'is_transfer': True, 'spread_months': 12,
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)
        # Without the spread it is accepted.
        ok = self.client.post(reverse('rule_list'), {
            'match_text': 'broker top-up', 'is_transfer': True,
        }, format='json')
        self.assertEqual(ok.status_code, 201, ok.data)

    def test_first_matching_rule_wins_by_position(self):
        from portfolio.classification import apply_rules
        # 'shell' is more specific than 'she'... use a realistic overlap instead:
        self._rule('tank', self.fuel, position=0)
        self._rule('tankstelle shop', self.travel, position=1)
        tx = self._tx('Tankstelle Shop A5')
        apply_rules(self.user)
        tx.refresh_from_db()
        self.assertEqual(tx.category, self.fuel)

    def test_reorder_changes_which_rule_wins(self):
        from portfolio.classification import apply_rules
        broad = self._rule('tank', self.fuel, position=0)
        specific = self._rule('tankstelle shop', self.travel, position=1)
        resp = self.client.post(
            reverse('rule_reorder'), {'ids': [specific.id, broad.id]}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual([r['id'] for r in resp.data], [specific.id, broad.id])
        tx = self._tx('Tankstelle Shop A5')
        apply_rules(self.user)
        tx.refresh_from_db()
        self.assertEqual(tx.category, self.travel)

    def test_reorder_keeps_rules_missing_from_the_payload(self):
        a = self._rule('aaa', self.fuel, position=0)
        b = self._rule('bbb', self.fuel, position=1)
        c = self._rule('ccc', self.fuel, position=2)
        resp = self.client.post(reverse('rule_reorder'), {'ids': [c.id]}, format='json')
        self.assertEqual([r['id'] for r in resp.data], [c.id, a.id, b.id])

    def test_reorder_ignores_other_users_rule_ids(self):
        from portfolio.models import TransactionCategory
        mine = self._rule('mine', self.fuel, position=0)
        other, _, _ = make_kek_user(username='bob')
        foreign_cat = TransactionCategory.objects.create(user=other, name='Theirs')
        foreign = self.CategoryRule.objects.create(
            user=other, match_text='theirs', category=foreign_cat, position=0,
        )
        resp = self.client.post(
            reverse('rule_reorder'), {'ids': [foreign.id, mine.id]}, format='json',
        )
        self.assertEqual([r['id'] for r in resp.data], [mine.id])
        foreign.refresh_from_db()
        self.assertEqual(foreign.position, 0)

    def test_new_rules_are_appended_last(self):
        self._rule('first', self.fuel, position=0)
        resp = self.client.post(reverse('rule_list'), {
            'match_text': 'second', 'category': self.fuel.id,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['position'], 1)

    def test_legacy_rules_without_positions_keep_creation_order(self):
        # Existing rows migrate in with position 0; id must break the tie.
        first = self._rule('aaa', self.fuel, position=0)
        second = self._rule('bbb', self.travel, position=0)
        self.assertEqual(
            [r.id for r in self.CategoryRule.objects.filter(user=self.user)],
            [first.id, second.id],
        )


class AiPricingRefreshTests(APITestCase):
    def setUp(self):
        self.user, self.kek, _ = make_kek_user()
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_X_KEK=self.kek)
        self.client.put(reverse('ai_config'), {
            'api_key': 'k', 'model': 'gemini-3.6-flash', 'display_name': 'Gemini 3.6 Flash',
        }, format='json')

    def test_saving_a_model_snapshots_its_price_with_a_timestamp(self):
        resp = self.client.get(reverse('ai_config'))
        pricing = resp.data['pricing']
        self.assertEqual(pricing['display_name'], 'Gemini 3.6 Flash')
        self.assertEqual(pricing['input_price_per_1m'], 0.75)
        self.assertEqual(pricing['output_price_per_1m'], 3.75)
        self.assertTrue(pricing['checked_at'])
        self.assertTrue(resp.data['pricing_source_url'].startswith('https://'))

    @patch('portfolio.ai_categorization.list_models')
    def test_refresh_restamps_and_reports_unchanged(self, m_list):
        m_list.return_value = [{
            'id': 'gemini-3.6-flash', 'display_name': 'Gemini 3.6 Flash',
            'input_price_per_1m': 0.75, 'output_price_per_1m': 3.75,
        }]
        before = self.client.get(reverse('ai_config')).data['pricing']['checked_at']
        resp = self.client.post(reverse('ai_refresh_pricing'), {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.data['changed'])
        self.assertTrue(resp.data['model_still_available'])
        self.assertGreaterEqual(resp.data['pricing']['checked_at'], before)

    @patch('portfolio.ai_categorization.list_models')
    def test_refresh_flags_a_model_the_key_no_longer_offers(self, m_list):
        m_list.return_value = [{
            'id': 'gemini-9-flash', 'display_name': 'Other',
            'input_price_per_1m': None, 'output_price_per_1m': None,
        }]
        resp = self.client.post(reverse('ai_refresh_pricing'), {}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['model_still_available'])

    def test_refresh_requires_configuration(self):
        self.client.delete(reverse('ai_config'))
        resp = self.client.post(reverse('ai_refresh_pricing'), {}, format='json')
        self.assertEqual(resp.status_code, 400)


class AiPricingBackfillTests(APITestCase):
    """A model chosen before pricing snapshots existed must still show a price."""

    def setUp(self):
        self.user, self.kek, _ = make_kek_user()
        self.client.force_authenticate(user=self.user)
        self.client.credentials(HTTP_X_KEK=self.kek)

    def test_config_get_fills_a_missing_pricing_snapshot(self):
        profile = self.user.profile
        profile.encrypted_gemini_key = b'blob'
        profile.gemini_model = 'gemini-3.7-flash'
        profile.gemini_pricing = None  # pre-existing configuration
        profile.save()

        resp = self.client.get(reverse('ai_config'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['pricing']['input_price_per_1m'], 0.75)
        self.assertEqual(resp.data['pricing']['model'], 'gemini-3.7-flash')
        # Persisted, so the timestamp does not move on every read.
        profile.refresh_from_db()
        self.assertIsNotNone(profile.gemini_pricing)
        stamped = profile.gemini_pricing['checked_at']
        self.assertEqual(
            self.client.get(reverse('ai_config')).data['pricing']['checked_at'],
            stamped,
        )

    def test_no_model_means_no_snapshot(self):
        resp = self.client.get(reverse('ai_config'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data['pricing'])
