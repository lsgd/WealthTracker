/**
 * Colors plus patterns for spending categories.
 *
 * Fourteen colors cover the wheel and then some; past that a fifteenth
 * category could only repeat one. A pattern is an orthogonal axis: the same
 * fourteen colors come back striped, then dotted, then crosshatched, so
 * "Groceries" and the fifteenth category share a hue but never a look.
 *
 * The first fourteen stay solid deliberately — patterns cost legibility on the
 * thin segments of a stacked bar, so nobody should pay for them until the
 * palette actually runs out.
 */

// Excludes INCOME_COLOR and UNCATEGORIZED_COLOR so neither the income line nor
// the uncategorized bucket shares a color with a category. Eight hues around
// the wheel, then deep variants: once the wheel is covered only lightness can
// still separate two categories.
export const COLORS = [
  '#4f8cff', '#fb923c', '#a3e635', '#e879f9',
  '#fbbf24', '#38bdf8', '#f87171', '#a78bfa',
  '#f472b6', '#0e7490', '#4d7c0f', '#c2410c',
  '#6d28d9', '#be123c',
];

export const INCOME_COLOR = '#34d399';
// Not a category but the absence of one — grey, and the same grey as the app.
export const UNCATEGORIZED_COLOR = '#5b6270';
export const UNCATEGORIZED = 'Uncategorized';

export type Pattern = 'solid' | 'stripes' | 'dots' | 'crosshatch';

const PATTERNS: Pattern[] = ['solid', 'stripes', 'dots', 'crosshatch'];

/** Dark overlay rather than a lighter tone: readable over any base color. */
export const PATTERN_INK = 'rgba(0, 0, 0, 0.45)';

/**
 * Shade applied per lap through the palette: a fraction towards white when
 * positive, towards black when negative.
 *
 * The pattern alone would be enough here, but the app's stacked bars can only
 * take a flat color (fl_chart's BarChartRodStackItem has no gradient), so the
 * shade is what keeps a fifteenth category distinguishable there. Both clients
 * compute it the same way, so a category's color still matches across them.
 * Lighter first: the pattern ink is dark, and it needs something to sit on.
 */
const LAP_SHADES = [0, 0.4, -0.4, 0.65];

export interface CategoryStyle {
  color: string;
  pattern: Pattern;
  /** SVG paint: the color itself, or a reference to the pattern definition. */
  fill: string;
  /** The same thing for an HTML swatch, which cannot reference SVG paint. */
  background: string;
}

/** Mixes a hex color towards white (amount > 0) or black (amount < 0). */
export function shade(hex: string, amount: number): string {
  if (!amount) return hex;
  const target = amount > 0 ? 255 : 0;
  const weight = Math.abs(amount);
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `#${channels
    .map((c) => Math.round(c + (target - c) * weight).toString(16).padStart(2, '0'))
    .join('')}`;
}

export function patternId(index: number): string {
  return `cat-pattern-${index}`;
}

/**
 * Style for the category at [index] of the report's list (uncategorized
 * excluded from that count — it is not part of the rotation).
 */
export function categoryStyle(index: number): CategoryStyle {
  if (index < 0) {
    return {
      color: UNCATEGORIZED_COLOR,
      pattern: 'solid',
      fill: UNCATEGORIZED_COLOR,
      background: UNCATEGORIZED_COLOR,
    };
  }
  const lap = Math.floor(index / COLORS.length);
  const color = shade(COLORS[index % COLORS.length],
                      LAP_SHADES[lap % LAP_SHADES.length]);
  const pattern = PATTERNS[lap % PATTERNS.length];
  return {
    color,
    pattern,
    fill: pattern === 'solid' ? color : `url(#${patternId(index)})`,
    background: cssBackground(color, pattern),
  };
}

function cssBackground(color: string, pattern: Pattern): string {
  switch (pattern) {
    case 'stripes':
      return `repeating-linear-gradient(45deg, transparent 0 3px, ${PATTERN_INK} 3px 6px), ${color}`;
    case 'dots':
      return `radial-gradient(${PATTERN_INK} 1.4px, transparent 1.5px) 0 0 / 6px 6px, ${color}`;
    case 'crosshatch':
      return `repeating-linear-gradient(0deg, transparent 0 3px, ${PATTERN_INK} 3px 4px), `
        + `repeating-linear-gradient(90deg, transparent 0 3px, ${PATTERN_INK} 3px 4px), ${color}`;
    default:
      return color;
  }
}
