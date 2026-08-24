from datetime import date, timedelta
from decimal import Decimal
from typing import List

import requests

from .models import ExchangeRate


class ExchangeRateService:
    """Service for fetching and managing exchange rates from Frankfurter API."""

    API_BASE = 'https://api.frankfurter.dev/v1'
    SUPPORTED_CURRENCIES = ['EUR', 'USD', 'CHF', 'GBP']
    # The ECB reference-rate series behind Frankfurter starts here.
    DATA_START = date(1999, 1, 4)

    @classmethod
    def fetch_rates_for_date(cls, target_date: date) -> List[ExchangeRate]:
        """Fetch all exchange rates for a specific date."""
        created_rates = []

        for base_currency in cls.SUPPORTED_CURRENCIES:
            symbols = [c for c in cls.SUPPORTED_CURRENCIES if c != base_currency]

            response = requests.get(
                f'{cls.API_BASE}/{target_date.isoformat()}',
                params={'base': base_currency, 'symbols': ','.join(symbols)},
                timeout=30
            )

            if response.ok:
                data = response.json()
                rates = data.get('rates', {})

                for to_currency, rate in rates.items():
                    exchange_rate, created = ExchangeRate.objects.update_or_create(
                        from_currency=base_currency,
                        to_currency=to_currency,
                        rate_date=target_date,
                        defaults={
                            'rate': Decimal(str(rate)),
                            'source': 'frankfurter'
                        }
                    )
                    if created:
                        created_rates.append(exchange_rate)

        return created_rates

    @classmethod
    def fetch_latest_rates(cls) -> List[ExchangeRate]:
        """Fetch the latest available exchange rates."""
        return cls.fetch_rates_for_date(date.today())

    @classmethod
    def fetch_rates_range(cls, start_date: date, end_date: date) -> int:
        """Fetch daily rates for a whole period via the range endpoint.

        One request per base currency per <=1-year chunk (a year of rates is a
        few kB) instead of four requests per day. Rows already stored are left
        untouched; returns the number of newly stored rates.
        """
        start_date = max(start_date, cls.DATA_START)
        end_date = min(end_date, date.today())
        created = 0

        chunk_start = start_date
        while chunk_start <= end_date:
            chunk_end = min(chunk_start + timedelta(days=364), end_date)
            rows = []
            for base_currency in cls.SUPPORTED_CURRENCIES:
                symbols = [c for c in cls.SUPPORTED_CURRENCIES if c != base_currency]

                response = requests.get(
                    f'{cls.API_BASE}/{chunk_start.isoformat()}..{chunk_end.isoformat()}',
                    params={'base': base_currency, 'symbols': ','.join(symbols)},
                    timeout=30
                )
                if not response.ok:
                    continue

                for day, day_rates in response.json().get('rates', {}).items():
                    for to_currency, rate in day_rates.items():
                        rows.append(ExchangeRate(
                            from_currency=base_currency,
                            to_currency=to_currency,
                            rate_date=date.fromisoformat(day),
                            rate=Decimal(str(rate)),
                            source='frankfurter',
                        ))

            if rows:
                existing = set(
                    ExchangeRate.objects
                    .filter(rate_date__range=(chunk_start, chunk_end))
                    .values_list('from_currency', 'to_currency', 'rate_date')
                )
                new_rows = [
                    r for r in rows
                    if (r.from_currency, r.to_currency, r.rate_date) not in existing
                ]
                ExchangeRate.objects.bulk_create(new_rows, ignore_conflicts=True)
                created += len(new_rows)

            chunk_start = chunk_end + timedelta(days=1)

        return created

    @classmethod
    def backfill_rates(cls, start_date: date, end_date: date) -> int:
        """Backfill historical exchange rates."""
        return cls.fetch_rates_range(start_date, end_date)

    @classmethod
    def fill_gap_before(cls, rate_date: date,
                        from_currency: str = None, to_currency: str = None) -> None:
        """Fill the store from ``rate_date`` up to the earliest stored rate.

        Called when nothing is stored at or before ``rate_date``: one ranged
        fetch closes the entire gap, so a batch of scattered old dates does
        not trigger a fetch each. Starts a week early so weekend/holiday dates
        find a preceding business-day rate. Pass the pair being looked up so
        an unsupported currency skips the fetch (it could never succeed and
        would otherwise refetch on every call).
        """
        for currency in (from_currency, to_currency):
            if currency and currency not in cls.SUPPORTED_CURRENCIES:
                return
        earliest = (
            ExchangeRate.objects.order_by('rate_date')
            .values_list('rate_date', flat=True).first()
        )
        fetch_end = earliest if earliest and earliest > rate_date else date.today()
        cls.fetch_rates_range(rate_date - timedelta(days=7), fetch_end)

    @classmethod
    def get_rate(
        cls,
        from_currency: str,
        to_currency: str,
        rate_date: date
    ) -> Decimal:
        """Get exchange rate, fetching (ranged) if necessary."""
        rate = ExchangeRate.get_rate(from_currency, to_currency, rate_date)

        if rate is None:
            cls.fill_gap_before(rate_date, from_currency, to_currency)
            rate = ExchangeRate.get_rate(from_currency, to_currency, rate_date)

        return rate if rate else Decimal('1.0')
