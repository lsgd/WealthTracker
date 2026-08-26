import { ArrowDown, ArrowUp, X } from 'lucide-react';
import type { CategoryStyle } from '../../utils/categoryPalette';

export interface CategoryRow {
  name: string;
  amount: number;
  /** Same category in the period before, for the delta. */
  previous: number | null;
  /** Average over the trailing completed periods. */
  average: number | null;
  /** Target for this period, already scaled from the monthly budget. */
  budget: number | null;
  style: CategoryStyle;
}

interface Props {
  rows: CategoryRow[];
  total: number;
  currency: string;
  selected: string[];
  onToggle: (name: string) => void;
  onClear: () => void;
  onOpenDetail: (name: string) => void;
  periodNoun: string;
}

function formatAmount(value: number, currency: string): string {
  return new Intl.NumberFormat('de-CH', {
    style: 'currency', currency, maximumFractionDigits: 0,
  }).format(value);
}

function Delta({ amount, reference }: { amount: number; reference: number | null }) {
  if (reference === null || reference === 0) return <span className="cat-delta muted">—</span>;
  const change = Math.round(((amount - reference) / reference) * 100);
  if (change === 0) return <span className="cat-delta muted">0%</span>;
  return (
    <span className={`cat-delta ${change > 0 ? 'bad' : 'good'}`}>
      {change > 0 ? <ArrowUp size={11} /> : <ArrowDown size={11} />}
      {Math.abs(change)}%
    </span>
  );
}

/**
 * Categories of one period as selectable chips over a ranked bar list.
 *
 * Chips instead of a dropdown because the question is usually about more than
 * one category at a time ("groceries plus restaurants"), which a single-select
 * cannot answer; the ranked bars replace the donut's legend because eleven
 * slices in a donut are a lookup exercise, not a picture.
 */
export default function CategoryBreakdown({
  rows, total, currency, selected, onToggle, onClear, onOpenDetail, periodNoun,
}: Props) {
  // Bars are scaled against the largest of spend and budget, so a category
  // that is under its target shows visibly short of the marker.
  const largest = rows.reduce(
    (max, r) => Math.max(max, r.amount, r.budget ?? 0), 0);
  const selectedRows = rows.filter((r) => selected.includes(r.name));
  const selectedTotal = selectedRows.reduce((sum, r) => sum + r.amount, 0);

  if (rows.length === 0) {
    return <div className="chart-empty"><p>No spending in this {periodNoun}.</p></div>;
  }

  return (
    <div className="category-breakdown">
      <div className="category-chips">
        {rows.map((row) => (
          <button
            key={row.name}
            className={`category-chip ${selected.includes(row.name) ? 'selected' : ''}`}
            onClick={() => onToggle(row.name)}
          >
            <span className="category-chip-dot" style={{ background: row.style.background }} />
            {row.name}
            <span className="category-chip-amount">{formatAmount(row.amount, currency)}</span>
          </button>
        ))}
      </div>

      {selectedRows.length > 0 && (
        <div className="category-selection">
          <strong>{formatAmount(selectedTotal, currency)}</strong>
          {' '}
          {selectedRows.map((r) => r.name).join(' + ')}
          {total > 0 && ` · ${((selectedTotal / total) * 100).toFixed(1)}% of this ${periodNoun}`}
          <button className="btn btn-sm btn-ghost" onClick={onClear}>
            <X size={13} /> Clear
          </button>
        </div>
      )}

      <table className="category-ranking">
        <thead>
          <tr>
            <th colSpan={2}>Category</th>
            <th className="category-ranking-amount">Spent</th>
            <th className="category-ranking-share">Share</th>
            <th className="category-ranking-delta" title={
              `Against the average of the previous ${periodNoun}s`
            }>vs avg</th>
            <th className="category-ranking-budget">Budget</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.name}
              className={selected.length && !selected.includes(row.name) ? 'dimmed' : ''}
            >
              <td className="category-ranking-name">
                <button className="linklike" onClick={() => onOpenDetail(row.name)}>
                  {row.name}
                </button>
              </td>
              <td className="category-ranking-bar">
                <span className="category-ranking-track">
                  <span
                    className={`category-ranking-fill ${
                      row.budget !== null && row.amount > row.budget ? 'over' : ''}`}
                    style={{
                      width: `${largest ? (row.amount / largest) * 100 : 0}%`,
                      background: row.style.background,
                    }}
                  />
                  {row.budget !== null && row.budget > 0 && (
                    <span
                      className="category-ranking-target"
                      title={`Budget ${formatAmount(row.budget, currency)}`}
                      style={{ left: `${largest ? (row.budget / largest) * 100 : 0}%` }}
                    />
                  )}
                </span>
              </td>
              <td className="category-ranking-amount">
                {formatAmount(row.amount, currency)}
              </td>
              <td className="category-ranking-share">
                {total > 0 ? `${((row.amount / total) * 100).toFixed(0)}%` : '—'}
              </td>
              <td className="category-ranking-delta">
                <Delta amount={row.amount} reference={row.average ?? row.previous} />
              </td>
              <td className="category-ranking-budget">
                {row.budget === null ? (
                  <span className="cat-delta muted">—</span>
                ) : (
                  <span className={row.amount > row.budget ? 'cat-delta bad' : 'cat-delta good'}>
                    {row.amount > row.budget
                      ? `${formatAmount(row.amount - row.budget, currency)} over`
                      : `${formatAmount(row.budget - row.amount, currency)} left`}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
