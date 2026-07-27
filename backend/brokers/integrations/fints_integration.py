"""
FinTS integration for German banks (DKB, Commerzbank).
"""
import logging
import os
from datetime import date
from decimal import Decimal, InvalidOperation
from time import sleep
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fints.client import FinTS3PinTanClient, NeedTANResponse

from .base import (
    AccountInfo,
    AuthResult,
    BalanceInfo,
    BrokerIntegrationBase,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tolerant balance parsing.
#
# python-fints maps a HISAL (balance) response to a typed segment only for the
# versions it knows (5/6/7). Some banks (observed with DKB) return a HISAL whose
# version isn't registered, so it falls back to a generic FinTS3Segment with no
# `.balance_booked` attribute — and the stock client crashes with
# "'FinTS3Segment' object has no attribute 'balance_booked'".
#
# The generic segment still keeps the raw data elements in `_additional_data`, in
# the standard HISAL order: [account, product, currency, balance_booked, ...] where
# balance_booked is [credit_debit(C/D), amount, currency, date, time?]. We read the
# booked balance from there instead of crashing.
# ---------------------------------------------------------------------------

def _balance_from_generic_hisal(additional_data):
    """Extract (Decimal amount, currency) from a generic HISAL segment's raw data.

    Returns None if the shape isn't recognisable. Debit balances are negative.
    """
    if not additional_data or len(additional_data) < 4:
        return None
    booked = additional_data[3]
    if not isinstance(booked, (list, tuple)) or len(booked) < 3:
        return None
    credit_debit, amount_str, currency = booked[0], booked[1], booked[2]
    try:
        amount = Decimal(str(amount_str).replace(',', '.'))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if str(credit_debit).upper().startswith('D'):
        amount = -amount
    return amount, (currency or 'EUR')


def _tolerant_get_balance(self, command_seg, response):
    """Drop-in for ``FinTS3PinTanClient._get_balance`` that tolerates an unmapped
    HISAL segment version by reading the booked balance from the raw data elements."""
    for resp in response.response_segments(command_seg, 'HISAL'):
        booked = getattr(resp, 'balance_booked', None)
        if booked is not None:
            return booked.as_mt940_Balance()
        extracted = _balance_from_generic_hisal(getattr(resp, '_additional_data', None))
        if extracted is not None:
            amount, currency = extracted
            logger.warning(
                'FinTS: bank returned an unmapped HISAL segment version; read balance '
                'from raw data (%s %s).', amount, currency,
            )
            return SimpleNamespace(
                amount=SimpleNamespace(amount=amount, currency=currency),
                currency=currency, date=date.today(),
            )
    return None


# Patch the library once: only the unmapped-segment path changes; the typed path
# behaves exactly as before.
if not getattr(FinTS3PinTanClient, '_wt_tolerant_balance_patch', False):
    FinTS3PinTanClient._get_balance = _tolerant_get_balance
    FinTS3PinTanClient._wt_tolerant_balance_patch = True

# FinTS/HBCI error code translations
FINTS_ERROR_MESSAGES = {
    '900': 'Invalid TAN code. Please check and try again.',
    '9000': 'Invalid TAN code. Please check and try again.',
    '9010': 'TAN has expired. Please restart the authentication process.',
    '9050': 'TAN mechanism is locked. Please contact your bank.',
    '9210': 'Invalid credentials. Please check your username and PIN.',
    '9800': 'Dialog initialization failed. Please try again.',
    '9900': 'Authentication failed. Please check your credentials.',
    '9910': 'Session expired. Please restart the authentication process.',
    '9920': 'Too many failed attempts. Please try again later.',
    '9930': 'Account locked. Please contact your bank.',
    '9931': 'PIN locked. Please contact your bank.',
    '9941': 'TAN required but not provided.',
    '9942': 'Invalid TAN format.',
}


def _translate_fints_error(error: Exception) -> str:
    """Translate FinTS error codes to user-friendly messages."""
    error_str = str(error).strip()

    # Strip quotes that may wrap the error code (e.g., "'900'" -> "900")
    error_str_clean = error_str.strip("'\"")

    # Check if it's a pure error code (just digits)
    if error_str_clean.isdigit():
        return FINTS_ERROR_MESSAGES.get(error_str_clean, f'Bank error ({error_str_clean}). Please try again.')

    # Check if error contains a known code
    for code, message in FINTS_ERROR_MESSAGES.items():
        if code in error_str:
            return message

    # Return original error if no translation found, but clean it up
    if len(error_str) < 100:
        return f'Bank error: {error_str}'
    return 'An error occurred during authentication. Please try again.'


class FinTSIntegration(BrokerIntegrationBase):
    """Integration for German banks using FinTS protocol."""

    # FinTS product ID for this application (from environment)
    PRODUCT_ID = os.environ.get('FINTS_PRODUCT_ID', '')

    def __init__(
        self,
        credentials: Dict[str, Any],
        bank_identifier: str,
        fints_server: str
    ):
        super().__init__(credentials)
        self.bank_identifier = bank_identifier
        self.fints_server = fints_server
        self._client: Optional[FinTS3PinTanClient] = None
        self._accounts = None
        self._authenticated = False

    def get_pause_state(self) -> Optional[dict]:
        """Get serializable state for cross-worker persistence.

        Returns dict with 'client_data' (from deconstruct) and 'dialog_data' (from pause_dialog).
        """
        if not self._client:
            return None
        try:
            # Get full client state including credentials
            client_data = self._client.deconstruct(including_private=True)
            # Get dialog-specific state (for resuming mid-authentication)
            dialog_data = self._client.pause_dialog()
            logger.info(f"FinTS: Paused dialog, client_data={len(client_data)} bytes, dialog_data={len(dialog_data) if dialog_data else 0} bytes")
            return {
                'client_data': client_data,
                'dialog_data': dialog_data,
            }
        except Exception as e:
            logger.warning(f"Failed to pause FinTS dialog: {e}")
            return None

    def restore_from_pause(self, state: dict) -> bool:
        """Restore FinTS client from serialized state."""
        if not state:
            return False
        try:
            client_data = state.get('client_data')
            dialog_data = state.get('dialog_data')

            if not client_data:
                logger.error("No client_data in pause state")
                return False

            # Recreate client from serialized state
            self._client = FinTS3PinTanClient(
                product_id=self.PRODUCT_ID,
                bank_identifier=self.bank_identifier,
                server=self.fints_server,
                user_id=self.credentials.get('username'),
                pin=self.credentials.get('pin'),
                from_data=client_data,
            )

            # Resume dialog if we have dialog data
            # resume_dialog() returns the pending TAN response
            if dialog_data:
                tan_response = self._client.resume_dialog(dialog_data)
                # Set init_tan_response so complete_2fa can use it
                self._client.init_tan_response = tan_response
                logger.info(f"FinTS: Successfully restored client and resumed dialog, tan_response={type(tan_response)}")
            else:
                logger.info("FinTS: Successfully restored client (no dialog data)")

            return True
        except Exception as e:
            logger.exception(f"Failed to restore FinTS client: {e}")
            return False

    def authenticate(self) -> AuthResult:
        """Initialize FinTS client and start authentication."""
        try:
            self._client = FinTS3PinTanClient(
                product_id=self.PRODUCT_ID,
                bank_identifier=self.bank_identifier,
                server=self.fints_server,
                user_id=self.credentials.get('username'),
                pin=self.credentials.get('pin'),
            )

            # Fetch available TAN mechanisms
            self._client.fetch_tan_mechanisms()
            mechs = self._client.get_tan_mechanisms()

            # Log available mechanisms with details
            logger.info(f"FinTS: Available TAN mechanisms: {mechs}")
            if isinstance(mechs, dict):
                for key, mech in mechs.items():
                    mech_name = getattr(mech, 'name', 'unknown') if hasattr(mech, 'name') else str(mech)
                    is_decoupled = getattr(mech, 'decoupled', False) if hasattr(mech, 'decoupled') else False
                    logger.info(f"FinTS: Mechanism {key}: {mech_name}, decoupled={is_decoupled}")

            # Build list of mechanism keys
            mech_keys = list(mechs.keys()) if isinstance(mechs, dict) else [str(m) for m in mechs]

            # Prefer decoupled TAN mechanisms (push notification, no manual entry needed)
            # Common decoupled TAN mechanism IDs: 940 (PushTAN), 942, 944
            selected_mechanism = None
            for preferred in ['940', '942', '944', '920', '921']:
                if preferred in mech_keys:
                    selected_mechanism = preferred
                    break

            if selected_mechanism:
                logger.info(f"FinTS: Selecting decoupled TAN mechanism: {selected_mechanism}")
                self._client.set_tan_mechanism(selected_mechanism)
            elif mech_keys:
                # Fallback to first available mechanism
                selected_mechanism = mech_keys[0]
                logger.info(f"FinTS: No decoupled TAN found, using first mechanism: {selected_mechanism}")
                self._client.set_tan_mechanism(selected_mechanism)

            # Start the session
            self._client.__enter__()

            # Check if 2FA is required
            if isinstance(self._client.init_tan_response, NeedTANResponse):
                tan_resp = self._client.init_tan_response

                # Check decoupled status
                is_decoupled = getattr(tan_resp, 'decoupled', False)
                challenge_text = getattr(tan_resp, 'challenge', None)

                # Also check if the selected mechanism is typically decoupled
                # Mechanisms 940, 942, 944 are usually decoupled (PushTAN)
                if selected_mechanism in ['940', '942', '944']:
                    is_decoupled = True

                if is_decoupled:
                    # Poll for app approval (decoupled TAN) — up to 5 minutes
                    logger.info("Waiting for banking app approval...")
                    max_attempts = 60  # 5 min at 5s intervals
                    for attempt in range(max_attempts):
                        result = self._client.send_tan(tan_resp, None)
                        if not isinstance(result, NeedTANResponse):
                            self._authenticated = True
                            logger.info("App approval received.")
                            return AuthResult(success=True)
                        tan_resp = result
                        self._client.init_tan_response = result
                        logger.debug(
                            f"Waiting for app approval... ({attempt + 1}/{max_attempts})"
                        )
                        sleep(5)

                    return AuthResult(
                        success=False,
                        error_message='2FA approval timeout (5 min). Please approve in your banking app and retry.'
                    )
                else:
                    # Manual TAN entry required — return to frontend

                    # Extract all available challenge data
                    challenge_text = getattr(tan_resp, 'challenge', None)
                    challenge_html = getattr(tan_resp, 'challenge_html', None)

                    # For photoTAN/chipTAN, the image data can be in various attributes
                    challenge_hhduc = getattr(tan_resp, 'challenge_hhduc', None)
                    challenge_matrix = getattr(tan_resp, 'challenge_matrix', None)
                    challenge_raw = getattr(tan_resp, 'challenge_raw', None)

                    logger.info(f"TAN challenge - text: {bool(challenge_text)}, html: {bool(challenge_html)}, hhduc: {bool(challenge_hhduc)}, matrix: {bool(challenge_matrix)}, raw: {bool(challenge_raw)}")

                    # If we have matrix data (photoTAN image), convert to displayable format
                    if challenge_matrix:
                        import base64
                        logger.info(f"PhotoTAN: challenge_matrix type={type(challenge_matrix)}")

                        # Extract image data - challenge_matrix can be:
                        # - bytes: raw image data
                        # - str: base64 encoded
                        # - tuple: (mime_type, image_data)
                        img_data = None
                        mime_type = 'image/png'

                        if isinstance(challenge_matrix, tuple) and len(challenge_matrix) >= 2:
                            # Tuple format: (mime_type, image_data)
                            mime_type = challenge_matrix[0] or 'image/png'
                            img_data = challenge_matrix[1]
                        elif isinstance(challenge_matrix, bytes):
                            img_data = challenge_matrix
                        elif isinstance(challenge_matrix, str):
                            # Already base64 encoded
                            img_base64 = challenge_matrix
                            challenge_html = f'<div class="phototan-challenge"><p>{challenge_text or "Scan this code with your banking app:"}</p><img src="data:image/png;base64,{img_base64}" alt="PhotoTAN" style="max-width: 250px; margin: 10px auto; display: block;" /></div>'
                            img_data = None  # Already handled

                        # Convert bytes to base64 if we have raw data
                        if img_data is not None:
                            if isinstance(img_data, bytes):
                                img_base64 = base64.b64encode(img_data).decode('utf-8')
                                challenge_html = f'<div class="phototan-challenge"><p>{challenge_text or "Scan this code with your banking app:"}</p><img src="data:{mime_type};base64,{img_base64}" alt="PhotoTAN" style="max-width: 250px; margin: 10px auto; display: block;" /></div>'
                            elif isinstance(img_data, str):
                                # img_data is already base64
                                challenge_html = f'<div class="phototan-challenge"><p>{challenge_text or "Scan this code with your banking app:"}</p><img src="data:{mime_type};base64,{img_data}" alt="PhotoTAN" style="max-width: 250px; margin: 10px auto; display: block;" /></div>'

                    # Fallback to HHD UC data if no matrix
                    elif challenge_hhduc:
                        # HHD UC is typically used for flicker code TAN generators
                        challenge_html = f'<div class="phototan-challenge"><p>{challenge_text or "Use your TAN generator:"}</p><p class="form-hint">HHD UC Code: {challenge_hhduc}</p></div>'

                    return AuthResult(
                        success=False,
                        requires_2fa=True,
                        two_fa_type='tan',
                        session_data={'decoupled': False},
                        challenge_data={
                            'challenge': challenge_text,
                            'challenge_html': challenge_html,
                            'challenge_hhduc': challenge_hhduc,
                            'challenge_matrix': bool(challenge_matrix),  # Just indicate if present
                        }
                    )

            self._authenticated = True
            return AuthResult(success=True)

        except Exception as e:
            logger.exception("FinTS authentication failed")
            return AuthResult(
                success=False,
                error_message=_translate_fints_error(e)
            )

    def complete_2fa(
        self,
        auth_code: Optional[str],
        session_data: Dict[str, Any]
    ) -> AuthResult:
        """Complete 2FA authentication."""
        if not self._client:
            return AuthResult(
                success=False,
                error_message="No active session. Call authenticate() first."
            )

        try:
            tan_response = self._client.init_tan_response

            if not tan_response:
                return AuthResult(
                    success=False,
                    error_message="Session state could not be restored. Please restart discovery."
                )

            if session_data.get('decoupled'):
                # Poll for app approval (decoupled TAN)
                max_attempts = 120  # 2 minutes timeout
                for attempt in range(max_attempts):
                    result = self._client.send_tan(tan_response, None)
                    if not isinstance(result, NeedTANResponse):
                        self._authenticated = True
                        return AuthResult(success=True)
                    logger.debug(f"Waiting for app approval... ({attempt + 1}/{max_attempts})")
                    sleep(1)

                return AuthResult(
                    success=False,
                    error_message='2FA approval timeout. Please approve in your banking app.'
                )
            else:
                # Submit TAN code
                if not auth_code:
                    return AuthResult(
                        success=False,
                        error_message='TAN code required for this authentication method.'
                    )
                self._client.send_tan(tan_response, auth_code)
                self._authenticated = True
                return AuthResult(success=True)

        except Exception as e:
            logger.exception("2FA completion failed")
            return AuthResult(
                success=False,
                error_message=_translate_fints_error(e)
            )

    def get_accounts(self) -> List[AccountInfo]:
        """Fetch SEPA accounts from the bank."""
        if not self._client or not self._authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        # Small delay to ensure connection is ready
        sleep(2)

        sepa_accounts = self._client.get_sepa_accounts()
        self._accounts = sepa_accounts  # Cache for balance lookup

        accounts = []
        for acc in sepa_accounts:
            accounts.append(AccountInfo(
                identifier=acc.iban,
                name=getattr(acc, 'account_name', '') or acc.iban,
                account_type='checking',
                currency='EUR'
            ))

        return accounts

    def get_balance(self, account_identifier: str) -> BalanceInfo:
        """Fetch balance for a specific account."""
        if not self._client or not self._authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        if not self._accounts:
            self.get_accounts()

        # Find the account by IBAN
        account = None
        for acc in self._accounts:
            if acc.iban == account_identifier:
                account = acc
                break

        if not account:
            raise ValueError(f"Account {account_identifier} not found")

        balance = self._client.get_balance(account)

        # Extract balance amount
        amount = balance.amount.amount if hasattr(balance.amount, 'amount') else balance.amount
        currency = getattr(balance, 'currency', 'EUR')

        return BalanceInfo(
            balance=Decimal(str(amount)),
            currency=currency,
            balance_date=date.today(),
            raw_data={'fints_balance': str(balance)}
        )

    def close(self):
        """Close FinTS session."""
        if self._client:
            try:
                self._client.__exit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing FinTS session: {e}")
            finally:
                self._client = None
                self._authenticated = False
