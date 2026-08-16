"""Tests for portfolio models, serializers, and account/snapshot/sync endpoints."""
from datetime import date
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
        created = backfill_account_transactions(
            self.account, integration, date(2025, 1, 1), date(2025, 12, 31))
        self.assertEqual(created, 1)
        self.assertEqual(integration.calls[0], (date(2025, 1, 1), date(2025, 12, 31)))
        # Re-running the same range imports nothing new.
        self.assertEqual(
            backfill_account_transactions(
                self.account, integration, date(2025, 1, 1), date(2025, 12, 31)),
            0,
        )
        self.assertEqual(Transaction.objects.filter(account=self.account).count(), 1)


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
