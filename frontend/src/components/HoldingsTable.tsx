import { useEffect, useState } from 'react';
import { getWealthHoldings, type HoldingsReport } from '../api/client';

const ASSET_CLASS_LABELS: Record<string, string> = {
  equity: 'Equity',
  fixed_income: 'Fixed income',
  cash: 'Cash',
  real_estate: 'Real estate',
  commodity: 'Commodities',
  crypto: 'Crypto',
  other: 'Other',
};

function formatCurrency(value: number, currency: string): string {
  return new Intl.NumberFormat('de-CH', {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

function formatQuantity(value: number): string {
  return new Intl.NumberFormat('de-CH', { maximumFractionDigits: 4 }).format(value);
}

interface Props {
  refreshKey?: number;
}

export default function HoldingsTable({ refreshKey }: Props) {
  const [report, setReport] = useState<HoldingsReport | null>(null);

  useEffect(() => {
    getWealthHoldings().then(setReport).catch(() => setReport(null));
  }, [refreshKey]);

  // Positions only exist for brokers that report them (IBKR, Morgan Stanley) and
  // only after a sync — render nothing at all until there is something to show.
  if (!report || report.holdings.length === 0) return null;

  return (
    <div className="card">
      <div className="chart-header">
        <h2>Holdings</h2>
        {report.as_of && <span className="form-hint">as of {report.as_of}</span>}
      </div>
      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Asset</th>
              <th>Class</th>
              <th className="spending-amount-col">Quantity</th>
              <th className="spending-amount-col">Value</th>
              <th className="spending-amount-col">%</th>
              <th>Accounts</th>
            </tr>
          </thead>
          <tbody>
            {report.holdings.map((h) => (
              <tr key={h.isin || h.symbol || h.name}>
                <td>
                  {h.name || h.symbol}
                  {h.symbol && h.name && (
                    <span className="form-hint"> {h.symbol}</span>
                  )}
                </td>
                <td>{ASSET_CLASS_LABELS[h.asset_class] ?? h.asset_class}</td>
                <td className="spending-amount-col">{formatQuantity(h.quantity)}</td>
                <td className="spending-amount-col">
                  {formatCurrency(h.value_base_currency, report.base_currency)}
                </td>
                <td className="spending-amount-col">{h.percentage.toFixed(1)}%</td>
                <td>{h.accounts.join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
