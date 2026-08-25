import { useLayoutEffect, useRef, useState } from 'react';

interface Props {
  text: string;
  className?: string;
  /** Lines to show before clamping. */
  lines?: number;
}

/**
 * Text cut off after a few lines, with a "more" chip when there is more to see.
 *
 * Bank wording can run to a dozen lines — a German Rechnungsabschluss recites
 * every interest rate — and one such row pushes everything else off the screen.
 * Clamping silently would hide the text with no way back, so the chip appears
 * exactly when the text really is cut off, which depends on the column width
 * and therefore has to be measured rather than guessed from its length.
 */
export default function ClampedText({ text, className = '', lines = 2 }: Props) {
  const ref = useRef<HTMLSpanElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [truncated, setTruncated] = useState(false);

  useLayoutEffect(() => {
    const el = ref.current;
    // While expanded nothing is cut off by definition — keep the flag from the
    // clamped state, or the "less" chip would remove itself.
    if (!el || expanded) return;
    const measure = () => setTruncated(el.scrollHeight > el.clientHeight + 1);
    measure();
    // The column is elastic: the same text is cut off at one window width and
    // not at another.
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text, expanded]);

  return (
    <>
      <span
        ref={ref}
        className={`${className} ${expanded ? '' : 'clamped'}`.trim()}
        style={expanded ? undefined : { WebkitLineClamp: lines }}
      >
        {text}
      </span>
      {(truncated || expanded) && (
        <button
          type="button"
          className="clamp-toggle"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? 'less' : 'more'}
        </button>
      )}
    </>
  );
}
