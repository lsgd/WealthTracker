import { useEffect, useState } from 'react';
import { AlertTriangle, Check, CheckCircle2, ChevronDown, RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import { stripLeadingIban } from '../utils/iban';
import type { AiConfig, AiModel, AiPricing, AiSuggestResponse } from '../api/client';
import {
  aiApply,
  aiSuggest,
  deleteAiConfig,
  getAiConfig,
  listAiModels,
  refreshAiPricing,
  saveAiConfig,
} from '../api/client';

interface Props {
  // Called after suggestions were applied — parent refreshes report/categories/rules/transactions.
  onApplied: () => void;
}

function formatPrice(model: AiModel | AiPricing): string {
  if (model.input_price_per_1m === null) return 'pricing not listed';
  return `$${model.input_price_per_1m} in / $${model.output_price_per_1m} out per 1M tokens`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

export default function AiCategorization({ onApplied }: Props) {
  const [config, setConfig] = useState<AiConfig | null>(null);
  const [editing, setEditing] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [models, setModels] = useState<AiModel[] | null>(null);
  const [selectedModel, setSelectedModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [noticeKind, setNoticeKind] = useState<'success' | 'warning'>('success');

  const [result, setResult] = useState<AiSuggestResponse | null>(null);
  const [checkedTx, setCheckedTx] = useState<Set<number>>(new Set());
  const [checkedRules, setCheckedRules] = useState<Set<number>>(new Set());
  // Model pricing/meta and the data disclosure are reference material —
  // collapsed to just the model name once everything is configured.
  const [detailsOpen, setDetailsOpen] = useState(false);

  useEffect(() => {
    getAiConfig().then(setConfig).catch((e) =>
      setError(e instanceof Error ? e.message : 'Failed to load AI configuration'));
  }, []);

  const loadModels = async () => {
    setError('');
    setBusy(true);
    try {
      const list = await listAiModels(apiKey || undefined);
      setModels(list);
      if (list.length > 0 && !selectedModel) {
        setSelectedModel(config?.model || list[0].id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch models');
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setError('');
    setBusy(true);
    try {
      await saveAiConfig({
        ...(apiKey ? { api_key: apiKey } : {}),
        model: selectedModel,
        display_name: models?.find((m) => m.id === selectedModel)?.display_name,
      });
      setConfig(await getAiConfig());
      cancelEditing();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save');
    } finally {
      setBusy(false);
    }
  };

  const cancelEditing = () => {
    setEditing(false);
    setApiKey('');
    setModels(null);
    setSelectedModel('');
    setError('');
  };

  const refreshPricing = async () => {
    setError('');
    setNotice('');
    setNoticeKind('success');
    setBusy(true);
    try {
      const outcome = await refreshAiPricing();
      setConfig(await getAiConfig());
      if (!outcome.model_still_available) {
        setNoticeKind('warning');
        setNotice('Your key no longer lists this model — pick another one under "Change".');
      } else if (outcome.changed) {
        setNotice('Pricing updated.');
      } else {
        setNotice('Pricing is unchanged.');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to refresh pricing');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setError('');
    try {
      await deleteAiConfig();
      setConfig(await getAiConfig());
      setResult(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to remove');
    }
  };

  // Which round is running/shown: per-item labels and rule proposals are
  // separate flows — one mixed review round proved noisy.
  const [suggestMode, setSuggestMode] = useState<'items' | 'rules' | null>(null);

  const suggest = async (mode: 'items' | 'rules') => {
    setError('');
    setNotice('');
    setNoticeKind('success');
    setBusy(true);
    setSuggestMode(mode);
    setResult(null);
    try {
      const data = await aiSuggest(mode);
      setResult(data);
      setCheckedTx(new Set(data.suggestions.map((s) => s.transaction_id)));
      setCheckedRules(new Set(data.rules.map((_, i) => i)));
      if (data.sent_count === 0) {
        setNotice('Nothing to categorize — all transactions already have a category.');
      } else if (data.suggestions.length === 0 && data.rules.length === 0) {
        setNotice(mode === 'rules'
          ? 'Gemini found no recurring merchants that need a new rule.'
          : 'Gemini had no category proposals for the current transactions.');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Suggestion request failed');
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!result) return;
    setError('');
    setBusy(true);
    try {
      const outcome = await aiApply({
        assignments: result.suggestions
          .filter((s) => checkedTx.has(s.transaction_id))
          .map((s) => ({ transaction_id: s.transaction_id, category: s.category })),
        rules: result.rules
          .filter((_, i) => checkedRules.has(i))
          .map((r) => ({ match_text: r.match_text, category: r.category })),
      });
      setNotice(
        `Applied: ${outcome.assigned} transactions categorized, ${outcome.rules_created} rules created`
        + (outcome.rule_applied ? `, rules categorized ${outcome.rule_applied} more transactions` : ''),
      );
      setResult(null);
      onApplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to apply suggestions');
    } finally {
      setBusy(false);
    }
  };

  const toggle = (set: Set<number>, value: number, setter: (s: Set<number>) => void) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value); else next.add(value);
    setter(next);
  };

  const showSetup = editing || (config !== null && !config.configured);
  // While setting up (or with no model picked yet) there is nothing to
  // collapse — the full state explanation stays visible.
  const collapsible = Boolean(config?.configured && config.model) && !editing;
  const showDetails = !collapsible || detailsOpen;

  return (
    <div className="card">
      <div className="chart-header">
        <h2>AI categorization (Gemini)</h2>
        {config?.configured && !editing && (
          <div className="range-buttons">
            <button className="btn btn-sm btn-ghost" onClick={() => setEditing(true)}>
              Change
            </button>
            <button className="btn btn-sm btn-ghost" title="Remove key and model" onClick={remove}>
              <Trash2 size={14} />
            </button>
          </div>
        )}
      </div>

      {/* Collapsed: only the selected model. Expanded (or while setting up):
          pricing details plus the data disclosure. */}
      {collapsible && (
        <div
          className="ai-model-summary card-toggle"
          role="button"
          tabIndex={0}
          aria-expanded={detailsOpen}
          onClick={() => setDetailsOpen((v) => !v)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              setDetailsOpen((v) => !v);
            }
          }}
        >
          <span className="ai-model-name">
            {config?.pricing?.display_name ?? config?.model}
          </span>
          <ChevronDown
            size={16}
            className={`card-toggle-chevron ${detailsOpen ? 'open' : ''}`}
          />
        </div>
      )}

      {/* Never hidden while editing: whatever the state is, it is named here
          rather than leaving a blank card. */}
      {config && showDetails && (
        <div className="ai-model-banner">
          <div>
            {!collapsible && (
              <div className="ai-model-name">
                {config.model
                  ? (config.pricing?.display_name ?? config.model)
                  : (config.configured ? 'No model selected' : 'Gemini not set up')}
              </div>
            )}
            <div className="ai-model-price">
              {!config.model
                ? (config.configured
                    ? 'Key stored — press Change to pick a model'
                    : 'Add an API key below to enable suggestions')
                : config.pricing
                  ? formatPrice(config.pricing)
                  : 'price not checked yet'}
            </div>
            {config.model && (
              <div className="ai-model-meta">
                <code>{config.model}</code>
                {config.pricing
                  ? ` · prices checked ${formatDate(config.pricing.checked_at)}`
                  : ' · press “Check prices” to look up the rate'}
                {' · from the rate table shipped with this app ('}
                <a href={config.pricing_source_url} target="_blank" rel="noreferrer">
                  Google's pricing page
                </a>
                {')'}
              </div>
            )}
          </div>
          {config.configured && config.model && (
            <button
              className="btn btn-sm btn-ghost"
              title="Re-check the listed price for this model"
              onClick={refreshPricing}
              disabled={busy}
            >
              <RefreshCw size={14} /> {busy ? 'Checking…' : 'Check prices'}
            </button>
          )}
        </div>
      )}

      {config && showDetails && (
        <div className="ai-disclosure">
          <strong>Data sent to Google when you request suggestions:</strong>
          <ul>
            {config.disclosed_fields.map((f) => <li key={f}>{f}</li>)}
          </ul>
          <p>
            Not transferred: account numbers/IBANs, booking dates, balances, or your identity.
            Suggestions are never applied without your confirmation below.
          </p>
        </div>
      )}

      {error && <div className="form-error" onClick={() => setError('')}>{error}</div>}
      {notice && (
        <div
          className={noticeKind === 'warning' ? 'form-warning' : 'form-success'}
          onClick={() => setNotice('')}
        >
          {noticeKind === 'warning'
            ? <AlertTriangle size={16} />
            : <CheckCircle2 size={16} />} {notice}
        </div>
      )}

      {collapsible && !result && (
        <div className="ai-suggest-ctas">
          <button
            className="btn btn-primary ai-suggest-cta"
            title="Ask Gemini for a category per uncategorized transaction"
            onClick={() => suggest('items')}
            disabled={busy}
          >
            <Sparkles size={16} />
            {busy && suggestMode === 'items' ? 'Asking Gemini…' : 'Categorize items'}
          </button>
          <button
            className="btn btn-primary ai-suggest-cta"
            title="Ask Gemini for reusable rules covering recurring merchants"
            onClick={() => suggest('rules')}
            disabled={busy}
          >
            <Sparkles size={16} />
            {busy && suggestMode === 'rules' ? 'Asking Gemini…' : 'Suggest rules'}
          </button>
        </div>
      )}

      {showSetup && (
        <div className="ai-setup">
          <div className="spending-rule-row spending-rule-new">
            <input
              className="ai-key-input"
              type="password"
              placeholder="Gemini API key"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <button
              className="btn btn-sm btn-primary"
              onClick={loadModels}
              disabled={busy || (!apiKey && !config?.configured)}
            >
              {busy ? 'Loading…' : 'Load models'}
            </button>
            {editing && (
              <button className="btn btn-sm btn-ghost" onClick={cancelEditing}>
                Cancel
              </button>
            )}
          </div>
          {models && (
            <div className="spending-rule-row spending-rule-new">
              <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name} — {formatPrice(m)}
                  </option>
                ))}
              </select>
              <button
                className="btn btn-sm btn-primary"
                onClick={save}
                disabled={busy || !selectedModel || (!apiKey && !config?.configured)}
              >
                Save
              </button>
            </div>
          )}
          <p className="form-hint">
            {config?.configured
              ? 'Leave the key empty to keep the one already stored and only change the model. '
              : 'Paste your Gemini API key (aistudio.google.com). '}
            Load the model list to pick a model; prices shown are Google's standard
            per-1M-token rates.
          </p>
        </div>
      )}


      {result && (result.suggestions.length > 0 || result.rules.length > 0) && (
        <div className="ai-suggestions">
          {result.suggestions.length > 0 && (<>
          <h3>Suggested categories ({result.suggestions.length} of {result.sent_count} sent
            {result.total_uncategorized > result.sent_count
              ? `, ${result.total_uncategorized - result.sent_count} more uncategorized remain`
              : ''})</h3>
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th></th>
                  <th>Date</th>
                  <th>Counterparty</th>
                  <th>Description</th>
                  <th>Suggested category</th>
                  <th className="spending-amount-col">Amount</th>
                </tr>
              </thead>
              <tbody>
                {result.suggestions.map((s) => (
                  <tr key={s.transaction_id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={checkedTx.has(s.transaction_id)}
                        onChange={() => toggle(checkedTx, s.transaction_id, setCheckedTx)}
                      />
                    </td>
                    <td>{s.booking_date}</td>
                    <td>{stripLeadingIban(s.counterparty)}</td>
                    <td>{s.description}</td>
                    <td>
                      {s.category}
                      {s.is_new_category && <span className="ai-new-badge">NEW</span>}
                    </td>
                    <td className={`spending-amount-col ${Number(s.amount) < 0 ? 'spending-neg' : 'spending-pos'}`}>
                      {s.amount} {s.currency}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>)}

          {result.rules.length > 0 && (
            <>
              <h3>Suggested rules (categorize future transactions without AI)</h3>
              <div className="spending-rules">
                {result.rules.map((r, i) => (
                  <div key={`${r.match_text}-${i}`} className="spending-rule-row">
                    <input
                      type="checkbox"
                      checked={checkedRules.has(i)}
                      onChange={() => toggle(checkedRules, i, setCheckedRules)}
                    />
                    <code>{r.match_text}</code>
                    <span>→ {r.category}</span>
                    {r.is_new_category && <span className="ai-new-badge">NEW</span>}
                  </div>
                ))}
              </div>
            </>
          )}

          {result.usage && (
            <p className="form-hint">
              Tokens: {result.usage.input_tokens} in / {result.usage.output_tokens} out
              {result.usage.estimated_cost_usd !== null
                ? ` — estimated cost $${result.usage.estimated_cost_usd}`
                : ''}
            </p>
          )}

          <div className="form-actions">
            <button className="btn btn-ghost" onClick={() => setResult(null)}>Discard</button>
            <button
              className="btn btn-primary"
              onClick={apply}
              disabled={busy || (checkedTx.size === 0 && checkedRules.size === 0)}
            >
              <Check size={14} /> Apply selected ({checkedTx.size + checkedRules.size})
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
