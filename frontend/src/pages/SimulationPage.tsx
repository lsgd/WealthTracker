import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Play } from 'lucide-react';
import {
  getWealthSimulation,
  type SimulationParams,
  type SimulationResult,
} from '../api/client';

const YEAR_OPTIONS = [5, 10, 15, 20, 30];

// The simulation runs in today's purchasing power; label everything accordingly.
function formatAmount(value: number, currency: string): string {
  return new Intl.NumberFormat('de-CH', {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

const ASSET_CLASS_LABELS: Record<string, string> = {
  equity: 'Equity',
  fixed_income: 'Fixed income',
  cash: 'Cash',
  real_estate: 'Real estate',
  commodity: 'Commodities',
  crypto: 'Crypto',
  other: 'Other',
};

/** Chart rows: stacked deltas so Recharts renders the percentile fan. */
function toChartData(result: SimulationResult) {
  return result.bands.map((b) => ({
    year: b.year,
    base: b.p5,
    outerLow: b.p25 - b.p5,
    inner: b.p75 - b.p25,
    outerHigh: b.p95 - b.p75,
    p50: b.p50,
    p5: b.p5,
    p95: b.p95,
  }));
}

interface FieldSpec {
  key: string;
  label: string;
  /** Fractions (returns, volatility, inflation) are edited as percent. */
  percent?: boolean;
  step?: string;
}

const FIELDS: FieldSpec[] = [
  { key: 'start_wealth', label: 'Starting wealth' },
  { key: 'monthly_contribution', label: 'Monthly contribution' },
  { key: 'expected_return', label: 'Expected return (nominal, %/y)', percent: true, step: '0.1' },
  { key: 'volatility', label: 'Volatility (%/y)', percent: true, step: '0.1' },
  { key: 'inflation', label: 'Inflation (%/y)', percent: true, step: '0.1' },
];

/** Canonical text form of an echoed value, used for prefill AND change detection. */
function echoText(spec: FieldSpec, value: number): string {
  return spec.percent
    ? String(Number((value * 100).toFixed(2)))
    : String(Math.round(value));
}

export default function SimulationPage() {
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [targetAmount, setTargetAmount] = useState('');
  // Text values as of the last server echo. A field is only SENT when its text
  // differs from this — sent parameters become persistent overrides, so an
  // untouched field must stay unsent to keep re-deriving (e.g. start_wealth
  // follows the actual balances).
  const syncedRef = useRef<Record<string, string>>({});
  const derivedRef = useRef<Record<string, boolean>>({});

  const run = useCallback(async (extra: SimulationParams = {}) => {
    setBusy(true);
    setError('');
    const params: SimulationParams = { ...extra };
    for (const spec of FIELDS) {
      const text = fields[spec.key] ?? '';
      if (text === (syncedRef.current[spec.key] ?? '')) continue;
      if (text === '') {
        params[spec.key] = ''; // explicit clear of the stored override
        continue;
      }
      const value = Number(text);
      if (Number.isNaN(value)) continue;
      params[spec.key] = spec.percent ? value / 100 : value;
    }
    const targetSynced = syncedRef.current['target_amount'] ?? '';
    if (targetAmount !== targetSynced) {
      params['target_amount'] =
        targetAmount === '' ? '' : Number(targetAmount) || '';
    }
    try {
      const r = await getWealthSimulation(params);
      setResult(r);
      derivedRef.current = Object.fromEntries(
        Object.entries(r.parameters).map(([k, p]) => [k, p.derived]),
      );
      // The echo is now the source of truth: prefill every field from it and
      // remember the texts so the next run only sends real changes.
      const synced: Record<string, string> = {};
      const nextFields: Record<string, string> = {};
      for (const spec of FIELDS) {
        const p = r.parameters[spec.key];
        const text = p ? echoText(spec, p.value) : '';
        nextFields[spec.key] = text;
        synced[spec.key] = text;
      }
      const targetText = r.target ? String(Math.round(r.target.amount)) : '';
      synced['target_amount'] = targetText;
      syncedRef.current = synced;
      setFields(nextFields);
      setTargetAmount(targetText);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Simulation failed');
    } finally {
      setBusy(false);
    }
  }, [fields, targetAmount]);

  // First run: no parameters, so stored overrides + fresh derivation apply.
  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const years = result?.years ?? 15;
  const currency = result?.base_currency ?? 'CHF';
  const chartData = result ? toChartData(result) : [];
  const target = result?.target;
  const weights = Object.entries(result?.asset_class_weights ?? {});

  return (
    <div className="dashboard">
      <div className="card">
        <div className="chart-header">
          <h2>Wealth simulation</h2>
          <div className="range-buttons">
            {YEAR_OPTIONS.map((y) => (
              <button
                key={y}
                className={`btn btn-sm ${years === y ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => run({ years: y })}
              >
                {y}y
              </button>
            ))}
          </div>
        </div>
        <p className="form-hint">
          Monte Carlo projection ({result?.paths ?? '…'} paths) in today's purchasing
          power. Bands show the 5–95% and 25–75% ranges; the line is the median.
          Defaults are derived from your accounts, spending, and holdings — override
          any of them below (overrides are saved to your profile; clear a field to
          go back to the derived value).
        </p>

        {error && <p className="form-error">{error}</p>}

        {result && (
          <ResponsiveContainer width="100%" height={340}>
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.25} />
              <XAxis dataKey="year" tickFormatter={(y) => `+${y}y`} />
              <YAxis
                width={78}
                tickFormatter={(v: number) =>
                  Intl.NumberFormat('de-CH', { notation: 'compact' }).format(v)}
              />
              <Tooltip
                // The fan areas are excluded via tooltipType="none", so only
                // p50/p5/p95 ever reach this formatter.
                formatter={(value, name) => {
                  const labels: Record<string, string> = {
                    p50: 'Median',
                    p5: '5th percentile',
                    p95: '95th percentile',
                  };
                  return [
                    typeof value === 'number' ? formatAmount(value, currency) : '',
                    labels[String(name)] ?? String(name),
                  ];
                }}
                labelFormatter={(y) => `Year +${y}`}
              />
              {/* Invisible base lifts the stack to p5. */}
              <Area dataKey="base" stackId="fan" fill="none" stroke="none" tooltipType="none" />
              <Area dataKey="outerLow" stackId="fan" fill="#4f8cff" fillOpacity={0.15} stroke="none" tooltipType="none" />
              <Area dataKey="inner" stackId="fan" fill="#4f8cff" fillOpacity={0.35} stroke="none" tooltipType="none" />
              <Area dataKey="outerHigh" stackId="fan" fill="#4f8cff" fillOpacity={0.15} stroke="none" tooltipType="none" />
              <Line dataKey="p50" stroke="#4f8cff" strokeWidth={2} dot={false} />
              {/* Hidden series so the tooltip can show the band edges. */}
              <Line dataKey="p5" stroke="none" dot={false} />
              <Line dataKey="p95" stroke="none" dot={false} />
              {target && (
                <ReferenceLine
                  y={target.amount}
                  stroke="#fbbf24"
                  strokeDasharray="6 3"
                  label={{ value: 'Target', fill: '#fbbf24', position: 'insideTopRight' }}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}

        {target && result && (
          <p className="form-hint">
            Probability of reaching {formatAmount(target.amount, currency)} within{' '}
            {result.years} years: <strong>{(target.probability * 100).toFixed(0)}%</strong>
            {target.median_reached_year !== null
              ? ` — the median path gets there in year ${target.median_reached_year}.`
              : ' — the median path does not get there in this horizon.'}
          </p>
        )}
      </div>

      <div className="card">
        <div className="chart-header">
          <h2>Assumptions</h2>
        </div>
        <div className="simulation-params">
          {FIELDS.map((spec) => (
            <label key={spec.key} className="simulation-param">
              <span>
                {spec.label}
                {derivedRef.current[spec.key] && (
                  <span className="form-hint"> (derived)</span>
                )}
              </span>
              <input
                type="number"
                step={spec.step ?? '1'}
                value={fields[spec.key] ?? ''}
                onChange={(e) =>
                  setFields((prev) => ({ ...prev, [spec.key]: e.target.value }))}
              />
            </label>
          ))}
          <label className="simulation-param">
            <span>Target amount (optional)</span>
            <input
              type="number"
              step="1000"
              placeholder="e.g. 1000000"
              value={targetAmount}
              onChange={(e) => setTargetAmount(e.target.value)}
            />
          </label>
        </div>
        <div className="table-actions">
          <button className="btn btn-sm btn-primary" onClick={() => run()} disabled={busy}>
            <Play size={14} /> {busy ? 'Simulating…' : 'Run simulation'}
          </button>
        </div>
        {weights.length > 0 && (
          <p className="form-hint">
            Return/volatility blended from your holdings:{' '}
            {weights
              .map(([k, w]) => `${ASSET_CLASS_LABELS[k] ?? k} ${(w * 100).toFixed(0)}%`)
              .join(', ')}
            .
          </p>
        )}
      </div>
    </div>
  );
}
