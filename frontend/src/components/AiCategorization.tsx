import { useEffect, useState } from 'react';
import { Check, Sparkles, Trash2 } from 'lucide-react';
import type { AiConfig, AiModel, AiSuggestResponse } from '../api/client';
import {
  aiApply,
  aiSuggest,
  deleteAiConfig,
  getAiConfig,
  listAiModels,
  saveAiConfig,
} from '../api/client';

interface Props {
  // Called after suggestions were applied — parent refreshes report/categories/rules/transactions.
  onApplied: () => void;
}

function formatPrice(model: AiModel): string {
  if (model.input_price_per_1m === null) return 'pricing not listed';
  return `$${model.input_price_per_1m} in / $${model.output_price_per_1m} out per 1M tokens`;
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

  const [result, setResult] = useState<AiSuggestResponse | null>(null);
  const [checkedTx, setCheckedTx] = useState<Set<number>>(new Set());
  const [checkedRules, setCheckedRules] = useState<Set<number>>(new Set());

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
      });
      setConfig(await getAiConfig());
      setEditing(false);
      setApiKey('');
      setModels(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save');
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

  const suggest = async () => {
    setError('');
    setNotice('');
    setBusy(true);
    setResult(null);
    try {
      const data = await aiSuggest();
      setResult(data);
      setCheckedTx(new Set(data.suggestions.map((s) => s.transaction_id)));
      setCheckedRules(new Set(data.rules.map((_, i) => i)));
      if (data.sent_count === 0) {
        setNotice('Nothing to categorize — all transactions already have a category.');
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

  return (
    <div className="card">
      <div className="chart-header">
        <h2>AI categorization (Gemini)</h2>
        {config?.configured && !editing && (
          <div className="range-buttons">
            <button className="btn btn-sm btn-primary" onClick={suggest} disabled={busy}>
              <Sparkles size={14} /> {busy ? 'Asking Gemini…' : 'Get suggestions'}
            </button>
            <button className="btn btn-sm btn-ghost" onClick={() => setEditing(true)}>
              Change
            </button>
            <button className="btn btn-sm btn-ghost" title="Remove key and model" onClick={remove}>
              <Trash2 size={14} />
            </button>
          </div>
        )}
      </div>

      {config && (
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
      {notice && <p className="form-hint">{notice}</p>}

      {showSetup && (
        <div className="ai-setup">
          <div className="spending-rule-row spending-rule-new">
            <input
              type="password"
              placeholder={config?.configured ? 'API key (leave empty to keep current)' : 'Gemini API key'}
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
              {editing && (
                <button className="btn btn-sm btn-ghost" onClick={() => { setEditing(false); setModels(null); setApiKey(''); }}>
                  Cancel
                </button>
              )}
            </div>
          )}
          {!models && (
            <p className="form-hint">
              Paste your Gemini API key (aistudio.google.com), then load the model list to
              pick a model. Prices shown are Google's standard per-1M-token rates.
            </p>
          )}
        </div>
      )}

      {config?.configured && !editing && (
        <p className="form-hint">Model: <code>{config.model}</code></p>
      )}

      {result && result.suggestions.length > 0 && (
        <div className="ai-suggestions">
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
                    <td>{s.counterparty}</td>
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
