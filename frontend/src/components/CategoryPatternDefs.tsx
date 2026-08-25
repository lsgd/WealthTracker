import { categoryStyle, patternId, PATTERN_INK, type Pattern } from '../utils/categoryPalette';

function shapes(pattern: Pattern) {
  switch (pattern) {
    case 'stripes':
      return <path d="M-2 2 L2 -2 M0 8 L8 0 M6 10 L10 6" stroke={PATTERN_INK} strokeWidth="2.5" />;
    case 'dots':
      return (
        <>
          <circle cx="2" cy="2" r="1.5" fill={PATTERN_INK} />
          <circle cx="6" cy="6" r="1.5" fill={PATTERN_INK} />
        </>
      );
    case 'crosshatch':
      return <path d="M0 4 H8 M4 0 V8" stroke={PATTERN_INK} strokeWidth="1.4" />;
    default:
      return null;
  }
}

/**
 * The pattern definitions the given number of categories needs, in a
 * zero-sized SVG.
 *
 * Kept out of the charts on purpose: recharts renders the legend in its own
 * <svg>, and paint references resolve against the whole HTML document, so one
 * shared set of defs serves chart and legend alike.
 */
export default function CategoryPatternDefs({ count }: { count: number }) {
  const patterned = Array.from({ length: Math.max(0, count) }, (_, i) => i)
    .filter((i) => categoryStyle(i).pattern !== 'solid');
  if (patterned.length === 0) return null;
  return (
    <svg width="0" height="0" aria-hidden="true" style={{ position: 'absolute' }}>
      <defs>
        {patterned.map((index) => {
          const { color, pattern } = categoryStyle(index);
          return (
            <pattern
              key={index}
              id={patternId(index)}
              width="8"
              height="8"
              patternUnits="userSpaceOnUse"
            >
              <rect width="8" height="8" fill={color} />
              {shapes(pattern)}
            </pattern>
          );
        })}
      </defs>
    </svg>
  );
}
