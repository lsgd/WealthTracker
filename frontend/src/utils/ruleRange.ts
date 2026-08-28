/** A rule's optional amount bounds, as the form holds them. */
export interface AmountRange {
  /** Empty string means "no bound". */
  min: string;
  minInclusive: boolean;
  max: string;
  maxInclusive: boolean;
}

export const EMPTY_RANGE: AmountRange = {
  min: '', minInclusive: true, max: '', maxInclusive: false,
};

/** Human reading of the configured bounds, or null when there are none. */
export function describeRange(range: AmountRange): string | null {
  const parts: string[] = [];
  if (range.min !== '') parts.push(`amount ${range.minInclusive ? '≥' : '>'} ${range.min}`);
  if (range.max !== '') parts.push(`amount ${range.maxInclusive ? '≤' : '<'} ${range.max}`);
  return parts.length ? parts.join(' and ') : null;
}

/** True when the two bounds exclude every possible amount. */
export function isImpossible(range: AmountRange): boolean {
  if (range.min === '' || range.max === '') return false;
  const low = Number(range.min);
  const high = Number(range.max);
  if (Number.isNaN(low) || Number.isNaN(high)) return false;
  // Equal bounds only hold when BOTH ends include the value.
  return low > high || (low === high && !(range.minInclusive && range.maxInclusive));
}

/** The bound fields as the API takes them; nulls clear a bound. */
export function rangePayload(range: AmountRange) {
  return {
    min_amount: range.min === '' ? null : range.min,
    min_inclusive: range.minInclusive,
    max_amount: range.max === '' ? null : range.max,
    max_inclusive: range.maxInclusive,
  };
}

/** The form's shape for a rule loaded from the API. */
export function rangeOf(rule: {
  min_amount: string | null;
  min_inclusive: boolean;
  max_amount: string | null;
  max_inclusive: boolean;
}): AmountRange {
  // The API renders decimals as "20.00"; trailing zeros in an input the user
  // is about to edit are noise, so they are trimmed for display only.
  const trim = (v: string | null) =>
    v === null ? '' : String(Number(v));
  return {
    min: trim(rule.min_amount),
    minInclusive: rule.min_inclusive,
    max: trim(rule.max_amount),
    maxInclusive: rule.max_inclusive,
  };
}
