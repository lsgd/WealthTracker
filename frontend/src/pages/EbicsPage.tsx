import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Landmark, Plus, Trash2, FileSignature, Download, PlugZap, Loader, X, ArrowLeft,
} from 'lucide-react';
import {
  getBrokersList,
  getEbicsCredentials,
  createEbicsCredential,
  deleteEbicsCredential,
  initializeEbicsCredential,
  getEbicsLetter,
  testEbicsCredential,
  downloadEbicsLetter,
  createAccount,
  getAccounts,
  linkEbicsAccount,
  type EbicsCredential,
  type EbicsDiscoveredAccount,
} from '../api/client';

interface Broker {
  code: string;
  name: string;
  integration_type: string;
  api_base_url?: string;
}

interface ExistingAccount {
  id: number;
  name: string;
  account_identifier: string | null;
  broker_code: string;
}

// A pending "add account" awaiting confirmation. `existing` is set when the user
// already has an account for this IBAN (→ offer to link instead of duplicate).
interface PendingAdd {
  cred: EbicsCredential;
  acct: EbicsDiscoveredAccount;
  existing: ExistingAccount | null;
}

const STATE_LABEL: Record<EbicsCredential['state'], string> = {
  new: 'Keys generated — not submitted',
  keys_sent: 'Awaiting bank activation',
  active: 'Active',
  error: 'Error',
};

const emptyForm = {
  broker_code: '',
  label: '',
  host_id: '',
  partner_id: '',
  user_id: '',
  url: '',
  bank_hash_auth: '',
  bank_hash_enc: '',
};

export default function EbicsPage() {
  const [credentials, setCredentials] = useState<EbicsCredential[]>([]);
  const [brokers, setBrokers] = useState<Broker[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...emptyForm });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  // Per-credential transient state
  const [busy, setBusy] = useState<Record<number, string>>({}); // id -> action label
  const [discovered, setDiscovered] = useState<Record<number, EbicsDiscoveredAccount[]>>({});
  const [addedIbans, setAddedIbans] = useState<Record<string, boolean>>({});
  const [pendingDelete, setPendingDelete] = useState<EbicsCredential | null>(null);
  const [accounts, setAccounts] = useState<ExistingAccount[]>([]);
  const [pendingAdd, setPendingAdd] = useState<PendingAdd | null>(null);

  async function load() {
    try {
      const [creds, brk, accts] = await Promise.all([
        getEbicsCredentials(), getBrokersList<Broker>(), getAccounts(),
      ]);
      setCredentials(creds);
      setBrokers(brk.filter((b) => b.integration_type === 'ebics'));
      // getAccounts is paginated; normalise to a flat list of what we need.
      const list = Array.isArray(accts) ? accts : (accts?.results ?? []);
      setAccounts(list.map((a: { id: number; name: string; account_identifier: string | null; broker?: { code?: string } }) => ({
        id: a.id, name: a.name, account_identifier: a.account_identifier,
        broker_code: a.broker?.code ?? '',
      })));
    } catch (err) {
      console.error('Failed to load EBICS credentials:', err);
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }

  // Wrapped in an async IIFE so the initial load (and its setState calls) runs
  // after the effect returns rather than synchronously in the effect body.
  useEffect(() => { (async () => { await load(); })(); }, []);

  function openForm() {
    const first = brokers[0];
    setForm({
      ...emptyForm,
      broker_code: first?.code ?? '',
      url: first?.api_base_url ?? '',
    });
    setError('');
    setMessage('');
    setShowForm(true);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError('');
    setMessage('');
    try {
      await createEbicsCredential({
        broker_code: form.broker_code,
        label: form.label,
        host_id: form.host_id.trim(),
        partner_id: form.partner_id.trim(),
        user_id: form.user_id.trim(),
        bank_hash_auth: form.bank_hash_auth.trim() || undefined,
        bank_hash_enc: form.bank_hash_enc.trim() || undefined,
      });
      setShowForm(false);
      setMessage('Credential created. Submit your keys next to produce the initialisation letter.');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create credential');
    } finally {
      setCreating(false);
    }
  }

  function withBusy(id: number, label: string) {
    setBusy((b) => ({ ...b, [id]: label }));
    setError('');
    setMessage('');
  }
  function clearBusy(id: number) {
    setBusy((b) => { const next = { ...b }; delete next[id]; return next; });
  }

  async function handleInitialize(cred: EbicsCredential) {
    withBusy(cred.id, 'Submitting keys...');
    try {
      const res = await initializeEbicsCredential(cred.id);
      downloadEbicsLetter(res.letter);
      setMessage(
        'Keys submitted. The initialisation letter downloaded — print it, sign it by hand, ' +
        'and mail it to the bank. Once they activate your access, use "Test connection".',
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Key submission failed');
      // The server may have flipped the credential to 'error' (e.g. the bank rejected
      // the keys as already-initialised); refresh so the card reflects that.
      await load();
    } finally {
      clearBusy(cred.id);
    }
  }

  async function handleDownloadLetter(cred: EbicsCredential) {
    withBusy(cred.id, 'Rendering letter...');
    try {
      const letter = await getEbicsLetter(cred.id);
      downloadEbicsLetter(letter);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to render letter');
    } finally {
      clearBusy(cred.id);
    }
  }

  async function handleTest(cred: EbicsCredential) {
    withBusy(cred.id, 'Testing connection...');
    try {
      const res = await testEbicsCredential(cred.id);
      setDiscovered((d) => ({ ...d, [cred.id]: res.accounts }));
      const tofu = res.bank_key_hashes_recorded
        ? ' Bank keys were pinned on first use — verify the hashes below against your paper letter.'
        : '';
      setMessage(`Connection verified — ${res.accounts.length} account(s) found.${tofu}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection test failed');
    } finally {
      clearBusy(cred.id);
    }
  }

  async function confirmDelete() {
    const cred = pendingDelete;
    if (!cred) return;
    setPendingDelete(null);
    withBusy(cred.id, 'Deleting...');
    try {
      await deleteEbicsCredential(cred.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete');
    } finally {
      clearBusy(cred.id);
    }
  }

  // Open a confirmation dialog. If an account for this IBAN already exists, offer to
  // link it (avoid a duplicate); otherwise confirm creating a new one.
  function handleAddAccount(cred: EbicsCredential, acct: EbicsDiscoveredAccount) {
    const existing = accounts.find(
      (a) => a.account_identifier === acct.iban && a.broker_code === cred.broker_code,
    ) ?? null;
    setError('');
    setMessage('');
    setPendingAdd({ cred, acct, existing });
  }

  async function confirmAdd() {
    const p = pendingAdd;
    if (!p) return;
    setPendingAdd(null);
    const { cred, acct, existing } = p;
    withBusy(cred.id, existing ? `Linking ${acct.iban}...` : `Adding ${acct.iban}...`);
    try {
      if (existing) {
        await linkEbicsAccount(cred.id, existing.id);
        setMessage(`Linked "${existing.name}" (${acct.iban}) to this EBICS credential — it now auto-syncs.`);
      } else {
        await createAccount({
          name: acct.iban,
          broker_code: cred.broker_code,
          account_identifier: acct.iban,
          account_type: 'checking',
          currency: acct.currency,
          is_manual: false,
          ebics_credential_id: cred.id,
        });
        setMessage(`Account ${acct.iban} added. It will sync via this EBICS credential.`);
      }
      setAddedIbans((a) => ({ ...a, [acct.iban]: true }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add account');
    } finally {
      clearBusy(cred.id);
    }
  }

  if (loading) return <div className="loading">Loading...</div>;

  return (
    <div className="page">
      <div className="page-header">
        <div className="page-header-left">
          <Link to="/settings" className="btn btn-ghost btn-sm" title="Back to settings">
            <ArrowLeft size={16} />
          </Link>
          <h1><Landmark size={22} /> EBICS bank connections</h1>
        </div>
        {brokers.length > 0 && (
          <button className="btn btn-primary" onClick={openForm}>
            <Plus size={16} /> New credential
          </button>
        )}
      </div>

      <p className="form-hint" style={{ maxWidth: '68ch' }}>
        EBICS credentials (e.g. Zürcher Kantonalbank) are set up once and shared across all of that
        bank's accounts. Setup is a one-time key exchange: create a credential, submit the keys to
        produce an initialisation letter, print &amp; sign it, mail it to the bank, then test the
        connection once they activate your access.
      </p>

      {error && <div className="form-error" style={{ marginTop: 16 }}>{error}</div>}
      {message && <div className="form-success" style={{ marginTop: 16 }}>{message}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal ebics-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>New EBICS credential</h3>
              <button className="btn btn-ghost" onClick={() => setShowForm(false)}><X size={18} /></button>
            </div>
            <form onSubmit={handleCreate}>
              <p className="form-hint">
                Enter the connection parameters from your bank's EBICS "Bankparameterdaten" letter.
                A fresh RSA keyring is generated and encrypted with your account key.
              </p>
              <div className="form-group">
                <label>Bank</label>
                <select
                  value={form.broker_code}
                  onChange={(e) => {
                    const b = brokers.find((x) => x.code === e.target.value);
                    setForm({ ...form, broker_code: e.target.value, url: b?.api_base_url ?? form.url });
                  }}
                  required
                >
                  {brokers.map((b) => <option key={b.code} value={b.code}>{b.name}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>Label</label>
                <input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })}
                  placeholder="e.g. ZKB DataLink" required />
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>Host ID</label>
                  <input value={form.host_id} onChange={(e) => setForm({ ...form, host_id: e.target.value })}
                    placeholder="ZKBKCHZZ" required />
                </div>
                <div className="form-group">
                  <label>EBICS URL (provided by the bank)</label>
                  <input value={form.url} readOnly tabIndex={-1}
                    aria-readonly="true" title="Set by the selected bank; not editable" />
                </div>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>Partner ID (Kunden-ID)</label>
                  <input value={form.partner_id} onChange={(e) => setForm({ ...form, partner_id: e.target.value })}
                    placeholder="e.g. 1234567" required />
                </div>
                <div className="form-group">
                  <label>User ID (Teilnehmer-ID)</label>
                  <input value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })}
                    placeholder="e.g. 1234567" required />
                </div>
              </div>
              <fieldset className="form-fieldset">
                <legend>Bank key pinning (optional, recommended)</legend>
                <p className="form-hint">
                  SHA-256 hashes of the bank's keys from page 2 of the letter. Leave blank to pin
                  on first connection (verify them afterwards against the letter).
                </p>
                <div className="form-group">
                  <label>Authentication (X002) hash</label>
                  <input value={form.bank_hash_auth} onChange={(e) => setForm({ ...form, bank_hash_auth: e.target.value })}
                    placeholder="03 B1 E7 F5 …" />
                </div>
                <div className="form-group">
                  <label>Encryption (E002) hash</label>
                  <input value={form.bank_hash_enc} onChange={(e) => setForm({ ...form, bank_hash_enc: e.target.value })}
                    placeholder="03 B1 E7 F5 …" />
                </div>
              </fieldset>
              <div className="form-actions">
                <button type="button" className="btn btn-ghost" onClick={() => setShowForm(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={creating}>
                  {creating ? <><Loader size={16} className="spin" /> Creating…</> : 'Create & generate keys'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {pendingDelete && (
        <div className="modal-overlay" onClick={() => setPendingDelete(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Delete credential</h3>
              <button className="btn btn-ghost" onClick={() => setPendingDelete(null)}><X size={18} /></button>
            </div>
            <p className="form-hint">
              Delete EBICS credential <strong>{pendingDelete.label}</strong>? This permanently
              removes its keys and cannot be undone. You would need a fresh key exchange with the
              bank to reconnect.
            </p>
            <div className="form-actions">
              <button className="btn btn-ghost" onClick={() => setPendingDelete(null)}>Cancel</button>
              <button className="btn btn-danger" onClick={confirmDelete}>Delete</button>
            </div>
          </div>
        </div>
      )}

      {pendingAdd && (
        <div className="modal-overlay" onClick={() => setPendingAdd(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{pendingAdd.existing ? 'Link existing account' : 'Add account'}</h3>
              <button className="btn btn-ghost" onClick={() => setPendingAdd(null)}><X size={18} /></button>
            </div>
            {pendingAdd.existing ? (
              <p className="form-hint">
                You already have an account <strong>{pendingAdd.existing.name}</strong> for
                IBAN <code>{pendingAdd.acct.iban}</code>. Link it to this EBICS credential so it
                auto-syncs from the bank? Its stored credentials (if any) are removed and it
                switches to EBICS as the source of truth. No duplicate account is created.
              </p>
            ) : (
              <p className="form-hint">
                Add a new account for IBAN <code>{pendingAdd.acct.iban}</code>
                {' '}({pendingAdd.acct.balance.toLocaleString()} {pendingAdd.acct.currency})? It
                will sync via this EBICS credential.
              </p>
            )}
            <div className="form-actions">
              <button className="btn btn-ghost" onClick={() => setPendingAdd(null)}>Cancel</button>
              <button className="btn btn-primary" onClick={confirmAdd}>
                {pendingAdd.existing ? 'Link account' : 'Add account'}
              </button>
            </div>
          </div>
        </div>
      )}

      {credentials.length === 0 && !showForm && (
        <div className="empty-state">
          {brokers.length === 0
            ? 'No EBICS-capable banks are configured.'
            : 'No EBICS credentials yet. Create one to connect a bank via EBICS.'}
        </div>
      )}

      <div className="ebics-list">
        {credentials.map((cred) => {
          const busyLabel = busy[cred.id];
          const accts = discovered[cred.id];
          return (
            <div key={cred.id} className="ebics-card">
              <div className="ebics-card-head">
                <div>
                  <h3>{cred.label}</h3>
                  <div className="ebics-meta">
                    {cred.broker_name} · Host {cred.host_id} · Partner {cred.partner_id} · User {cred.user_id}
                  </div>
                </div>
                <span className={`ebics-badge ebics-badge-${cred.state}`}>{STATE_LABEL[cred.state]}</span>
              </div>

              {cred.last_error && cred.state !== 'active' && (
                <div className="form-error" style={{ marginTop: 8 }}>{cred.last_error}</div>
              )}
              {(cred.bank_hash_auth || cred.bank_hash_enc) && (
                <div className="ebics-hashes">
                  <div><strong>Bank X002:</strong> <code>{cred.bank_hash_auth || '—'}</code></div>
                  <div><strong>Bank E002:</strong> <code>{cred.bank_hash_enc || '—'}</code></div>
                </div>
              )}

              <div className="ebics-actions">
                {(cred.state === 'new') && (
                  <button className="btn btn-primary btn-sm" disabled={!!busyLabel}
                    onClick={() => handleInitialize(cred)}>
                    <FileSignature size={15} /> Submit keys &amp; get letter
                  </button>
                )}
                {(cred.state === 'keys_sent' || cred.state === 'active' || cred.state === 'error') && (
                  <button className="btn btn-ghost btn-sm" disabled={!!busyLabel}
                    onClick={() => handleDownloadLetter(cred)}>
                    <Download size={15} /> Download letter
                  </button>
                )}
                {(cred.state === 'keys_sent' || cred.state === 'active' || cred.state === 'error') && (
                  <button className="btn btn-primary btn-sm" disabled={!!busyLabel}
                    onClick={() => handleTest(cred)}>
                    <PlugZap size={15} /> {cred.state === 'active' ? 'Re-test / discover' : 'Test connection'}
                  </button>
                )}
                <button className="btn btn-ghost btn-sm" disabled={!!busyLabel || cred.account_count > 0}
                  title={cred.account_count > 0 ? 'Remove its accounts first' : 'Delete credential'}
                  onClick={() => setPendingDelete(cred)}>
                  <Trash2 size={15} /> Delete
                </button>
                {busyLabel && <span className="ebics-busy"><Loader size={14} className="spin" /> {busyLabel}</span>}
              </div>

              {accts && (
                <div className="ebics-discovered">
                  <div className="ebics-discovered-title">Accounts at the bank</div>
                  {accts.length === 0 && <div className="form-hint">No statements were delivered.</div>}
                  {accts.map((a) => (
                    <div key={a.iban} className="ebics-acct-row">
                      <div>
                        <code>{a.iban}</code>
                        <span className="ebics-acct-bal">{a.balance.toLocaleString()} {a.currency} · {a.date}</span>
                      </div>
                      <button className="btn btn-sm btn-primary" disabled={!!busyLabel || addedIbans[a.iban]}
                        onClick={() => handleAddAccount(cred, a)}>
                        {addedIbans[a.iban] ? 'Added' : <><Plus size={14} /> Add account</>}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
