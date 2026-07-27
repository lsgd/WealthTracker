import { type ReactNode, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

/**
 * Lightweight hover/focus tooltip. The bubble is rendered into document.body with
 * fixed positioning so it can never be clipped by an overflow container (e.g. a
 * scrolling table) — a proper overlay in place of the native `title` attribute.
 */
export default function Tooltip({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);

  function show() {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos({ x: r.left + r.width / 2, y: r.top });
  }
  function hide() {
    setPos(null);
  }

  return (
    <span
      ref={ref}
      className={`tt-trigger${className ? ` ${className}` : ''}`}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      tabIndex={0}
    >
      {children}
      {pos
        && createPortal(
          <span className="tt-bubble" role="tooltip" style={{ left: pos.x, top: pos.y }}>
            {label}
          </span>,
          document.body,
        )}
    </span>
  );
}
