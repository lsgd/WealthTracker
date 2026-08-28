import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { describeRange, isImpossible, type AmountRange } from '../../utils/ruleRange';

interface Props {
  value: AmountRange;
  onChange: (next: AmountRange) => void;
  currency: string;
  startOpen?: boolean;
}

/**
 * Optional amount bounds for a rule: a lower one, an upper one, or both.
 *
 * Two is the natural maximum — a third condition on one number is either
 * redundant or contradictory — so this is two rows rather than a condition
 * builder. Bounds are compared against the amount WITHOUT its sign, because
 * spending is stored negative and "between 1.57 and 20" would otherwise have
 * to be written as an inverted, negated range.
 */
export default function RuleAmountRange({ value, onChange, currency, startOpen }: Props) {
  const [open, setOpen] = useState(Boolean(startOpen));
  const summary = describeRange(value);

  const set = (patch: Partial<AmountRange>) => onChange({ ...value, ...patch });

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
          <p className="form-hint">
            Limit the rule to an amount range. Compared without the sign, so 20
            means a {currency} 20 payment or refund. Leave a field empty for no
            bound.
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
                onChange={(e) => set({ [flag]: e.target.value === 'inc' } as Partial<AmountRange>)}
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
                onChange={(e) => set({ [field]: e.target.value } as Partial<AmountRange>)}
              />
              <span className="rule-bound-currency">{currency}</span>
            </div>
          ))}
          {summary && (
            <div className="rule-advanced-echo">
              Matches when <code>{summary}</code>
              {isImpossible(value)
                && <span className="rule-advanced-bad"> — no amount can satisfy both</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
