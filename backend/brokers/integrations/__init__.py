"""
Broker integration factory.
"""
from typing import Any, Dict

from brokers.models import Broker

from .base import BrokerIntegrationBase


# Brokers whose sync cannot finish without the user answering a challenge in
# that moment (an SMS code). Bulk and automatic syncs skip them: firing an SMS
# on every "Sync all" would be noise at best, and repeated unanswered
# challenges can trip a bank's fraud checks. They sync on demand, per account.
INTERACTIVE_BROKER_CODES = {'swisscard'}


def get_broker_integration(
    broker: Broker,
    credentials: Dict[str, Any],
    account_id: Any = None,
) -> BrokerIntegrationBase:
    """
    Factory function to get the appropriate broker integration.

    Args:
        broker: The Broker model instance
        credentials: Decrypted credentials dictionary
        account_id: Optional FinancialAccount id. Used by integrations that
            persist per-account state (e.g. Morgan Stanley's browser device-trust
            storage). None during pre-account flows like discovery.

    Returns:
        BrokerIntegrationBase: The appropriate integration instance

    Raises:
        ValueError: If the broker is not supported
    """
    if broker.integration_type == 'fints':
        from .fints_integration import FinTSIntegration
        return FinTSIntegration(
            credentials=credentials,
            bank_identifier=broker.bank_identifier,
            fints_server=broker.fints_server
        )

    if broker.integration_type == 'ebics':
        # EBICS (e.g. ZKB). The keyring/connection params are passed in `credentials`,
        # decrypted from the account's shared EbicsCredential by the sync view.
        from .zkb_ebics import ZKBEbicsIntegration
        return ZKBEbicsIntegration(credentials=credentials)

    if broker.code == 'ibkr':
        # IBKR uses Flex Web Service (requires flex_token and query_id)
        if credentials.get('flex_token') and credentials.get('query_id'):
            from .ibkr_flex import IBKRFlexIntegration
            return IBKRFlexIntegration(credentials=credentials)
        else:
            raise ValueError(
                "IBKR requires flex_token and query_id credentials. "
                "Get these from IBKR Client Portal > Performance & Reports > Flex Queries."
            )

    if broker.code == 'truewealth':
        from .truewealth import TrueWealthIntegration
        return TrueWealthIntegration(credentials=credentials)

    if broker.code == 'viac':
        from .viac import VIACIntegration
        return VIACIntegration(credentials=credentials)

    if broker.code == 'swisscard':
        from .swisscard import SwisscardIntegration
        return SwisscardIntegration(credentials=credentials, account_id=account_id)

    if broker.code == 'morganstanley':
        from .morganstanley import MorganStanleyIntegration
        return MorganStanleyIntegration(credentials=credentials, account_id=account_id)

    raise ValueError(f"Broker '{broker.code}' is not yet supported for automated sync.")
