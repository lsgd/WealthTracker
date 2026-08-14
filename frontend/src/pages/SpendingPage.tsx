import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { ArrowLeftRight, Plus, Trash2 } from 'lucide-react';
import type {
  CategoryRule,
  SpendingReport,
  Transaction,
  TransactionCategory,
} from '../api/client';
import {
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
} from '../api/client';

const COLORS = [
  '#4f8cff', '#34d399', '#fbbf24', '#f87171',
  '#a78bfa', '#fb923c', '#38bdf8', '#e879f9',
];

const MODES = [
  { label: 'Normalized', value: 'normalized' as const },
  { label: 'Actual', value: 'actual' as const },
];

const RANGES = [6, 12, 24];

interface AccountOption {
  id: number;
  name: string;
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

  // New rule form
  const [ruleText, setRuleText] = useState('');
  const [ruleCategory, setRuleCategory] = useState<number | ''>('');
  const [ruleSpread, setRuleSpread] = useState(1);

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

  const chartData = useMemo(() => {
    if (!report) return [];
    return report.months.map((m) => ({
      month: m.month,
      Income: m.income,
      ...m.by_category,
    }));
  }, [report]);

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

  const handleAddRule = async () => {
    if (!ruleText.trim() || ruleCategory === '') return;
    try {
      const rule = await createCategoryRule({
        match_text: ruleText.trim(),
        category: ruleCategory,
        spread_months: ruleSpread,
      });
      setRules((prev) => [...prev, rule]);
      setRuleText('');
      setRuleSpread(1);
      // The rule applied retroactively — refresh everything that may have changed.
      loadReport();
      if (accountId !== null) loadTransactions(accountId, 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create rule');
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

  const handleAddCategory = async () => {
    const name = window.prompt('New category name');
    if (!name?.trim()) return;
    try {
      const category = await createCategory(name.trim());
      setCategories((prev) => [...prev, category].sort((a, b) => a.name.localeCompare(b.name)));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create category');
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

  const currency = report?.base_currency ?? 'EUR';

  return (
    <div className="dashboard">
        {error && (
          <div className="form-error" onClick={() => setError('')}>{error}</div>
        )}

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
                  formatter={(value: number | string, name: string) =>
                    [formatAmount(Number(value), currency), name]}
                  contentStyle={{ background: '#1a1f2e', border: '1px solid #2a3040' }}
                />
                <Legend />
                {report?.categories.map((name, i) => (
                  <Bar
                    key={name}
                    dataKey={name}
                    stackId="expenses"
                    fill={COLORS[i % COLORS.length]}
                  />
                ))}
                <Line dataKey="Income" stroke="#34d399" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="card">
          <div className="chart-header">
            <h2>Rules</h2>
            <button className="btn btn-sm btn-ghost" onClick={handleAddCategory}>
              <Plus size={14} /> Category
            </button>
          </div>
          <p className="form-hint">
            Match text is compared against counterparty and description. New rules apply
            to all still-uncategorized transactions. A spread of 12 shows a yearly bill
            as one twelfth per month in the normalized view.
          </p>
          <div className="spending-rules">
            {rules.map((rule) => (
              <div key={rule.id} className="spending-rule-row">
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
                onChange={(e) => setRuleCategory(e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">Category…</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <select value={ruleSpread} onChange={(e) => setRuleSpread(Number(e.target.value))}>
                <option value={1}>no spread</option>
                <option value={3}>/3 months</option>
                <option value={6}>/6 months</option>
                <option value={12}>/12 months</option>
              </select>
              <button className="btn btn-sm btn-primary" onClick={handleAddRule}>
                <Plus size={14} /> Rule
              </button>
            </div>
          </div>
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
    </div>
  );
}
