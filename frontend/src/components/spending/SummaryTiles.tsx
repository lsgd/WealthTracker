import { ArrowDown, ArrowUp, Minus } from 'lucide-react';

export interface Comparison {
  /** Change against the period right before, as a fraction (0.12 = +12%). */
  vsPrevious: number | null;
  /** Change against the trailing average of completed periods. */
  vsAverage: number | null;
}

interface Tile {
  label: string;
  value: number;
  comparison: Comparison;
  /** Whether more is good: net and income yes, spending no. */
  moreIsBetter: boolean;
}

interface Props {
  tiles: Tile[];
  currency: string;
  periodNoun: string;
  /** True while the selected period is still running (a partial total). */
  partial: boolean;
}

function formatAmount(value: number, currency: string): string {
  return new Intl.NumberFormat('de-CH', {
    style: 'currency', currency, maximumFractionDigits: 0,
  }).format(value);
}

function Delta({ change, moreIsBetter, suffix }: {
  change: number | null; moreIsBetter: boolean; suffix: string;
}) {
  if (change === null) return <span className="summary-delta muted">no {suffix} yet</span>;
  const rounded = Math.round(change * 100);
  if (rounded === 0) {
    return (
      <span className="summary-delta muted">
        <Minus size={12} /> flat vs {suffix}
      </span>
    );
  }
  // Spending more is bad, earning more is good — the arrow shows direction,
  // the color says whether that direction is welcome.
  const good = rounded > 0 === moreIsBetter;
  return (
    <span className={`summary-delta ${good ? 'good' : 'bad'}`}>
      {rounded > 0 ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
      {Math.abs(rounded)}% vs {suffix}
    </span>
  );
}

/**
 * Spending, income and net for the selected period, each against the previous
 * period and against the trailing average.
 *
 * Both comparisons on purpose: month-on-month is noisy when a yearly bill
 * lands (a 300% jump that means nothing), while the average says whether this
 * period is genuinely out of line.
 */
export default function SummaryTiles({ tiles, currency, periodNoun, partial }: Props) {
  return (
    <div className="summary-tiles">
      {tiles.map((tile) => (
        <div key={tile.label} className="summary-tile">
          <div className="summary-tile-label">{tile.label}</div>
          <div className="summary-tile-value">
            {formatAmount(tile.value, currency)}
            {partial && <span className="summary-partial" title={
              `This ${periodNoun} is not over yet`
            }>so far</span>}
          </div>
          <div className="summary-tile-deltas">
            <Delta
              change={tile.comparison.vsPrevious}
              moreIsBetter={tile.moreIsBetter}
              suffix={`last ${periodNoun}`}
            />
            <Delta
              change={tile.comparison.vsAverage}
              moreIsBetter={tile.moreIsBetter}
              suffix="average"
            />
          </div>
        </div>
      ))}
    </div>
  );
}
