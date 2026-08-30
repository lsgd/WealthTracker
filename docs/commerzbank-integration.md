# Commerzbank

**Status: manual account. Automated sync is not viable and will not be built.**

Commerzbank is configured as a FinTS broker (`integration_type: fints`, BLZ
`16040000`, `https://fints.commerzbank.de/fints`) and the login itself works.
The blocker is the second factor, not the protocol.

## What the bank actually offers over FinTS

A dialog against Commerzbank advertises exactly one TAN mechanism:

```
'900': TwoStepParameters6(
    security_function='900', tan_process='2', tech_id='MS1.4.1',
    name='photoTAN', text_return_value='photoTAN-Grafik',
    max_length_input=10, allowed_format=ALPHANUMERIC,
    challenge_structured=True, supported_media_number=1)
```

`decoupled=False`. There is no push/decoupled variant on this channel.

This matters because the tap-to-confirm prompt Commerzbank sends on **web
portal** login is their own frontend's flow, not something FinTS exposes.
Sparkasse-style pushTAN and DKB's TAN2go are decoupled mechanisms that
`FinTSIntegration.authenticate()` already prefers and polls for
(`fints_integration.py`, the `['940', '942', '944', ...]` preference list).
Commerzbank offers none of them, so that path can never engage — the code
correctly falls through to `No decoupled TAN found, using first mechanism: 900`.

Answering mechanism 900 means scanning a mosaic graphic with the photoTAN app
and typing back the TAN it computes. There is no variant that avoids the camera:
the photoTAN reader device is also scan-based, and smsTAN has been retired.

## Why scanning doesn't rescue it

The photoTAN app's scanner is camera-only. When a sync is triggered from the
phone, the mosaic renders on the same screen that would have to scan it, so the
challenge is unanswerable by construction. That confines any scan-based flow to
"sit at a desktop, scan with your phone, every single sync" — which fails the
project's own app-vs-web split, since syncing is a routine action and routine
actions belong in the app.

It also means `supports_auto_sync` must stay `false`: an unattended or scheduled
run would stall on a challenge with nobody holding a camera.

## Decision

The account stays a **Commerzbank** account — that is what identifies it and its
CSV export format — but the broker is marked as non-syncing, so it behaves like a
manual one everywhere.

`Broker.supports_sync` is the flag: `supports_auto_sync or code in
INTERACTIVE_BROKER_CODES`. It distinguishes "cannot finish unattended" (an
interactive broker still fetches, it just stops for a code) from "never fetches
at all", which is Commerzbank. With `supports_auto_sync: false` in the fixture
and no interactive entry, `supports_sync` is false and:

- the sync button, the credential form and the "Fetch from bank" backfill picker
  disappear from the web UI (`brokerCanSync()` in `api/client.ts`);
- the app already hid them — `Account.canSync` has always been
  `supportsAutoSync || requiresInteractiveSync`;
- adding an account picks the manual form instead of asking for credentials;
- the sync, backfill and credential-write endpoints reject it with an
  explanation rather than starting a login nobody can complete;
- "Sync all" filters on `broker__supports_auto_sync=True`, so it is skipped.

What remains:

- **Balances** — entered by hand via the "Add Snapshot" (+) action on the
  account row. That button is not gated on `is_manual`, so it works either way.
- **Transactions** — imported from the bank's CSV export at
  `/spending?tab=config` → *Import history* → *Import CSV export*. The parser
  already recognises the format (`csv_import.py`, `_parse_commerzbank`): header
  row one (`Buchungstag;…`), German number format, own IBAN per row under "IBAN
  Kontoinhaber" for account auto-matching, counterparty IBAN extracted from the
  booking text so transfer detection can pair entries, and content-hash dedup
  since Commerzbank sends no unique bank reference. Re-importing an overlapping
  file changes nothing.

Because the export carries its own IBAN, `TransactionCsvImportView` resolves the
target account purely from `account_identifier`. Keep the account's identifier
set to the IBAN and the import lands on it; the broker only matters as a
fallback, for formats whose export names no account.

## Known defects, if anyone revisits this

Three separate bugs sit on the sync path. None are worth fixing for a manual
account, but they are real and would need addressing before any scan flow works:

1. **The sync path discards the challenge.** `_sync_all_accounts` and
   `_sync_single_account` put only `id`, `name` and `two_fa_type` into the
   `pending_2fa` payload — `auth_result.challenge_data` is dropped, so the
   photoTAN graphic never leaves the server. The discovery path
   (`AddAccountModal`) does pass and render it, which is why connecting an
   account works but syncing it doesn't.
2. **The frontend couldn't render it anyway.** `AccountsTable` reads
   `result.challenge?.message`, a key FinTS never sends (it sends `challenge`,
   `challenge_html`, `challenge_hhduc`), and `TwoFactorModal`'s `AuthPrompt` has
   no field for `challenge_html`. The result is a modal asking for a code from
   an "authenticator app" that does not exist. `SpendingPage` has the same
   mapping bug on the backfill path.
3. **The TAN would be rejected even if shown.** `requires_reauth_before_2fa()`
   defaults to `True`, so `AccountAuthView` re-runs `authenticate()` before
   answering — Commerzbank issues a *fresh* graphic, and the TAN scanned from
   the previous one is validated against the new challenge. The docstring's
   "stateless protocol" assumption holds for a TAN list, not for a
   challenge-bound photoTAN. `FinTSIntegration.get_pause_state()` and
   `restore_from_pause()` exist for exactly this and are called from nowhere;
   wiring them into `pending_auth_state` is the fix.

A fourth, smaller one: `TwoFactorModal` hardcodes `maxLength={6}` and
`disabled={code.length < 6}`, while mechanism 900 declares
`max_length_input=10, allowed_format=ALPHANUMERIC`.

## Rejected alternative

Enrolling a virtual photoTAN device from the activation letter and deriving TANs
server-side would give genuinely headless sync. Rejected: substantial crypto
work, Commerzbank's terms expect the device key to stay device-bound, and it
would put a transfer-authorising secret in the credential store.
