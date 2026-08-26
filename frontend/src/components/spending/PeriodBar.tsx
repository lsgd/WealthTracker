import { ChevronLeft, ChevronRight } from 'lucide-react';
import { formatPeriod, HISTORY_CHOICES, type Granularity } from '../../utils/periods';

const GRANULARITIES: { value: Granularity; label: string }[] = [
  { value: 'month', label: 'Month' },
  { value: 'quarter', label: 'Quarter' },
  { value: 'year', label: 'Year' },
];

interface Props {
  granularity: Granularity;
  onGranularity: (value: Granularity) => void;
  /** Every period the report covers, oldest first. */
  periods: string[];
  selected: string | null;
  onSelect: (period: string) => void;
  history: number;
  onHistory: (value: number) => void;
  mode: 'normalized' | 'actual';
  onMode: (value: 'normalized' | 'actual') => void;
}

/**
 * The one period control for the whole page: chart, breakdown and transaction
 * list all follow it.
 *
 * Before this, the month lived in three places (the breakdown stepper, the
 * transaction filter, and implicitly the chart's range), and they could
 * disagree — the donut showed August while the list showed everything.
 */
export default function PeriodBar({
  granularity, onGranularity, periods, selected, onSelect,
  history, onHistory, mode, onMode,
}: Props) {
  const index = selected ? periods.indexOf(selected) : periods.length - 1;
  const step = (delta: number) => {
    const next = periods[index + delta];
    if (next) onSelect(next);
  };

  return (
    <div className="period-bar">
      <div className="period-bar-main">
        <div className="range-buttons">
          {GRANULARITIES.map((g) => (
            <button
              key={g.value}
              className={`btn btn-sm ${granularity === g.value ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => onGranularity(g.value)}
            >
              {g.label}
            </button>
          ))}
        </div>

        <div className="period-stepper">
          <button
            className="btn btn-sm btn-ghost"
            title="Previous period"
            disabled={index <= 0}
            onClick={() => step(-1)}
          >
            <ChevronLeft size={16} />
          </button>
          <select
            aria-label="Period"
            className="spending-month-select"
            value={selected ?? ''}
            onChange={(e) => onSelect(e.target.value)}
          >
            {[...periods].reverse().map((p) => (
              <option key={p} value={p}>{formatPeriod(p)}</option>
            ))}
          </select>
          <button
            className="btn btn-sm btn-ghost"
            title="Next period"
            disabled={index < 0 || index >= periods.length - 1}
            onClick={() => step(1)}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      <div className="period-bar-secondary">
        <div className="range-buttons">
          <button
            className={`btn btn-sm ${mode === 'normalized' ? 'btn-primary' : 'btn-ghost'}`}
            title="Yearly bills spread across the months they cover"
            onClick={() => onMode('normalized')}
          >
            Normalized
          </button>
          <button
            className={`btn btn-sm ${mode === 'actual' ? 'btn-primary' : 'btn-ghost'}`}
            title="Raw cash flow, each bill in the period it was paid"
            onClick={() => onMode('actual')}
          >
            Actual
          </button>
        </div>
        <div className="range-buttons">
          {HISTORY_CHOICES[granularity].map((count) => (
            <button
              key={count}
              className={`btn btn-sm ${history === count ? 'btn-primary' : 'btn-ghost'}`}
              title={`Show ${count} ${granularity}s of history`}
              onClick={() => onHistory(count)}
            >
              {count}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
