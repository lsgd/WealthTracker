/**
 * A rule's optional amount condition, as the form holds it.
 *
 * Direction and size are independent facts, so they are separate fields: a
 * signed bound cannot say "payments between 1 and 20" without inverting the
 * range, and an unsigned one cannot say "payments" at all. Split, the bounds
 * stay positive — the way an amount is spoken about.
 */
export type Direction = 'any' | 'payment' | 'income';

export interface AmountFilter {
  direction: Direction;
  /** Empty string means "no bound". Always positive: the size, not the sign. */
  min: string;
  minInclusive: boolean;
  max: string;
  maxInclusive: boolean;
}

export const EMPTY_FILTER: AmountFilter = {
  direction: 'any', min: '', minInclusive: true, max: '', maxInclusive: false,
};

export const DIRECTION_LABELS: Record<Direction, string> = {
  any: 'Any',
  payment: 'Payments',
  income: 'Income',
};

/** Human reading of the configured conditions, or null when there are none. */
export function describeFilter(filter: AmountFilter): string | null {
  const parts: string[] = [];
  if (filter.direction !== 'any') {
    parts.push(filter.direction === 'payment' ? 'payments' : 'income');
  }
  if (filter.min !== '') parts.push(`${filter.minInclusive ? '≥' : '>'} ${filter.min}`);
  if (filter.max !== '') parts.push(`${filter.maxInclusive ? '≤' : '<'} ${filter.max}`);
  return parts.length ? parts.join(', ') : null;
}

/** True when the two bounds exclude every possible amount. */
export function isImpossible(filter: AmountFilter): boolean {
  if (filter.min === '' || filter.max === '') return false;
  const low = Number(filter.min);
  const high = Number(filter.max);
  if (Number.isNaN(low) || Number.isNaN(high)) return false;
  // Equal bounds only hold when BOTH ends include the value.
  return low > high || (low === high && !(filter.minInclusive && filter.maxInclusive));
}

/** The fields as the API takes them; nulls clear a bound. */
export function filterPayload(filter: AmountFilter) {
  return {
    direction: filter.direction,
    min_amount: filter.min === '' ? null : filter.min,
    min_inclusive: filter.minInclusive,
    max_amount: filter.max === '' ? null : filter.max,
    max_inclusive: filter.maxInclusive,
  };
}

/** The form's shape for a rule loaded from the API. */
export function filterOf(rule: {
  direction?: Direction;
  min_amount: string | null;
  min_inclusive: boolean;
  max_amount: string | null;
  max_inclusive: boolean;
}): AmountFilter {
  // The API renders decimals as "20.00"; trailing zeros in an input the user
  // is about to edit are noise, so they are trimmed for display only.
  const trim = (v: string | null) => (v === null ? '' : String(Number(v)));
  return {
    direction: rule.direction ?? 'any',
    min: trim(rule.min_amount),
    minInclusive: rule.min_inclusive,
    max: trim(rule.max_amount),
    maxInclusive: rule.max_inclusive,
  };
}
