import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
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
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, GripVertical, History, Plus, Trash2, Upload, X } from 'lucide-react';
import AiCategorization from '../components/AiCategorization';
import TwoFactorModal, { type AuthPrompt } from '../components/TwoFactorModal';
import { stripLeadingIban } from '../utils/iban';
import type {
  BackfillOutcome,
  CategoryRule,
  SpendingReport,
  Transaction,
  TransactionCategory,
} from '../api/client';
import {
  backfillTransactions,
  completeAccountAuth,
  importTransactionsCsv,
  classifyTransaction,
  createCategory,
  createCategoryRule,
  deleteCategoryRule,
  updateCategoryRule,
  getAccounts,
  getTransactions,
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

// Metacharacters that clearly signal a regex is being typed. '.' and bare
// parentheses are deliberately excluded — they are common in plain merchant
// names ("dm.drogerie") and would auto-enable the switch falsely.
const REGEX_HINT = /[[\]{}|\\^$?*+]/;
// Anything regex-meaningful at all, for the opposite check on save: a
// "regex" without any of these is really a plain substring.
const ANY_REGEX_SYNTAX = /[.[\]{}()|\\^$?*+]/;

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
  // The tab lives in the URL (?tab=config) so a refresh or shared link lands
  // on the same tab instead of falling back to Insights.
  const [searchParams, setSearchParams] = useSearchParams();
  const tab: 'insights' | 'config' =
    searchParams.get('tab') === 'config' ? 'config' : 'insights';
  const setTab = (next: 'insights' | 'config') => {
    setSearchParams(next === 'config' ? { tab: 'config' } : {}, { replace: true });
  };
  const [mode, setMode] = useState<'normalized' | 'actual'>('normalized');
  const [months, setMonths] = useState(12);
  const [report, setReport] = useState<SpendingReport | null>(null);
  const [categories, setCategories] = useState<TransactionCategory[]>([]);
  const [rules, setRules] = useState<CategoryRule[]>([]);
  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  // Transaction list filter: '' = all, 'none' = uncategorized, 'transfer', or
  // a category id.
  const [txCategory, setTxCategory] = useState<'' | 'none' | 'transfer' | number>('');
  // '' = every month. Picking a month in the overview sets this too, so the
  // list answers the question the chart just raised.
  const [txMonth, setTxMonth] = useState('');
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [txCount, setTxCount] = useState(0);
  const [txPage, setTxPage] = useState(1);
  const [error, setError] = useState('');

  // New rule form. ruleCategory '__new__' means "create a category first" —
  // the Add Rule click then opens the naming dialog instead of saving directly.
  const [ruleText, setRuleText] = useState('');
  const [ruleCategory, setRuleCategory] =
    useState<number | '' | '__new__' | '__transfer__'>('');
  const [ruleSpread, setRuleSpread] = useState(1);
  const [ruleIsRegex, setRuleIsRegex] = useState(false);
  // Once the user flips the regex switch by hand it stays put — the
  // auto-detection only drives it while untouched.
  const [ruleRegexTouched, setRuleRegexTouched] = useState(false);
  // Rules default to a compact by-category view; the flat first-match-wins
  // list (with drag-to-reorder) is one toggle away for the rare
  // specific-before-generic conflict.
  const [rulesView, setRulesView] = useState<'grouped' | 'order'>('grouped');
  // Group label whose "+" chip was clicked: the rule form renders right below
  // that group's chips. Only the "+" moves it — changing the category
  // dropdown by hand does not. Null = form at the bottom of the card.
  const [ruleFormAnchor, setRuleFormAnchor] = useState<string | null>(null);
  // "Regex enabled but the text has no regex syntax" confirmation dialog.
  const [regexConfirmOpen, setRegexConfirmOpen] = useState(false);
  // Rule being edited (chip click) — null when the dialog is closed.
  const [editRule, setEditRule] = useState<CategoryRule | null>(null);
  const [editText, setEditText] = useState('');
  const [editTarget, setEditTarget] = useState<number | '__transfer__'>('__transfer__');
  const [editSpread, setEditSpread] = useState(1);
  const [editIsRegex, setEditIsRegex] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [ruleFilter, setRuleFilter] = useState('');
  const ruleInputRef = useRef<HTMLInputElement>(null);
  const [draggedRule, setDraggedRule] = useState<number | null>(null);
  const [categoryDialogOpen, setCategoryDialogOpen] = useState(false);
  // When set, the naming dialog assigns the new category to this transaction
  // instead of finishing a rule.
  const [categoryDialogTx, setCategoryDialogTx] = useState<Transaction | null>(null);
  const [newCategoryName, setNewCategoryName] = useState('');
  const [savingRule, setSavingRule] = useState(false);
  const ruleFormRef = useRef<HTMLDivElement>(null);

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
  // A broker that texts a code (Swisscard) stops the backfill mid-way; this holds
  // the challenge until the user types the code, which resumes the same fetch.
  const [authPrompt, setAuthPrompt] = useState<AuthPrompt | null>(null);
  // CSV import (web only): the file resolves its own account (DKB names its
  // IBAN; ZKB is matched by currency) — only an ambiguous match needs a pick.
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvBusy, setCsvBusy] = useState(false);
  const [csvCandidates, setCsvCandidates] = useState<{ id: number; name: string }[]>([]);
  const [csvAccountChoice, setCsvAccountChoice] = useState<number | ''>('');
  const csvInputRef = useRef<HTMLInputElement>(null);
  // Import history is a once-in-a-while tool — collapsed unless in use.
  const [importOpen, setImportOpen] = useState(false);

  const loadReport = useCallback(async () => {
    try {
      setReport(await getSpendingMonthly(months, mode));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load report');
    }
  }, [months, mode]);

  const loadTransactions = useCallback(async (
    id: number | null,
    page: number,
    category: '' | 'none' | 'transfer' | number = txCategory,
    month: string = txMonth,
  ) => {
    try {
      const data = await getTransactions(
        page, id ?? undefined, category === '' ? undefined : category,
        month || undefined);
      setTxCount(data.count);
      setTransactions((prev) => (page === 1 ? data.results : [...prev, ...data.results]));
      setTxPage(page);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load transactions');
    }
  }, [txCategory, txMonth]);

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
        // No preselection: the list shows all accounts chronologically, the
        // dropdown only narrows it.
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load data');
      }
    })();
  }, []);

  useEffect(() => {
    loadTransactions(accountId, 1);
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

  const accountNames = useMemo(
    () => Object.fromEntries(accounts.map((a) => [a.id, a.name])),
    [accounts],
  );

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

  /// Months offered by the list filter: the report's window, newest first,
  /// plus whatever is selected (a month picked before the range was shortened
  /// must still be representable).
  const monthFilterOptions = useMemo(() => {
    const labels = [...(report?.months ?? [])].map((m) => m.month).reverse();
    if (txMonth && !labels.includes(txMonth)) labels.unshift(txMonth);
    return labels;
  }, [report, txMonth]);

  /// Picking a month anywhere in the overview (bar, dropdown, arrows) also
  /// narrows the transaction list to it — the two views answer the same
  /// question, and re-picking the month by hand was pure friction.
  const selectMonth = (month: string) => {
    setSelectedMonth(month);
    setTxMonth(month);
  };

  const stepMonth = (delta: number) => {
    if (!report || monthIndex < 0) return;
    const next = report.months[monthIndex + delta];
    if (next) selectMonth(next.month);
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

  const saveRule = async (target: number | '__transfer__', asRegex = ruleIsRegex) => {
    setSavingRule(true);
    try {
      const rule = await createCategoryRule({
        match_text: ruleText.trim(),
        ...(target === '__transfer__'
          ? { is_transfer: true }
          : { category: target }),
        // A hidden spread control must not smuggle a stale value along.
        spread_months: target === '__transfer__' ? 1 : ruleSpread,
        is_regex: asRegex,
      });
      setRules((prev) => [...prev, rule]);
      setRuleText('');
      // A form anchored to a group keeps its target for quick successive adds.
      setRuleCategory(ruleFormAnchor ? target : '');
      setRuleSpread(1);
      setRuleIsRegex(false);
      setRuleRegexTouched(false);
      // The rule applied retroactively — refresh everything that may have changed.
      loadReport();
      loadTransactions(accountId, 1);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create rule');
      return false;
    } finally {
      setSavingRule(false);
    }
  };

  /// Second half of handleAddRule, also entered from the "not a regex?"
  /// dialog with the user's choice.
  const proceedSaveRule = (asRegex: boolean) => {
    setRegexConfirmOpen(false);
    if (!asRegex) setRuleIsRegex(false);
    if (ruleCategory === '') return;
    if (ruleCategory === '__new__') {
      setCategoryDialogOpen(true);
      return;
    }
    saveRule(ruleCategory, asRegex);
  };

  const handleAddRule = () => {
    if (!ruleText.trim() || ruleCategory === '') return;
    if (ruleIsRegex) {
      // Instant feedback for a broken pattern. The server re-validates with
      // Python's `re` (the engine that actually runs the rule) — this JS
      // check only catches the obvious cases early.
      try {
        new RegExp(ruleText.trim());
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Invalid regular expression');
        return;
      }
      // "hello" with the regex switch on is almost certainly a mistake — ask
      // instead of blindly submitting.
      if (!ANY_REGEX_SYNTAX.test(ruleText)) {
        setRegexConfirmOpen(true);
        return;
      }
    }
    proceedSaveRule(ruleIsRegex);
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
      if (categoryDialogTx) {
        // "+ New category…" was picked on a transaction row, not the rule form.
        const tx = categoryDialogTx;
        setCategoryDialogTx(null);
        await handleClassify(tx, {
          category: category.id,
          ...(tx.is_transfer ? { is_transfer: false } : {}),
        });
      } else {
        await saveRule(category.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create category');
    }
  };

  /// One dropdown covers categories AND the transfer flag: they are mutually
  /// exclusive on a transaction (transfers never carry a category).
  const handleCategoryChoice = (tx: Transaction, value: string) => {
    if (value === '__new__') {
      setCategoryDialogTx(tx);
      setCategoryDialogOpen(true);
      return;
    }
    if (value === '__transfer__') {
      handleClassify(tx, { is_transfer: true, category: null });
      return;
    }
    handleClassify(tx, {
      category: value ? Number(value) : null,
      ...(tx.is_transfer ? { is_transfer: false } : {}),
    });
  };

  /// Rules bucketed by target for the compact view. Groups sort
  /// alphabetically with Transfer last; the filter narrows by match text or
  /// target name.
  const ruleGroups = useMemo(() => {
    const q = ruleFilter.trim().toLowerCase();
    const visible = q
      ? rules.filter((r) =>
          r.match_text.toLowerCase().includes(q)
          || (r.is_transfer ? 'transfer' : (r.category_name ?? ''))
            .toLowerCase().includes(q))
      : rules;
    const groups = new Map<string, {
      label: string;
      target: number | '__transfer__';
      rules: CategoryRule[];
    }>();
    for (const r of visible) {
      const label = r.is_transfer ? 'Transfer (excluded)' : (r.category_name ?? '—');
      const entry = groups.get(label)
        ?? { label, target: r.is_transfer ? '__transfer__' as const : (r.category as number), rules: [] };
      entry.rules.push(r);
      groups.set(label, entry);
    }
    return [...groups.values()].sort((a, b) =>
      Number(a.target === '__transfer__') - Number(b.target === '__transfer__')
      || a.label.localeCompare(b.label));
  }, [rules, ruleFilter]);

  /// The "+" on a group: move the form below that group, prefill its target,
  /// and put the cursor in the match-text input.
  const startRuleFor = (group: { label: string; target: number | '__transfer__' }) => {
    setRuleCategory(group.target);
    setRuleFormAnchor(group.label);
    setTimeout(() => ruleInputRef.current?.focus(), 0);
  };

  /// Prefill the rule form from one transaction and jump to it.
  const craftRuleFrom = (tx: Transaction) => {
    const base = stripLeadingIban(tx.counterparty) || tx.description;
    setRuleText(base.toLowerCase().slice(0, 128).trim());
    setRuleCategory(tx.is_transfer ? '__transfer__' : (tx.category ?? ''));
    setRuleIsRegex(false);
    setRuleRegexTouched(false);
    setRuleFormAnchor(null);
    setTab('config');
    setTimeout(() => ruleFormRef.current?.scrollIntoView(
      { behavior: 'smooth', block: 'center' }), 50);
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

  const openRuleEditor = (rule: CategoryRule) => {
    setEditRule(rule);
    setEditText(rule.match_text);
    setEditTarget(rule.is_transfer ? '__transfer__' : (rule.category as number));
    setEditSpread(rule.spread_months);
    setEditIsRegex(rule.is_regex);
    setError('');
  };

  const handleSaveRuleEdit = async () => {
    const rule = editRule;
    if (!rule || !editText.trim()) return;
    if (editIsRegex) {
      try {
        new RegExp(editText.trim());
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Invalid regular expression');
        return;
      }
    }
    const isTransfer = editTarget === '__transfer__';
    setEditSaving(true);
    try {
      const updated = await updateCategoryRule(rule.id, {
        match_text: editText.trim(),
        is_regex: editIsRegex,
        is_transfer: isTransfer,
        category: isTransfer ? null : editTarget,
        // Transfers are excluded from spending — nothing to amortize.
        spread_months: isTransfer ? 1 : editSpread,
      });
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
      setEditRule(null);
      // Rules re-run server-side: the report and labels may have changed.
      loadReport();
      loadTransactions(accountId, 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update rule');
    } finally {
      setEditSaving(false);
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
      applyBackfillOutcome(await backfillTransactions(backfillAccount, start, end));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Backfill failed');
    } finally {
      setBackfillBusy(false);
    }
  };

  // Shared by the direct fetch and the one resumed after a one-time code.
  const applyBackfillOutcome = (outcome: BackfillOutcome) => {
    if (outcome.status === 'pending_auth') {
      const account = accounts.find((a) => a.id === backfillAccount);
      setAuthPrompt({
        accountId: backfillAccount as number,
        accountName: account?.name || 'this account',
        twoFaType: outcome.two_fa_type || 'totp',
        challenge: outcome.challenge?.message,
      });
      return;
    }
    if (outcome.status === 'error') {
      setError(outcome.error || 'Backfill failed');
      return;
    }
    setBackfillNotice(
      outcome.message || `${outcome.imported ?? 0} new transactions imported`,
    );
    setBackfillTruncated(Boolean(outcome.truncated));
    loadReport();
    loadTransactions(accountId, 1);
  };

  // The code the bank just sent resumes the parked fetch — the same endpoint the
  // account list uses, which returns this backfill's result instead of a sync's.
  const handleAuthSubmit = async (code: string) => {
    if (!authPrompt) return;
    setBackfillBusy(true);
    try {
      const outcome = await completeAccountAuth(authPrompt.accountId, code);
      setAuthPrompt(null);
      applyBackfillOutcome(outcome);
    } finally {
      setBackfillBusy(false);
    }
  };

  const handleCsvImport = async () => {
    if (!csvFile) return;
    setError('');
    setBackfillNotice('');
    setBackfillTruncated(false);
    setCsvBusy(true);
    try {
      const outcome = await importTransactionsCsv(
        csvFile,
        csvAccountChoice === '' ? undefined : csvAccountChoice,
      );
      if (outcome.status === 'ambiguous') {
        // Keep the file; the user picks one of the candidates and retries.
        setCsvCandidates(outcome.accounts ?? []);
        return;
      }
      setBackfillNotice(outcome.message || `${outcome.imported ?? 0} new transactions imported`);
      setCsvFile(null);
      setCsvCandidates([]);
      setCsvAccountChoice('');
      if (csvInputRef.current) csvInputRef.current.value = '';
      loadReport();
      loadTransactions(accountId, 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'CSV import failed');
    } finally {
      setCsvBusy(false);
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

  // Escape on the regex confirmation = cancel, i.e. save nothing.
  useEffect(() => {
    if (!regexConfirmOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setRegexConfirmOpen(false);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [regexConfirmOpen]);

  const currency = report?.base_currency ?? 'EUR';

  // One shared form row: rendered below the anchored group's chips (after its
  // "+" was clicked) or at the bottom of the rules card otherwise.
  const ruleFormRow = (
    <div className="spending-rule-row spending-rule-new" ref={ruleFormRef}>
      <input
        ref={ruleInputRef}
        className="spending-rule-match"
        placeholder="match text, e.g. rewe"
        value={ruleText}
        onChange={(e) => {
          const value = e.target.value;
          setRuleText(value);
          // Obvious pattern syntax flips the switch on (and off again when
          // deleted) — but never after the user touched it themselves.
          if (!ruleRegexTouched) setRuleIsRegex(REGEX_HINT.test(value));
        }}
      />
      <label className="spending-switch" title="Interpret the match text as a regular expression instead of a plain substring">
        <input
          type="checkbox"
          checked={ruleIsRegex}
          onChange={(e) => {
            setRuleIsRegex(e.target.checked);
            setRuleRegexTouched(true);
          }}
        />
        Regex
      </label>
      <select
        value={ruleCategory}
        onChange={(e) => {
          const v = e.target.value;
          setRuleCategory(
            v === '' || v === '__new__' || v === '__transfer__' ? v : Number(v));
        }}
      >
        <option value="">Category…</option>
        <option value="__transfer__">Transfer (excluded)</option>
        {categories.map((c) => (
          <option key={c.id} value={c.id}>{c.name}</option>
        ))}
        <option value="__new__">+ New category…</option>
      </select>
      {/* Transfers are excluded from spending entirely — there is nothing to
          amortize, so the spread control does not apply to them. */}
      {ruleCategory !== '__transfer__' && (
        <select value={ruleSpread} onChange={(e) => setRuleSpread(Number(e.target.value))}>
          <option value={1}>no spread</option>
          <option value={3}>/3 months</option>
          <option value={6}>/6 months</option>
          <option value={12}>/12 months</option>
        </select>
      )}
      <button
        className="btn btn-sm btn-primary"
        onClick={handleAddRule}
        disabled={savingRule || !ruleText.trim() || ruleCategory === ''}
      >
        <Plus size={14} /> Rule
      </button>
    </div>
  );
  // The anchored group can disappear (filter, last rule deleted, Order view)
  // — the form then falls back to the bottom of the card.
  const ruleFormInGroup = rulesView === 'grouped'
    && ruleGroups.some((g) => g.label === ruleFormAnchor);

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
                      if (m) selectMonth(m);
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
                onChange={(e) => selectMonth(e.target.value)}
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
                onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">All accounts</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
              <select
                aria-label="Filter by category"
                value={txCategory}
                onChange={(e) => {
                  const v = e.target.value;
                  setTxCategory(
                    v === '' || v === 'none' || v === 'transfer' ? v : Number(v));
                }}
              >
                <option value="">All categories</option>
                <option value="none">Uncategorized</option>
                <option value="transfer">Transfer (excluded)</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <select
                aria-label="Filter by month"
                value={txMonth}
                onChange={(e) => setTxMonth(e.target.value)}
              >
                <option value="">All months</option>
                {monthFilterOptions.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
          </div>
          {transactions.length === 0 ? (
            <p className="table-empty">
              {txCategory !== '' || txMonth || accountId !== null
                ? 'No transactions match this filter.'
                : 'No transactions yet.'}
            </p>
          ) : (
            <div className="table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Account</th>
                    <th>Counterparty</th>
                    <th>Description</th>
                    {/* One dropdown for category OR transfer: mutually
                        exclusive, and transfers never carry a category.
                        Manual transfer marking stays possible here because
                        auto-detection only pairs entries between two
                        accounts that both have a feed. */}
                    <th>Category</th>
                    {/* Per-transaction amortization: a rule spreads every match,
                        but a one-off yearly bill has no rule to hang it on. */}
                    <th>Spread</th>
                    <th aria-label="Actions" />
                    <th className="spending-amount-col">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((tx) => (
                    <tr key={tx.id} className={tx.is_transfer ? 'spending-transfer-row' : ''}>
                      <td>{tx.booking_date}</td>
                      <td>{accountNames[tx.account] ?? ''}</td>
                      <td>{stripLeadingIban(tx.counterparty)}</td>
                      <td>{tx.description}</td>
                      <td>
                        <select
                          value={tx.is_transfer ? '__transfer__' : (tx.category ?? '')}
                          onChange={(e) => handleCategoryChoice(tx, e.target.value)}
                        >
                          <option value="">—</option>
                          <option value="__transfer__">Transfer (excluded)</option>
                          {categories.map((c) => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                          ))}
                          <option value="__new__">+ New category…</option>
                        </select>
                      </td>
                      <td>
                        {/* A transfer is excluded from spending entirely, so
                            there is nothing to amortize. */}
                        {tx.is_transfer ? (
                          <span className="spending-muted">—</span>
                        ) : (
                          <select
                            aria-label="Spread over months"
                            value={tx.spread_months}
                            onChange={(e) =>
                              handleClassify(tx, { spread_months: Number(e.target.value) })}
                          >
                            <option value={1}>—</option>
                            <option value={3}>/3m</option>
                            <option value={6}>/6m</option>
                            <option value={12}>/12m</option>
                          </select>
                        )}
                      </td>
                      <td>
                        <button
                          className="btn btn-sm btn-ghost"
                          title="Create a rule from this transaction"
                          onClick={() => craftRuleFrom(tx)}
                        >
                          <Plus size={14} /> Rule
                        </button>
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
                    onClick={() => loadTransactions(accountId, txPage + 1)}
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
            <h2>
              Rules
              {rules.length > 0 && (
                <span className="spending-month-title"> · {rules.length}</span>
              )}
            </h2>
            <div className="range-buttons">
              {rulesView === 'grouped' && rules.length > 0 && (
                <input
                  className="rule-filter"
                  placeholder="Filter…"
                  value={ruleFilter}
                  onChange={(e) => setRuleFilter(e.target.value)}
                />
              )}
              <button
                className={`btn btn-sm ${rulesView === 'grouped' ? 'btn-primary' : 'btn-ghost'}`}
                title="Rules bucketed by category"
                onClick={() => setRulesView('grouped')}
              >
                Grouped
              </button>
              <button
                className={`btn btn-sm ${rulesView === 'order' ? 'btn-primary' : 'btn-ghost'}`}
                title="Flat evaluation order with drag-to-reorder"
                onClick={() => setRulesView('order')}
              >
                Order
              </button>
            </div>
          </div>
          <p className="form-hint">
            Match text is compared against counterparty and description; rules are
            checked top to bottom and the first match wins. New rules apply to all
            still-uncategorized transactions; a spread of 12 shows a yearly bill as one
            twelfth per month in the normalized view. Order only matters when rules
            overlap — switch to Order to drag a specific rule above a broader one.
          </p>
          {rulesView === 'grouped' && rules.length > 0 && (
            <div className="rule-groups">
              {ruleGroups.map((group) => (
                <div key={group.label} className="rule-group">
                  <div className="rule-group-title">
                    {group.label} <span>({group.rules.length})</span>
                  </div>
                  <div className="rule-chips">
                    {group.rules.map((rule) => (
                      <span
                        key={rule.id}
                        className="rule-chip"
                        title={[
                          'Click to edit',
                          rule.is_regex ? 'regular expression' : null,
                          rule.spread_months > 1
                            ? `spread over ${rule.spread_months} months` : null,
                        ].filter(Boolean).join(' · ')}
                      >
                        <button
                          className="rule-chip-edit"
                          onClick={() => openRuleEditor(rule)}
                        >
                          <code>{rule.is_regex ? `/${rule.match_text}/` : rule.match_text}</code>
                          {rule.spread_months > 1 && <em>/{rule.spread_months}m</em>}
                        </button>
                        <button
                          aria-label={`Delete rule ${rule.match_text}`}
                          onClick={() => handleDeleteRule(rule.id)}
                        >
                          <X size={12} />
                        </button>
                      </span>
                    ))}
                    <button
                      className="rule-chip rule-chip-add"
                      title={`New ${group.label} rule`}
                      onClick={() => startRuleFor(group)}
                    >
                      <Plus size={12} />
                    </button>
                  </div>
                  {ruleFormAnchor === group.label && ruleFormRow}
                </div>
              ))}
              {ruleGroups.length === 0 && (
                <p className="form-hint">No rules match the filter.</p>
              )}
            </div>
          )}
          <div className="spending-rules">
            {rulesView === 'order' && rules.map((rule, index) => (
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
                <code>{rule.is_regex ? `/${rule.match_text}/` : rule.match_text}</code>
                <span>→ {rule.is_transfer ? 'Transfer (excluded)' : rule.category_name}</span>
                {rule.is_regex && <span className="spending-spread-badge">regex</span>}
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
            {!ruleFormInGroup && ruleFormRow}
          </div>
        </div>

        <div className="card">
          <div
            className="chart-header card-toggle"
            role="button"
            tabIndex={0}
            aria-expanded={importOpen}
            onClick={() => setImportOpen((v) => !v)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setImportOpen((v) => !v);
              }
            }}
          >
            <h2>Import history</h2>
            <ChevronDown
              size={18}
              className={`card-toggle-chevron ${importOpen ? 'open' : ''}`}
            />
          </div>
          {importOpen && (<>
          <div className="import-columns">
            <div>
              <h3 className="import-col-title">Fetch from bank</h3>
              <p className="form-hint">
                A sync only fetches transactions newer than the ones already stored;
                this pulls an older period once. The default asks for the last{' '}
                {DEFAULT_BACKFILL_MONTHS} months — banks that keep less return what
                they have (EBICS often serves years, FinTS/DKB about 90 days).
                Banks that need a one-time code (Swisscard) will ask for one.
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
              </div>
              {backfillAccount !== '' && (
                <div className="spending-rule-row spending-rule-new">
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
                      backfillBusy || (!backfillDefaultRange && !backfillStart)
                    }
                  >
                    <History size={14} /> {backfillBusy ? 'Fetching…' : 'Fetch'}
                  </button>
                </div>
              )}
            </div>
            <div>
              <h3 className="import-col-title">Import CSV export</h3>
              <p className="form-hint">
                An export from the bank&apos;s online banking — ZKB (&quot;with
                details&quot; export), DKB, and Commerzbank are recognized
                automatically, and the file determines its account. Re-importing
                an overlapping file changes nothing.
              </p>
              <div className="spending-rule-row spending-rule-new">
                <input
                  ref={csvInputRef}
                  type="file"
                  accept=".csv,text/csv"
                  aria-label="CSV file"
                  onChange={(e) => {
                    setCsvFile(e.target.files?.[0] ?? null);
                    setCsvCandidates([]);
                    setCsvAccountChoice('');
                  }}
                />
                <button
                  className="btn btn-sm btn-primary"
                  onClick={handleCsvImport}
                  disabled={
                    csvBusy || !csvFile
                    || (csvCandidates.length > 0 && csvAccountChoice === '')
                  }
                >
                  <Upload size={14} /> {csvBusy ? 'Importing…' : 'Import CSV'}
                </button>
              </div>
              {csvCandidates.length > 0 && (
                <div className="spending-rule-row spending-rule-new">
                  <span className="form-hint">
                    Several accounts match the file&apos;s currency — pick one:
                  </span>
                  <select
                    value={csvAccountChoice}
                    onChange={(e) =>
                      setCsvAccountChoice(e.target.value ? Number(e.target.value) : '')}
                  >
                    <option value="">Account…</option>
                    {csvCandidates.map((a) => (
                      <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          </div>
          {backfillNotice && (
            backfillTruncated ? (
              <div className="form-warning">
                <AlertTriangle size={16} /> {backfillNotice}
              </div>
            ) : (
              <div className="form-success">
                <CheckCircle2 size={16} /> {backfillNotice}
              </div>
            )
          )}
          </>)}
        </div>

        <AiCategorization onApplied={() => {
          loadReport();
          getCategories().then(setCategories).catch(() => {});
          getCategoryRules().then(setRules).catch(() => {});
          loadTransactions(accountId, 1);
        }} />
        </>)}

        {editRule && (
          <div className="modal-overlay" onClick={() => setEditRule(null)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3>Edit rule</h3>
                <button className="btn btn-ghost" onClick={() => setEditRule(null)}>
                  <X size={18} />
                </button>
              </div>
              <div className="form-group">
                <label htmlFor="edit-rule-text">Match text</label>
                <input
                  id="edit-rule-text"
                  autoFocus
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label className="spending-switch">
                  <input
                    type="checkbox"
                    checked={editIsRegex}
                    onChange={(e) => setEditIsRegex(e.target.checked)}
                  />
                  Regular expression
                </label>
              </div>
              <div className="form-group">
                <label htmlFor="edit-rule-target">Target</label>
                <select
                  id="edit-rule-target"
                  value={editTarget}
                  onChange={(e) => {
                    const v = e.target.value;
                    setEditTarget(v === '__transfer__' ? v : Number(v));
                  }}
                >
                  <option value="__transfer__">Transfer (excluded)</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
              {editTarget !== '__transfer__' && (
                <div className="form-group">
                  <label htmlFor="edit-rule-spread">Spread</label>
                  <select
                    id="edit-rule-spread"
                    value={editSpread}
                    onChange={(e) => setEditSpread(Number(e.target.value))}
                  >
                    <option value={1}>no spread</option>
                    <option value={3}>/3 months</option>
                    <option value={6}>/6 months</option>
                    <option value={12}>/12 months</option>
                  </select>
                  <small className="form-hint">
                    A yearly bill shows as one twelfth per month in the
                    normalized view.
                  </small>
                </div>
              )}
              <div className="form-actions">
                <button className="btn btn-ghost" onClick={() => setEditRule(null)}>
                  Cancel
                </button>
                <button
                  className="btn btn-primary"
                  onClick={handleSaveRuleEdit}
                  disabled={editSaving || !editText.trim()}
                >
                  {editSaving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        )}

        {authPrompt && (
          <TwoFactorModal
            prompt={authPrompt}
            purpose="fetch transactions for"
            submitLabel="Verify & Fetch"
            onSubmit={handleAuthSubmit}
            onClose={() => setAuthPrompt(null)}
          />
        )}

        {regexConfirmOpen && (
          <div className="modal-overlay" onClick={() => setRegexConfirmOpen(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3>Not a regular expression?</h3>
                <button className="btn btn-ghost" onClick={() => setRegexConfirmOpen(false)}>
                  <X size={18} />
                </button>
              </div>
              <p className="form-hint">
                <code>{ruleText.trim()}</code> contains no regular-expression
                syntax — no <code>[ ]</code>, <code>|</code>, <code>?</code>,{' '}
                <code>*</code>, <code>+</code> or similar. As a regex it behaves
                exactly like a plain substring, only slower to read later.
              </p>
              <div className="form-actions">
                <button
                  className="btn btn-ghost"
                  onClick={() => setRegexConfirmOpen(false)}
                >
                  Cancel
                </button>
                <button
                  className="btn btn-ghost"
                  onClick={() => proceedSaveRule(true)}
                >
                  Save as regex
                </button>
                <button
                  className="btn btn-primary"
                  onClick={() => proceedSaveRule(false)}
                  autoFocus
                >
                  Save as plain text
                </button>
              </div>
            </div>
          </div>
        )}

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
                  {categoryDialogTx
                    ? 'The selected transaction will be assigned this category.'
                    : <>The rule <code>{ruleText}</code> will be created with this category.</>}
                </p>
                <div className="form-actions">
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      setCategoryDialogOpen(false);
                      setCategoryDialogTx(null);
                    }}
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
