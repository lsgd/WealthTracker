import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from time import time

logger = logging.getLogger(__name__)

# Discovery sessions stored in memory (requires single gunicorn worker for FinTS)
# FinTS client objects contain TCP connections that cannot be pickled/serialized
# Sessions expire after 10 minutes (photoTAN requires scanning + entering code)
DISCOVERY_SESSION_TIMEOUT = 600  # 10 minutes
_discovery_sessions: dict[str, dict] = {}


def _get_session(token: str) -> dict | None:
    """Get a session by token from in-memory storage."""
    return _discovery_sessions.get(token)


def _set_session(token: str, data: dict):
    """Set a session in in-memory storage."""
    _discovery_sessions[token] = data


def _delete_session(token: str):
    """Delete a session from in-memory storage."""
    _discovery_sessions.pop(token, None)


def _cleanup_expired_sessions():
    """Remove expired sessions from memory."""
    now = time()
    expired = [
        token for token, data in _discovery_sessions.items()
        if now - data.get('created_at', 0) > DISCOVERY_SESSION_TIMEOUT
    ]
    for token in expired:
        session = _discovery_sessions.pop(token, None)
        if session:
            integration = session.get('integration')
            if integration:
                try:
                    integration.close()
                except Exception:
                    pass


from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.kek_auth import KEKAuthenticationMixin
from exchange_rates.models import ExchangeRate

from .models import (
    AccountSnapshot,
    CategoryRule,
    FinancialAccount,
    Transaction,
    TransactionCategory,
)
from .serializers import (
    AccountSnapshotCreateSerializer,
    AccountSnapshotSerializer,
    CategoryRuleSerializer,
    FinancialAccountCreateSerializer,
    FinancialAccountSerializer,
    ManualTransactionUpdateSerializer,
    TransactionCategorySerializer,
    TransactionClassificationSerializer,
    TransactionCreateSerializer,
    TransactionSerializer,
)


class FinancialAccountListCreateView(generics.ListCreateAPIView):
    """List user's accounts or create a new one."""
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return FinancialAccountCreateSerializer
        return FinancialAccountSerializer

    def get_queryset(self):
        return FinancialAccount.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class FinancialAccountDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update or delete a financial account."""
    serializer_class = FinancialAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return FinancialAccount.objects.filter(user=self.request.user)


def _sync_single_account(*, account_id, credentials, base_currency):
    """Run on the sync worker thread. Syncs a single account."""
    import django
    django.db.connections.close_all()  # Get fresh DB connections for this thread

    from brokers.integrations import get_broker_integration

    account = FinancialAccount.objects.get(pk=account_id)
    integration = get_broker_integration(account.broker, credentials, account_id=account.id)

    try:
        auth_result = integration.authenticate()

        if not auth_result.success:
            if auth_result.requires_2fa:
                account.status = 'pending_auth'
                account.pending_auth_state = {
                    'two_fa_type': auth_result.two_fa_type,
                    'session_data': auth_result.session_data,
                }
                account.save()
                return {
                    'status': 'pending_auth',
                    'message': 'Two-factor authentication required',
                    'two_fa_type': auth_result.two_fa_type,
                    'challenge': auth_result.challenge_data,
                }
            else:
                account.status = 'error'
                account.last_sync_error = auth_result.error_message
                account.save()
                return {'status': 'error', 'error': auth_result.error_message}

        # Auth successful — fetch balance
        from brokers.integrations.base import NoNewDataError
        try:
            balance_info = integration.get_balance(account.account_identifier)
        except NoNewDataError as e:
            # Nothing new to record (e.g. EBICS 090005 on a quiet day). Not an error:
            # keep the account active and its last snapshot, advance last_sync_at.
            account.status = 'active'
            account.last_sync_at = timezone.now()
            account.last_sync_error = ''
            account.pending_auth_state = None
            account.save()
            logger.info("Sync: no new data for account %s (%s)", account.id, e)
            return {'status': 'success', 'message': 'No new data', 'snapshot': None}

        existing = AccountSnapshot.objects.filter(
            account=account,
            balance=balance_info.balance,
            currency=balance_info.currency,
            snapshot_date=balance_info.balance_date,
        ).first()

        if existing:
            snapshot = existing
            created = False
        else:
            snapshot = AccountSnapshot.objects.create(
                account=account,
                balance=balance_info.balance,
                currency=balance_info.currency,
                snapshot_date=balance_info.balance_date,
                snapshot_source='auto',
                raw_data=balance_info.raw_data,
            )
            created = True

        # Convert to base currency
        if balance_info.currency != base_currency:
            from exchange_rates.services import ExchangeRateService
            rate = ExchangeRateService.get_rate(
                balance_info.currency, base_currency, balance_info.balance_date,
            )
            if rate and rate != Decimal('1.0'):
                snapshot.balance_base_currency = balance_info.balance * rate
                snapshot.base_currency = base_currency
                snapshot.exchange_rate_used = rate
                snapshot.save()

        # Backfill historical data if supported
        backfilled_count = 0
        if integration.supports_historical_data():
            backfilled_count = _backfill_historical(
                account, integration, base_currency,
            )

        # Record the per-asset holdings behind this balance, where the broker reports
        # them. Same rule as the transaction import: never fail a balance sync that
        # already succeeded over a secondary fetch.
        position_count = 0
        if integration.supports_positions():
            try:
                from .snapshot_writer import store_positions
                position_count = store_positions(
                    snapshot, integration.get_positions(account.account_identifier),
                )
            except Exception:
                logger.exception("Position import failed for account %s", account.id)

        # Import booked transactions if supported. A transaction-import failure must
        # never fail the balance sync that already succeeded — log and move on.
        imported_tx_count = 0
        try:
            from .transaction_importer import import_account_transactions
            imported_tx_count = import_account_transactions(account, integration)
        except Exception:
            logger.exception("Transaction import failed for account %s", account.id)

        account.status = 'active'
        account.last_sync_at = timezone.now()
        account.last_sync_error = ''
        account.pending_auth_state = None
        account.save()

        message = 'Sync completed' if created else 'No change (snapshot already exists)'
        if backfilled_count > 0:
            message += f' + {backfilled_count} historical snapshots backfilled'
        if imported_tx_count > 0:
            message += f' + {imported_tx_count} transactions imported'
        if position_count > 0:
            message += f' + {position_count} positions recorded'

        return {
            'status': 'success',
            'message': message,
            'snapshot': {
                'id': snapshot.id,
                'balance': float(snapshot.balance),
                'currency': snapshot.currency,
                'date': snapshot.snapshot_date.isoformat(),
                'created': created,
            },
            'backfilled': backfilled_count,
        }
    finally:
        integration.close()


def _sync_all_accounts(*, account_creds, base_currency):
    """Run on the sync worker thread. Syncs all accounts sequentially."""
    import django
    django.db.connections.close_all()

    from brokers.integrations import get_broker_integration

    results = {
        'synced': [],
        'pending_2fa': [],
        'errors': [],
        'skipped': [],
    }

    for account_id, credentials in account_creds:
        try:
            account = FinancialAccount.objects.get(pk=account_id)
            integration = get_broker_integration(account.broker, credentials, account_id=account.id)

            try:
                auth_result = integration.authenticate()

                if not auth_result.success:
                    if auth_result.requires_2fa:
                        account.status = 'pending_auth'
                        account.pending_auth_state = {
                            'two_fa_type': auth_result.two_fa_type,
                            'session_data': auth_result.session_data,
                        }
                        account.save()
                        results['pending_2fa'].append({
                            'id': account.id,
                            'name': account.name,
                            'two_fa_type': auth_result.two_fa_type,
                        })
                        continue
                    else:
                        account.status = 'error'
                        account.last_sync_error = auth_result.error_message
                        account.save()
                        results['errors'].append({
                            'id': account.id,
                            'name': account.name,
                            'error': auth_result.error_message,
                        })
                        continue

                from brokers.integrations.base import NoNewDataError
                try:
                    balance_info = integration.get_balance(account.account_identifier)
                except NoNewDataError:
                    # Routine "nothing new" (e.g. EBICS 090005) — a skip, not an error.
                    account.status = 'active'
                    account.last_sync_at = timezone.now()
                    account.last_sync_error = ''
                    account.pending_auth_state = None
                    account.save()
                    results['skipped'].append({
                        'id': account.id, 'name': account.name, 'reason': 'No new data',
                    })
                    continue

                existing = AccountSnapshot.objects.filter(
                    account=account,
                    balance=balance_info.balance,
                    currency=balance_info.currency,
                    snapshot_date=balance_info.balance_date,
                ).first()

                if existing:
                    results['skipped'].append({
                        'id': account.id,
                        'name': account.name,
                        'reason': 'No change',
                    })
                else:
                    snapshot = AccountSnapshot.objects.create(
                        account=account,
                        balance=balance_info.balance,
                        currency=balance_info.currency,
                        snapshot_date=balance_info.balance_date,
                        snapshot_source='auto',
                        raw_data=balance_info.raw_data,
                    )

                    if balance_info.currency != base_currency:
                        from exchange_rates.services import ExchangeRateService
                        rate = ExchangeRateService.get_rate(
                            balance_info.currency, base_currency,
                            balance_info.balance_date,
                        )
                        if rate and rate != Decimal('1.0'):
                            snapshot.balance_base_currency = balance_info.balance * rate
                            snapshot.base_currency = base_currency
                            snapshot.exchange_rate_used = rate
                            snapshot.save()

                    results['synced'].append({
                        'id': account.id,
                        'name': account.name,
                        'balance': float(balance_info.balance),
                        'currency': balance_info.currency,
                    })

                # Snapshot every other day the broker delivered too (e.g. an EBICS
                # camt.053 backlog), not just the latest — otherwise those are lost.
                if integration.supports_historical_data():
                    _backfill_historical(account, integration, base_currency)

                # Import booked transactions; a failure here must not fail the sync.
                try:
                    from .transaction_importer import import_account_transactions
                    import_account_transactions(account, integration)
                except Exception:
                    logger.exception("Transaction import failed for account %s", account.id)

                account.status = 'active'
                account.last_sync_at = timezone.now()
                account.last_sync_error = ''
                account.pending_auth_state = None
                account.save()

            finally:
                integration.close()

        except Exception as e:
            logger.exception("Sync failed for account %s", account_id)
            try:
                account = FinancialAccount.objects.get(pk=account_id)
                account.status = 'error'
                account.last_sync_error = str(e) or repr(e)
                account.save()
            except Exception:
                pass
            results['errors'].append({
                'id': account_id,
                'name': getattr(account, 'name', str(account_id)),
                'error': str(e) or repr(e),
            })

    return {
        'status': 'success',
        'synced_count': len(results['synced']),
        'pending_2fa_count': len(results['pending_2fa']),
        'error_count': len(results['errors']),
        'skipped_count': len(results['skipped']),
        'details': results,
    }


def _backfill_historical(account, integration, base_currency):
    """
    Backfill historical snapshots from broker if available.
    Returns the number of snapshots created.

    Strategy:
    - Look at past HISTORICAL_BACKFILL_MAX_LOOKBACK_DAYS (365) days
    - Find oldest missing date (gap) in that window
    - Request from that date + HISTORICAL_BACKFILL_BUFFER_DAYS (5) buffer
    - Max request is 365 + 5 = 370 days
    - Skip if already have good recent coverage
    """
    from django.conf import settings as django_settings

    try:
        max_lookback = getattr(django_settings, 'HISTORICAL_BACKFILL_MAX_LOOKBACK_DAYS', 365)
        buffer_days = getattr(django_settings, 'HISTORICAL_BACKFILL_BUFFER_DAYS', 5)
        skip_if_recent_days = getattr(django_settings, 'HISTORICAL_BACKFILL_SKIP_IF_RECENT_DAYS', 2)

        existing_dates = set(
            AccountSnapshot.objects.filter(account=account)
            .values_list('snapshot_date', flat=True)
        )

        end_date = date.today()

        if integration.historical_data_requires_extra_request():
            oldest_gap = None
            for days_ago in range(max_lookback, skip_if_recent_days, -1):
                check_date = end_date - timedelta(days=days_ago)
                if check_date not in existing_dates:
                    oldest_gap = check_date
                    break

            if oldest_gap is None:
                return 0

            start_date = oldest_gap - timedelta(days=buffer_days)
            max_start = end_date - timedelta(days=max_lookback + buffer_days)
            if start_date < max_start:
                start_date = max_start
        else:
            start_date = end_date - timedelta(days=3650)

        logger.info(f"Backfilling {account.name} historical data from {start_date} to {end_date}")

        historical = integration.get_historical_balances(
            account.account_identifier, start_date, end_date
        )

        if not historical:
            return 0

        from .snapshot_writer import upsert_daily_snapshot

        created_count = 0
        for bal_info in historical:
            if bal_info.balance_date in existing_dates:
                continue
            # Gap-fill only: never clobber an existing snapshot for that date here.
            upsert_daily_snapshot(account, bal_info, base_currency)
            created_count += 1
            existing_dates.add(bal_info.balance_date)

        logger.info(f"Backfilled {created_count} snapshots for {account.name}")
        return created_count

    except Exception as e:
        logger.warning(f"Failed to backfill historical data for {account.name}: {e}")
        return 0


def _backfill_transactions_worker(*, account_id, credentials, start_date, end_date):
    """Run on the sync worker thread: fetch transactions for an explicit range."""
    import django
    django.db.connections.close_all()

    from brokers.integrations import get_broker_integration

    from .transaction_importer import backfill_account_transactions

    account = FinancialAccount.objects.get(pk=account_id)
    integration = get_broker_integration(account.broker, credentials, account_id=account.id)
    try:
        auth_result = integration.authenticate()
        if not auth_result.success:
            return {
                'status': 'error',
                'error': auth_result.error_message or 'Authentication failed',
            }
        if not integration.supports_transactions():
            return {
                'status': 'error',
                'error': f'{account.broker.name} does not support transaction download.',
            }
        result = backfill_account_transactions(
            account, integration, start_date, end_date,
        )
        return {
            'status': 'success',
            'imported': result.imported,
            'fetched': result.fetched,
            'covered_start': result.covered_start.isoformat() if result.covered_start else None,
            'covered_end': result.covered_end.isoformat() if result.covered_end else None,
            'truncated': result.is_truncated,
            'message': result.describe(),
        }
    finally:
        integration.close()


class AccountTransactionBackfillView(KEKAuthenticationMixin, APIView):
    """Fetch historical transactions for an explicit date range (web only).

    The regular sync only walks forward from the newest stored transaction; this
    pulls an arbitrary past window on demand. Storage is idempotent, so an
    overlapping range adds nothing. Whether a bank actually re-serves old data is
    bank-specific (EBICS dated downloads often do; FinTS usually has a limit of
    ~90 days).

    Body: ``start`` and ``end`` as ISO dates (``end`` defaults to today).
    Returns a queued task id — poll it via the existing sync-task endpoint.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from .sync_queue import sync_queue

        try:
            account = FinancialAccount.objects.get(pk=pk, user=request.user)
        except FinancialAccount.DoesNotExist:
            return Response({'error': 'Account not found'}, status=status.HTTP_404_NOT_FOUND)

        if account.is_manual:
            return Response(
                {'error': 'Manual accounts have no transaction feed'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not account.encrypted_credentials and not account.ebics_credential_id:
            return Response({'error': 'No credentials configured'},
                            status=status.HTTP_400_BAD_REQUEST)
        if account.ebics_credential_id and account.ebics_credential.state != 'active':
            return Response({'error': 'EBICS access is not active yet.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            start_date = date.fromisoformat(request.data['start'])
            end_date = (
                date.fromisoformat(request.data['end'])
                if request.data.get('end') else date.today()
            )
        except (KeyError, TypeError, ValueError):
            return Response(
                {'error': 'Provide "start" (and optionally "end") as ISO dates, e.g. 2025-01-01'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if start_date > end_date:
            return Response({'error': 'Start date must be before end date'},
                            status=status.HTTP_400_BAD_REQUEST)

        existing = sync_queue.has_pending_task(request.user.id)
        if existing:
            return Response({
                'status': 'queued', 'task_id': existing,
                'message': 'A sync is already in progress',
            })

        try:
            credentials = self.decrypt_sync_credentials(request, account)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        task_id = sync_queue.enqueue(
            request.user.id,
            _backfill_transactions_worker,
            account_id=account.id,
            credentials=credentials,
            start_date=start_date,
            end_date=end_date,
        )
        return Response({
            'status': 'queued', 'task_id': task_id,
            'message': f'Fetching transactions from {start_date} to {end_date}',
        })


class AccountSyncView(KEKAuthenticationMixin, APIView):
    """Trigger a sync for an account.

    Decrypts credentials on the request thread, then enqueues the actual
    sync work to a dedicated background thread so other API requests
    (graphs, snapshots) are not blocked.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from .sync_queue import sync_queue

        try:
            account = FinancialAccount.objects.get(pk=pk, user=request.user)
        except FinancialAccount.DoesNotExist:
            return Response({'error': 'Account not found'}, status=status.HTTP_404_NOT_FOUND)

        if account.is_manual:
            return Response({'error': 'Cannot sync manual accounts'}, status=status.HTTP_400_BAD_REQUEST)

        # EBICS accounts carry their secret on the shared credential, not here.
        if not account.encrypted_credentials and not account.ebics_credential_id:
            return Response({'error': 'No credentials configured'}, status=status.HTTP_400_BAD_REQUEST)

        # An EBICS account can't sync until the bank activates the subscriber's keys.
        # Until then it behaves like a manual account (add snapshots by hand).
        if account.ebics_credential_id and account.ebics_credential.state != 'active':
            return Response(
                {'error': 'EBICS access is not active yet. Add snapshots manually '
                          'until the bank activates your key exchange.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check for already-running sync for this user
        existing = sync_queue.has_pending_task(request.user.id)
        if existing:
            return Response({
                'status': 'queued',
                'task_id': existing,
                'message': 'A sync is already in progress',
            })

        try:
            # Decrypt credentials on the request thread (needs KEK header).
            # For EBICS accounts this pulls the shared credential's keyring.
            credentials = self.decrypt_sync_credentials(request, account)
            base_currency = request.user.profile.base_currency
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Enqueue sync work to background thread
        task_id = sync_queue.enqueue(
            request.user.id,
            _sync_single_account,
            account_id=account.id,
            credentials=credentials,
            base_currency=base_currency,
        )

        return Response({
            'status': 'queued',
            'task_id': task_id,
            'message': 'Sync started',
        })


class SyncAllAccountsView(KEKAuthenticationMixin, APIView):
    """Trigger sync for all accounts that support auto-sync.

    Decrypts all credentials on the request thread, then enqueues the
    sync work to run sequentially on the background thread.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .sync_queue import sync_queue

        # Check for already-running sync for this user
        existing = sync_queue.has_pending_task(request.user.id)
        if existing:
            return Response({
                'status': 'queued',
                'task_id': existing,
                'message': 'A sync is already in progress',
            })

        # Find all syncable accounts: those with stored credentials, OR EBICS
        # accounts whose secret lives on a shared, *activated* credential. An EBICS
        # credential that hasn't completed its key exchange with the bank yet
        # (state != 'active') can't sync, so it's excluded here — the account is
        # treated like a manual one until the bank activates it.
        from django.db.models import Q
        accounts = FinancialAccount.objects.filter(
            user=request.user,
            is_manual=False,
            sync_enabled=True,
        ).filter(
            ~Q(encrypted_credentials__isnull=True) & ~Q(encrypted_credentials=b'')
            | Q(ebics_credential__state='active')
        ).select_related('broker', 'ebics_credential')

        if not accounts.exists():
            return Response({
                'status': 'success',
                'message': 'No accounts to sync',
                'synced_count': 0,
                'pending_2fa_count': 0,
                'error_count': 0,
                'skipped_count': 0,
                'details': {'synced': [], 'pending_2fa': [], 'errors': [], 'skipped': []},
            })

        # Decrypt all credentials on the request thread (needs KEK header)
        base_currency = request.user.profile.base_currency
        account_creds = []
        for account in accounts:
            try:
                creds = self.decrypt_sync_credentials(request, account)
                account_creds.append((account.id, creds))
            except Exception as e:
                logger.warning("Failed to decrypt credentials for account %s: %s", account.id, e)

        if not account_creds:
            return Response({
                'error': 'Failed to decrypt credentials for all accounts',
            }, status=status.HTTP_400_BAD_REQUEST)

        # Enqueue sync work to background thread
        task_id = sync_queue.enqueue(
            request.user.id,
            _sync_all_accounts,
            account_creds=account_creds,
            base_currency=base_currency,
        )

        return Response({
            'status': 'queued',
            'task_id': task_id,
            'message': f'Sync started for {len(account_creds)} accounts',
        })


class SyncTaskStatusView(APIView):
    """Poll for the status of a background sync task."""
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        from .sync_queue import sync_queue

        result = sync_queue.get_status(task_id)
        if result is None:
            return Response(
                {'error': 'Task not found or expired'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(result)


class AccountAuthView(KEKAuthenticationMixin, APIView):
    """Handle 2FA authentication for an account."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from brokers.integrations import get_broker_integration

        try:
            account = FinancialAccount.objects.get(pk=pk, user=request.user)
        except FinancialAccount.DoesNotExist:
            return Response({'error': 'Account not found'}, status=status.HTTP_404_NOT_FOUND)

        if account.status != 'pending_auth':
            return Response(
                {'error': 'Account is not pending authentication'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not account.pending_auth_state:
            return Response(
                {'error': 'No pending auth state. Please initiate sync first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        auth_code = request.data.get('auth_code')
        session_data = account.pending_auth_state.get('session_data', {})

        try:
            # Decrypt credentials and get integration
            credentials = self.decrypt_account_credentials(request, account)
            integration = get_broker_integration(account.broker, credentials, account_id=account.id)

            # Re-authenticate to restore session
            auth_result = integration.authenticate()

            if auth_result.requires_2fa:
                # Complete 2FA
                auth_result = integration.complete_2fa(auth_code, session_data)

                if not auth_result.success:
                    return Response(
                        {'error': auth_result.error_message or '2FA failed'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # 2FA successful, complete the sync
            sync_view = AccountSyncView()
            return sync_view._complete_sync(account, integration, request)

        except Exception as e:
            account.status = 'error'
            account.last_sync_error = str(e)
            account.save()
            return Response(
                {'error': f'Authentication failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AccountCredentialsView(KEKAuthenticationMixin, APIView):
    """Get or update credentials for an account."""
    permission_classes = [IsAuthenticated]

    # Fields that should be masked when returning credentials
    SENSITIVE_FIELDS = ('password', 'pin', 'secret', 'flex_token', 'token', 'api_key')

    def get(self, request, pk):
        """Get current credentials with sensitive fields masked."""
        try:
            account = FinancialAccount.objects.get(pk=pk, user=request.user)
        except FinancialAccount.DoesNotExist:
            return Response({'error': 'Account not found'}, status=status.HTTP_404_NOT_FOUND)

        if account.is_manual:
            return Response({'credentials': {}})

        if not account.encrypted_credentials:
            return Response({'credentials': {}})

        try:
            credentials = self.decrypt_account_credentials(request, account)
            # Mask sensitive fields
            masked = {}
            for key, value in credentials.items():
                if any(s in key.lower() for s in self.SENSITIVE_FIELDS):
                    # Show masked placeholder if value exists
                    masked[key] = '••••••••' if value else ''
                else:
                    masked[key] = value
            return Response({'credentials': masked})
        except Exception:
            return Response({'credentials': {}})

    def put(self, request, pk):
        try:
            account = FinancialAccount.objects.get(pk=pk, user=request.user)
        except FinancialAccount.DoesNotExist:
            return Response({'error': 'Account not found'}, status=status.HTTP_404_NOT_FOUND)

        if account.is_manual:
            return Response(
                {'error': 'Manual accounts do not have credentials'},
                status=status.HTTP_400_BAD_REQUEST
            )

        credentials = request.data.get('credentials')
        if not credentials:
            return Response(
                {'error': 'Credentials are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get existing credentials to merge with
        existing = {}
        if account.encrypted_credentials:
            try:
                existing = self.decrypt_account_credentials(request, account)
            except Exception:
                pass

        # Merge: only update fields that have non-empty, non-masked values
        one_time_fields = ('token', 'totp_token', 'otp', 'tan', 'sms_code')
        for key, value in credentials.items():
            if key in one_time_fields:
                continue
            # Skip empty values and masked placeholders
            if value and value != '••••••••':
                existing[key] = value

        account.encrypted_credentials = self.encrypt_account_credentials(request, existing)
        account.status = 'active'  # Reset status since credentials were updated
        account.last_sync_error = ''
        account.save()

        return Response({'status': 'success', 'message': 'Credentials updated'})


class AccountSnapshotListCreateView(generics.ListCreateAPIView):
    """List snapshots for an account or create a manual one."""
    permission_classes = [IsAuthenticated]
    serializer_class = AccountSnapshotSerializer

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return AccountSnapshotCreateSerializer
        return AccountSnapshotSerializer

    def create(self, request, *args, **kwargs):
        """Override to return full snapshot data after creation."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # Return full snapshot using read serializer
        snapshot = serializer.instance
        response_serializer = AccountSnapshotSerializer(snapshot)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def get_queryset(self):
        account_id = self.kwargs['account_id']
        return AccountSnapshot.objects.filter(
            account_id=account_id,
            account__user=self.request.user
        )

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError

        account_id = self.kwargs['account_id']
        account = FinancialAccount.objects.get(pk=account_id, user=self.request.user)

        # Check for duplicate snapshot (same date, currency, and balance)
        balance = serializer.validated_data.get('balance')
        currency = serializer.validated_data.get('currency')
        snapshot_date = serializer.validated_data.get('snapshot_date')

        existing = AccountSnapshot.objects.filter(
            account=account,
            balance=balance,
            currency=currency,
            snapshot_date=snapshot_date
        ).exists()

        if existing:
            raise ValidationError({
                'detail': 'A snapshot with the same date, currency, and balance already exists.'
            })

        snapshot = serializer.save(account=account)

        # Convert to base currency
        user_profile = self.request.user.profile
        if snapshot.currency != user_profile.base_currency:
            rate = ExchangeRate.get_rate(
                snapshot.currency,
                user_profile.base_currency,
                snapshot.snapshot_date
            )
            # Fetch exchange rates (ranged, closing the whole gap) if missing
            if not rate:
                from exchange_rates.services import ExchangeRateService
                try:
                    ExchangeRateService.fill_gap_before(
                        snapshot.snapshot_date,
                        snapshot.currency, user_profile.base_currency,
                    )
                    # Retry getting rate after fetch
                    rate = ExchangeRate.get_rate(
                        snapshot.currency,
                        user_profile.base_currency,
                        snapshot.snapshot_date
                    )
                except Exception:
                    pass  # Will leave base_currency fields empty if fetch fails
            if rate:
                snapshot.balance_base_currency = snapshot.balance * rate
                snapshot.base_currency = user_profile.base_currency
                snapshot.exchange_rate_used = rate
                snapshot.save()


class AccountSnapshotDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, or delete a snapshot."""
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return AccountSnapshotCreateSerializer
        return AccountSnapshotSerializer

    def get_queryset(self):
        return AccountSnapshot.objects.filter(account__user=self.request.user)

    def perform_update(self, serializer):
        snapshot = serializer.save()
        # Recalculate base currency conversion
        user_profile = self.request.user.profile
        if snapshot.currency != user_profile.base_currency:
            rate = ExchangeRate.get_rate(
                snapshot.currency,
                user_profile.base_currency,
                snapshot.snapshot_date
            )
            # Fetch exchange rates (ranged, closing the whole gap) if missing
            if not rate:
                from exchange_rates.services import ExchangeRateService
                try:
                    ExchangeRateService.fill_gap_before(
                        snapshot.snapshot_date,
                        snapshot.currency, user_profile.base_currency,
                    )
                    # Retry getting rate after fetch
                    rate = ExchangeRate.get_rate(
                        snapshot.currency,
                        user_profile.base_currency,
                        snapshot.snapshot_date
                    )
                except Exception:
                    pass
            if rate:
                snapshot.balance_base_currency = snapshot.balance * rate
                snapshot.base_currency = user_profile.base_currency
                snapshot.exchange_rate_used = rate
            else:
                snapshot.balance_base_currency = None
                snapshot.base_currency = None
                snapshot.exchange_rate_used = None
        else:
            # Same currency, no conversion needed
            snapshot.balance_base_currency = snapshot.balance
            snapshot.base_currency = user_profile.base_currency
            snapshot.exchange_rate_used = Decimal('1')
        snapshot.save()


_CSV_IMPORT_MAX_SIZE = 5 * 1024 * 1024


def _read_csv_upload(request):
    """(content bytes, None) or (None, error Response)."""
    upload = request.FILES.get('file')
    if upload is None:
        return None, Response({'error': 'Attach the CSV as "file"'}, status=400)
    if upload.size > _CSV_IMPORT_MAX_SIZE:
        return None, Response({'error': 'File is larger than 5 MB'}, status=400)
    return upload.read(), None


def _import_parsed_csv(request, account, fmt, currency, infos, skipped):
    """Common tail of the CSV import views: guards, storage, classification."""
    from .transaction_importer import store_transactions

    if not infos:
        return Response({'error': 'No importable rows found in the file'}, status=400)
    # The exports are per account — a currency mismatch means the file
    # belongs to a different account. Refuse rather than corrupt.
    if currency != account.currency:
        return Response({
            'error': f'The file contains {currency} entries but the account '
                     f'"{account.name}" is in {account.currency}. '
                     'Pick the matching account.',
        }, status=400)

    imported = store_transactions(account, infos, source='csv')
    if imported:
        from .classification import apply_rules, detect_transfers
        apply_rules(request.user)
        detect_transfers(request.user)

    dates = [i.booking_date for i in infos]
    covered_start, covered_end = min(dates), max(dates)
    message = f'{imported} new transactions imported into {account.name}'
    if imported != len(infos):
        message += f' ({len(infos)} rows read, the rest were already stored)'
    message += f'. The file covers {covered_start} to {covered_end}.'

    return Response({
        'status': 'success',
        'format': fmt,
        'account_id': account.id,
        'account_name': account.name,
        'imported': imported,
        'fetched': len(infos),
        'skipped': skipped,
        'covered_start': covered_start,
        'covered_end': covered_end,
        'message': message,
    })


class AccountTransactionCsvImportView(APIView):
    """Import a bank CSV export into one specific account (web-only backfill).

    Multipart body: ``file`` — a per-account export from the bank's online
    banking (ZKB "with details" or DKB; format is auto-detected). Storage is
    the same idempotent importer the sync paths use, so re-importing a file
    (or an overlapping export) creates nothing new; ZKB rows even dedup
    against EBICS-synced entries via the shared bank reference.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from .csv_import import CsvImportError, parse_transactions_csv

        try:
            account = FinancialAccount.objects.get(pk=pk, user=request.user)
        except FinancialAccount.DoesNotExist:
            return Response({'error': 'Account not found'}, status=404)

        content, error = _read_csv_upload(request)
        if error is not None:
            return error
        try:
            fmt, currency, infos, skipped, file_iban = parse_transactions_csv(
                content, account.currency,
            )
        except CsvImportError as e:
            return Response({'error': str(e)}, status=400)

        # When the file names its own account (DKB preamble IBAN), a mismatch
        # with the chosen account is a wrong-file mistake — refuse.
        own = (account.account_identifier or '').replace(' ', '').upper()
        if file_iban and own and file_iban != own:
            return Response({
                'error': f'The file belongs to {file_iban}, not to '
                         f'"{account.name}". Pick the matching account.',
            }, status=400)

        return _import_parsed_csv(request, account, fmt, currency, infos, skipped)


class TransactionCsvImportView(APIView):
    """Import a bank CSV export, resolving the target account from the file.

    DKB exports name their own IBAN in the preamble — matched against the
    account identifiers. ZKB and Swisscard exports carry no identifier: the
    format names its bank, so candidates are narrowed to accounts of that
    broker when the user has any, then by currency. When exactly one account
    remains the choice is unambiguous, otherwise the response lists the
    candidates (``status: 'ambiguous'``) and the client retries via the
    per-account endpoint.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .csv_import import CsvImportError, parse_transactions_csv

        content, error = _read_csv_upload(request)
        if error is not None:
            return error
        try:
            fmt, currency, infos, skipped, file_iban = parse_transactions_csv(content, '')
        except CsvImportError as e:
            return Response({'error': str(e)}, status=400)

        accounts = list(FinancialAccount.objects.filter(user=request.user))
        if file_iban:
            account = next(
                (a for a in accounts
                 if (a.account_identifier or '').replace(' ', '').upper() == file_iban),
                None,
            )
            if account is None:
                return Response({
                    'error': f'The file belongs to {file_iban}, but no account '
                             'has that identifier. Use the import action on the '
                             'account itself.',
                }, status=400)
            return _import_parsed_csv(request, account, fmt, currency, infos, skipped)

        candidates = [a for a in accounts if a.currency == currency]
        # The format identifies the bank: a Swisscard export belongs to a
        # Swisscard account, not to the CHF bank account that settles it.
        same_broker = [a for a in candidates if a.broker.code == fmt]
        if same_broker:
            candidates = same_broker
        if len(candidates) == 1:
            return _import_parsed_csv(
                request, candidates[0], fmt, currency, infos, skipped,
            )
        if not candidates:
            return Response({
                'error': f'The file contains {currency} entries but no account '
                         f'uses {currency}.',
            }, status=400)
        return Response({
            'status': 'ambiguous',
            'format': fmt,
            'currency': currency,
            'accounts': [{'id': a.id, 'name': a.name} for a in candidates],
        })


class TransactionListView(generics.ListAPIView):
    """All of the user's transactions, newest first, across accounts.

    Optional query params: ``account`` (id, restrict to one account),
    ``uncategorized`` (truthy, only transactions without a category),
    ``category`` (id, or ``transfer`` for transfers only).
    """
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionSerializer

    def get_queryset(self):
        # select_related: the serializer reads category.name per row.
        qs = Transaction.objects.filter(
            account__user=self.request.user,
        ).select_related('category')
        account = self.request.query_params.get('account')
        if account:
            qs = qs.filter(account_id=account)
        if self.request.query_params.get('uncategorized') in ('1', 'true'):
            qs = qs.filter(category__isnull=True)
        category = self.request.query_params.get('category')
        if category == 'transfer':
            qs = qs.filter(is_transfer=True)
        elif category:
            # Own categories only — an id from another user must not leak rows.
            qs = qs.filter(category_id=category, category__user=self.request.user)
        return qs


class AccountTransactionListCreateView(generics.ListCreateAPIView):
    """List transactions for an account or create a manual one.

    Optional query params: ``start`` / ``end`` (ISO dates, filter on booking_date).
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TransactionCreateSerializer
        return TransactionSerializer

    def get_queryset(self):
        qs = Transaction.objects.filter(
            account_id=self.kwargs['account_id'],
            account__user=self.request.user,
        ).select_related('category')
        start = self.request.query_params.get('start')
        end = self.request.query_params.get('end')
        if start:
            qs = qs.filter(booking_date__gte=start)
        if end:
            qs = qs.filter(booking_date__lte=end)
        return qs

    def create(self, request, *args, **kwargs):
        """Override to return full transaction data after creation."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            TransactionSerializer(serializer.instance).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_create(self, serializer):
        account = FinancialAccount.objects.get(
            pk=self.kwargs['account_id'], user=self.request.user,
        )
        currency = serializer.validated_data.get('currency') or account.currency
        serializer.save(account=account, currency=currency)


class TransactionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, or delete a transaction.

    Imported rows mirror the bank's statement: their financial fields are
    read-only and they cannot be deleted (they would be re-imported on the next
    sync anyway) — but their *classification* (category, spread, transfer flag)
    is always the user's to change. Manual transactions are fully editable.
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            if self.get_object().source == 'manual':
                return ManualTransactionUpdateSerializer
            return TransactionClassificationSerializer
        return TransactionSerializer

    def get_queryset(self):
        return Transaction.objects.filter(account__user=self.request.user)

    def update(self, request, *args, **kwargs):
        """Override to return the full transaction after a partial update."""
        super().update(request, *args, **kwargs)
        return Response(TransactionSerializer(self.get_object()).data)

    def perform_destroy(self, instance):
        if instance.source != 'manual':
            from rest_framework.exceptions import ValidationError
            raise ValidationError({
                'detail': 'Only manual transactions can be deleted. '
                          'Imported transactions mirror the bank statement.'
            })
        instance.delete()


class TransactionCategoryListCreateView(generics.ListCreateAPIView):
    """List or create the user's spending categories."""
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionCategorySerializer
    pagination_class = None

    def get_queryset(self):
        return TransactionCategory.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class TransactionCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TransactionCategorySerializer

    def get_queryset(self):
        return TransactionCategory.objects.filter(user=self.request.user)


class CategoryRuleListCreateView(generics.ListCreateAPIView):
    """List or create category rules. Creating a rule applies it retroactively
    to all still-uncategorized transactions."""
    permission_classes = [IsAuthenticated]
    serializer_class = CategoryRuleSerializer
    pagination_class = None

    def get_queryset(self):
        return CategoryRule.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        from .classification import apply_rules, next_rule_position

        serializer.save(user=self.request.user, position=next_rule_position(self.request.user))
        apply_rules(self.request.user)


class CategoryRuleDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CategoryRuleSerializer

    def get_queryset(self):
        return CategoryRule.objects.filter(user=self.request.user)


class CategoryRuleReorderView(APIView):
    """Set the evaluation order of the user's rules.

    Body: ``ids`` — the rule ids in the desired order. Rules the payload omits
    keep their relative order after the listed ones, so a partial or stale list
    can never drop a rule out of the ordering.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ids = request.data.get('ids')
        if not isinstance(ids, list):
            return Response({'error': 'Provide "ids" as a list of rule ids'}, status=400)

        rules = {r.id: r for r in CategoryRule.objects.filter(user=request.user)}
        ordered = [rules[i] for i in ids if i in rules]
        ordered += [r for r in rules.values() if r.id not in set(ids)]

        for position, rule in enumerate(ordered):
            rule.position = position
        CategoryRule.objects.bulk_update(ordered, ['position'])
        return Response(CategoryRuleSerializer(ordered, many=True).data)


class CategoryRulesReplaceView(APIView):
    """Atomically replace the user's whole rule set (confirmed consolidation).

    Body: ``rules`` — [{match_text, category, spread_months}] in evaluation
    order. Categories must already exist (consolidation never invents them),
    and an invalid or duplicate entry rejects the whole payload — silently
    dropping entries would shrink the rule set behind the user's back. The new
    set is re-applied to still-uncategorized transactions afterwards.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.db import transaction as db_transaction

        from .classification import apply_rules

        items = request.data.get('rules')
        if not isinstance(items, list) or not items:
            return Response({'error': 'Provide "rules" as a non-empty list'}, status=400)

        categories = {
            c.name.lower(): c
            for c in TransactionCategory.objects.filter(user=request.user)
        }
        import re as re_module

        new_rules = []
        seen = set()
        for item in items:
            match_text = str(item.get('match_text', '')).strip().lower()[:128]
            is_regex = bool(item.get('is_regex'))
            is_transfer = bool(item.get('is_transfer'))
            category = None if is_transfer else categories.get(
                str(item.get('category', '')).strip().lower())
            try:
                spread = max(1, int(item.get('spread_months', 1)))
            except (TypeError, ValueError):
                return Response({'error': f'Invalid spread_months: {item}'}, status=400)
            if not match_text or (category is None and not is_transfer) \
                    or match_text in seen:
                return Response({'error': f'Invalid or duplicate rule: {item}'}, status=400)
            if is_regex:
                try:
                    re_module.compile(match_text)
                except re_module.error as e:
                    return Response(
                        {'error': f'Invalid regular expression "{match_text}": {e}'},
                        status=400)
            seen.add(match_text)
            new_rules.append(CategoryRule(
                user=request.user, match_text=match_text, category=category,
                spread_months=spread, position=len(new_rules),
                is_regex=is_regex, is_transfer=is_transfer,
            ))

        with db_transaction.atomic():
            CategoryRule.objects.filter(user=request.user).delete()
            CategoryRule.objects.bulk_create(new_rules)

        applied = apply_rules(request.user)
        return Response({
            'status': 'success',
            'count': len(new_rules),
            'rule_applied': applied,
        })


class DetectTransfersView(APIView):
    """Re-run transfer detection across all of the user's accounts."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .classification import detect_transfers
        marked = detect_transfers(request.user)
        return Response({'status': 'success', 'marked': marked})


class AiConfigView(KEKAuthenticationMixin, APIView):
    """Configure Gemini-assisted categorization (API key + model).

    The API key is a user secret and is stored encrypted under the per-user key
    (same KEK scheme as account credentials), so reads/writes require the KEK.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .ai_categorization import (
            DISCLOSED_FIELDS,
            PRICING_SOURCE_URL,
            pricing_snapshot,
        )
        profile = request.user.profile
        # A model selected before pricing snapshots existed has none stored.
        # Fill it in from the local rate table (no API call) so the UI can
        # always show what the selected model costs.
        if profile.gemini_model and not profile.gemini_pricing:
            profile.gemini_pricing = pricing_snapshot(profile.gemini_model)
            profile.save(update_fields=['gemini_pricing'])
        return Response({
            'configured': bool(profile.encrypted_gemini_key),
            'model': profile.gemini_model,
            'pricing': profile.gemini_pricing,
            'pricing_source_url': PRICING_SOURCE_URL,
            'disclosed_fields': DISCLOSED_FIELDS,
        })

    def put(self, request):
        from .ai_categorization import pricing_snapshot

        profile = request.user.profile
        api_key = request.data.get('api_key')
        model = request.data.get('model')
        if api_key:
            profile.encrypted_gemini_key = self.encrypt_blob(request, {'api_key': api_key})
        if model is not None and model != profile.gemini_model:
            profile.gemini_model = model
            # Snapshot what the price was when the user picked this model, so the
            # UI can show how old that figure is.
            profile.gemini_pricing = pricing_snapshot(
                model, request.data.get('display_name'),
            )
        profile.save()
        return Response({'status': 'success', 'configured': bool(profile.encrypted_gemini_key),
                         'model': profile.gemini_model, 'pricing': profile.gemini_pricing})

    def delete(self, request):
        profile = request.user.profile
        profile.encrypted_gemini_key = None
        profile.gemini_model = ''
        profile.gemini_pricing = None
        profile.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AiRefreshPricingView(KEKAuthenticationMixin, APIView):
    """Re-check the selected model's listed price and stamp the check time.

    Prices are not available from any Google API, so they come from a table
    maintained in this app (updated with each release). This re-reads that table,
    confirms the model is still offered to the user's key, and records when the
    check happened — so the UI can show how current the figure is.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .ai_categorization import GeminiError, list_models, pricing_snapshot

        profile = request.user.profile
        if not profile.encrypted_gemini_key or not profile.gemini_model:
            return Response({'error': 'Gemini is not configured'}, status=400)
        api_key = self.decrypt_blob(request, profile.encrypted_gemini_key)['api_key']

        try:
            models = list_models(api_key)
        except GeminiError as e:
            return Response({'error': str(e)}, status=502)

        match = next((m for m in models if m['id'] == profile.gemini_model), None)
        previous = profile.gemini_pricing or {}
        profile.gemini_pricing = pricing_snapshot(
            profile.gemini_model,
            match['display_name'] if match else previous.get('display_name'),
        )
        profile.save(update_fields=['gemini_pricing'])

        changed = (
            previous.get('input_price_per_1m') != profile.gemini_pricing['input_price_per_1m']
            or previous.get('output_price_per_1m') != profile.gemini_pricing['output_price_per_1m']
        )
        return Response({
            'status': 'success',
            'pricing': profile.gemini_pricing,
            'changed': changed,
            'previous': previous or None,
            # A model Google no longer offers to this key can still be stored;
            # say so instead of silently keeping a dead selection.
            'model_still_available': match is not None,
        })


class AiModelsView(KEKAuthenticationMixin, APIView):
    """List Gemini models available to the user's key, with known prices.

    Accepts an ``api_key`` in the body (pre-save validation while configuring)
    or falls back to the stored key.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .ai_categorization import GeminiError, list_models

        api_key = request.data.get('api_key')
        if not api_key:
            profile = request.user.profile
            if not profile.encrypted_gemini_key:
                return Response({'error': 'No Gemini API key configured'}, status=400)
            api_key = self.decrypt_blob(request, profile.encrypted_gemini_key)['api_key']

        try:
            return Response({'models': list_models(api_key)})
        except GeminiError as e:
            return Response({'error': str(e)}, status=502)


class AiSuggestView(KEKAuthenticationMixin, APIView):
    """Ask Gemini to suggest categories for uncategorized transactions.

    Nothing is persisted: the response is a proposal the user reviews and
    applies (or not) via AiApplyView. The response also states exactly which
    data was transferred to Google.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .ai_categorization import (
            DISCLOSED_FIELDS,
            MAX_TRANSACTIONS,
            GeminiError,
            suggest_categories,
        )

        profile = request.user.profile
        if not profile.encrypted_gemini_key or not profile.gemini_model:
            return Response({'error': 'Gemini is not configured'}, status=400)
        api_key = self.decrypt_blob(request, profile.encrypted_gemini_key)['api_key']

        # 'items' and 'rules' are separate review flows (mixing one-off labels
        # with rule proposals in one round proved noisy); no mode keeps the
        # combined round for older app clients.
        mode = request.data.get('mode')
        if mode not in ('items', 'rules'):
            mode = 'both'

        qs = (
            Transaction.objects
            .filter(
                account__user=request.user,
                category__isnull=True,
                category_manual=False,
                is_transfer=False,
            )
            .order_by('-booking_date')
        )
        total = qs.count()
        transactions = list(qs[:MAX_TRANSACTIONS])
        if not transactions:
            return Response({
                'suggestions': [], 'rules': [], 'sent_count': 0, 'total_uncategorized': 0,
                'disclosed_fields': DISCLOSED_FIELDS,
            })

        categories = list(
            TransactionCategory.objects.filter(user=request.user).values_list('name', flat=True)
        )
        payload = [
            {
                'id': t.id, 'counterparty': t.counterparty,
                'description': t.description, 'amount': str(t.amount), 'currency': t.currency,
            }
            for t in transactions
        ]
        own_rules = list(
            CategoryRule.objects.filter(user=request.user).select_related('category')
        )
        existing_rules = None
        if mode == 'rules':
            # Ids included so Gemini can propose an improvement that REPLACES
            # a rule (e.g. a regex covering spellings the rule misses).
            existing_rules = [
                f"{r.id} | {r.match_text} | "
                f"{'Transfer' if r.is_transfer else r.category.name}"
                for r in own_rules
            ]

        try:
            result = suggest_categories(
                api_key, profile.gemini_model, payload, categories,
                mode=mode, existing_rules=existing_rules,
            )
        except GeminiError as e:
            return Response({'error': str(e)}, status=502)

        import re as re_mod

        by_id = {t.id: t for t in transactions}
        existing = {c.lower() for c in categories}
        suggestions = []
        for assignment in result['assignments']:
            tx = by_id.get(assignment['id'])
            if tx is None:
                continue  # never act on ids we did not send
            is_transfer = assignment.get('transfer') is True
            name = None if is_transfer else str(assignment['category']).strip()[:64]
            suggestions.append({
                'transaction_id': tx.id,
                'booking_date': tx.booking_date,
                'counterparty': tx.counterparty,
                'description': tx.description,
                'amount': str(tx.amount),
                'currency': tx.currency,
                'category': name,
                'is_transfer': is_transfer,
                'is_new_category': bool(name) and name.lower() not in existing,
            })

        def normalized(text):
            return re_mod.sub(r'[^a-z0-9äöüß]+', '', text.lower())

        rules_by_id = {r.id: r for r in own_rules}
        rules_by_norm = {}
        for r in own_rules:
            rules_by_norm.setdefault(normalized(r.match_text), r)

        rules = []
        for r in result['rules']:
            match_text = str(r['match_text']).strip().lower()[:128]
            is_regex = bool(r.get('is_regex'))
            if is_regex:
                try:
                    re_mod.compile(match_text)
                except re_mod.error:
                    continue  # a broken pattern would silently match nothing
            is_transfer = r.get('transfer') is True
            name = None if is_transfer else str(r['category']).strip()[:64]
            replaces = r.get('replaces')
            replaced = rules_by_id.get(replaces) if isinstance(replaces, int) else None
            if replaced is None and not is_regex:
                # Deterministic near-duplicate link Gemini may miss: a plain
                # suggestion whose normalized text equals an existing rule's
                # ("youtube premium" vs "youtubepremium") is an improvement of
                # that rule, not a new one — and an exact duplicate is noise.
                same = rules_by_norm.get(normalized(match_text))
                if same is not None:
                    if same.match_text == match_text:
                        continue
                    replaced = same
            rules.append({
                'match_text': match_text,
                'category': name,
                'is_regex': is_regex,
                'is_transfer': is_transfer,
                'is_new_category': bool(name) and name.lower() not in existing,
                'replaces_rule_id': replaced.id if replaced else None,
                'replaced_match_text': replaced.match_text if replaced else None,
            })

        return Response({
            'suggestions': suggestions,
            'rules': rules,
            'sent_count': len(transactions),
            'total_uncategorized': total,
            'disclosed_fields': DISCLOSED_FIELDS,
            'usage': result['usage'],
        })


class AiRelabelView(KEKAuthenticationMixin, APIView):
    """Propose fixing transactions similar to one the user just re-categorized.

    Body: ``transaction_id`` of a transaction that already carries the
    corrected category. Candidates are the user's other transactions that share
    a significant word with it and are not in that category yet (manual
    decisions and transfers excluded); Gemini judges which ones really are the
    same merchant or purpose. Nothing is persisted — the user confirms through
    AiApplyView, and the response states exactly which data was transferred to
    Google.
    """
    permission_classes = [IsAuthenticated]

    # A word must be this long to anchor the candidate search — shorter tokens
    # ("ag", "der", card suffixes) match half the table.
    MIN_TOKEN = 4
    MAX_TOKENS = 5

    def post(self, request):
        import re

        from django.db.models import Q

        from .ai_categorization import (
            MAX_TRANSACTIONS,
            RELABEL_DISCLOSED_FIELDS,
            GeminiError,
            relabel_similar,
        )

        profile = request.user.profile
        if not profile.encrypted_gemini_key or not profile.gemini_model:
            return Response({'error': 'Gemini is not configured'}, status=400)
        api_key = self.decrypt_blob(request, profile.encrypted_gemini_key)['api_key']

        try:
            tx = Transaction.objects.select_related('category').get(
                pk=request.data.get('transaction_id'), account__user=request.user,
            )
        except (Transaction.DoesNotExist, TypeError, ValueError):
            return Response({'error': 'Transaction not found'}, status=404)
        if tx.category is None:
            return Response(
                {'error': 'The transaction has no category to propagate'}, status=400,
            )

        tokens = [
            t for t in re.findall(r'[^\W\d_]+', f'{tx.counterparty} {tx.description}'.lower())
            if len(t) >= self.MIN_TOKEN
        ][:self.MAX_TOKENS]

        empty = {
            'suggestions': [], 'rules': [], 'sent_count': 0,
            'disclosed_fields': RELABEL_DISCLOSED_FIELDS,
        }
        if not tokens:
            return Response(empty)

        match = Q()
        for token in tokens:
            match |= Q(counterparty__icontains=token) | Q(description__icontains=token)
        # Re-labeling settled history is churn with little value — labeled
        # candidates only from the last 18 months: covers the default report
        # window plus yearly recurring bookings, whose previous instance sits
        # ~12 months back. Uncategorized ones are pure gain at any age.
        recent = timezone.localdate() - timedelta(days=548)
        candidates = list(
            Transaction.objects
            .filter(match, account__user=request.user,
                    category_manual=False, is_transfer=False)
            .filter(Q(category__isnull=True) |
                    (~Q(category=tx.category) & Q(booking_date__gte=recent)))
            .exclude(pk=tx.pk)
            .select_related('category')
            .order_by('-booking_date')[:MAX_TRANSACTIONS]
        )
        if not candidates:
            return Response(empty)

        def payload(t):
            return {
                'id': t.id, 'counterparty': t.counterparty,
                'description': t.description, 'amount': str(t.amount),
                'currency': t.currency,
                'current_category': t.category.name if t.category else None,
            }

        categories = list(
            TransactionCategory.objects.filter(user=request.user).values_list('name', flat=True)
        )
        try:
            result = relabel_similar(
                api_key, profile.gemini_model, payload(tx),
                [payload(t) for t in candidates], tx.category.name, categories,
            )
        except GeminiError as e:
            return Response({'error': str(e)}, status=502)

        by_id = {t.id: t for t in candidates}
        suggestions = []
        for tx_id in result['ids']:
            candidate = by_id.get(tx_id)
            if candidate is None:
                continue  # never act on ids we did not send
            suggestions.append({
                'transaction_id': candidate.id,
                'booking_date': candidate.booking_date,
                'counterparty': candidate.counterparty,
                'description': candidate.description,
                'amount': str(candidate.amount),
                'currency': candidate.currency,
                'category': tx.category.name,
                'current_category': candidate.category.name if candidate.category else None,
                'is_new_category': False,
            })

        # Rules are first-match-wins: a corrective rule is pointless while an
        # earlier rule claims the same transactions. Find the rule that would
        # classify a future twin of the corrected transaction — the new rule
        # must be placed before it. If it already maps to the corrected
        # category, future entries are fine and no new rule is needed.
        from .classification import first_matching_rule
        shadowing = first_matching_rule(request.user, tx)
        if shadowing is not None and shadowing.category_id == tx.category_id:
            result['rules'] = []

        rules = [
            {
                'match_text': str(r['match_text']).strip().lower()[:128],
                # Pin the rule to the corrected category, whatever the model said.
                'category': tx.category.name,
                'is_new_category': False,
                'place_before_rule_id': shadowing.id if shadowing else None,
                'shadowed_match_text': shadowing.match_text if shadowing else None,
            }
            for r in result['rules']
        ]

        return Response({
            'suggestions': suggestions,
            'rules': rules,
            'sent_count': len(candidates),
            'disclosed_fields': RELABEL_DISCLOSED_FIELDS,
            'usage': result['usage'],
        })


class AiConsolidateRulesView(KEKAuthenticationMixin, APIView):
    """Propose a smaller equivalent rule set (merge duplicates, drop dead rules).

    Sends only rule metadata to Gemini — match texts, category names, spread,
    and a per-rule match count — never transaction data. The response is a
    proposal for the COMPLETE replacement rule set; the user confirms through
    CategoryRulesReplaceView.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .ai_categorization import (
            CONSOLIDATE_DISCLOSED_FIELDS,
            GeminiError,
            consolidate_rules,
        )

        profile = request.user.profile
        if not profile.encrypted_gemini_key or not profile.gemini_model:
            return Response({'error': 'Gemini is not configured'}, status=400)
        api_key = self.decrypt_blob(request, profile.encrypted_gemini_key)['api_key']

        rules = list(
            CategoryRule.objects.filter(user=request.user)
            .select_related('category').order_by('position', 'id')
        )
        # Regex and transfer rules are hand-crafted and follow different
        # semantics than the substring/category merging the prompt describes —
        # they pass through untouched (and are never sent to Gemini).
        plain = [r for r in rules if not r.is_regex and not r.is_transfer]
        if len(plain) < 2:
            return Response(
                {'error': 'Not enough substring rules to consolidate'}, status=400)

        # Per-rule match counts in one pass over the transaction texts: a
        # strong dead-rule signal that discloses no transaction data.
        texts = [
            f'{c} {d}'.lower()
            for c, d in Transaction.objects.filter(account__user=request.user)
            .values_list('counterparty', 'description')
        ]
        payload = [
            {
                'id': r.id, 'match_text': r.match_text,
                'category': r.category.name, 'spread_months': r.spread_months,
                'matches': sum(1 for t in texts if r.match_text.lower() in t),
            }
            for r in plain
        ]

        try:
            result = consolidate_rules(api_key, profile.gemini_model, payload)
        except GeminiError as e:
            return Response({'error': str(e)}, status=502)

        # Only categories the rules already map to — consolidation never
        # invents categories, so anything else is a hallucination to drop.
        valid = {r.category.name.lower(): r.category.name for r in plain}
        by_id = {r.id: r for r in plain}
        proposed = []
        seen = {r.match_text for r in rules if r.is_regex or r.is_transfer}
        for index, r in enumerate(result['rules']):
            match_text = str(r['match_text']).strip().lower()[:128]
            name = valid.get(str(r['category']).strip().lower())
            if not match_text or name is None or match_text in seen:
                continue
            seen.add(match_text)
            sources = [
                i for i in r.get('sources', [])
                if isinstance(i, int) and i in by_id
            ]
            spread = r.get('spread_months')
            if not isinstance(spread, int) or spread < 1:
                spread = max((by_id[i].spread_months for i in sources), default=1)
            proposed.append({
                'match_text': match_text,
                'category': name,
                'spread_months': spread,
                'sources': sources,
                'is_regex': False,
                'is_transfer': False,
                # Evaluation order: a merged rule takes its earliest source's
                # place; regex/transfer passthroughs keep theirs (interleaved
                # below).
                '_position': min(
                    (by_id[i].position for i in sources),
                    default=len(rules) + index,
                ),
            })
        proposed += [
            {
                'match_text': r.match_text,
                'category': r.category.name if r.category else None,
                'spread_months': r.spread_months,
                'sources': [r.id],
                'is_regex': r.is_regex,
                'is_transfer': r.is_transfer,
                '_position': r.position,
            }
            for r in rules if r.is_regex or r.is_transfer
        ]
        proposed.sort(key=lambda r: r['_position'])
        for r in proposed:
            del r['_position']

        return Response({
            'rules': proposed,
            'before_count': len(rules),
            'after_count': len(proposed),
            'disclosed_fields': CONSOLIDATE_DISCLOSED_FIELDS,
            'usage': result['usage'],
        })


class AiApplyView(APIView):
    """Persist the user-confirmed subset of AI suggestions.

    Body: ``assignments`` [{transaction_id, category}] and ``rules``
    [{match_text, category}]. Categories are created on demand; confirmed
    assignments are marked ``category_manual`` (a human decision, sticky);
    created rules immediately apply to remaining uncategorized transactions.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .classification import apply_rules, next_rule_position

        def category_for(name):
            name = str(name).strip()[:64]
            if not name:
                return None
            category, _ = TransactionCategory.objects.get_or_create(
                user=request.user, name=name,
            )
            return category

        import re as re_mod

        assigned = 0
        for item in request.data.get('assignments', []):
            if item.get('is_transfer') is True:
                # Confirmed transfer: excluded from spending, sticky like any
                # manual transfer decision.
                assigned += Transaction.objects.filter(
                    pk=item.get('transaction_id'), account__user=request.user,
                ).update(is_transfer=True, transfer_manual=True, category=None)
                continue
            category = category_for(item.get('category'))
            if category is None:
                continue
            updated = Transaction.objects.filter(
                pk=item.get('transaction_id'), account__user=request.user,
            ).update(category=category, category_manual=True)
            assigned += updated

        from django.db.models import F

        rules_created = 0
        rules_updated = 0
        for item in request.data.get('rules', []):
            match_text = str(item.get('match_text', '')).strip().lower()[:128]
            is_regex = bool(item.get('is_regex'))
            is_transfer = item.get('is_transfer') is True
            category = None if is_transfer else category_for(item.get('category'))
            if not match_text or (category is None and not is_transfer):
                continue
            if is_regex:
                try:
                    re_mod.compile(match_text)
                except re_mod.error:
                    continue
            # An improvement proposal updates the named rule in place —
            # position and spread survive, no near-duplicate is created.
            replaces = CategoryRule.objects.filter(
                user=request.user, pk=item.get('replaces_rule_id') or -1,
            ).first()
            if replaces is not None:
                replaces.match_text = match_text
                replaces.is_regex = is_regex
                if not replaces.is_transfer and category is not None:
                    replaces.category = category
                replaces.save()
                rules_updated += 1
                continue
            # Rules are first-match-wins. A corrective rule from the relabel
            # flow names the rule that mislabeled its transactions — the new
            # rule only takes effect if it is evaluated BEFORE that one.
            position = next_rule_position(request.user)
            before = CategoryRule.objects.filter(
                user=request.user, pk=item.get('place_before_rule_id') or -1,
            ).first()
            if before is not None:
                position = before.position
                CategoryRule.objects.filter(
                    user=request.user, position__gte=position,
                ).update(position=F('position') + 1)
            _, created = CategoryRule.objects.get_or_create(
                user=request.user, match_text=match_text,
                defaults={
                    'category': category, 'spread_months': 1,
                    'position': position,
                    'is_regex': is_regex, 'is_transfer': is_transfer,
                },
            )
            rules_created += created

        rule_applied = (
            apply_rules(request.user) if rules_created or rules_updated else 0
        )
        return Response({
            'status': 'success',
            'assigned': assigned,
            'rules_created': rules_created,
            'rules_updated': rules_updated,
            'rule_applied': rule_applied,
        })


class SpendingMonthlyView(APIView):
    """Month-to-month spending report.

    Query params: ``months`` (default 12, max 60), ``mode`` (``normalized`` |
    ``actual``, default ``normalized``).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .spending import monthly_spending

        try:
            months = min(max(int(request.query_params.get('months', 12)), 1), 60)
        except ValueError:
            months = 12
        mode = request.query_params.get('mode', 'normalized')
        if mode not in ('normalized', 'actual'):
            mode = 'normalized'

        return Response(monthly_spending(request.user, months=months, mode=mode))


class WealthSummaryView(APIView):
    """Get current total wealth summary."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_profile = request.user.profile
        base_currency = user_profile.base_currency

        accounts = FinancialAccount.objects.filter(user=request.user)
        total_wealth = Decimal('0')
        account_summaries = []

        for account in accounts:
            snapshot = account.latest_snapshot
            if snapshot:
                if snapshot.balance_base_currency:
                    amount = snapshot.balance_base_currency
                elif snapshot.currency == base_currency:
                    amount = snapshot.balance
                else:
                    rate = ExchangeRate.get_rate(
                        snapshot.currency, base_currency, snapshot.snapshot_date
                    )
                    amount = snapshot.balance * rate if rate else Decimal('0')

                total_wealth += amount
                account_summaries.append({
                    'account_id': account.id,
                    'account_name': account.name,
                    'broker': account.broker.name,
                    'balance': float(snapshot.balance),
                    'currency': snapshot.currency,
                    'balance_base_currency': float(amount),
                    'snapshot_date': snapshot.snapshot_date,
                })

        return Response({
            'total_wealth': float(total_wealth),
            'base_currency': base_currency,
            'accounts': account_summaries,
            'account_count': len(account_summaries),
        })


class WealthHistoryView(APIView):
    """Get historical wealth timeline."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_profile = request.user.profile
        base_currency = user_profile.base_currency

        # Get date range from query params
        days = int(request.query_params.get('days', 30))
        granularity = request.query_params.get('granularity', 'daily')  # daily or monthly
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        # Limit start_date to oldest snapshot date if more recent
        oldest_snapshot = AccountSnapshot.objects.filter(
            account__user=request.user
        ).order_by('snapshot_date').first()
        if oldest_snapshot and oldest_snapshot.snapshot_date > start_date:
            start_date = oldest_snapshot.snapshot_date

        # Get all snapshots up to end_date (including before start_date for carry-forward).
        # Use only the fields we need to reduce memory and transfer.
        snapshots = AccountSnapshot.objects.filter(
            account__user=request.user,
            snapshot_date__lte=end_date
        ).order_by('snapshot_date', 'created_at').only(
            'account_id', 'snapshot_date', 'balance',
            'balance_base_currency', 'currency',
        )

        # Build a timeline of the latest balance for each account on each date
        # For each account, track all snapshots in chronological order
        account_snapshots = {}  # account_id -> list of (date, balance_in_base)
        for snapshot in snapshots:
            account_id = snapshot.account_id
            if account_id not in account_snapshots:
                account_snapshots[account_id] = []

            # Calculate balance in base currency
            if snapshot.balance_base_currency:
                amount = snapshot.balance_base_currency
            elif snapshot.currency == base_currency:
                amount = snapshot.balance
            else:
                rate = ExchangeRate.get_rate(
                    snapshot.currency, base_currency, snapshot.snapshot_date
                )
                amount = snapshot.balance * rate if rate else Decimal('0')

            account_snapshots[account_id].append((snapshot.snapshot_date, amount))

        # For each account, deduplicate by date (keep last per date due to
        # ordering by created_at) and build a sorted list.
        for account_id in account_snapshots:
            by_date = {}
            for snap_date, amount in account_snapshots[account_id]:
                by_date[snap_date] = amount
            account_snapshots[account_id] = sorted(by_date.items())

        # Generate daily totals using carry-forward with bisect.
        # For each account, binary-search for the latest snapshot <= current_date
        # instead of scanning all snapshots linearly.
        from bisect import bisect_right

        # Pre-extract date arrays for fast bisect lookup
        account_dates = {}   # account_id -> [date1, date2, ...]
        account_values = {}  # account_id -> [amount1, amount2, ...]
        for account_id, snapshots_list in account_snapshots.items():
            dates = [s[0] for s in snapshots_list]
            values = [s[1] for s in snapshots_list]
            account_dates[account_id] = dates
            account_values[account_id] = values

        daily_totals = {}
        current_date = start_date
        while current_date <= end_date:
            total = Decimal('0')
            for account_id in account_snapshots:
                dates = account_dates[account_id]
                idx = bisect_right(dates, current_date) - 1
                if idx >= 0:
                    total += account_values[account_id][idx]
            daily_totals[current_date.isoformat()] = total
            current_date += timedelta(days=1)

        # Aggregate to monthly if requested
        if granularity == 'monthly':
            import calendar
            aggregation = user_profile.monthly_aggregation  # last, min, max, avg

            # Group daily values by (year, month)
            monthly_buckets = {}  # (year, month) -> list of (date_str, total)
            for date_str, total in daily_totals.items():
                d = date.fromisoformat(date_str)
                key = (d.year, d.month)
                monthly_buckets.setdefault(key, []).append((date_str, total))

            monthly_totals = {}
            reference_day = end_date.day
            for (year, month), entries in monthly_buckets.items():
                last_day_of_month = calendar.monthrange(year, month)[1]
                target_day = min(reference_day, last_day_of_month)
                month_key = date(year, month, target_day).isoformat()

                values = [v for _, v in entries]
                if aggregation == 'min':
                    monthly_totals[month_key] = min(values)
                elif aggregation == 'max':
                    monthly_totals[month_key] = max(values)
                elif aggregation == 'avg':
                    monthly_totals[month_key] = sum(values) / len(values)
                else:  # 'last' — pick the value closest to target_day
                    best = entries[0]
                    target_date = date(year, month, target_day)
                    for date_str, total in entries:
                        d = date.fromisoformat(date_str)
                        best_d = date.fromisoformat(best[0])
                        if d <= target_date and (best_d > target_date or d > best_d):
                            best = (date_str, total)
                    monthly_totals[month_key] = best[1]

            history = [
                {'date': mk, 'total_wealth': float(v)}
                for mk, v in sorted(monthly_totals.items())
            ]
        else:
            history = [
                {'date': d, 'total_wealth': float(v)}
                for d, v in sorted(daily_totals.items())
            ]

        return Response({
            'base_currency': base_currency,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'granularity': granularity,
            'history': history,
        })


class WealthBreakdownView(APIView):
    """Get wealth breakdown by account, broker, or currency."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_profile = request.user.profile
        base_currency = user_profile.base_currency
        group_by = request.query_params.get('by', 'broker')

        accounts = FinancialAccount.objects.filter(user=request.user)
        breakdown = {}

        for account in accounts:
            snapshot = account.latest_snapshot
            if not snapshot:
                continue

            if snapshot.balance_base_currency:
                amount = snapshot.balance_base_currency
            elif snapshot.currency == base_currency:
                amount = snapshot.balance
            else:
                rate = ExchangeRate.get_rate(
                    snapshot.currency, base_currency, snapshot.snapshot_date
                )
                amount = snapshot.balance * rate if rate else Decimal('0')

            if group_by == 'broker':
                key = account.broker.name
            elif group_by == 'currency':
                key = snapshot.currency
            elif group_by == 'account_type':
                key = account.get_account_type_display()
            else:
                key = account.name

            if key not in breakdown:
                breakdown[key] = Decimal('0')
            breakdown[key] += amount

        total = sum(breakdown.values(), Decimal('0'))
        result = [
            {
                'category': k,
                'amount': float(v),
                'percentage': float(v / total * 100) if total else 0
            }
            for k, v in sorted(breakdown.items(), key=lambda x: -x[1])
        ]

        return Response({
            'base_currency': base_currency,
            'group_by': group_by,
            'total': float(total),
            'breakdown': result,
        })


class WealthHoldingsView(APIView):
    """Current per-asset holdings across every account that reports them.

    Reads each account's most recent snapshot that actually carries positions —
    not simply ``latest_snapshot``, because a balance-only sync (or a manual entry)
    would otherwise hide holdings that are still perfectly current.

    Rows for the same instrument held at several brokers are merged: quantities add
    up, and the blended price is derived from the base-currency value so mixed-currency
    listings of one ISIN stay coherent.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        base_currency = request.user.profile.base_currency
        accounts = FinancialAccount.objects.filter(user=request.user).select_related('broker')

        merged = {}
        as_of = None
        for account in accounts:
            snapshot = (
                AccountSnapshot.objects
                .filter(account=account, positions__isnull=False)
                .distinct()
                .order_by('-snapshot_date', '-created_at', '-id')
                .first()
            )
            if snapshot is None:
                continue
            if as_of is None or snapshot.snapshot_date > as_of:
                as_of = snapshot.snapshot_date

            for pos in snapshot.positions.all():
                if pos.currency == base_currency:
                    value = pos.market_value
                else:
                    rate = ExchangeRate.get_rate(
                        pos.currency, base_currency, snapshot.snapshot_date,
                    )
                    value = pos.market_value * rate if rate else Decimal('0')

                # ISIN is the stable identity; symbols differ per venue. Fall back to
                # the symbol, then the name, so instruments without an ISIN still merge.
                key = pos.isin or pos.symbol or pos.name
                row = merged.setdefault(key, {
                    'isin': pos.isin,
                    'symbol': pos.symbol,
                    'name': pos.name,
                    'asset_class': pos.asset_class,
                    'quantity': Decimal('0'),
                    'value_base': Decimal('0'),
                    'accounts': [],
                })
                row['quantity'] += pos.quantity
                row['value_base'] += value
                if account.name not in row['accounts']:
                    row['accounts'].append(account.name)

        total = sum((row['value_base'] for row in merged.values()), Decimal('0'))
        holdings = [
            {
                'isin': row['isin'],
                'symbol': row['symbol'],
                'name': row['name'],
                'asset_class': row['asset_class'],
                'quantity': float(row['quantity']),
                'value_base_currency': float(row['value_base']),
                'price_base_currency': (
                    float(row['value_base'] / row['quantity']) if row['quantity'] else None
                ),
                'percentage': float(row['value_base'] / total * 100) if total else 0,
                'accounts': row['accounts'],
            }
            for row in sorted(merged.values(), key=lambda r: -r['value_base'])
        ]

        by_class = {}
        for row in merged.values():
            by_class[row['asset_class']] = by_class.get(row['asset_class'], Decimal('0')) \
                + row['value_base']

        return Response({
            'base_currency': base_currency,
            'as_of': as_of.isoformat() if as_of else None,
            'total': float(total),
            'holdings': holdings,
            'by_asset_class': [
                {
                    'asset_class': name,
                    'amount': float(value),
                    'percentage': float(value / total * 100) if total else 0,
                }
                for name, value in sorted(by_class.items(), key=lambda kv: -kv[1])
            ],
        })


class WealthSimulationView(APIView):
    """Monte Carlo wealth projection (percentile fan, in today's purchasing power).

    Every parameter is optional. Resolution order per parameter:
    query param > stored override (``UserProfile.simulation_params``) > derived
    from the user's data. Explicitly sent parameters are persisted as overrides;
    an explicitly EMPTY parameter (``?volatility=``) clears the stored override.
    Parameters that were never overridden keep being derived fresh each run —
    deliberately, so start_wealth follows the actual balances.

    The echo under ``parameters`` flags each value: ``derived`` is True only when
    it came from derivation (neither sent now nor stored earlier).

    Query params: ``years, paths, start_wealth, monthly_contribution,
    expected_return, volatility, inflation, target_amount, seed``
    (``paths``/``seed`` are never persisted).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .simulation import (
            DEFAULT_INFLATION,
            derive_market_assumptions,
            derive_monthly_contribution,
            derive_start_wealth,
            run_simulation,
        )

        profile = request.user.profile
        stored = dict(profile.simulation_params or {})
        original_stored = dict(stored)

        def resolve(name, cast, derived_default=None):
            """(value, derived) with query > stored > derived, updating ``stored``."""
            raw = request.query_params.get(name)
            if raw is None:
                if name in stored:
                    try:
                        return cast(stored[name]), False
                    except (TypeError, ValueError):
                        stored.pop(name)  # corrupt entry: drop and re-derive
                return derived_default, True
            if raw == '':
                stored.pop(name, None)
                return derived_default, True
            try:
                value = cast(raw)
            except (TypeError, ValueError):
                raise ValueError(f'Invalid value for "{name}"')
            stored[name] = value
            return value, False

        def transient(name, cast, default=None):
            raw = request.query_params.get(name)
            if raw is None or raw == '':
                return default
            try:
                return cast(raw)
            except (TypeError, ValueError):
                raise ValueError(f'Invalid value for "{name}"')

        d_return, d_vol, weights = derive_market_assumptions(request.user)
        defaults = {
            'start_wealth': derive_start_wealth(request.user),
            'monthly_contribution': derive_monthly_contribution(request.user),
            'expected_return': d_return,
            'volatility': d_vol,
            'inflation': DEFAULT_INFLATION,
        }

        try:
            years, _ = resolve('years', int, 15)
            target_amount, _ = resolve('target_amount', float)
            paths = transient('paths', int, 2000)
            seed = transient('seed', int)
            values = {}
            derived = {}
            for name in defaults:
                values[name], derived[name] = resolve(name, float, defaults[name])
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if stored != original_stored:
            profile.simulation_params = stored or None
            profile.save(update_fields=['simulation_params', 'updated_at'])

        # Always simulate at least the largest selectable horizon: the bands
        # (and per-year target probabilities) then cover every horizon chip, so
        # clients switch horizons by slicing locally instead of re-requesting.
        display_years = max(1, min(years, 50))
        result = run_simulation(
            start_wealth=values['start_wealth'],
            monthly_contribution=values['monthly_contribution'],
            expected_return=values['expected_return'],
            volatility=values['volatility'],
            inflation=values['inflation'],
            years=max(display_years, 30),
            paths=paths,
            target_amount=target_amount,
            seed=seed,
        )
        # ``years`` reports the SELECTED horizon; bands may extend beyond it.
        result['years'] = display_years
        if 'target' in result:
            by_year = result['target']['probability_by_year']
            result['target']['probability'] = by_year[min(display_years, len(by_year) - 1)]
        result['base_currency'] = profile.base_currency
        result['parameters'] = {
            name: {'value': round(values[name], 4), 'derived': derived[name]}
            for name in defaults
        }
        result['asset_class_weights'] = {k: round(v, 4) for k, v in weights.items()}
        return Response(result)


class BrokerDiscoverView(APIView):
    """Authenticate with a broker and discover available accounts."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from brokers.integrations import get_broker_integration
        from brokers.models import Broker

        broker_code = request.data.get('broker_code')
        credentials = request.data.get('credentials', {})

        if not broker_code:
            return Response(
                {'error': 'broker_code is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            broker = Broker.objects.get(code=broker_code, is_active=True)
        except Broker.DoesNotExist:
            return Response(
                {'error': f'Broker "{broker_code}" not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Cleanup expired sessions periodically
        _cleanup_expired_sessions()

        try:
            integration = get_broker_integration(broker, credentials)
            auth_result = integration.authenticate()

            if not auth_result.success:
                if auth_result.requires_2fa:
                    # Generate session token and store integration for 2FA completion
                    # NOTE: Using 1 gunicorn worker, so in-memory storage works
                    session_token = str(uuid.uuid4())
                    _set_session(session_token, {
                        'integration': integration,
                        'broker_code': broker_code,
                        'session_data': auth_result.session_data or {},
                        'created_at': time(),
                    })

                    return Response({
                        'status': 'pending_auth',
                        'session_token': session_token,
                        'message': 'Two-factor authentication required',
                        'two_fa_type': auth_result.two_fa_type,
                        'challenge': auth_result.challenge_data,
                    })
                return Response(
                    {'error': auth_result.error_message or 'Authentication failed'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Auth succeeded — discover accounts and fetch balances
            accounts = integration.get_accounts()

            account_list = []
            for a in accounts:
                entry = {
                    'identifier': a.identifier,
                    'name': a.name,
                    'account_type': a.account_type,
                    'currency': a.currency,
                    'balance': None,
                }
                try:
                    balance_info = integration.get_balance(a.identifier)
                    entry['balance'] = float(balance_info.balance)
                    entry['currency'] = balance_info.currency
                    entry['balance_date'] = balance_info.balance_date.isoformat()
                except Exception as e:
                    logger.warning(f"Failed to fetch balance for {a.identifier}: {e}")
                account_list.append(entry)

            integration.close()

            return Response({
                'status': 'success',
                'accounts': account_list,
            })

        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {'error': f'Discovery failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BrokerDiscoverCompleteAuthView(APIView):
    """Complete 2FA authentication for broker discovery."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        session_token = request.data.get('session_token')
        auth_code = request.data.get('auth_code')

        if not session_token:
            return Response(
                {'error': 'session_token is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get the stored session from file
        session = _get_session(session_token)

        if not session:
            return Response(
                {'error': 'Session expired or invalid. Please restart discovery.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if session is expired
        if time() - session.get('created_at', 0) > DISCOVERY_SESSION_TIMEOUT:
            integration = session.get('integration')
            if integration:
                try:
                    integration.close()
                except Exception:
                    pass
            _delete_session(session_token)
            return Response(
                {'error': 'Session expired. Please restart discovery.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        integration = session.get('integration')
        session_data = session.get('session_data', {})

        if not integration:
            _delete_session(session_token)
            return Response(
                {'error': 'Invalid session. Please restart discovery.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Complete 2FA
            auth_result = integration.complete_2fa(auth_code, session_data)

            if not auth_result.success:
                if auth_result.requires_2fa:
                    # Still needs 2FA (e.g., waiting for app approval)
                    return Response({
                        'status': 'pending_auth',
                        'session_token': session_token,
                        'message': auth_result.error_message or 'Still waiting for authentication',
                        'two_fa_type': auth_result.two_fa_type,
                        'challenge': auth_result.challenge_data,
                    })
                return Response(
                    {'error': auth_result.error_message or 'Authentication failed'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Auth succeeded — discover accounts and fetch balances
            accounts = integration.get_accounts()

            account_list = []
            for a in accounts:
                entry = {
                    'identifier': a.identifier,
                    'name': a.name,
                    'account_type': a.account_type,
                    'currency': a.currency,
                    'balance': None,
                }
                try:
                    balance_info = integration.get_balance(a.identifier)
                    entry['balance'] = float(balance_info.balance)
                    entry['currency'] = balance_info.currency
                    entry['balance_date'] = balance_info.balance_date.isoformat()
                except Exception as e:
                    logger.warning(f"Failed to fetch balance for {a.identifier}: {e}")
                account_list.append(entry)

            # Cleanup session
            _delete_session(session_token)
            integration.close()

            return Response({
                'status': 'success',
                'accounts': account_list,
            })

        except Exception as e:
            logger.exception("Discovery 2FA completion failed")
            # Cleanup on error
            _delete_session(session_token)
            try:
                integration.close()
            except Exception:
                pass
            return Response(
                {'error': f'Authentication failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BulkAccountCreateView(KEKAuthenticationMixin, APIView):
    """Create multiple accounts for a broker with shared credentials."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from brokers.models import Broker

        broker_code = request.data.get('broker_code')
        credentials = request.data.get('credentials')
        accounts_data = request.data.get('accounts', [])

        if not broker_code or not accounts_data:
            return Response(
                {'error': 'broker_code and accounts are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            broker = Broker.objects.get(code=broker_code, is_active=True)
        except Broker.DoesNotExist:
            return Response(
                {'error': f'Broker "{broker_code}" not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Strip out one-time codes before storing (they expire quickly)
        # Permanent tokens like 'flex_token' are kept, while 'token' is a generic one-time code
        one_time_fields = ('token', 'totp_token', 'otp', 'tan', 'sms_code')
        stored_credentials = {k: v for k, v in (credentials or {}).items()
                             if k not in one_time_fields}
        encrypted = self.encrypt_account_credentials(
            request, stored_credentials
        ) if stored_credentials else None

        user_profile = request.user.profile
        base_currency = user_profile.base_currency

        created = []
        for acct in accounts_data:
            account = FinancialAccount.objects.create(
                user=request.user,
                broker=broker,
                name=acct.get('name', ''),
                account_identifier=acct.get('identifier', ''),
                account_type=acct.get('account_type', 'checking'),
                currency=acct.get('currency', 'EUR'),
                is_manual=False,
                encrypted_credentials=encrypted,
                sync_enabled=True,
            )

            # Create initial snapshot if balance was provided
            balance_value = acct.get('balance')
            if balance_value is not None:
                snapshot_currency = acct.get('currency', 'EUR')
                # Use balance_date from discovery if provided, otherwise today
                balance_date_str = acct.get('balance_date')
                if balance_date_str:
                    snapshot_date = date.fromisoformat(balance_date_str)
                else:
                    snapshot_date = date.today()
                snapshot = AccountSnapshot.objects.create(
                    account=account,
                    balance=Decimal(str(balance_value)),
                    currency=snapshot_currency,
                    snapshot_date=snapshot_date,
                    snapshot_source='auto',
                )
                # Convert to base currency
                if snapshot_currency != base_currency:
                    rate = ExchangeRate.get_rate(
                        snapshot_currency, base_currency, snapshot.snapshot_date
                    )
                    if rate:
                        snapshot.balance_base_currency = snapshot.balance * rate
                        snapshot.base_currency = base_currency
                        snapshot.exchange_rate_used = rate
                        snapshot.save()

                account.status = 'active'
                account.last_sync_at = timezone.now()
                account.save()

            created.append({
                'id': account.id,
                'name': account.name,
                'identifier': account.account_identifier,
                'account_type': account.account_type,
                'currency': account.currency,
                'balance': balance_value,
            })

        return Response({
            'status': 'success',
            'message': f'Created {len(created)} accounts',
            'accounts': created,
        }, status=status.HTTP_201_CREATED)


class CSVImportView(APIView):
    """Import snapshots from a CSV file."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Import CSV data into an account.

        Expected CSV format:
            date,balance,currency
            2025-01-26,77047,CHF

        Request body:
            - account_id: ID of the account to import into
            - csv_data: CSV content as string
            - skip_duplicates: bool (default True)
        """
        import csv
        from datetime import datetime
        from io import StringIO

        account_id = request.data.get('account_id')
        csv_data = request.data.get('csv_data')
        skip_duplicates = request.data.get('skip_duplicates', True)

        if not account_id:
            return Response(
                {'error': 'account_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not csv_data:
            return Response(
                {'error': 'csv_data is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            account = FinancialAccount.objects.get(pk=account_id, user=request.user)
        except FinancialAccount.DoesNotExist:
            return Response(
                {'error': 'Account not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Parse CSV
        reader = csv.DictReader(StringIO(csv_data))
        required_fields = {'date', 'balance', 'currency'}

        if not required_fields.issubset(set(reader.fieldnames or [])):
            return Response(
                {'error': f'CSV must have columns: {", ".join(required_fields)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        imported = 0
        skipped = 0
        errors = []
        base_currency = request.user.profile.base_currency

        for row_num, row in enumerate(reader, start=2):
            try:
                # Parse date
                date_str = row['date'].strip()
                try:
                    snapshot_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    errors.append(f'Row {row_num}: Invalid date format "{date_str}"')
                    continue

                # Parse balance
                balance_str = row['balance'].strip().replace(',', '').replace("'", '')
                try:
                    balance = Decimal(balance_str)
                except:
                    errors.append(f'Row {row_num}: Invalid balance "{row["balance"]}"')
                    continue

                currency = row['currency'].strip().upper()

                # Check for duplicate
                existing = AccountSnapshot.objects.filter(
                    account=account,
                    snapshot_date=snapshot_date,
                ).first()

                if existing:
                    if skip_duplicates:
                        skipped += 1
                        continue
                    else:
                        # Update existing
                        existing.balance = balance
                        existing.currency = currency
                        existing.save()
                        imported += 1
                else:
                    # Create new snapshot (imported = manual)
                    snapshot = AccountSnapshot.objects.create(
                        account=account,
                        snapshot_date=snapshot_date,
                        balance=balance,
                        currency=currency,
                        snapshot_source='manual',
                    )

                    # Convert to base currency if needed
                    if currency != base_currency:
                        from exchange_rates.services import ExchangeRateService
                        rate = ExchangeRateService.get_rate(currency, base_currency, snapshot_date)
                        if rate and rate != Decimal('1.0'):
                            snapshot.balance_base_currency = balance * rate
                            snapshot.base_currency = base_currency
                            snapshot.exchange_rate_used = rate
                            snapshot.save()
                    else:
                        snapshot.balance_base_currency = balance
                        snapshot.base_currency = base_currency
                        snapshot.exchange_rate_used = Decimal('1')
                        snapshot.save()

                    imported += 1

            except Exception as e:
                errors.append(f'Row {row_num}: {str(e)}')

        return Response({
            'status': 'success',
            'imported': imported,
            'skipped': skipped,
            'errors': errors[:10] if errors else [],
            'total_errors': len(errors),
        })
