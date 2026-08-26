/** Period labels and the shapes the spending page reads them in. */

export type Granularity = 'month' | 'quarter' | 'year';

/** How much history the trend chart shows, per granularity. */
export const HISTORY_CHOICES: Record<Granularity, number[]> = {
  month: [6, 12, 24],
  quarter: [4, 8, 12],
  year: [3, 5, 10],
};

/** Periods averaged for the "vs average" comparison. */
export const AVERAGE_WINDOW = 6;

/** Compact form for chart axes, where a dozen labels share the width. */
export function formatPeriodShort(label: string): string {
  if (/^\d{4}$/.test(label)) return label;
  const [year, part] = label.split('-');
  if (part?.startsWith('Q')) return `${part} '${year.slice(2)}`;
  return `${new Date(Number(year), Number(part) - 1, 1)
    .toLocaleString('en-GB', { month: 'short' })} '${year.slice(2)}`;
}

/** '2026-08' -> 'August 2026', '2026-Q3' -> 'Q3 2026', '2026' -> '2026'. */
export function formatPeriod(label: string): string {
  if (/^\d{4}$/.test(label)) return label;
  const [year, part] = label.split('-');
  if (part?.startsWith('Q')) return `${part} ${year}`;
  return new Date(Number(year), Number(part) - 1, 1)
    .toLocaleString('en-GB', { month: 'long', year: 'numeric' });
}
