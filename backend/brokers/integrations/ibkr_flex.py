"""
Interactive Brokers (IBKR) Flex Web Service integration.

This integration uses IBKR's Flex Web Service to fetch account data via
pre-configured Flex Queries. This is the recommended approach for individual
retail users as it only requires a token and query ID - no local gateway needed.

Requirements:
- IBKR account (Pro or Lite with Flex Query access)
- Flex Web Service enabled in Client Portal
- Flex Query token (valid up to 1 year)
- Activity Flex Query configured with required fields

Setup Guide:
1. Log in to IBKR Client Portal
2. Go to Performance & Reports > Flex Queries
3. Enable Flex Web Service and generate a token
4. Create an Activity Flex Query with positions and cash data
5. Note the Query ID

See: https://www.interactivebrokers.com/campus/ibkr-api-page/flex-web-service/
"""
import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import requests

from .base import (
    AccountInfo,
    AuthResult,
    BalanceInfo,
    BrokerIntegrationBase,
    PositionInfo,
)

logger = logging.getLogger(__name__)


class IBKRFlexIntegration(BrokerIntegrationBase):
    """
    Integration for Interactive Brokers via Flex Web Service.

    This integration fetches data from pre-configured Flex Queries using
    a token and query ID. No local gateway or manual login required.

    Note: Flex Query data is updated once daily at market close.
    """

    FLEX_SERVICE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"

    # Asset class mapping from IBKR asset categories
    ASSET_CLASS_MAP = {
        'STK': 'equity',
        'OPT': 'equity',
        'FUT': 'commodity',
        'CASH': 'cash',
        'BOND': 'fixed_income',
        'FUND': 'equity',
        'ETF': 'equity',
        'WAR': 'equity',
        'CRYPTO': 'crypto',
        'FOP': 'equity',  # Futures options
        'CFD': 'equity',
    }

    def __init__(self, credentials: Dict[str, Any]):
        """
        Initialize IBKR Flex integration.

        Args:
            credentials: Dict containing:
                - flex_token: Flex Web Service token (permanent, expires after ~1 year)
                - query_id: Activity Flex Query ID
                - account_id: (optional) IBKR account ID
        """
        super().__init__(credentials)
        self.token = credentials.get('flex_token')
        self.query_id = credentials.get('query_id')
        self.account_id = credentials.get('account_id')
        self._session = requests.Session()
        self._session.headers['User-Agent'] = 'WealthTracker/1.0'
        self._last_report: Optional[Dict] = None
        self._authenticated = False

    def authenticate(self) -> AuthResult:
        """
        Validate that Flex credentials are present.

        Note: We don't make an API call here to avoid wasting IBKR's strict
        rate limits. Actual token validation happens when fetching data.
        """
        if not self.token:
            return AuthResult(
                success=False,
                error_message="Flex token is required. Generate one in IBKR Client Portal > Performance & Reports > Flex Queries."
            )

        if not self.query_id:
            return AuthResult(
                success=False,
                error_message="Flex Query ID is required. Create a query in IBKR Client Portal > Performance & Reports > Flex Queries."
            )

        # Mark as authenticated based on credentials presence.
        # Actual validation happens when fetching data to avoid wasting API calls.
        self._authenticated = True
        return AuthResult(success=True)

    def complete_2fa(
        self,
        auth_code: Optional[str],
        session_data: Dict[str, Any]
    ) -> AuthResult:
        """
        Flex Web Service doesn't require 2FA - just token authentication.
        """
        return self.authenticate()

    def _send_request(self) -> str:
        """
        Send a request to generate a Flex report.

        Returns:
            Reference code for retrieving the report
        """
        url = f"{self.FLEX_SERVICE_URL}/SendRequest"
        params = {
            't': self.token,
            'q': self.query_id,
            'v': '3'
        }

        response = self._session.get(url, params=params, timeout=30)
        response.raise_for_status()

        # Parse XML response
        root = ET.fromstring(response.text)
        status = root.find('.//Status')

        if status is not None and status.text == 'Success':
            ref_code = root.find('.//ReferenceCode')
            if ref_code is not None:
                return ref_code.text
            raise RuntimeError("No reference code in response")

        # Handle error
        error_code = root.find('.//ErrorCode')
        error_msg = root.find('.//ErrorMessage')
        code = error_code.text if error_code is not None else 'Unknown'
        msg = error_msg.text if error_msg is not None else 'Unknown error'
        raise RuntimeError(f"Flex request failed ({code}): {msg}")

    def _get_statement(self, reference_code: str, max_retries: int = 10) -> str:
        """
        Retrieve the generated Flex report.

        Args:
            reference_code: Reference code from SendRequest
            max_retries: Maximum number of retry attempts

        Returns:
            Report content as string
        """
        url = f"{self.FLEX_SERVICE_URL}/GetStatement"
        params = {
            't': self.token,
            'q': reference_code,
            'v': '3'
        }

        for attempt in range(max_retries):
            response = self._session.get(url, params=params, timeout=60)

            # Check if it's still processing
            if response.status_code == 200:
                content = response.text

                # Check for "statement generation in progress" response
                if '<FlexStatementResponse' in content:
                    root = ET.fromstring(content)
                    status = root.find('.//Status')
                    if status is not None and status.text != 'Success':
                        # Still processing, wait and retry
                        logger.debug(f"Report still processing, attempt {attempt + 1}/{max_retries}")
                        time.sleep(2)
                        continue

                return content

            time.sleep(2)

        raise RuntimeError("Timeout waiting for Flex report generation")

    def _fetch_report(self) -> Dict[str, Any]:
        """
        Fetch and parse the Flex report.

        Returns:
            Parsed report data
        """
        # Request report generation
        reference_code = self._send_request()

        # Wait a moment for report to be generated
        time.sleep(1)

        # Retrieve the report
        content = self._get_statement(reference_code)

        # Save raw XML for debugging
        try:
            with open('/tmp/ibkr_flex_report.xml', 'w') as f:
                f.write(content)
            logger.info(f"IBKR Flex report saved to /tmp/ibkr_flex_report.xml ({len(content)} bytes)")
        except Exception as e:
            logger.warning(f"Failed to save IBKR Flex report: {e}")

        # Parse the report
        return self._parse_flex_report(content)

    def _parse_flex_report(self, content: str) -> Dict[str, Any]:
        """
        Parse a Flex XML report into structured data.

        Args:
            content: XML report content

        Returns:
            Parsed data with accounts, positions, and cash balances
        """
        root = ET.fromstring(content)
        result = {
            'accounts': [],
            'positions': [],
            'cash_balances': [],
            'net_asset_value': Decimal('0'),
            'currency': 'USD',
            'report_date': date.today()
        }

        # Find the FlexStatement
        statement = root.find('.//FlexStatement')
        if statement is None:
            # Try alternate structure
            statement = root

        # Log available sections for debugging
        sections = [child.tag for child in statement]
        logger.info(f"IBKR Flex report sections: {sections}")

        # Log ALL historical data sections for analysis
        for section_name in ['ChangeInNAV', 'MTMPerformanceSummaryInBase', 'NAVChange', 'EquitySummaryByReportDateInBase', 'CashReport', 'ChangeInDividendAccruals']:
            entries = statement.findall(f'.//{section_name}')
            if entries:
                logger.warning(f"IBKR Historical section '{section_name}': {len(entries)} entries")
                for i, entry in enumerate(entries[:5]):  # Log first 5 entries
                    logger.warning(f"  {section_name}[{i}]: {dict(entry.attrib)}")

        # Get account info
        account_info = statement.find('.//AccountInformation')
        if account_info is not None:
            result['accounts'].append({
                'account_id': account_info.get('accountId', ''),
                'name': account_info.get('name', '') or account_info.get('accountId', ''),
                'currency': account_info.get('currency', 'USD'),
            })
            result['currency'] = account_info.get('currency', 'USD')
            logger.info(f"IBKR account info: id={account_info.get('accountId')}, currency={account_info.get('currency')}")

        # Get statement date - IBKR uses toDate for end date of report period
        stmt_date = statement.get('toDate') or statement.get('whenGenerated')
        logger.info(f"IBKR Flex statement attributes: {dict(statement.attrib)}")
        logger.info(f"IBKR Flex stmt_date raw value: {stmt_date}")
        if stmt_date:
            parsed = False
            # Try different date formats
            for fmt in ['%Y%m%d', '%Y-%m-%d', '%Y%m%d;%H%M%S']:
                try:
                    result['report_date'] = datetime.strptime(stmt_date.split(';')[0], fmt.split(';')[0]).date()
                    logger.info(f"IBKR Flex parsed report_date: {result['report_date']} (from {stmt_date} using {fmt})")
                    parsed = True
                    break
                except ValueError:
                    continue
            if not parsed:
                logger.warning(f"IBKR Flex: Could not parse date '{stmt_date}', using today")
        else:
            logger.warning("IBKR Flex: No toDate or whenGenerated found in statement, using today")

        # Parse open positions
        for pos in statement.findall('.//OpenPosition'):
            position = self._parse_position(pos)
            if position:
                result['positions'].append(position)
        logger.info(f"IBKR parsed {len(result['positions'])} positions")

        # Parse cash report - sum all currencies
        total_cash_all = Decimal('0')
        for cash in statement.findall('.//CashReportCurrency'):
            currency = cash.get('currency', 'USD')
            ending_cash = cash.get('endingCash') or cash.get('endingSettledCash', '0')
            try:
                amount = Decimal(str(ending_cash))
                result['cash_balances'].append({
                    'currency': currency,
                    'amount': amount
                })
                total_cash_all += amount
                logger.info(f"IBKR cash: {currency} {amount}")
            except (ValueError, TypeError):
                pass

        # Calculate total position value (sum all currencies for now)
        total_positions = Decimal('0')
        for pos in result['positions']:
            total_positions += pos.get('market_value', Decimal('0'))
        logger.info(f"IBKR total positions value: {total_positions}")

        # Try multiple sources for NAV, in order of preference:
        nav = None

        # 1. EquitySummaryInBase / NAVInBase - most accurate if available
        for nav_element_name in ['EquitySummaryInBase', 'NAVInBase', 'NetAssetValueInBase']:
            nav_section = statement.find(f'.//{nav_element_name}')
            if nav_section is not None:
                # Log all attributes for debugging
                logger.info(f"IBKR {nav_element_name} attributes: {dict(nav_section.attrib)}")
                # Try various attribute names
                for attr in ['total', 'totalLong', 'netAssetValue', 'nav', 'endingValue', 'value']:
                    total_nav = nav_section.get(attr)
                    if total_nav:
                        try:
                            nav = Decimal(str(total_nav))
                            logger.info(f"IBKR NAV from {nav_element_name}.{attr}: {nav}")
                            break
                        except (ValueError, TypeError):
                            pass
                if nav is not None:
                    break

        # 2. Try NAV section
        if nav is None:
            nav_section = statement.find('.//NAV')
            if nav_section is not None:
                logger.info(f"IBKR NAV section attributes: {dict(nav_section.attrib)}")
                for attr in ['total', 'netAssetValue', 'nav', 'endingValue', 'value']:
                    nav_value = nav_section.get(attr)
                    if nav_value:
                        try:
                            nav = Decimal(str(nav_value))
                            logger.info(f"IBKR NAV from NAV.{attr}: {nav}")
                            break
                        except (ValueError, TypeError):
                            pass

        # 3. Try ChangeInNAV section for ending value
        if nav is None:
            change_nav = statement.find('.//ChangeInNAV')
            if change_nav is not None:
                logger.info(f"IBKR ChangeInNAV attributes: {dict(change_nav.attrib)}")
                for attr in ['endingValue', 'ending', 'total', 'value']:
                    ending_value = change_nav.get(attr)
                    if ending_value:
                        try:
                            nav = Decimal(str(ending_value))
                            logger.info(f"IBKR NAV from ChangeInNAV.{attr}: {nav}")
                            break
                        except (ValueError, TypeError):
                            pass

        # 4. Fallback: sum of cash + positions (may miss currency conversion)
        if nav is None:
            nav = total_cash_all + total_positions
            logger.warning(f"IBKR NAV fallback (cash + positions): {nav} - may be inaccurate if multiple currencies")

        result['net_asset_value'] = nav
        logger.info(f"IBKR final NAV: {nav}")

        return result

    def _parse_position(self, pos_elem) -> Optional[Dict]:
        """Parse a single position element."""
        try:
            quantity = Decimal(str(pos_elem.get('position', '0')))
            if quantity == 0:
                return None

            market_value = pos_elem.get('markMarketValue') or pos_elem.get('positionValue', '0')
            market_price = pos_elem.get('markPrice') or pos_elem.get('closePrice', '0')
            cost_basis = pos_elem.get('costBasisMoney', '0')

            asset_category = pos_elem.get('assetCategory', 'STK')

            return {
                'symbol': pos_elem.get('symbol', ''),
                'name': pos_elem.get('description', '') or pos_elem.get('symbol', ''),
                'isin': pos_elem.get('isin'),
                'quantity': abs(quantity),
                'market_price': Decimal(str(market_price)) if market_price else Decimal('0'),
                'market_value': abs(Decimal(str(market_value))) if market_value else Decimal('0'),
                'cost_basis': abs(Decimal(str(cost_basis))) if cost_basis else None,
                'currency': pos_elem.get('currency', 'USD'),
                'asset_class': self.ASSET_CLASS_MAP.get(asset_category, 'other'),
            }
        except Exception as e:
            logger.warning(f"Failed to parse position: {e}")
            return None

    def get_accounts(self) -> List[AccountInfo]:
        """Fetch list of accounts from the Flex report."""
        if not self._authenticated:
            result = self.authenticate()
            if not result.success:
                raise RuntimeError(result.error_message)

        # Fetch fresh report (this is where actual API validation happens)
        try:
            report = self._fetch_report()
        except Exception as e:
            error_msg = str(e)
            if 'Invalid token' in error_msg or '1003' in error_msg:
                raise RuntimeError("Invalid or expired Flex token. Please generate a new token in IBKR Client Portal.")
            elif 'Invalid query' in error_msg or '1004' in error_msg:
                raise RuntimeError("Invalid Query ID. Please verify the query exists in IBKR Client Portal.")
            elif '1018' in error_msg:
                raise RuntimeError("IBKR rate limit exceeded. Please wait before trying again. IBKR Flex API allows only a few requests per day per token.")
            raise

        self._last_report = report

        accounts = []
        for acc in report.get('accounts', []):
            accounts.append(AccountInfo(
                identifier=acc.get('account_id', self.account_id or 'unknown'),
                name=acc.get('name', 'IBKR Account'),
                account_type='brokerage',
                currency=acc.get('currency', 'USD')
            ))

        # If no accounts found but we have an account_id, use that
        if not accounts and self.account_id:
            accounts.append(AccountInfo(
                identifier=self.account_id,
                name='IBKR Account',
                account_type='brokerage',
                currency=report.get('currency', 'USD')
            ))

        return accounts

    def get_balance(self, account_identifier: str) -> BalanceInfo:
        """
        Get account balance from the Flex report.

        Returns the Net Asset Value (NAV) as the balance.
        """
        # Use cached report if available and recent
        if not self._last_report:
            self._last_report = self._fetch_report()

        report = self._last_report

        return BalanceInfo(
            balance=report.get('net_asset_value', Decimal('0')),
            currency=report.get('currency', 'USD'),
            balance_date=report.get('report_date', date.today()),
            raw_data={
                'cash_balances': [
                    {'currency': cb['currency'], 'amount': float(cb['amount'])}
                    for cb in report.get('cash_balances', [])
                ],
                'positions_count': len(report.get('positions', []))
            }
        )

    def supports_positions(self) -> bool:
        """Open positions come with the Flex report already fetched for the balance."""
        return True

    def get_positions(self, account_identifier: str) -> List[PositionInfo]:
        """Get positions from the Flex report."""
        if not self._last_report:
            self._last_report = self._fetch_report()

        report = self._last_report
        positions = []

        for pos in report.get('positions', []):
            positions.append(PositionInfo(
                symbol=pos.get('symbol', ''),
                name=pos.get('name', ''),
                isin=pos.get('isin'),
                quantity=pos.get('quantity', Decimal('0')),
                price_per_unit=pos.get('market_price', Decimal('0')),
                market_value=pos.get('market_value', Decimal('0')),
                currency=pos.get('currency', 'USD'),
                cost_basis=pos.get('cost_basis'),
                asset_class=pos.get('asset_class', 'other')
            ))

        return positions

    def supports_historical_data(self) -> bool:
        """IBKR Flex supports historical data via Flex Queries."""
        return True

    def historical_data_requires_extra_request(self) -> bool:
        """IBKR Flex includes historical data in the same report - no extra request."""
        return False

    def get_historical_balances(
        self,
        account_identifier: str,
        _start_date: date,
        _end_date: date
    ) -> List[BalanceInfo]:
        """
        Fetch historical balances from the Flex report.

        IBKR Flex reports include daily NAV values - we import ALL available
        data since no additional API request is needed (data comes with sync).
        Date params are ignored (prefixed with _) - we import everything.
        """
        if not self._last_report:
            self._last_report = self._fetch_report()

        historical = []

        # Try to read the saved XML report for detailed parsing
        try:
            with open('/tmp/ibkr_flex_report.xml', 'r') as f:
                content = f.read()

            root = ET.fromstring(content)
            currency = self._last_report.get('currency', 'USD')

            # Best source: EquitySummaryByReportDateInBase - has daily totals
            # Import ALL available data (no date filtering - it's already fetched)
            for equity_entry in root.findall('.//EquitySummaryByReportDateInBase'):
                report_date_str = equity_entry.get('reportDate')
                total_value = equity_entry.get('total')

                if report_date_str and total_value:
                    try:
                        nav_date = datetime.strptime(report_date_str, '%Y%m%d').date()
                        historical.append(BalanceInfo(
                            balance=Decimal(str(total_value)),
                            currency=equity_entry.get('currency', currency),
                            balance_date=nav_date
                        ))
                    except (ValueError, TypeError) as e:
                        logger.debug(f"Failed to parse EquitySummaryByReportDateInBase entry: {e}")

            # If we got data from EquitySummaryByReportDateInBase, we're done
            if historical:
                logger.info(f"IBKR: Found {len(historical)} entries from EquitySummaryByReportDateInBase")
            else:
                # Fallback: Look for ChangeInNAV entries with dates
                for nav_entry in root.findall('.//ChangeInNAV'):
                    report_date_str = nav_entry.get('reportDate') or nav_entry.get('toDate')
                    ending_value = nav_entry.get('endingValue') or nav_entry.get('ending')

                    if report_date_str and ending_value:
                        try:
                            for fmt in ['%Y%m%d', '%Y-%m-%d']:
                                try:
                                    nav_date = datetime.strptime(report_date_str, fmt).date()
                                    break
                                except ValueError:
                                    continue
                            else:
                                continue

                            historical.append(BalanceInfo(
                                balance=Decimal(str(ending_value)),
                                currency=currency,
                                balance_date=nav_date
                            ))
                        except (ValueError, TypeError) as e:
                            logger.debug(f"Failed to parse ChangeInNAV entry: {e}")

            # Also look for MTMPerformanceSummaryInBase entries (additional fallback)
            if not historical:
                for mtm_entry in root.findall('.//MTMPerformanceSummaryInBase'):
                    report_date_str = mtm_entry.get('reportDate')
                    ending_value = mtm_entry.get('mtmYTD') or mtm_entry.get('totalEndingValue')

                    if report_date_str and ending_value:
                        try:
                            for fmt in ['%Y%m%d', '%Y-%m-%d']:
                                try:
                                    mtm_date = datetime.strptime(report_date_str, fmt).date()
                                    break
                                except ValueError:
                                    continue
                            else:
                                continue

                            historical.append(BalanceInfo(
                                balance=Decimal(str(ending_value)),
                                currency=currency,
                                balance_date=mtm_date
                            ))
                        except (ValueError, TypeError) as e:
                            logger.debug(f"Failed to parse MTM entry: {e}")

            # Sort by date and deduplicate
            seen_dates = set()
            unique_historical = []
            for bal in sorted(historical, key=lambda x: x.balance_date):
                if bal.balance_date not in seen_dates:
                    seen_dates.add(bal.balance_date)
                    unique_historical.append(bal)

            if unique_historical:
                date_range = f"{unique_historical[0].balance_date} to {unique_historical[-1].balance_date}"
                logger.info(f"IBKR Flex: Found {len(unique_historical)} historical entries ({date_range})")
            return unique_historical

        except FileNotFoundError:
            logger.warning("IBKR Flex report file not found for historical data")
            return []
        except Exception as e:
            logger.warning(f"Failed to parse IBKR Flex historical data: {e}")
            return []

    def close(self):
        """Close the session."""
        if self._session:
            self._session.close()
            self._session = None
        self._last_report = None
        self._authenticated = False
