import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { AlertTriangle, ArrowLeftRight, ChevronLeft, ChevronRight, GripVertical, History, Plus, Trash2, X } from 'lucide-react';
import AiCategorization from '../components/AiCategorization';
import type {
  CategoryRule,
  SpendingReport,
  Transaction,
  TransactionCategory,
} from '../api/client';
import {
  backfillTransactions,
  classifyTransaction,
  createCategory,
  createCategoryRule,
  deleteCategoryRule,
  detectTransfers,
  getAccountTransactions,
  getAccounts,
  getCategories,
  getCategoryRules,
  getSpendingMonthly,
  reorderCategoryRules,
} from '../api/client';

// Category palette. Deliberately does NOT contain INCOME_COLOR so the income
// line never shares its color with a category.
const COLORS = [
  '#4f8cff', '#a3e635', '#fbbf24', '#f87171',
  '#a78bfa', '#fb923c', '#38bdf8', '#e879f9',
];

const INCOME_COLOR = '#34d399';

const MODES = [
  { label: 'Normalized', value: 'normalized' as const },
  { label: 'Actual', value: 'actual' as const },
];

const RANGES = [6, 12, 24];

// Default history window for a one-off import.
const DEFAULT_BACKFILL_MONTHS = 15;

interface AccountOption {
  id: number;
  name: string;
}

function formatMonthLabel(month: string): string {
  const [year, m] = month.split('-').map(Number);
  return new Date(year, m - 1, 1).toLocaleString('en-GB', { month: 'long', year: 'numeric' });
}

function formatAmount(value: number, currency: string): string {
  return new Intl.NumberFormat('de-CH', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export default function SpendingPage() {
  const [tab, setTab] = useState<'insights' | 'config'>('insights');
  const [mode, setMode] = useState<'normalized' | 'actual'>('normalized');
  const [months, setMonths] = useState(12);
  const [report, setReport] = useState<SpendingReport | null>(null);
  const [categories, setCategories] = useState<TransactionCategory[]>([]);
  const [rules, setRules] = useState<CategoryRule[]>([]);
  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [txCount, setTxCount] = useState(0);
  const [txPage, setTxPage] = useState(1);
  const [error, setError] = useState('');

  // New rule form. ruleCategory '__new__' means "create a category first" —
  // the Add Rule click then opens the naming dialog instead of saving directly.
  const [ruleText, setRuleText] = useState('');
  const [ruleCategory, setRuleCategory] = useState<number | '' | '__new__'>('');
  const [ruleSpread, setRuleSpread] = useState(1);
  const [draggedRule, setDraggedRule] = useState<number | null>(null);
  const [categoryDialogOpen, setCategoryDialogOpen] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState('');
  const [savingRule, setSavingRule] = useState(false);

  // Historical transaction backfill (web only — needs the KEK to decrypt credentials).
  const [backfillAccount, setBackfillAccount] = useState<number | ''>('');
  const [backfillStart, setBackfillStart] = useState('');
  const [backfillEnd, setBackfillEnd] = useState('');
  const [backfillDefaultRange, setBackfillDefaultRange] = useState(true);
  const [backfillBusy, setBackfillBusy] = useState(false);
  const [backfillNotice, setBackfillNotice] = useState('');
  // A short-served range is not an error, but it must not read like a success either:
  // the chart's earlier months stay empty and only this notice explains why.
  const [backfillTruncated, setBackfillTruncated] = useState(false);

  const loadReport = useCallback(async () => {
    try {
      setReport(await getSpendingMonthly(months, mode));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load report');
    }
  }, [months, mode]);

  const loadTransactions = useCallback(async (id: number, page: number) => {
    try {
      const data = await getAccountTransactions(id, page);
      setTxCount(data.count);
      setTransactions((prev) => (page === 1 ? data.results : [...prev, ...data.results]));
      setTxPage(page);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load transactions');
    }
  }, []);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  useEffect(() => {
    (async () => {
      try {
        const [cats, ruleList, accountData] = await Promise.all([
          getCategories(),
          getCategoryRules(),
          getAccounts(),
        ]);
        setCategories(cats);
        setRules(ruleList);
        const options: AccountOption[] = (accountData.results ?? accountData).map(
          (a: { id: number; name: string }) => ({ id: a.id, name: a.name }),
        );
        setAccounts(options);
        if (options.length > 0) {
          setAccountId(options[0].id);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load data');
      }
    })();
  }, []);

  useEffect(() => {
    if (accountId !== null) {
      loadTransactions(accountId, 1);
    }
  }, [accountId, loadTransactions]);

  // Month selected for the pie breakdown (bar click or dropdown); defaults to
  // the latest month of the report.
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);
  // Two-way hover sync between the donut and its legend rows.
  const [hoveredSlice, setHoveredSlice] = useState<number | null>(null);
  // Show/hide the Uncategorized bucket, separately per card.
  const [showUncatBars, setShowUncatBars] = useState(true);
  const [showUncatPie, setShowUncatPie] = useState(true);

  const chartData = useMemo(() => {
    if (!report) return [];
    return report.months.map((m) => ({
      month: m.month,
      Income: m.income,
      ...m.by_category,
    }));
  }, [report]);

  const monthDetail = useMemo(() => {
    if (!report || report.months.length === 0) return null;
    return report.months.find((m) => m.month === selectedMonth)
      ?? report.months[report.months.length - 1];
  }, [report, selectedMonth]);

  // Slice indices change with the month — drop a stale highlight.
  useEffect(() => {
    setHoveredSlice(null);
  }, [monthDetail]);

  const monthIndex = useMemo(() => {
    if (!report || !monthDetail) return -1;
    return report.months.findIndex((m) => m.month === monthDetail.month);
  }, [report, monthDetail]);

  const stepMonth = (delta: number) => {
    if (!report || monthIndex < 0) return;
    const next = report.months[monthIndex + delta];
    if (next) setSelectedMonth(next.month);
  };

  const pieData = useMemo(() => {
    if (!monthDetail || !report) return [];
    // Colors follow the bar chart: index within the report's category order.
    return Object.entries(monthDetail.by_category)
      .filter(([name]) => showUncatPie || name !== 'Uncategorized')
      .map(([name, value]) => {
        const index = report.categories.indexOf(name);
        return {
          name,
          value,
          color: index >= 0 ? COLORS[index % COLORS.length] : '#5b6270',
        };
      });
  }, [monthDetail, report, showUncatPie]);

  // Center total and percentages refer to what the donut actually shows.
  const pieTotal = useMemo(
    () => pieData.reduce((sum, entry) => sum + entry.value, 0),
    [pieData],
  );

  const avgExpenses = useMemo(() => {
    if (!report || report.months.length === 0) return 0;
    // The running month is always partial — exclude it from the average.
    const complete = report.months.slice(0, -1);
    if (complete.length === 0) return report.months[0].expenses;
    return complete.reduce((sum, m) => sum + m.expenses, 0) / complete.length;
  }, [report]);

  const handleClassify = async (
    tx: Transaction,
    fields: { category?: number | null; spread_months?: number; is_transfer?: boolean },
  ) => {
    try {
      const updated = await classifyTransaction(tx.id, fields);
      setTransactions((prev) => prev.map((t) => (t.id === tx.id ? updated : t)));
      loadReport();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update transaction');
    }
  };

  const saveRule = async (categoryId: number) => {
    setSavingRule(true);
    try {
      const rule = await createCategoryRule({
        match_text: ruleText.trim(),
        category: categoryId,
        spread_months: ruleSpread,
      });
      setRules((prev) => [...prev, rule]);
      setRuleText('');
      setRuleCategory('');
      setRuleSpread(1);
      // The rule applied retroactively — refresh everything that may have changed.
      loadReport();
      if (accountId !== null) loadTransactions(accountId, 1);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create rule');
      return false;
    } finally {
      setSavingRule(false);
    }
  };

  const handleAddRule = () => {
    if (!ruleText.trim() || ruleCategory === '') return;
    if (ruleCategory === '__new__') {
      setCategoryDialogOpen(true);
      return;
    }
    saveRule(ruleCategory);
  };

  const handleCreateCategoryAndRule = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = newCategoryName.trim();
    if (!name) return;
    try {
      const category = await createCategory(name);
      setCategories((prev) => [...prev, category].sort((a, b) => a.name.localeCompare(b.name)));
      setNewCategoryName('');
      setCategoryDialogOpen(false);
      await saveRule(category.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create category');
    }
  };

  // Drag-and-drop rule ordering: rules are first-match-wins, so a more specific
  // rule has to be able to sit above a broader one.
  const handleRuleDrop = async (targetIndex: number) => {
    const from = draggedRule;
    setDraggedRule(null);
    if (from === null || from === targetIndex) return;
    const next = [...rules];
    const [moved] = next.splice(from, 1);
    next.splice(targetIndex, 0, moved);
    setRules(next); // optimistic — the server echoes the persisted order back
    try {
      setRules(await reorderCategoryRules(next.map((r) => r.id)));
      loadReport();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reorder rules');
      getCategoryRules().then(setRules).catch(() => {});
    }
  };

  const handleDeleteRule = async (ruleId: number) => {
    try {
      await deleteCategoryRule(ruleId);
      setRules((prev) => prev.filter((r) => r.id !== ruleId));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete rule');
    }
  };

  // Default window: the last DEFAULT_BACKFILL_MONTHS months up to today, so a
  // full year of history plus the current partial month is covered in one go.
  const defaultBackfillStart = () => {
    const d = new Date();
    d.setMonth(d.getMonth() - DEFAULT_BACKFILL_MONTHS);
    return d.toISOString().slice(0, 10);
  };

  const handleBackfill = async () => {
    if (backfillAccount === '') return;
    const start = backfillDefaultRange ? defaultBackfillStart() : backfillStart;
    const end = backfillDefaultRange ? undefined : (backfillEnd || undefined);
    if (!start) return;
    setError('');
    setBackfillNotice('');
    setBackfillTruncated(false);
    setBackfillBusy(true);
    try {
      const outcome = await backfillTransactions(backfillAccount, start, end);
      if (outcome.status === 'error') {
        setError(outcome.error || 'Backfill failed');
      } else {
        setBackfillNotice(
          outcome.message || `${outcome.imported ?? 0} new transactions imported`,
        );
        setBackfillTruncated(Boolean(outcome.truncated));
        loadReport();
        if (accountId !== null) loadTransactions(accountId, 1);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Backfill failed');
    } finally {
      setBackfillBusy(false);
    }
  };

  const handleDetectTransfers = async () => {
    try {
      await detectTransfers();
      loadReport();
      if (accountId !== null) loadTransactions(accountId, 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Transfer detection failed');
    }
  };

  // Close the category dialog on Escape.
  useEffect(() => {
    if (!categoryDialogOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setCategoryDialogOpen(false);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [categoryDialogOpen]);

  const currency = report?.base_currency ?? 'EUR';

  return (
    <div className="dashboard">
        {error && (
          <div className="form-error" onClick={() => setError('')}>{error}</div>
        )}

        <div className="page-tabs">
          <button
            className={tab === 'insights' ? 'active' : ''}
            onClick={() => setTab('insights')}
          >
            Insights
          </button>
          <button
            className={tab === 'config' ? 'active' : ''}
            onClick={() => setTab('config')}
          >
            Configuration
          </button>
        </div>

        {tab === 'insights' && (<>
        <div className="card">
          <div className="chart-header">
            <h2>Monthly Spending</h2>
            <div className="range-buttons">
              {MODES.map((m) => (
                <button
                  key={m.value}
                  className={`btn btn-sm ${mode === m.value ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => setMode(m.value)}
                  title={m.value === 'normalized'
                    ? 'Yearly bills spread across their months'
                    : 'Raw cash flow per month'}
                >
                  {m.label}
                </button>
              ))}
              <span className="spending-toolbar-gap" />
              {RANGES.map((r) => (
                <button
                  key={r}
                  className={`btn btn-sm ${months === r ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => setMonths(r)}
                >
                  {r}m
                </button>
              ))}
              <span className="spending-toolbar-gap" />
              <button
                className={`btn btn-sm ${showUncatBars ? 'btn-primary' : 'btn-ghost'}`}
                title="Show or hide uncategorized spending"
                onClick={() => setShowUncatBars((v) => !v)}
              >
                Uncategorized
              </button>
            </div>
          </div>
          {report && (
            <p className="spending-average">
              Average monthly spending ({mode}): <strong>{formatAmount(avgExpenses, currency)}</strong>
            </p>
          )}
          {chartData.length === 0 ? (
            <div className="chart-empty"><p>No transactions yet.</p></div>
          ) : (
            <ResponsiveContainer width="100%" height={340}>
              <ComposedChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="month" stroke="#8b93a7" fontSize={12} />
                <YAxis stroke="#8b93a7" fontSize={12} />
                <Tooltip
                  formatter={(value, name) =>
                    [formatAmount(Number(value ?? 0), currency), String(name)]}
                  // Income first, then categories in report order (largest total first).
                  itemSorter={(item) => (item.name === 'Income'
                    ? -1
                    : report?.categories.indexOf(String(item.name)) ?? 0)}
                  contentStyle={{ background: '#1a1f2e', border: '1px solid #2a3040' }}
                />
                <Legend />
                {report?.categories.filter((name) => showUncatBars || name !== 'Uncategorized').map((name) => (
                  <Bar
                    key={name}
                    dataKey={name}
                    stackId="expenses"
                    fill={COLORS[(report?.categories.indexOf(name) ?? 0) % COLORS.length]}
                    onClick={(data: { month?: string; payload?: { month?: string } }) => {
                      const m = data?.month ?? data?.payload?.month;
                      if (m) setSelectedMonth(m);
                    }}
                    style={{ cursor: 'pointer' }}
                  />
                ))}
                <Line dataKey="Income" stroke={INCOME_COLOR} strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="card">
          <div className="chart-header">
            <h2>
              Breakdown
              {monthDetail && (
                <span className="spending-month-title"> · {formatMonthLabel(monthDetail.month)}</span>
              )}
            </h2>
            <div className="range-buttons">
              <button
                className={`btn btn-sm ${showUncatPie ? 'btn-primary' : 'btn-ghost'}`}
                title="Show or hide uncategorized spending"
                onClick={() => setShowUncatPie((v) => !v)}
              >
                Uncategorized
              </button>
              <span className="spending-toolbar-gap" />
              <button
                className="btn btn-sm btn-ghost"
                title="Previous month"
                disabled={monthIndex <= 0}
                onClick={() => stepMonth(-1)}
              >
                <ChevronLeft size={16} />
              </button>
              <select
                className="spending-month-select"
                value={monthDetail?.month ?? ''}
                onChange={(e) => setSelectedMonth(e.target.value)}
              >
                {report?.months.map((m) => (
                  <option key={m.month} value={m.month}>{m.month}</option>
                ))}
              </select>
              <button
                className="btn btn-sm btn-ghost"
                title="Next month"
                disabled={report === null || monthIndex < 0 || monthIndex >= report.months.length - 1}
                onClick={() => stepMonth(1)}
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
          {!monthDetail || pieData.length === 0 ? (
            <div className="chart-empty"><p>No spending in this month.</p></div>
          ) : (
            <div className="breakdown-content">
              <div className="breakdown-chart">
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={90}
                      paddingAngle={2}
                      onMouseLeave={() => setHoveredSlice(null)}
                    >
                      {pieData.map((entry, index) => (
                        <Cell
                          key={entry.name}
                          fill={entry.color}
                          opacity={hoveredSlice === null || hoveredSlice === index ? 1 : 0.4}
                          style={{ cursor: 'pointer' }}
                          onMouseEnter={() => setHoveredSlice(index)}
                        />
                      ))}
                    </Pie>
                    <text
                      x="50%" y="47%" textAnchor="middle" dominantBaseline="middle"
                      className="spending-donut-total"
                    >
                      {new Intl.NumberFormat('de-CH', {
                        style: 'currency', currency, maximumFractionDigits: 0,
                      }).format(pieTotal)}
                    </text>
                    <text
                      x="50%" y="57%" textAnchor="middle" dominantBaseline="middle"
                      className="spending-donut-label"
                    >
                      {formatMonthLabel(monthDetail.month)}
                    </text>
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="breakdown-legend">
                {pieData.map((entry, index) => (
                  <div
                    key={entry.name}
                    className={`breakdown-legend-item ${hoveredSlice === index ? 'highlighted' : ''} ${hoveredSlice !== null && hoveredSlice !== index ? 'dimmed' : ''}`}
                    onMouseEnter={() => setHoveredSlice(index)}
                    onMouseLeave={() => setHoveredSlice(null)}
                    onClick={() => setHoveredSlice(index)}
                  >
                    <span
                      className="breakdown-legend-color"
                      style={{ backgroundColor: entry.color }}
                    />
                    <span className="breakdown-legend-label">{entry.name}</span>
                    <span className="breakdown-legend-value">
                      {formatAmount(entry.value, currency)}
                    </span>
                    <span className="breakdown-legend-pct">
                      {pieTotal > 0 ? ((entry.value / pieTotal) * 100).toFixed(1) : '0.0'}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="card">
          <div className="chart-header">
            <h2>Transactions</h2>
            <div className="range-buttons">
              <select
                value={accountId ?? ''}
                onChange={(e) => setAccountId(Number(e.target.value))}
              >
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
              <button
                className="btn btn-sm btn-ghost"
                title="Re-run transfer detection"
                onClick={handleDetectTransfers}
              >
                <ArrowLeftRight size={14} /> Detect transfers
              </button>
            </div>
          </div>
          {transactions.length === 0 ? (
            <p className="table-empty">No transactions for this account.</p>
          ) : (
            <div className="table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Counterparty</th>
                    <th>Description</th>
                    <th>Category</th>
                    <th title="Exclude from the spending report">Transfer</th>
                    <th className="spending-amount-col">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((tx) => (
                    <tr key={tx.id} className={tx.is_transfer ? 'spending-transfer-row' : ''}>
                      <td>{tx.booking_date}</td>
                      <td>{tx.counterparty}</td>
                      <td>
                        {tx.description}
                        {tx.is_transfer && <span className="spending-transfer-badge">Transfer</span>}
                        {tx.spread_months > 1 && (
                          <span className="spending-spread-badge">/{tx.spread_months}m</span>
                        )}
                      </td>
                      <td>
                        <select
                          value={tx.category ?? ''}
                          onChange={(e) => handleClassify(tx, {
                            category: e.target.value ? Number(e.target.value) : null,
                          })}
                        >
                          <option value="">—</option>
                          {categories.map((c) => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                          ))}
                        </select>
                      </td>
                      <td>
                        {/* Auto-detection only pairs entries between two accounts that
                            both have a feed, so broker funding (e.g. a wire to IBKR)
                            can never be detected — it has to be markable by hand. */}
                        <input
                          type="checkbox"
                          aria-label="Mark as transfer"
                          title="Transfers are excluded from the spending report"
                          checked={tx.is_transfer}
                          onChange={(e) => handleClassify(tx, { is_transfer: e.target.checked })}
                        />
                      </td>
                      <td className={`spending-amount-col ${Number(tx.amount) < 0 ? 'spending-neg' : 'spending-pos'}`}>
                        {formatAmount(Number(tx.amount), tx.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {transactions.length < txCount && (
                <div className="table-actions">
                  <button
                    className="btn btn-sm btn-ghost"
                    onClick={() => accountId !== null && loadTransactions(accountId, txPage + 1)}
                  >
                    Load more ({transactions.length}/{txCount})
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
        </>)}

        {tab === 'config' && (<>
        <div className="card">
          <div className="chart-header">
            <h2>Rules</h2>
          </div>
          <p className="form-hint">
            Match text is compared against counterparty and description. New rules apply
            to all still-uncategorized transactions. A spread of 12 shows a yearly bill
            as one twelfth per month in the normalized view. Rules are checked top to
            bottom and the first match wins — drag to reorder, so a specific rule can sit
            above a broader one.
          </p>
          <div className="spending-rules">
            {rules.map((rule, index) => (
              <div
                key={rule.id}
                className={`spending-rule-row spending-rule-draggable ${draggedRule === index ? 'dragging' : ''}`}
                draggable
                onDragStart={() => setDraggedRule(index)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => handleRuleDrop(index)}
                onDragEnd={() => setDraggedRule(null)}
              >
                <GripVertical size={14} className="spending-rule-grip" />
                <span className="spending-rule-index">{index + 1}</span>
                <code>{rule.match_text}</code>
                <span>→ {rule.category_name}</span>
                {rule.spread_months > 1 && <span className="spending-spread-badge">/{rule.spread_months} months</span>}
                <button
                  className="btn btn-sm btn-ghost"
                  title="Delete rule"
                  onClick={() => handleDeleteRule(rule.id)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <div className="spending-rule-row spending-rule-new">
              <input
                placeholder="match text, e.g. rewe"
                value={ruleText}
                onChange={(e) => setRuleText(e.target.value)}
              />
              <select
                value={ruleCategory}
                onChange={(e) => {
                  const v = e.target.value;
                  setRuleCategory(v === '' ? '' : v === '__new__' ? '__new__' : Number(v));
                }}
              >
                <option value="">Category…</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
                <option value="__new__">+ New category…</option>
              </select>
              <select value={ruleSpread} onChange={(e) => setRuleSpread(Number(e.target.value))}>
                <option value={1}>no spread</option>
                <option value={3}>/3 months</option>
                <option value={6}>/6 months</option>
                <option value={12}>/12 months</option>
              </select>
              <button
                className="btn btn-sm btn-primary"
                onClick={handleAddRule}
                disabled={savingRule || !ruleText.trim() || ruleCategory === ''}
              >
                <Plus size={14} /> Rule
              </button>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="chart-header">
            <h2>Import history</h2>
          </div>
          <p className="form-hint">
            A sync only fetches transactions newer than the ones already stored. Use this
            to pull an older period once. Re-importing a period you already have changes
            nothing. The default asks for the last {DEFAULT_BACKFILL_MONTHS} months — that
            is the requested maximum, banks that keep less simply return what they have
            (EBICS often serves years, FinTS/DKB typically about 90 days).
          </p>
          <div className="spending-rule-row spending-rule-new">
            <select
              value={backfillAccount}
              onChange={(e) => setBackfillAccount(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">Account…</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            <label className="spending-switch">
              <input
                type="checkbox"
                checked={backfillDefaultRange}
                onChange={(e) => setBackfillDefaultRange(e.target.checked)}
              />
              Last {DEFAULT_BACKFILL_MONTHS} months (max)
            </label>
            {!backfillDefaultRange && (
              <>
                <input
                  type="date"
                  aria-label="Start date"
                  value={backfillStart}
                  onChange={(e) => setBackfillStart(e.target.value)}
                />
                <input
                  type="date"
                  aria-label="End date (defaults to today)"
                  value={backfillEnd}
                  onChange={(e) => setBackfillEnd(e.target.value)}
                />
              </>
            )}
            <button
              className="btn btn-sm btn-primary"
              onClick={handleBackfill}
              disabled={
                backfillBusy || backfillAccount === ''
                || (!backfillDefaultRange && !backfillStart)
              }
            >
              <History size={14} /> {backfillBusy ? 'Fetching…' : 'Fetch'}
            </button>
          </div>
          {backfillNotice && (
            <p className={backfillTruncated ? 'form-hint form-hint-warning' : 'form-hint'}>
              {backfillTruncated && <AlertTriangle size={14} />} {backfillNotice}
            </p>
          )}
        </div>

        <AiCategorization onApplied={() => {
          loadReport();
          getCategories().then(setCategories).catch(() => {});
          getCategoryRules().then(setRules).catch(() => {});
          if (accountId !== null) loadTransactions(accountId, 1);
        }} />
        </>)}

        {categoryDialogOpen && (
          <div className="modal-overlay" onClick={() => setCategoryDialogOpen(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3>New Category</h3>
                <button className="btn btn-ghost" onClick={() => setCategoryDialogOpen(false)}>
                  <X size={18} />
                </button>
              </div>
              <form onSubmit={handleCreateCategoryAndRule}>
                <div className="form-group">
                  <label htmlFor="new-category-name">Category name</label>
                  <input
                    id="new-category-name"
                    required
                    autoFocus
                    value={newCategoryName}
                    onChange={(e) => setNewCategoryName(e.target.value)}
                    placeholder="e.g. Insurance"
                  />
                </div>
                <p className="form-hint">
                  The rule <code>{ruleText}</code> will be created with this category.
                </p>
                <div className="form-actions">
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => setCategoryDialogOpen(false)}
                  >
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-primary" disabled={savingRule}>
                    Create
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
    </div>
  );
}
