import { useState, useEffect, useRef } from 'react';
import { Upload, X } from 'lucide-react';
import { importTransactionsCsv } from '../api/client';

interface Props {
  accountId: number;
  accountName: string;
  onClose: () => void;
  onImported: () => void;
}

/**
 * Import a bank CSV export (ZKB "with details" or DKB, auto-detected) as
 * transactions of one account. Idempotent server-side: re-importing an
 * overlapping file changes nothing.
 */
export default function TransactionCsvImportModal({
  accountId,
  accountName,
  onClose,
  onImported,
}: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const handleImport = async () => {
    if (!file) return;
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const outcome = await importTransactionsCsv(file, accountId);
      setNotice(outcome.message || `${outcome.imported ?? 0} new transactions imported`);
      setFile(null);
      if (inputRef.current) inputRef.current.value = '';
      onImported();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'CSV import failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Import Transactions - {accountName}</h3>
          <button className="btn btn-ghost" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        {error && <div className="form-error">{error}</div>}
        <p className="form-hint">
          A per-account CSV export from the bank&apos;s online banking — ZKB
          (&quot;with details&quot; export) and DKB are recognized automatically.
          Re-importing an overlapping file changes nothing, so it is safe to
          retry.
        </p>
        <div className="form-group">
          <label htmlFor="tx-csv-file">CSV file</label>
          <input
            ref={inputRef}
            id="tx-csv-file"
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
        {notice && <p className="form-hint">{notice}</p>}
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Close
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleImport}
            disabled={busy || !file}
          >
            <Upload size={14} /> {busy ? 'Importing…' : 'Import'}
          </button>
        </div>
      </div>
    </div>
  );
}
