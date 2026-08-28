import { useEffect, useRef, type ReactNode } from 'react';

interface Props {
  onClose: () => void;
  children: ReactNode;
  /** Set for a dialog that must not be dismissed by accident (mid-save). */
  locked?: boolean;
  className?: string;
}

/**
 * The backdrop every dialog sits on: Escape closes, and so does a click on the
 * backdrop itself — but only when the click BEGAN there.
 *
 * Without that second condition, selecting text inside a dialog and releasing
 * the mouse past its edge closes it: the browser fires `click` on the nearest
 * common ancestor of press and release, which is the backdrop. Losing a
 * half-written rule to a text selection is the kind of bug that makes a dialog
 * feel hostile, so the press target is remembered rather than trusting the
 * click's target alone.
 */
export default function ModalOverlay({ onClose, children, locked, className }: Props) {
  const pressedBackdrop = useRef(false);

  useEffect(() => {
    if (locked) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose, locked]);

  return (
    <div
      className={`modal-overlay${className ? ` ${className}` : ''}`}
      onMouseDown={(e) => { pressedBackdrop.current = e.target === e.currentTarget; }}
      onClick={(e) => {
        if (locked || e.target !== e.currentTarget || !pressedBackdrop.current) return;
        pressedBackdrop.current = false;
        onClose();
      }}
    >
      {children}
    </div>
  );
}
