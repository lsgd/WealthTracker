import { useState } from 'react';
import { Key, X } from 'lucide-react';

export interface AuthPrompt {
  accountId: number;
  accountName: string;
  twoFaType: string;
  // What the broker said about the challenge, e.g. the masked phone number
  // an SMS code was sent to.
  challenge?: string;
}

interface Props {
  prompt: AuthPrompt;
  /** What the code unlocks, e.g. "sync" or "fetch transactions for". */
  purpose?: string;
  submitLabel?: string;
  /** Rejects with the message to show inside the modal; resolves on success. */
  onSubmit: (code: string) => Promise<void>;
  onClose: () => void;
}

/**
 * Asks for the one-time code a broker just challenged with.
 *
 * Shared by the account list (sync) and the spending page (transaction
 * backfill): both hit the same endpoint, and an SMS code is only valid for the
 * minute it arrives in, so every flow that can trigger one must be able to ask.
 */
export default function TwoFactorModal({
  prompt,
  purpose = 'sync',
  submitLabel = 'Verify & Sync',
  onSubmit,
  onClose,
}: Props) {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    setSubmitting(true);
    setError('');
    try {
      await onSubmit(code.trim());
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'Authentication failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>
            <Key size={18} style={{ marginRight: 8 }} />
            Authentication Required
          </h3>
          <button className="btn btn-ghost" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {error && <div className="form-error">{error}</div>}

        <form onSubmit={handleSubmit}>
          <p className="form-hint" style={{ marginBottom: 16 }}>
            {prompt.challenge
              || (prompt.twoFaType === 'sms'
                ? 'Enter the code the bank just sent you by SMS'
                : 'Enter the one-time code from your authenticator app')}
            {` to ${purpose} `}
            <strong>{prompt.accountName}</strong>.
          </p>

          <div className="form-group">
            <label htmlFor="auth-code">
              {prompt.twoFaType === 'totp' ? 'TOTP Code'
                : prompt.twoFaType === 'sms' ? 'SMS Code'
                : 'Authentication Code'}
            </label>
            <input
              id="auth-code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="Enter 6-digit code"
              maxLength={6}
            />
          </div>

          <div className="form-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting || code.length < 6}
            >
              {submitting ? 'Verifying...' : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
