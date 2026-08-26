import { X } from 'lucide-react';
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis } from 'recharts';
import type { CategoryStyle } from '../../utils/categoryPalette';
import { formatPeriod, formatPeriodShort } from '../../utils/periods';

interface Props {
  name: string;
  style: CategoryStyle;
  /** One entry per period of the loaded window, oldest first. */
  series: { period: string; amount: number }[];
  selectedPeriod: string | null;
  currency: string;
  periodNoun: string;
  onSelectPeriod: (period: string) => void;
  onClose: () => void;
}

function formatAmount(value: number, currency: string, digits = 0): string {
  return new Intl.NumberFormat('de-CH', {
    style: 'currency', currency, maximumFractionDigits: digits,
  }).format(value);
}

/**
 * One category across the whole loaded window: what it costs per period, on
 * average, and in total.
 *
 * The breakdown answers "where did this period's money go"; this answers "is
 * this normal", which is the question that follows.
 */
export default function CategoryDetail({
  name, style, series, selectedPeriod, currency, periodNoun, onSelectPeriod, onClose,
}: Props) {
  const total = series.reduce((sum, s) => sum + s.amount, 0);
  // Averaged over the completed periods that actually had spending: the
  // running one is partial, and the empty ones before a category existed are
  // absence of data, not a month of spending nothing.
  const spent = series.slice(0, -1).filter((s) => s.amount > 0);
  const average = spent.length
    ? spent.reduce((sum, s) => sum + s.amount, 0) / spent.length
    : 0;
  const biggest = series.reduce(
    (max, s) => (s.amount > max.amount ? s : max), series[0] ?? { period: '', amount: 0 });

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>
            <span className="category-chip-dot" style={{ background: style.background }} />
            {name}
          </h3>
          <button className="btn btn-ghost" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="category-detail-stats">
          <div>
            <div className="summary-tile-label">Total ({series.length} {periodNoun}s)</div>
            <div className="summary-tile-value">{formatAmount(total, currency)}</div>
          </div>
          <div>
            <div className="summary-tile-label" title={
              `Over the completed ${periodNoun}s that had spending`
            }>Average per {periodNoun}</div>
            <div className="summary-tile-value">{formatAmount(average, currency)}</div>
          </div>
          <div>
            <div className="summary-tile-label">Highest</div>
            <div className="summary-tile-value">
              {formatAmount(biggest.amount, currency)}
              <span className="summary-partial">{formatPeriod(biggest.period)}</span>
            </div>
          </div>
        </div>

        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
            <XAxis dataKey="period" stroke="#8b93a7" fontSize={11}
                   tickFormatter={formatPeriodShort} />
            <Tooltip
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
              formatter={(value) => [formatAmount(Number(value), currency, 2), name]}
              labelFormatter={(label) => formatPeriod(String(label))}
              contentStyle={{ background: '#1a1f2e', border: '1px solid #2a3040' }}
            />
            <Bar
              dataKey="amount"
              style={{ cursor: 'pointer' }}
              onClick={(data: { period?: string; payload?: { period?: string } }) => {
                const period = data?.period ?? data?.payload?.period;
                if (period) onSelectPeriod(period);
              }}
            >
              {series.map((entry) => (
                <Cell
                  key={entry.period}
                  fill={style.fill}
                  // The period being inspected stands out from its history.
                  opacity={selectedPeriod === null || entry.period === selectedPeriod ? 1 : 0.45}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
