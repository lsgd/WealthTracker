# ZKB EBICS Integration Setup

This guide explains how to request EBICS access from **Zürcher Kantonalbank (ZKB)**
and configure it in Wealth Tracker.

## Overview

[ZKB](https://www.zkb.ch) is connected over **EBICS 3.0 (H005)** — the standardised
Swiss/European banking protocol — rather than a scraped web login. The integration is
**read-only**: it downloads `camt.053` end-of-day statements and records the closing
balance per IBAN.

Two properties make EBICS different from the other integrations:

- **Subscriber-level, not account-level.** One key exchange (one hand-signed
  initialisation letter) activates a subscriber at the bank, who can then read *all*
  of that subscriber's accounts. In Wealth Tracker the secret (an RSA keyring) is
  stored once as an **EBICS credential** and shared by every ZKB account you link to it.
- **A one-time paper handshake.** Before any data flows you generate a key pair, mail
  ZKB a signed initialisation letter, and wait for them to activate it. This is a
  regulatory requirement of EBICS, not a limitation of the app.

## Requirements

- A ZKB account (private or business) with **eBanking**.
- **EBICS access** requested from and activated by ZKB (see Step 1).
- The **Bankparameterdaten** (bank parameter data) that ZKB sends you: Host ID,
  Partner ID, User ID, and the bank's public-key hashes.
- The ability to **print, hand-sign, and mail** the initialisation letter.

## Step 1: Request EBICS access from ZKB

EBICS is not enabled by default. Request it through one of:

- ZKB eBanking → search/settings for **"EBICS"**, or
- The ZKB website: <https://www.zkb.ch> → Business / Payments → **EBICS**, or
- Your ZKB client advisor / the ZKB support line.

Tell them you want an **EBICS subscriber for account reporting (camt.053 / statement
download)**. For a read-only balance sync you only need download (`BTD`/statement)
permission — you do not need payment-submission rights.

ZKB then provisions a subscriber and sends you the **Bankparameterdaten** letter. It
contains everything you enter in Step 3:

| Field on the ZKB letter | Typical German label | Used as |
|---|---|---|
| Host ID | *Host-ID* | `Host ID` |
| Partner ID | *Kunden-ID* | `Partner ID` |
| User ID | *Teilnehmer-ID* | `User ID` |
| EBICS URL | *EBICS-Adresse / URL* | (configured server-side, see note) |
| Bank key hashes | *Hashwerte der Bankschlüssel* | `bank_hash_auth` / `bank_hash_enc` |

> **The EBICS URL is not entered in the UI.** Wealth Tracker pins ZKB's endpoint
> (`https://ebicsweb.zkb.ch/ebicsweb`) server-side from the broker configuration, so a
> client can't point the app at an arbitrary host. Confirm the URL on your letter
> matches; if ZKB ever changes it, update the `zkb` broker's `api_base_url`.

Example values (illustrative — **use the ones on your own letter**):

```
Host ID     : ZKBKCHZZ          # ZKB's BIC; this is public
Partner ID  : 1234567           # your Kunden-ID
User ID     : 7654321           # your Teilnehmer-ID
EBICS URL   : https://ebicsweb.zkb.ch/ebicsweb
```

## Step 2: Create the EBICS credential

In Wealth Tracker, open **EBICS bank connections** (the `Landmark` / bank icon in the
nav) and fill in **New EBICS credential**:

1. **Label** — a name for you, e.g. `ZKB DataLink`.
2. **Host ID** — from the letter (e.g. `ZKBKCHZZ`).
3. **Partner ID (Kunden-ID)** — from the letter.
4. **User ID (Teilnehmer-ID)** — from the letter.
5. **Bank key hashes** (optional) — the SHA-256 hashes of ZKB's authentication (X002)
   and encryption (E002) keys, printed on the letter. Leave blank to **pin on first
   connection** and verify them afterwards against the paper (see Step 5).

Creating the credential **generates a fresh RSA keyring server-side** and encrypts it
under your KEK (the same Fernet-under-password scheme as every other stored secret —
the server can't read it at rest without your password-derived key).

> ZKB uses a "plain keys" profile in which the **X002 (authentication) and E002
> (encryption) bank keys are identical** — so the two hashes on your letter may match.
> That is expected ZKB behaviour, not an error.

### Via API

```bash
curl -X POST http://localhost:8000/api/brokers/ebics/credentials/ \
  -H "Authorization: Bearer <your-jwt-token>" \
  -H "X-KEK: <your-kek>" \
  -H "Content-Type: application/json" \
  -d '{
    "broker_code": "zkb",
    "label": "ZKB DataLink",
    "host_id": "ZKBKCHZZ",
    "partner_id": "1234567",
    "user_id": "7654321"
  }'
```

## Step 3: Submit keys and mail the initialisation letter

Click **Submit keys & get letter** on the credential.

This sends the EBICS **INI** (signature key) and **HIA** (authentication + encryption
keys) orders to ZKB, then downloads a PDF **initialisation letter** containing the
fingerprints of the keys just sent. Then:

1. **Print** the letter.
2. **Sign it by hand.**
3. **Mail it to ZKB** at the address on the letter.

The credential moves to **Keys sent — awaiting bank activation**.

> **If ZKB reports the subscriber is already initialised (EBICS `091002`)**, the app
> stops and does **not** produce a letter. That code means ZKB still holds an earlier
> initialisation for this subscriber and silently ignored the new keys — a letter would
> carry fingerprints that can never match. Ask ZKB to **reset (delete) your EBICS
> subscriber initialisation**, then click **Submit keys & get letter** again on the
> same credential. (See "Re-initialising" below.)

## Step 4: Wait for ZKB to activate

ZKB verifies your signed letter against the keys they received and activates the
subscriber. This typically takes a few business days. There is nothing to do in the app
while you wait.

## Step 5: Test the connection and discover accounts

Once ZKB confirms activation, click **Test connection** (labelled **Re-test / discover**
after the first success).

This performs an EBICS **HPB** (fetches and pins ZKB's public keys) and a
**non-consuming** statement peek:

- If you left the hashes blank, they are **pinned on first use** — the app shows the
  pinned `auth`/`enc` hashes. **Verify them against page 2 of your paper letter** to be
  sure you're talking to ZKB and not a man-in-the-middle.
- Every IBAN found in the delivered `camt.053` is listed for you to add. The peek uses
  a negative receipt so it **does not consume** the pending statements — the first real
  sync still captures them.
- If nothing is pending (e.g. the backlog was already collected), the app **falls back
  to a dated look-back** (up to 365 days) to discover accounts from historical
  statements. Whether ZKB re-serves a past range is bank-specific.

## Step 6: Add or convert accounts

For each discovered IBAN you can:

- **Add account** — create a new Wealth Tracker account linked to this credential, or
- **Convert existing account** — adopt a manual account you already track (e.g. a
  "ZKB Lukas" balance you kept by hand). Converting stamps the IBAN and switches it to
  auto-sync while **keeping its history**.

Every add/convert asks for confirmation first. On add/convert, the app best-effort
**backfills** daily end-of-day balances from the statements already fetched: a brand-new
account is populated from the delivered range, and a converted account has its snapshots
for those days **overwritten** with the (more trustworthy) EBICS values.

## Syncing

After setup, ZKB accounts sync like any other. Each sync:

- runs HPB, downloads the pending `camt.053`, and records the **closing balance** per
  IBAN as a snapshot;
- snapshots **every delivered day**, not just the latest, so a run that covers several
  days backfills all of them;
- treats "no statement available" (EBICS `090005` — weekend/holiday, or already fetched)
  as a benign **no-op**: the account stays active and keeps its last snapshot instead of
  erroring.

## Re-initialising (bank reset)

If ZKB **resets/deletes** your subscriber (e.g. because the first handshake failed),
you do **not** need a new credential. Prerequisites before regenerating:

1. ZKB has confirmed the subscriber initialisation is **deleted** on their side.
2. Your credential still holds its keyring (it does — a keyring is generated once at
   creation and survives password changes, which only re-wrap it).
3. You are ready to print/sign/mail a fresh letter.

Then click **Submit keys & get letter** again to re-send INI/HIA and get a new letter.
The freshly submitted keys must match the letter you mail — so always mail the letter
produced by that same click, not an older one.

## Troubleshooting

### "Submit keys" fails with `091002` (subscriber already initialised)
ZKB still holds an earlier initialisation. Ask ZKB to reset (delete) your EBICS
subscriber, then submit keys again. See "Re-initialising".

### "Test connection" reports 0 accounts
The pending backlog may already have been consumed. The app automatically retries with
a dated look-back; if that's still empty, ZKB isn't re-serving a past range. Wait for
the next end-of-day statement, or ask ZKB whether download reporting (camt.053) is
enabled for your subscriber.

### Pinned hashes don't match the letter
**Stop.** A hash mismatch means the keys the app received are not the ones ZKB printed.
Do not proceed — re-check with ZKB before trusting the connection.

### Balance looks wrong-signed
`camt.053` reports an amount plus a CRDT/DBIT indicator; the app folds that into a signed
balance (a debit balance is negative). An overdraft therefore shows as a negative number,
which is correct.

## Security Considerations

1. **The RSA keyring is the only real secret** and is stored Fernet-encrypted under your
   password-derived KEK — the server can't decrypt it at rest without your password.
2. **Connection identifiers and bank-key hashes are non-secret** (they're printed on the
   paper letter) and stored as plain columns so credentials can be listed without a KEK.
3. **The EBICS endpoint is pinned server-side** from the broker config; clients cannot
   redirect the app to another host.
4. **Bank keys are pinned** and verified on every connection (HPB), so a swapped bank key
   is detected.
5. **Read-only:** the subscriber is set up for statement download, not payment submission.

## What Data is Fetched

| Data | Description |
|------|-------------|
| **Closing balance** | End-of-day balance per IBAN, from `camt.053` |
| **Currency** | Statement currency (typically CHF) |
| **Balance date** | The statement's closing-balance date |
| **Daily history** | Every end-of-day statement in a delivery (for backfill) |

Positions/holdings are **not** provided — EBICS `camt.053` is a cash-statement feed, so
ZKB accounts report a balance only.

## EBICS Orders Used

| Order | Purpose |
|-------|---------|
| `INI` | Send the subscriber signature key |
| `HIA` | Send the authentication + encryption keys |
| `HPB` | Fetch and pin the bank's public keys |
| `BTD` (camt.053) | Download end-of-day statements |

## Sources

- [ZKB website](https://www.zkb.ch)
- ZKB EBICS endpoint: `https://ebicsweb.zkb.ch/ebicsweb`
- [EBICS specification](https://www.ebics.org)
