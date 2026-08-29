import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { AlertTriangle, ArrowDown, ArrowUp, CheckCircle2, ChevronDown, GripVertical, History, Plus, Search, Trash2, Upload, X } from 'lucide-react';
import AiCategorization from '../components/AiCategorization';
import CategoryPatternDefs from '../components/CategoryPatternDefs';
import ClampedText from '../components/ClampedText';
import CategoryBreakdown from '../components/spending/CategoryBreakdown';
import CategoryDetail from '../components/spending/CategoryDetail';
import PeriodBar from '../components/spending/PeriodBar';
import RuleAmountFilter from '../components/spending/RuleAmountFilter';
import RuleImpact from '../components/spending/RuleImpact';
import SummaryTiles from '../components/spending/SummaryTiles';
import {
  AVERAGE_WINDOW,
  formatPeriod,
  formatPeriodShort,
  HISTORY_CHOICES,
  type Granularity,
} from '../utils/periods';
import {
  categoryStyle,
  INCOME_COLOR,
  UNCATEGORIZED,
} from '../utils/categoryPalette';
import TwoFactorModal, { type AuthPrompt } from '../components/TwoFactorModal';
import { stripLeadingIban } from '../utils/iban';
import { trimLeading, trimmedInput } from '../utils/text';
import {
  describeFilter, EMPTY_FILTER, filterOf, filterPayload, isImpossible,
  type AmountFilter,
} from '../utils/ruleAmount';
import type {
  BackfillOutcome,
  TransactionSortKey,
  CategoryRule,
  SpendingMonth,
  SpendingReport,
  Transaction,
  TransactionCategory,
} from '../api/client';
import {
  backfillTransactions,
  compareCategoryNames,
  completeAccountAuth,
  importTransactionsCsv,
  classifyTransaction,
  createCategory,
  createCategoryRule,
  setCategoryBudget,
  deleteCategoryRule,
  updateCategoryRule,
  getAccounts,
  getTransactions,
  getCategories,
  getCategoryRules,
  getSpendingMonthly,
  reorderCategoryRules,
} from '../api/client';
import ModalOverlay from '../components/ModalOverlay';


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
  // One period selection drives the whole page. `months` counts periods of the
  // current granularity: 12 months, 8 quarters, 5 years.
  const [granularity, setGranularity] = useState<Granularity>('month');
  const [months, setMonths] = useState(12);
  const [report, setReport] = useState<SpendingReport | null>(null);
  const [categories, setCategories] = useState<TransactionCategory[]>([]);
  const [rules, setRules] = useState<CategoryRule[]>([]);
  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  // Transaction list filter: '' = all, 'none' = uncategorized, 'transfer', or
  // comma-separated category ids (the breakdown chips).
  const [txCategory, setTxCategory] = useState<'' | 'none' | 'transfer' | string>('');
  // The period everything on the page refers to; defaults to the newest one.
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);
  // Uncategorized is spending like any other — one switch for the whole page.
  const [showUncategorized, setShowUncategorized] = useState(true);
  // The list follows the selected period unless it is widened on purpose —
  // derived rather than mirrored, so the two can never disagree.
  const [txAllPeriods, setTxAllPeriods] = useState(false);
  // Two values: what is being typed, and what has settled long enough to ask
  // the server about. Without the second, every keystroke is a request.
  const [txSearchInput, setTxSearchInput] = useState('');
  const [txSearch, setTxSearch] = useState('');
  // Category names picked in the breakdown; they filter the list and sum up.
  const [pickedCategories, setPickedCategories] = useState<string[]>([]);
  // Category whose history is open, if any.
  const [detailCategory, setDetailCategory] = useState<string | null>(null);
  // Sorted column, newest bookings first by default (what the server did before
  // the column headers became clickable).
  const [txSort, setTxSort] = useState<TransactionSortKey>('date');
  const [txSortDesc, setTxSortDesc] = useState(true);
  // A manual correction that contradicts the rule which classified the row:
  // holds the rule and the corrected transaction until the user decides.
  const [staleRule, setStaleRule] = useState<{
    rule: CategoryRule;
    transaction: Transaction;
    // What the user changed, so only that is carried over to the rule.
    fields: { category?: number | null; spread_months?: number; is_transfer?: boolean };
  } | null>(null);
  const [staleRuleBusy, setStaleRuleBusy] = useState(false);
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
  // The rule dialog: an existing rule (chip click), or 'new' when crafting one
  // from a transaction. Null when closed.
  const [editRule, setEditRule] = useState<CategoryRule | 'new' | null>(null);
  const [editText, setEditText] = useState('');
  const [editTarget, setEditTarget] =
    useState<number | '__transfer__' | ''>('__transfer__');
  const [editSpread, setEditSpread] = useState(1);
  const [editIsRegex, setEditIsRegex] = useState(false);
  const [editFilter, setEditRange] = useState<AmountFilter>(EMPTY_FILTER);
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

  /// The period in focus: the picked one, or the newest the report covers.
  const monthDetail = useMemo(() => {
    if (!report || report.months.length === 0) return null;
    return report.months.find((m) => m.month === selectedMonth)
      ?? report.months[report.months.length - 1];
  }, [report, selectedMonth]);

  const monthIndex = useMemo(() => {
    if (!report || !monthDetail) return -1;
    return report.months.findIndex((m) => m.month === monthDetail.month);
  }, [report, monthDetail]);

  const txPeriod = txAllPeriods ? '' : (monthDetail?.month ?? '');

  // Let the typed query settle before asking the server: one request per
  // pause in typing rather than one per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setTxSearch(txSearchInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [txSearchInput]);

  const loadReport = useCallback(async () => {
    try {
      setReport(await getSpendingMonthly(months, mode, granularity));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load report');
    }
  }, [months, mode, granularity]);

  const loadTransactions = useCallback(async (
    id: number | null,
    page: number,
    category: '' | 'none' | 'transfer' | number | string = txCategory,
    period: string = txPeriod,
  ) => {
    try {
      const data = await getTransactions(
        page, id ?? undefined, category === '' ? undefined : category,
        period || undefined, `${txSortDesc ? '-' : ''}${txSort}`, mode,
        txSearch);
      setTxCount(data.count);
      setTransactions((prev) => (page === 1 ? data.results : [...prev, ...data.results]));
      setTxPage(page);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load transactions');
    }
    // `mode`: the normalized view puts a bill in every period it covers, so
    // the list has to follow it or it cannot add up to the chart above.
  }, [txCategory, txPeriod, txSort, txSortDesc, mode, txSearch]);

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

  /// Clicking the sorted column flips the direction; a new column starts in
  /// the direction that column is usually read — dates and amounts biggest
  /// first, text A to Z.
  const toggleSort = (key: TransactionSortKey) => {
    if (txSort === key) {
      setTxSortDesc((v) => !v);
    } else {
      setTxSort(key);
      setTxSortDesc(key === 'date' || key === 'amount');
    }
  };

  const sortHeader = (key: TransactionSortKey, label: string) => (
    <button
      type="button"
      className={`sort-header ${txSort === key ? 'active' : ''}`}
      onClick={() => toggleSort(key)}
    >
      {label}
      {txSort === key && (txSortDesc ? <ArrowDown size={13} /> : <ArrowUp size={13} />)}
    </button>
  );

  /// Every period the report covers, oldest first.
  const periodLabels = useMemo(
    () => (report?.months ?? []).map((m) => m.month), [report]);

  const periodNoun = granularity;

  /// Picking a period anywhere (bar click, dropdown, arrows) drives the whole
  /// page: breakdown, summary and the transaction list all follow it.
  const selectMonth = (month: string) => setSelectedMonth(month);

  /// Switching granularity keeps the history choice sensible (24 months is a
  /// reasonable window, 24 years is not) and re-selects the newest period.
  const changeGranularity = (next: Granularity) => {
    setGranularity(next);
    setMonths(HISTORY_CHOICES[next][1]);
    // The old label means nothing in the new granularity; fall back to newest.
    setSelectedMonth(null);
  };

  /// Categories in report order without the uncategorized bucket, which is not
  /// part of the color rotation (it always draws in its own grey).
  const paletteCategories = useMemo(
    () => (report?.categories ?? []).filter((c) => c !== UNCATEGORIZED),
    [report],
  );

  /// One look per category — color, and past the palette a pattern too —
  /// shared by the bars, the chips and the ranked list.
  const styleFor = useCallback(
    (name: string) => categoryStyle(
      name === UNCATEGORIZED ? -1 : paletteCategories.indexOf(name),
    ),
    [paletteCategories],
  );

  const visibleCategories = useMemo(
    () => (report?.categories ?? []).filter(
      (name) => showUncategorized || name !== UNCATEGORIZED),
    [report, showUncategorized],
  );

  /// Completed periods before the selected one, newest first — the basis for
  /// "vs average". The running period is excluded: a third of a month
  /// compared against whole months always looks like a saving.
  const trailing = useMemo(() => {
    if (!report || monthIndex < 0) return [];
    return report.months.slice(Math.max(0, monthIndex - AVERAGE_WINDOW), monthIndex);
  }, [report, monthIndex]);

  const isCurrentPeriod = useMemo(
    () => !!report && monthIndex === report.months.length - 1, [report, monthIndex]);

  const compare = useCallback((
    value: number, pick: (m: SpendingMonth) => number,
  ) => {
    const previousPeriod = report?.months[monthIndex - 1];
    const previous = previousPeriod ? pick(previousPeriod) : null;
    // Only periods that had something to compare: a year before the data
    // starts is absence of history, not a year of spending nothing, and
    // averaging those in turns every delta into a meaningless +400%.
    const seen = trailing.map(pick).filter((v) => v !== 0);
    const average = seen.length
      ? seen.reduce((sum, v) => sum + v, 0) / seen.length
      : null;
    return {
      vsPrevious: previous ? (value - previous) / Math.abs(previous) : null,
      vsAverage: average ? (value - average) / Math.abs(average) : null,
    };
  }, [report, monthIndex, trailing]);

  /// What the summary tiles show for the selected period. Spending excludes
  /// the uncategorized bucket when it is switched off, so every number on the
  /// page refers to the same set of transactions.
  const spentInPeriod = useMemo(() => {
    if (!monthDetail) return 0;
    if (showUncategorized) return monthDetail.expenses;
    return monthDetail.expenses - (monthDetail.by_category[UNCATEGORIZED] ?? 0);
  }, [monthDetail, showUncategorized]);

  /// Sum of the budgets of the categories on screen, for the roll-up tile.
  const budgetTotal = useMemo(() => {
    const budgets = report?.budgets ?? {};
    const relevant = Object.entries(budgets).filter(
      ([name]) => showUncategorized || name !== UNCATEGORIZED);
    return relevant.length
      ? relevant.reduce((sum, [, value]) => sum + value, 0)
      : null;
  }, [report, showUncategorized]);

  /// How much of the period's spending falls in categories that have a budget
  /// — without it, "CHF 400 left" reads as if it covered everything.
  const budgetedShare = useMemo(() => {
    if (!monthDetail || !report?.budgets) return 100;
    const budgeted = Object.keys(report.budgets)
      .reduce((sum, name) => sum + (monthDetail.by_category[name] ?? 0), 0);
    return spentInPeriod > 0 ? (budgeted / spentInPeriod) * 100 : 100;
  }, [monthDetail, report, spentInPeriod]);

  const summaryTiles = useMemo(() => {
    if (!monthDetail) return [];
    const spentOf = (m: SpendingMonth) => (showUncategorized
      ? m.expenses
      : m.expenses - (m.by_category[UNCATEGORIZED] ?? 0));
    return [
      {
        label: 'Spent',
        value: spentInPeriod,
        comparison: compare(spentInPeriod, spentOf),
        moreIsBetter: false,
      },
      {
        label: 'Income',
        value: monthDetail.income,
        comparison: compare(monthDetail.income, (m) => m.income),
        moreIsBetter: true,
      },
      {
        label: 'Net',
        value: monthDetail.income - spentInPeriod,
        comparison: compare(monthDetail.income - spentInPeriod,
          (m) => m.income - spentOf(m)),
        moreIsBetter: true,
      },
    ];
  }, [monthDetail, spentInPeriod, showUncategorized, compare]);

  /// Mean of the non-zero values, or null when there is nothing to average.
  const averageOf = (values: number[]) => {
    const seen = values.filter((v) => v !== 0);
    return seen.length ? seen.reduce((sum, v) => sum + v, 0) / seen.length : null;
  };

  /// The selected period's categories, ranked, each with the period before and
  /// the trailing average for context.
  const categoryRows = useMemo(() => {
    if (!monthDetail) return [];
    const previousPeriod = report?.months[monthIndex - 1];
    // Budgeted categories appear even with nothing spent — "EUR 200 left" is
    // exactly the row a budget is there to show, and dropping it would make a
    // category look untracked.
    const spent: Record<string, number> = { ...monthDetail.by_category };
    for (const name of Object.keys(report?.budgets ?? {})) {
      if (!(name in spent)) spent[name] = 0;
    }
    return Object.entries(spent)
      .filter(([name]) => showUncategorized || name !== UNCATEGORIZED)
      .sort((a, b) => b[1] - a[1])
      .map(([name, amount]) => ({
        name,
        amount,
        previous: previousPeriod ? (previousPeriod.by_category[name] ?? 0) : null,
        // Same rule as the tiles: average only over the periods that had this
        // category, so a category added last month is not "up 500%".
        average: averageOf(trailing.map((m) => m.by_category[name] ?? 0)),
        budget: report?.budgets?.[name] ?? null,
        style: styleFor(name),
      }));
  }, [monthDetail, report, monthIndex, trailing, showUncategorized, styleFor]);

  const categoryTotal = useMemo(
    () => categoryRows.reduce((sum, r) => sum + r.amount, 0), [categoryRows]);

  /// A category's own history across the loaded window, for the detail view.
  const detailSeries = useMemo(() => {
    if (!detailCategory || !report) return [];
    return report.months.map((m) => ({
      period: m.month,
      amount: m.by_category[detailCategory] ?? 0,
    }));
  }, [detailCategory, report]);

  /// Chips filter the transaction list; several of them sum up, which is the
  /// whole reason they are chips and not a dropdown.
  const togglePickedCategory = (name: string) => {
    setPickedCategories((prev) => {
      const next = prev.includes(name)
        ? prev.filter((n) => n !== name)
        : [...prev, name];
      const ids = next
        .map((n) => categories.find((c) => c.name === n)?.id)
        .filter((id): id is number => id !== undefined);
      // Uncategorized has no id — on its own it maps to the dedicated filter.
      if (next.length && ids.length === 0 && next.includes(UNCATEGORIZED)) {
        setTxCategory('none');
      } else {
        setTxCategory(ids.join(','));
      }
      return next;
    });
  };

  const filterSummary = useMemo(() => {
    const parts = [txPeriod ? formatPeriod(txPeriod) : 'all periods'];
    if (pickedCategories.length) parts.push(pickedCategories.join(', '));
    else if (txCategory === 'none') parts.push('uncategorized');
    else if (txCategory === 'transfer') parts.push('transfers');
    if (accountId !== null) {
      parts.push(accounts.find((a) => a.id === accountId)?.name ?? 'one account');
    }
    if (txSearch) parts.push(`“${txSearch}”`);
    return parts.join(' · ');
  }, [txPeriod, pickedCategories, txCategory, accountId, accounts, txSearch]);

  const avgExpenses = useMemo(() => {
    if (!report || report.months.length === 0) return 0;
    // The running period is always partial — exclude it from the average.
    const complete = report.months.slice(0, -1);
    if (complete.length === 0) return report.months[0].expenses;
    return complete.reduce((sum, m) => sum + m.expenses, 0) / complete.length;
  }, [report]);

  /// Budget inputs are drafts until they lose focus: typing "12" on the way to
  /// "120" must not save a budget of twelve. A category with no draft shows
  /// what is stored, so no effect has to copy one into the other.
  const [budgetDrafts, setBudgetDrafts] = useState<Record<number, string>>({});

  const budgetValue = (category: TransactionCategory) =>
    budgetDrafts[category.id]
    ?? (category.monthly_budget !== null ? String(Number(category.monthly_budget)) : '');

  const budgetedCount = categories.filter((c) => c.monthly_budget !== null).length;

  const monthlyBudgetTotal = categories.reduce(
    (sum, c) => sum + Number(c.monthly_budget ?? 0), 0);

  const saveBudget = async (category: TransactionCategory) => {
    const draft = budgetValue(category).trim();
    const value = draft === '' ? null : Number(draft);
    if (value !== null && (Number.isNaN(value) || value < 0)) return;
    // Unchanged: nothing to send, and no report reload to pay for.
    if (Number(category.monthly_budget ?? NaN) === value
        || (category.monthly_budget === null && value === null)) return;
    try {
      const updated = await setCategoryBudget(category.id, value);
      setCategories((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
      // Drop the draft so the row shows what the server stored.
      setBudgetDrafts((prev) => {
        const next = { ...prev };
        delete next[category.id];
        return next;
      });
      loadReport();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save the budget');
    }
  };

  const handleClassify = async (
    tx: Transaction,
    fields: { category?: number | null; spread_months?: number; is_transfer?: boolean },
  ) => {
    try {
      const updated = await classifyTransaction(tx.id, fields);
      setTransactions((prev) => prev.map((t) => (t.id === tx.id ? updated : t)));
      loadReport();
      // The rule behind this transaction now disagrees with the correction.
      // Left alone it keeps sending every future booking of this merchant to
      // the old category, so offer to fix it while the user is looking.
      if (updated.stale_rule) {
        setStaleRule({ rule: updated.stale_rule, transaction: updated, fields });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update transaction');
    }
  };

  /// Applies the correction to the rule itself, then reloads: the rule runs
  /// retroactively, so other transactions of the same merchant move too.
  ///
  /// Only what the user actually changed is carried over — correcting a
  /// category must not quietly rewrite the rule's spread as well.
  const handleUpdateStaleRule = async () => {
    if (!staleRule) return;
    const { rule, transaction, fields } = staleRule;
    setStaleRuleBusy(true);
    try {
      const updated = await updateCategoryRule(rule.id, {
        ...(fields.is_transfer === true
          ? { is_transfer: true, category: null, spread_months: 1 }
          : {}),
        ...(fields.category !== undefined && !transaction.is_transfer
          ? { category: transaction.category, is_transfer: false }
          : {}),
        ...(fields.spread_months !== undefined && !transaction.is_transfer
          ? { spread_months: transaction.spread_months }
          : {}),
      });
      setRules((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      setStaleRule(null);
      loadReport();
      loadTransactions(accountId, 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update the rule');
    } finally {
      setStaleRuleBusy(false);
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
      setCategories((prev) => [...prev, category]
        .sort((a, b) => compareCategoryNames(a.name, b.name)));
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

  /// "+ Rule" on a transaction row: open the rule dialog prefilled from it.
  /// Crafting a rule is a decision about that one row, so it stays where the
  /// row is — sending the user to another tab lost both the context and the
  /// scroll position they were working through.
  const craftRuleFrom = (tx: Transaction) => {
    const base = stripLeadingIban(tx.counterparty) || tx.description;
    setEditText(base.toLowerCase().slice(0, 128).trim());
    setEditTarget(tx.is_transfer ? '__transfer__' : (tx.category ?? ''));
    setEditSpread(tx.spread_months > 1 ? tx.spread_months : 1);
    setEditIsRegex(false);
    setEditRange(EMPTY_FILTER);
    setError('');
    setEditRule('new');
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
    setEditRange(filterOf(rule));
    setError('');
  };

  const handleSaveRuleEdit = async () => {
    const rule = editRule;
    if (!rule || !editText.trim() || editTarget === '') return;
    if (editIsRegex) {
      try {
        new RegExp(editText.trim());
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Invalid regular expression');
        return;
      }
    }
    if (isImpossible(editFilter)) {
      setError('The amount range is empty — no transaction can satisfy both bounds.');
      return;
    }
    const isTransfer = editTarget === '__transfer__';
    const match_text = editText.trim();
    // Transfers are excluded from spending — nothing to amortize.
    const target = isTransfer
      ? { is_transfer: true, spread_months: 1 }
      : { category: editTarget as number, spread_months: editSpread };
    const bounds = filterPayload(editFilter);
    setEditSaving(true);
    try {
      if (rule === 'new') {
        const created = await createCategoryRule({
          match_text, is_regex: editIsRegex, ...target, ...bounds,
        });
        setRules((prev) => [...prev, created]);
      } else {
        const updated = await updateCategoryRule(rule.id, {
          match_text,
          is_regex: editIsRegex,
          is_transfer: isTransfer,
          category: isTransfer ? null : (editTarget as number),
          spread_months: target.spread_months,
          ...bounds,
        });
        setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
      }
      setEditRule(null);
      // Rules re-run server-side: the report and labels may have changed.
      loadReport();
      loadTransactions(accountId, 1);
    } catch (e) {
      setError(e instanceof Error ? e.message
        : `Failed to ${rule === 'new' ? 'create' : 'update'} rule`);
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
          const value = trimLeading(e.target.value);
          setRuleText(value);
          // Obvious pattern syntax flips the switch on (and off again when
          // deleted) — but never after the user touched it themselves.
          if (!ruleRegexTouched) setRuleIsRegex(REGEX_HINT.test(value));
        }}
        onBlur={(e) => setRuleText(e.target.value.trim())}
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
      <RuleImpact
        matchText={ruleText}
        isRegex={ruleIsRegex}
        isTransfer={ruleCategory === '__transfer__'}
      />
    </div>
  );
  // The anchored group can disappear (filter, last rule deleted, Order view)
  // — the form then falls back to the bottom of the card.
  const ruleFormInGroup = rulesView === 'grouped'
    && ruleGroups.some((g) => g.label === ruleFormAnchor);

  return (
    <div className="dashboard">
        {/* Shared by the bar chart, the donut and recharts' own legend, which
            renders in a separate <svg> — paint references resolve document-wide. */}
        <CategoryPatternDefs count={paletteCategories.length} />
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
            <h2>Spending</h2>
            <button
              className={`btn btn-sm ${showUncategorized ? 'btn-primary' : 'btn-ghost'}`}
              title="Count spending that has no category yet"
              onClick={() => setShowUncategorized((v) => !v)}
            >
              Uncategorized
            </button>
          </div>

          <PeriodBar
            granularity={granularity}
            onGranularity={changeGranularity}
            periods={periodLabels}
            selected={monthDetail?.month ?? null}
            onSelect={selectMonth}
            history={months}
            onHistory={setMonths}
            mode={mode}
            onMode={setMode}
          />

          {monthDetail && (
            <SummaryTiles
              tiles={summaryTiles}
              currency={currency}
              periodNoun={periodNoun}
              partial={isCurrentPeriod}
            />
          )}

          {monthDetail && budgetTotal !== null && (
            <p className={`budget-summary ${
              spentInPeriod > budgetTotal ? 'over' : ''}`}>
              {spentInPeriod > budgetTotal
                ? <><strong>{formatAmount(spentInPeriod - budgetTotal, currency)}</strong>
                    {' over budget'}</>
                : <><strong>{formatAmount(budgetTotal - spentInPeriod, currency)}</strong>
                    {' left of budget'}</>}
              {` (${formatAmount(budgetTotal, currency)} for this ${periodNoun}`}
              {budgetedShare < 100 && `, covering ${budgetedShare.toFixed(0)}% of what you spend`}
              {')'}
            </p>
          )}

          {chartData.length === 0 ? (
            <div className="chart-empty"><p>No transactions yet.</p></div>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="month" stroke="#8b93a7" fontSize={12}
                       tickFormatter={formatPeriodShort} />
                <YAxis stroke="#8b93a7" fontSize={12} />
                <Tooltip
                  formatter={(value, name) =>
                    [formatAmount(Number(value ?? 0), currency), String(name)]}
                  labelFormatter={(label) => formatPeriod(String(label))}
                  // Income first, then categories in report order (largest total first).
                  itemSorter={(item) => (item.name === 'Income'
                    ? -1
                    : report?.categories.indexOf(String(item.name)) ?? 0)}
                  contentStyle={{ background: '#1a1f2e', border: '1px solid #2a3040' }}
                  // The legend is a sibling div that would otherwise paint over
                  // the tooltip, making its background look see-through.
                  wrapperStyle={{ zIndex: 10 }}
                />
                {visibleCategories.map((name) => (
                  <Bar
                    key={name}
                    dataKey={name}
                    stackId="expenses"
                    fill={styleFor(name).fill}
                    onClick={(data: { month?: string; payload?: { month?: string } }) => {
                      const m = data?.month ?? data?.payload?.month;
                      if (m) selectMonth(m);
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    {chartData.map((entry) => (
                      // The selected period stands out; the rest is context.
                      <Cell
                        key={entry.month}
                        opacity={entry.month === monthDetail?.month ? 1 : 0.5}
                      />
                    ))}
                  </Bar>
                ))}
                <Line dataKey="Income" stroke={INCOME_COLOR} strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
          <p className="form-hint spending-chart-hint">
            Click a bar to inspect that {periodNoun}. Average spending per{' '}
            {periodNoun} over the completed ones: <strong>
              {formatAmount(avgExpenses, currency)}
            </strong>.
          </p>
        </div>

        <div className="card">
          <div className="chart-header">
            <h2>
              Breakdown
              {monthDetail && (
                <span className="spending-month-title">
                  {' · '}{formatPeriod(monthDetail.month)}
                </span>
              )}
            </h2>
          </div>
          <CategoryBreakdown
            rows={categoryRows}
            total={categoryTotal}
            currency={currency}
            selected={pickedCategories}
            onToggle={togglePickedCategory}
            onClear={() => setPickedCategories([])}
            onOpenDetail={setDetailCategory}
            periodNoun={periodNoun}
          />
        </div>

        <div className="card">
          <div className="chart-header">
            <h2>
              Transactions
              <span className="spending-month-title"> · {filterSummary}</span>
            </h2>
            <div className="range-buttons">
              <div className="tx-search">
                <Search size={14} className="tx-search-icon" />
                <input
                  type="search"
                  aria-label="Search transactions"
                  placeholder="Search text or amount…"
                  value={txSearchInput}
                  {...trimmedInput(setTxSearchInput)}
                  onKeyDown={(e) => { if (e.key === 'Escape') setTxSearchInput(''); }}
                />
                {txSearchInput && (
                  <button
                    className="tx-search-clear"
                    aria-label="Clear search"
                    onClick={() => setTxSearchInput('')}
                  >
                    <X size={13} />
                  </button>
                )}
              </div>
              <select
                aria-label="Filter by account"
                value={accountId ?? ''}
                onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">All accounts</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
              {/* The period bar and the breakdown chips above already say
                  which period and which categories — these only add what
                  they cannot express. */}
              <select
                aria-label="Show"
                value={txCategory === 'none' || txCategory === 'transfer' ? txCategory : ''}
                onChange={(e) => {
                  const v = e.target.value;
                  setPickedCategories([]);
                  setTxCategory(v === 'none' || v === 'transfer' ? v : '');
                }}
              >
                <option value="">Everything</option>
                <option value="none">Uncategorized only</option>
                <option value="transfer">Transfers only</option>
              </select>
              <button
                className="btn btn-sm btn-ghost"
                title="Show every period, not just the selected one"
                onClick={() => setTxAllPeriods((v) => !v)}
              >
                {txPeriod ? 'All periods' : `Back to ${periodNoun}`}
              </button>
            </div>
          </div>
          {transactions.length === 0 ? (
            <p className="table-empty">
              {txCategory !== '' || txPeriod || accountId !== null || txSearch
                ? 'No transactions match this filter.'
                : 'No transactions yet.'}
            </p>
          ) : (
            // Five columns, no horizontal scrolling: date and account share a
            // cell, counterparty and description share the one column that
            // absorbs the slack, and the controls stay narrow.
            <div className="table-wrapper">
              <table className="data-table spending-tx-table">
                <thead>
                  <tr>
                    <th className="spending-tx-when">{sortHeader('date', 'Date')}</th>
                    <th>{sortHeader('text', 'Transaction')}</th>
                    {/* One dropdown for category OR transfer: mutually
                        exclusive, and transfers never carry a category.
                        Manual transfer marking stays possible here because
                        auto-detection only pairs entries between two
                        accounts that both have a feed. Next to it the
                        per-transaction spread: a rule amortizes every match,
                        but a one-off yearly bill has no rule to hang it on. */}
                    <th className="spending-tx-controls-col">
                      {sortHeader('category', 'Category · spread')}
                    </th>
                    <th className="spending-tx-action-col" aria-label="Actions" />
                    <th className="spending-amount-col">
                      {sortHeader('amount', 'Amount')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((tx) => {
                    // Not every feed fills in a counterparty — a ZKB card
                    // purchase puts the merchant in the booking text instead.
                    // Whatever names the transaction is the primary line, so a
                    // row never consists of grey detail text alone.
                    const party = stripLeadingIban(tx.counterparty);
                    const primary = party || tx.description;
                    const secondary = party ? tx.description : '';
                    return (
                    <tr key={tx.id} className={tx.is_transfer ? 'spending-transfer-row' : ''}>
                      <td className="spending-tx-when">
                        <div>{tx.booking_date}</div>
                        <div className="spending-muted" title={accountNames[tx.account] ?? ''}>
                          {accountNames[tx.account] ?? ''}
                        </div>
                      </td>
                      <td className="spending-tx-details">
                        {primary && (
                          <div className="spending-tx-party">
                            <ClampedText text={primary} />
                          </div>
                        )}
                        {secondary && (
                          <div className="spending-muted">
                            <ClampedText text={secondary} />
                          </div>
                        )}
                      </td>
                      <td>
                        <div className="spending-tx-controls">
                          <select
                            aria-label="Category"
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
                          {/* A transfer is excluded from spending entirely, so
                              there is nothing to amortize. */}
                          {!tx.is_transfer && (
                            <select
                              className="spending-tx-spread"
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
                        </div>
                      </td>
                      <td>
                        <button
                          className="btn btn-sm btn-ghost"
                          title="Create a rule from this transaction"
                          aria-label="Create a rule from this transaction"
                          onClick={() => craftRuleFrom(tx)}
                        >
                          <Plus size={14} />
                          <span className="spending-tx-rule-label">Rule</span>
                        </button>
                      </td>
                      <td className={`spending-amount-col ${Number(tx.amount) < 0 ? 'spending-neg' : 'spending-pos'}`}>
                        {formatAmount(Number(tx.amount), tx.currency)}
                        {/* A spread bill only counts partly towards this
                            period — say how much, so the list adds up to the
                            figure in the breakdown above it. */}
                        {tx.period_slice && (
                          <div className="spending-tx-slice" title={
                            `${tx.period_slice.months} of ${tx.period_slice.of} months `
                            + `of this bill are counted in `
                            + `${txPeriod ? formatPeriod(txPeriod) : 'this period'}`}>
                            {formatAmount(Number(tx.period_slice.amount), tx.currency)}
                            <span className="spending-muted">
                              {' '}· {tx.period_slice.months}/{tx.period_slice.of}
                            </span>
                          </div>
                        )}
                      </td>
                    </tr>
                    );
                  })}
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
              Budgets
              {budgetedCount > 0 && (
                <span className="spending-month-title"> · {budgetedCount} set</span>
              )}
            </h2>
          </div>
          <p className="form-hint">
            A monthly target per category, in {currency}. The insights scale it to
            whatever period is on screen — a quarter shows three times this, a year
            twelve — and leaving a field empty means the category has no target.
          </p>
          {categories.length === 0 ? (
            <p className="table-empty">No categories yet.</p>
          ) : (<>
            {categories.map((category) => (
              <div
                key={category.id}
                className={`budget-row${budgetValue(category) ? ' has-budget' : ''}`}
              >
                <span className="budget-row-name">{category.name}</span>
                <span className="budget-input">
                  <input
                    type="number"
                    min="0"
                    step="10"
                    aria-label={`Monthly budget for ${category.name}`}
                    placeholder="none"
                    value={budgetValue(category)}
                    onChange={(e) => setBudgetDrafts(
                      (prev) => ({ ...prev, [category.id]: e.target.value }))}
                    onBlur={() => saveBudget(category)}
                    onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
                  />
                  <span className="budget-input-currency">{currency}</span>
                </span>
              </div>
            ))}
            <div className="budget-total">
              <span>Total per month</span>
              <span>{formatAmount(monthlyBudgetTotal, currency)}</span>
            </div>
          </>)}
        </div>

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
                  {...trimmedInput(setRuleFilter)}
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
          <ModalOverlay onClose={() => setEditRule(null)}>
            <div className="modal modal-rule" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3>{editRule === 'new' ? 'New rule' : 'Edit rule'}</h3>
                <button className="btn btn-ghost" onClick={() => setEditRule(null)}>
                  <X size={18} />
                </button>
              </div>
              {/* Two columns: the rule on the left, what it does on the right.
                  The match count arrives asynchronously — in one column it
                  appeared between the fields and pushed everything down as
                  you typed. */}
              <div className="rule-dialog">
                <div className="rule-dialog-form">
                  <div className="form-group">
                    <label htmlFor="edit-rule-text">Match text</label>
                    <input
                      id="edit-rule-text"
                      autoFocus
                      value={editText}
                      {...trimmedInput(setEditText)}
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
                        setEditTarget(
                          v === '__transfer__' || v === '' ? v : Number(v));
                      }}
                    >
                      {/* A row with no category yet opens with nothing picked —
                          better than silently defaulting to Transfer. */}
                      {editTarget === '' && <option value="">Category…</option>}
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
                </div>

                <div className="rule-dialog-side">
                  <RuleAmountFilter
                    value={editFilter}
                    onChange={setEditRange}
                    currency={currency}
                    // Open when the rule already has a range, so an existing
                    // condition is never hidden behind a collapsed section.
                    startOpen={describeFilter(editFilter) !== null}
                  />
                  <RuleImpact
                    matchText={editText}
                    isRegex={editIsRegex}
                    isTransfer={editTarget === '__transfer__'}
                    ruleId={editRule === 'new' ? undefined : editRule.id}
                    filter={editFilter}
                  />
                </div>
              </div>
              <div className="form-actions">
                <button className="btn btn-ghost" onClick={() => setEditRule(null)}>
                  Cancel
                </button>
                <button
                  className="btn btn-primary"
                  onClick={handleSaveRuleEdit}
                  disabled={editSaving || !editText.trim() || editTarget === ''}
                >
                  {editSaving
                    ? 'Saving…'
                    : (editRule === 'new' ? 'Create rule' : 'Save')}
                </button>
              </div>
            </div>
          </ModalOverlay>
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

        {detailCategory && (
          <CategoryDetail
            name={detailCategory}
            style={styleFor(detailCategory)}
            series={detailSeries}
            selectedPeriod={monthDetail?.month ?? null}
            currency={currency}
            periodNoun={periodNoun}
            onSelectPeriod={(period) => { selectMonth(period); setDetailCategory(null); }}
            onClose={() => setDetailCategory(null)}
          />
        )}

        {staleRule && (
          <ModalOverlay onClose={() => setStaleRule(null)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3>Update the rule too?</h3>
                <button className="btn btn-ghost" onClick={() => setStaleRule(null)}>
                  <X size={18} />
                </button>
              </div>
              <p className="form-hint" style={{ marginBottom: 16 }}>
                The rule <code>{staleRule.rule.match_text}</code> classifies this
                transaction as{' '}
                <strong>
                  {staleRule.rule.is_transfer
                    ? 'Transfer (excluded)'
                    : staleRule.rule.category_name}
                  {staleRule.rule.spread_months > 1
                    && ` /${staleRule.rule.spread_months}m`}
                </strong>
                {' '}— so the next booking that matches it lands there again.
                Point the rule at{' '}
                <strong>
                  {staleRule.transaction.is_transfer
                    ? 'Transfer (excluded)'
                    : staleRule.transaction.category_name}
                  {staleRule.transaction.spread_months > 1
                    && ` /${staleRule.transaction.spread_months}m`}
                </strong>
                {' '}instead? Transactions you already categorized by hand keep
                their category.
              </p>
              <div className="form-actions">
                <button
                  className="btn btn-ghost"
                  onClick={() => setStaleRule(null)}
                >
                  Just this transaction
                </button>
                <button
                  className="btn btn-primary"
                  onClick={handleUpdateStaleRule}
                  disabled={staleRuleBusy}
                >
                  {staleRuleBusy ? 'Updating…' : 'Update the rule'}
                </button>
              </div>
            </div>
          </ModalOverlay>
        )}

        {regexConfirmOpen && (
          <ModalOverlay onClose={() => setRegexConfirmOpen(false)}>
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
          </ModalOverlay>
        )}

        {categoryDialogOpen && (
          <ModalOverlay onClose={() => setCategoryDialogOpen(false)}>
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
                    {...trimmedInput(setNewCategoryName)}
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
          </ModalOverlay>
        )}
    </div>
  );
}
