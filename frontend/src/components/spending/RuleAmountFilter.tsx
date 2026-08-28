import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import {
  DIRECTION_LABELS, describeFilter, isImpossible,
  type AmountFilter, type Direction,
} from '../../utils/ruleAmount';

interface Props {
  value: AmountFilter;
  onChange: (next: AmountFilter) => void;
  currency: string;
  startOpen?: boolean;
}

const DIRECTIONS: Direction[] = ['any', 'payment', 'income'];

/**
 * Optional amount conditions for a rule: a direction, and up to two bounds.
 *
 * Two bounds is the natural maximum — a third condition on one number is
 * either redundant or contradictory — so this is two rows rather than a
 * condition builder. The bounds are the size only; whether the money went out
 * or came in is the direction above them, which is why they stay positive.
 */
export default function RuleAmountFilter({ value, onChange, currency, startOpen }: Props) {
  const [open, setOpen] = useState(Boolean(startOpen));
  const summary = describeFilter(value);

  const set = (patch: Partial<AmountFilter>) => onChange({ ...value, ...patch });

  return (
    <div className={`rule-advanced${open ? ' open' : ''}`}>
      <button
        type="button"
        className="rule-advanced-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        Advanced
        {!open && summary && <span className="rule-advanced-summary">{summary}</span>}
      </button>

      {open && (
        <div className="rule-advanced-body">
          <div className="rule-bound rule-direction-row">
            <span className="rule-bound-label">Direction</span>
            <div className="range-buttons rule-direction">
              {DIRECTIONS.map((d) => (
                <button
                  key={d}
                  type="button"
                  className={`btn btn-sm ${value.direction === d ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => set({ direction: d })}
                >
                  {DIRECTION_LABELS[d]}
                </button>
              ))}
            </div>
          </div>
          <p className="form-hint">
            Sizes are written without a sign — paying {currency} 1.00 is
            &ldquo;Payments, &lt; 2&rdquo;. Leave a bound empty for no limit.
          </p>
          {([
            ['min', 'minInclusive', ['≥', '>'], 'At least'],
            ['max', 'maxInclusive', ['≤', '<'], 'At most'],
          ] as const).map(([field, flag, [inc, exc], label]) => (
            <div className="rule-bound" key={field}>
              <span className="rule-bound-label">{label}</span>
              <select
                aria-label={`${label} comparison`}
                value={value[flag] ? 'inc' : 'exc'}
                onChange={(e) => set({ [flag]: e.target.value === 'inc' } as Partial<AmountFilter>)}
              >
                <option value="inc">{inc}</option>
                <option value="exc">{exc}</option>
              </select>
              <input
                type="number"
                min="0"
                step="0.01"
                inputMode="decimal"
                aria-label={`${label} amount`}
                placeholder="any"
                value={value[field]}
                onChange={(e) => set({ [field]: e.target.value } as Partial<AmountFilter>)}
              />
              <span className="rule-bound-currency">{currency}</span>
            </div>
          ))}
          {summary && (
            <div className="rule-advanced-echo">
              Matches <code>{summary}</code>
              {isImpossible(value)
                && <span className="rule-advanced-bad"> — no amount can satisfy both bounds</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
