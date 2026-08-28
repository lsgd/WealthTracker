import { useEffect, useState } from 'react';
import { previewCategoryRule, type RulePreview } from '../../api/client';
import {
  EMPTY_RANGE, isImpossible, rangePayload, type AmountRange,
} from '../../utils/ruleRange';

interface Props {
  matchText: string;
  isRegex: boolean;
  isTransfer: boolean;
  /** Set when editing an existing rule, so it is simulated in its own place. */
  ruleId?: number;
  /** Optional amount bounds — the preview must apply them too. */
  range?: AmountRange;
}

// Long enough that typing a merchant name is one request, short enough that
// the answer arrives before the eye leaves the field.
const DEBOUNCE_MS = 350;

/**
 * What this rule would do, answered before it is saved.
 *
 * The useful number is not how many bookings contain the text: rules never
 * overwrite an existing category, and first-match-wins means an earlier rule
 * can claim a row first. Both are called out separately, because a rule that
 * reports zero is far more often shadowed than wrong — and that is invisible
 * from the match text alone.
 */
export default function RuleImpact({
  matchText, isRegex, isTransfer, ruleId, range = EMPTY_RANGE,
}: Props) {
  const text = matchText.trim();
  // Requests are keyed so a stale answer is never shown next to newer input;
  // the previous count simply stays until its replacement lands.
  const key = JSON.stringify([text, isRegex, isTransfer, ruleId ?? null, range]);
  const [result, setResult] =
    useState<{ key: string; data?: RulePreview; error?: string } | null>(null);
  const impossible = isImpossible(range);

  useEffect(() => {
    if (!text || impossible) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      previewCategoryRule(
        {
          match_text: text,
          is_regex: isRegex,
          is_transfer: isTransfer,
          ...(ruleId ? { rule_id: ruleId } : {}),
          ...rangePayload(range),
        },
        controller.signal,
      )
        .then((data) => setResult({ key, data }))
        .catch((e: unknown) => {
          if (controller.signal.aborted) return;
          setResult({ key, error: e instanceof Error ? e.message : 'Preview failed' });
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [key, text, isRegex, isTransfer, ruleId, range, impossible]);

  if (!text) return null;
  if (impossible) {
    return (
      <div className="rule-impact bad">
        <strong>The amount range is empty</strong> — no transaction can satisfy
        both bounds.
      </div>
    );
  }
  const fresh = result?.key === key ? result : null;
  if (!fresh) return <div className="rule-impact muted">Checking…</div>;
  if (fresh.error) return <div className="rule-impact bad">{fresh.error}</div>;

  const p = fresh.data!;
  const verb = isTransfer ? 'mark as transfers' : 'categorize';
  const notes = [
    p.shadowed > 0
      && `${p.shadowed} more ${p.shadowed === 1 ? 'is' : 'are'} claimed by an earlier rule`,
    p.already_classified > 0
      && `${p.already_classified} more already ${p.already_classified === 1 ? 'has' : 'have'} a category`,
  ].filter(Boolean) as string[];

  return (
    <div className={`rule-impact ${p.will_classify > 0 ? 'good' : 'muted'}`}>
      {p.will_classify > 0 ? (
        <strong>
          Will {verb} {p.will_classify} existing{' '}
          {p.will_classify === 1 ? 'transaction' : 'transactions'}
        </strong>
      ) : (
        <strong>
          {p.matched === 0
            ? 'Matches nothing so far — it still applies to future bookings'
            : 'No existing transaction would change'}
        </strong>
      )}
      {notes.length > 0 && <span className="rule-impact-notes"> ({notes.join(', ')})</span>}
      {p.examples.length > 0 && (
        <ul className="rule-impact-examples">
          {p.examples.map((e) => (
            <li key={`${e.booking_date}-${e.text}`}>{e.text}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
