from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from .models import ExchangeRate
from .services import ExchangeRateService


def _range_response(url, params=None, timeout=None):
    """Fake frankfurter range endpoint: one business-day rate per request."""
    class Resp:
        ok = True

        def json(self):
            start = url.rsplit('/', 1)[-1].split('..')[0]
            base = params['base']
            symbols = params['symbols'].split(',')
            return {'rates': {start: {s: 1.5 for s in symbols}}}

    return Resp()


class FetchRatesRangeTests(TestCase):
    @patch('exchange_rates.services.requests.get', side_effect=_range_response)
    def test_one_request_per_base_per_year_chunk(self, mock_get):
        start = date.today() - timedelta(days=500)  # spans two <=1-year chunks
        ExchangeRateService.fetch_rates_range(start, date.today())
        # 4 base currencies x 2 chunks — NOT 4 x 500 days.
        self.assertEqual(mock_get.call_count, 8)
        # Ranged URL, not a single-date one.
        called_url = mock_get.call_args_list[0][0][0]
        self.assertIn('..', called_url)

    @patch('exchange_rates.services.requests.get', side_effect=_range_response)
    def test_existing_rows_are_kept(self, mock_get):
        day = date.today() - timedelta(days=30)
        ExchangeRate.objects.create(
            from_currency='EUR', to_currency='CHF', rate_date=day,
            rate=Decimal('0.93'), source='manual',
        )
        created = ExchangeRateService.fetch_rates_range(day, day)
        # The stored EUR->CHF row survives; only the other pairs are new.
        self.assertEqual(
            ExchangeRate.objects.get(
                from_currency='EUR', to_currency='CHF', rate_date=day,
            ).rate,
            Decimal('0.93'),
        )
        self.assertEqual(created, 11)  # 4 bases x 3 symbols - 1 existing

    @patch('exchange_rates.services.requests.get', side_effect=_range_response)
    def test_clamped_to_data_start_and_today(self, mock_get):
        ExchangeRateService.fetch_rates_range(
            date(1980, 1, 1), date.today() + timedelta(days=30))
        first_url = mock_get.call_args_list[0][0][0]
        self.assertIn(ExchangeRateService.DATA_START.isoformat(), first_url)
        last_url = mock_get.call_args_list[-1][0][0]
        self.assertIn(date.today().isoformat(), last_url)


class GetRateGapFillTests(TestCase):
    @patch('exchange_rates.services.requests.get', side_effect=_range_response)
    def test_miss_fills_gap_up_to_earliest_stored_rate(self, mock_get):
        # Store covers only the recent past; the lookup is 100 days earlier.
        ExchangeRate.objects.create(
            from_currency='EUR', to_currency='CHF',
            rate_date=date.today() - timedelta(days=10), rate=Decimal('0.93'),
        )
        old = date.today() - timedelta(days=110)
        rate = ExchangeRateService.get_rate('CHF', 'EUR', old)
        self.assertEqual(rate, Decimal('1.5'))
        # One chunk (gap < 1 year): 4 requests, ending at the earliest stored
        # rate rather than today.
        self.assertEqual(mock_get.call_count, 4)
        url = mock_get.call_args_list[0][0][0]
        self.assertIn(
            (date.today() - timedelta(days=10)).isoformat(), url)

    @patch('exchange_rates.services.requests.get', side_effect=_range_response)
    def test_second_lookup_hits_the_store(self, mock_get):
        old = date.today() - timedelta(days=100)
        ExchangeRateService.get_rate('CHF', 'EUR', old)
        calls = mock_get.call_count
        ExchangeRateService.get_rate('CHF', 'EUR', old + timedelta(days=3))
        self.assertEqual(mock_get.call_count, calls)

    @patch('exchange_rates.services.requests.get', side_effect=_range_response)
    def test_unsupported_currency_never_fetches(self, mock_get):
        rate = ExchangeRateService.get_rate('SEK', 'EUR', date.today())
        self.assertEqual(rate, Decimal('1.0'))
        mock_get.assert_not_called()
