import { argon2id } from 'hash-wasm';

const TOKEN_KEY = 'wealth_access_token';
const REFRESH_KEY = 'wealth_refresh_token';
const KEK_KEY = 'wealth_kek';
const AUTH_SALT_KEY = 'wealth_auth_salt';
const KEK_SALT_KEY = 'wealth_kek_salt';

// Argon2 parameters (must match server expectations)
const ARGON2_TIME_COST = 3;
const ARGON2_MEMORY_COST = 65536; // 64 MB
const ARGON2_PARALLELISM = 4;
const ARGON2_HASH_LEN = 32;

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem(TOKEN_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  // Also clear KEK and salts on logout
  sessionStorage.removeItem(KEK_KEY);
  sessionStorage.removeItem(AUTH_SALT_KEY);
  sessionStorage.removeItem(KEK_SALT_KEY);
}

// KEK Management
export function getKEK(): string | null {
  return sessionStorage.getItem(KEK_KEY);
}

export function setKEK(kek: string) {
  sessionStorage.setItem(KEK_KEY, kek);
}

export function setSalts(authSalt: string, kekSalt: string) {
  sessionStorage.setItem(AUTH_SALT_KEY, authSalt);
  sessionStorage.setItem(KEK_SALT_KEY, kekSalt);
}

export function getSalts(): { authSalt: string | null; kekSalt: string | null } {
  return {
    authSalt: sessionStorage.getItem(AUTH_SALT_KEY),
    kekSalt: sessionStorage.getItem(KEK_SALT_KEY),
  };
}

// Crypto utilities
function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

async function deriveKey(password: string, salt: string): Promise<Uint8Array> {
  const saltBytes = base64ToBytes(salt);
  const hash = await argon2id({
    password,
    salt: saltBytes,
    iterations: ARGON2_TIME_COST,
    memorySize: ARGON2_MEMORY_COST,
    parallelism: ARGON2_PARALLELISM,
    hashLength: ARGON2_HASH_LEN,
    outputType: 'binary',
  });
  return hash;
}

async function refreshAccessToken(): Promise<string | null> {
  const refresh = localStorage.getItem(REFRESH_KEY);
  if (!refresh) return null;

  const res = await fetch('/api/auth/refresh/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
    credentials: 'include',
  });

  if (!res.ok) {
    clearTokens();
    return null;
  }

  const data = await res.json();
  setTokens(data.access, data.refresh ?? refresh);
  return data.access;
}

// KEK recovery: the KEK lives in sessionStorage and is wiped when the tab closes
// (or never set in a tab that got its token from another tab / a refresh). The
// access token persists in localStorage, so the user looks logged in but
// encrypted operations 403 with "KEK required". A handler (registered by the
// UI) re-prompts for the password, re-derives the KEK, and we retry once. The
// in-flight promise is shared so concurrent 403s trigger a single prompt.
type KekRecoveryHandler = () => Promise<boolean>;
let kekRecoveryHandler: KekRecoveryHandler | null = null;
let kekRecoveryInFlight: Promise<boolean> | null = null;

export function setKekRecoveryHandler(fn: KekRecoveryHandler | null) {
  kekRecoveryHandler = fn;
}

function isKekRequired(body: unknown): boolean {
  const detail = (body as { detail?: unknown } | null)?.detail;
  return typeof detail === 'string' && /KEK required/i.test(detail);
}

function recoverKek(): Promise<boolean> {
  if (!kekRecoveryHandler) return Promise.resolve(false);
  if (!kekRecoveryInFlight) {
    kekRecoveryInFlight = Promise.resolve(kekRecoveryHandler())
      .catch(() => false)
      .finally(() => { kekRecoveryInFlight = null; }) as Promise<boolean>;
  }
  return kekRecoveryInFlight;
}

export async function fetchWithAuth(
  url: string,
  options: RequestInit = {},
): Promise<Response> {
  const token = getAccessToken();
  const kek = getKEK();

  const headers: Record<string, string> = {
    // FormData bodies must set their own multipart boundary — forcing JSON
    // here would break file uploads.
    ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    ...(options.headers as Record<string, string> ?? {}),
  };

  if (token) {
    // Use X-Auth-Token to avoid conflict with HTTP Basic Auth's Authorization header
    headers['X-Auth-Token'] = `Bearer ${token}`;
  }

  // Add KEK header for encrypted operations (migrated users)
  if (kek) {
    headers['X-KEK'] = kek;
  }

  let res = await fetch(url, { ...options, headers, credentials: 'include' });

  if (res.status === 401 && token) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      headers['X-Auth-Token'] = `Bearer ${newToken}`;
      res = await fetch(url, { ...options, headers, credentials: 'include' });
    }
  }

  // Missing KEK (sessionStorage wiped, token still valid): recover and retry once.
  if (res.status === 403 && kekRecoveryHandler) {
    const peeked = await res.clone().json().catch(() => null);
    if (isKekRequired(peeked) && await recoverKek()) {
      const freshToken = getAccessToken();
      if (freshToken) headers['X-Auth-Token'] = `Bearer ${freshToken}`;
      const freshKek = getKEK();
      if (freshKek) headers['X-KEK'] = freshKek;
      res = await fetch(url, { ...options, headers, credentials: 'include' });
    }
  }

  return res;
}

// Auth API

// Get salts for a user (for key derivation)
async function getSaltsFromServer(username: string): Promise<{
  auth_salt: string;
  kek_salt: string;
  migrated: boolean;
}> {
  const res = await fetch(`/api/auth/salt/?username=${encodeURIComponent(username)}`, {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error('Failed to get salts');
  }
  return res.json();
}

export async function login(username: string, password: string) {
  // 1. Get salts from server
  const { auth_salt, kek_salt, migrated } = await getSaltsFromServer(username);

  let loginPayload: { username: string; password?: string; auth_hash?: string };

  if (migrated) {
    // 2a. User is migrated - derive auth_hash and KEK client-side
    const authHashBytes = await deriveKey(password, auth_salt);
    const kekBytes = await deriveKey(password, kek_salt);

    const authHash = bytesToBase64(authHashBytes);
    const kek = bytesToBase64(kekBytes);

    loginPayload = { username, auth_hash: authHash };

    // 3. Login with auth_hash
    const res = await fetch('/api/auth/login/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(loginPayload),
      credentials: 'include',
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || data.detail || 'Login failed');
    }

    const data = await res.json();
    setTokens(data.access, data.refresh);

    // Store KEK and salts for encrypted operations
    setKEK(kek);
    setSalts(auth_salt, kek_salt);

    return data;
  } else {
    // 2b. User not migrated - use legacy password auth
    const res = await fetch('/api/auth/login/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      credentials: 'include',
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || data.detail || 'Login failed');
    }

    const data = await res.json();
    setTokens(data.access, data.refresh);

    // Store salts for potential migration
    setSalts(auth_salt, kek_salt);

    // If user needs to set up encryption, derive and store KEK
    if (!data.encryption_migrated) {
      const kekBytes = await deriveKey(password, kek_salt);
      const kek = bytesToBase64(kekBytes);
      setKEK(kek);

      // Derive auth_hash for setup
      const authHashBytes = await deriveKey(password, auth_salt);
      const authHash = bytesToBase64(authHashBytes);

      // Auto-setup encryption for the user
      await setupEncryption(kek, authHash, auth_salt, kek_salt);
    }

    return data;
  }
}

// Set up per-user encryption (for migration)
export async function setupEncryption(
  kek: string,
  authHash: string,
  authSalt: string,
  kekSalt: string,
) {
  const res = await fetchWithAuth('/api/auth/setup-encryption/', {
    method: 'POST',
    body: JSON.stringify({
      kek,
      auth_hash: authHash,
      auth_salt: authSalt,
      kek_salt: kekSalt,
    }),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || 'Failed to setup encryption');
  }

  return res.json();
}

export async function register(fields: {
  username: string;
  email: string;
  password: string;
  password_confirm: string;
  base_currency: string;
}) {
  const res = await fetch('/api/auth/register/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
    credentials: 'include',
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const msg = Object.values(data).flat().join(' ') || 'Registration failed';
    throw new Error(msg);
  }
  const data = await res.json();
  if (data.tokens) {
    setTokens(data.tokens.access, data.tokens.refresh);
  }
  return data;
}

export async function getCurrentUser() {
  const res = await fetchWithAuth('/api/auth/me/');
  if (!res.ok) throw new Error('Not authenticated');
  return res.json();
}

// Wealth API
export async function getWealthSummary() {
  const res = await fetchWithAuth('/api/wealth/summary/');
  if (!res.ok) throw new Error('Failed to fetch summary');
  return res.json();
}

export async function getWealthHistory(days: number, granularity: 'daily' | 'monthly' = 'daily') {
  const res = await fetchWithAuth(`/api/wealth/history/?days=${days}&granularity=${granularity}`);
  if (!res.ok) throw new Error('Failed to fetch history');
  return res.json();
}

export async function getWealthBreakdown(by: string) {
  const res = await fetchWithAuth(`/api/wealth/breakdown/?by=${by}`);
  if (!res.ok) throw new Error('Failed to fetch breakdown');
  return res.json();
}

export interface Holding {
  isin: string;
  symbol: string;
  name: string;
  asset_class: string;
  quantity: number;
  value_base_currency: number;
  price_base_currency: number | null;
  percentage: number;
  accounts: string[];
}

export interface HoldingsReport {
  base_currency: string;
  as_of: string | null;
  total: number;
  holdings: Holding[];
  by_asset_class: { asset_class: string; amount: number; percentage: number }[];
}

export async function getWealthHoldings(): Promise<HoldingsReport> {
  const res = await fetchWithAuth('/api/wealth/holdings/');
  if (!res.ok) throw new Error('Failed to fetch holdings');
  return res.json();
}

// Monte Carlo wealth simulation

export interface SimulationBand {
  year: number;
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
}

export interface SimulationParameter {
  value: number;
  derived: boolean;
}

export interface SimulationResult {
  years: number;
  paths: number;
  base_currency: string;
  bands: SimulationBand[];
  parameters: Record<string, SimulationParameter>;
  asset_class_weights: Record<string, number>;
  target?: {
    amount: number;
    probability: number;
    probability_by_year?: number[];
    median_reached_year: number | null;
  };
}

/**
 * Only send parameters the user explicitly changed: the server persists sent
 * parameters as overrides on the profile, an empty-string value clears an
 * override, and unsent parameters are re-derived fresh (stored override first).
 */
export type SimulationParams = Record<string, number | string>;

export async function getWealthSimulation(
  params: SimulationParams = {},
): Promise<SimulationResult> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    query.set(key, String(value));
  }
  const qs = query.toString();
  const res = await fetchWithAuth(`/api/wealth/simulation/${qs ? `?${qs}` : ''}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((data as { error?: string }).error || 'Simulation failed');
  }
  return data;
}

// Broker API
export interface Broker {
  id: number;
  code: string;
  name: string;
  integration_type: string;
  country: string;
  is_active: boolean;
  supports_2fa: boolean;
  supports_auto_sync: boolean;
  credential_schema: Record<string, unknown>;
  logo_url?: string;
  website_url?: string;
  api_base_url?: string;
}

// DRF list endpoints are paginated ({count, next, previous, results}). Unwrap to a
// plain array (tolerating a bare array too) so callers never touch pagination.
function unwrapResults<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  const results = (data as { results?: unknown } | null)?.results;
  return Array.isArray(results) ? (results as T[]) : [];
}

// Returns a plain Broker[] regardless of pagination. Use this, not a raw fetch:
// callers that assumed an array crashed on the paginated object.
export async function getBrokersList<T = Broker>(): Promise<T[]> {
  const res = await fetchWithAuth('/api/brokers/');
  if (!res.ok) throw new Error('Failed to fetch brokers');
  return unwrapResults<T>(await res.json());
}

export async function discoverAccounts(brokerCode: string, credentials: Record<string, string>) {
  const res = await fetchWithAuth('/api/brokers/discover/', {
    method: 'POST',
    body: JSON.stringify({ broker_code: brokerCode, credentials }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || 'Discovery failed');
  }
  return data;
}

export async function completeDiscoveryAuth(sessionToken: string, authCode: string) {
  const res = await fetchWithAuth('/api/brokers/discover/complete-auth/', {
    method: 'POST',
    body: JSON.stringify({ session_token: sessionToken, auth_code: authCode }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || 'Authentication failed');
  }
  return data;
}

export async function createAccountsBulk(
  brokerCode: string,
  credentials: Record<string, string>,
  accounts: { identifier: string; name: string; account_type: string; currency: string; balance?: number | null; balance_date?: string }[],
) {
  const res = await fetchWithAuth('/api/accounts/bulk/', {
    method: 'POST',
    body: JSON.stringify({ broker_code: brokerCode, credentials, accounts }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || 'Failed to create accounts');
  }
  return res.json();
}

// Account API
export async function getAccounts() {
  const res = await fetchWithAuth('/api/accounts/');
  if (!res.ok) throw new Error('Failed to fetch accounts');
  return res.json();
}

export async function createAccount(fields: {
  name: string;
  broker_code: string;
  account_identifier?: string;
  account_type: string;
  currency: string;
  is_manual: boolean;
  credentials?: Record<string, string>;
  ebics_credential_id?: number;
}) {
  const res = await fetchWithAuth('/api/accounts/', {
    method: 'POST',
    body: JSON.stringify(fields),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const msg = Object.values(data).flat().join(' ') || 'Failed to create account';
    throw new Error(msg);
  }
  return res.json();
}

export async function getSyncTaskStatus(taskId: string) {
  const res = await fetchWithAuth(`/api/accounts/sync/${taskId}/`);
  if (!res.ok) throw new Error('Failed to get sync status');
  return res.json();
}

// The sync runs on a background worker thread; the POST returns immediately with
// {status:'queued', task_id}. Poll the task to completion and resolve with the
// real outcome ({status:'success'|'pending_auth'|'error', ...}) so the UI reflects
// the actual result instead of refreshing stale data mid-sync.
async function pollSyncTask(
  taskId: string,
  { timeoutMs = 180_000, intervalMs = 1500 } = {},
) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, intervalMs));
    let task;
    try {
      task = await getSyncTaskStatus(taskId);
    } catch {
      continue; // transient (e.g. brief 404 before the task registers) — keep polling
    }
    if (task.status === 'completed') {
      return task.result ?? { status: 'success' };
    }
    if (task.status === 'failed') {
      return { status: 'error', error: task.error || 'Sync failed' };
    }
    // 'pending' / 'running' — keep polling
  }
  return { status: 'error', error: 'Sync timed out' };
}

export async function syncAccount(accountId: number) {
  const res = await fetchWithAuth(`/api/accounts/${accountId}/sync/`, {
    method: 'POST',
  });
  const data = await res.json();
  if (!res.ok && !data.status) {
    throw new Error(data.error || 'Sync failed');
  }
  // Async queue: wait for the worker to finish, then return the real outcome.
  if (data.status === 'queued' && data.task_id) {
    return pollSyncTask(data.task_id);
  }
  return data;
}

export async function completeAccountAuth(accountId: number, authCode: string) {
  const res = await fetchWithAuth(`/api/accounts/${accountId}/auth/`, {
    method: 'POST',
    body: JSON.stringify({ auth_code: authCode }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || 'Authentication failed');
  }
  return data;
}

export async function addSnapshot(
  accountId: number,
  balance: number,
  currency: string,
  snapshotDate: string,
) {
  const res = await fetchWithAuth(`/api/accounts/${accountId}/snapshots/`, {
    method: 'POST',
    body: JSON.stringify({
      balance,
      currency,
      snapshot_date: snapshotDate,
    }),
  });
  if (!res.ok) throw new Error('Failed to add snapshot');
  return res.json();
}

export async function getSnapshots(accountId: number, page = 1) {
  const url = `/api/accounts/${accountId}/snapshots/${page > 1 ? `?page=${page}` : ''}`;
  const res = await fetchWithAuth(url);
  if (!res.ok) throw new Error('Failed to fetch snapshots');
  return res.json();
}

export async function updateSnapshot(
  snapshotId: number,
  balance: number,
  currency: string,
  snapshotDate: string,
) {
  const res = await fetchWithAuth(`/api/snapshots/${snapshotId}/`, {
    method: 'PUT',
    body: JSON.stringify({
      balance,
      currency,
      snapshot_date: snapshotDate,
    }),
  });
  if (!res.ok) throw new Error('Failed to update snapshot');
  return res.json();
}

export async function deleteSnapshot(snapshotId: number) {
  const res = await fetchWithAuth(`/api/snapshots/${snapshotId}/`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || 'Failed to delete snapshot');
  }
}

export async function updateAccount(
  accountId: number,
  fields: {
    name?: string;
    sync_enabled?: boolean;
    broker_code?: string;
    is_manual?: boolean;
    account_identifier?: string;
    account_type?: string;
    currency?: string;
    notes?: string;
  },
) {
  const res = await fetchWithAuth(`/api/accounts/${accountId}/`, {
    method: 'PATCH',
    body: JSON.stringify(fields),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || 'Failed to update account');
  }
  return res.json();
}

export async function deleteAccount(accountId: number) {
  const res = await fetchWithAuth(`/api/accounts/${accountId}/`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || 'Failed to delete account');
  }
}

export async function getAccountCredentials(accountId: number) {
  const res = await fetchWithAuth(`/api/accounts/${accountId}/credentials/`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || 'Failed to fetch credentials');
  }
  return res.json();
}

export async function updateAccountCredentials(
  accountId: number,
  credentials: Record<string, string>,
) {
  const res = await fetchWithAuth(`/api/accounts/${accountId}/credentials/`, {
    method: 'PUT',
    body: JSON.stringify({ credentials }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || 'Failed to update credentials');
  }
  return res.json();
}

export async function getBroker(brokerCode: string) {
  const res = await fetchWithAuth(`/api/brokers/${brokerCode}/`);
  if (!res.ok) throw new Error('Failed to fetch broker');
  return res.json();
}

// EBICS credential API (e.g. ZKB). Subscriber-level credentials shared across
// accounts. All go through fetchWithAuth, so X-KEK + KEK-recovery are automatic.
export interface EbicsCredential {
  id: number;
  label: string;
  broker_code: string;
  broker_name: string;
  host_id: string;
  partner_id: string;
  user_id: string;
  url: string;
  bank_hash_auth: string;
  bank_hash_enc: string;
  state: 'new' | 'keys_sent' | 'active' | 'error';
  last_error: string;
  initialized: boolean;
  account_count: number;
  created_at: string;
  updated_at: string;
}

export interface EbicsLetter {
  media_type: string;
  filename: string;
  content_base64: string;
}

export interface EbicsDiscoveredAccount {
  iban: string;
  currency: string;
  balance: number;
  date: string;
}

export async function getEbicsCredentials(): Promise<EbicsCredential[]> {
  const res = await fetchWithAuth('/api/ebics/credentials/');
  if (!res.ok) throw new Error('Failed to fetch EBICS credentials');
  return res.json();
}

export async function createEbicsCredential(fields: {
  broker_code: string;
  label: string;
  host_id: string;
  partner_id: string;
  user_id: string;
  bank_hash_auth?: string;
  bank_hash_enc?: string;
}): Promise<EbicsCredential> {
  const res = await fetchWithAuth('/api/ebics/credentials/', {
    method: 'POST',
    body: JSON.stringify(fields),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to create EBICS credential');
  return data;
}

// Link (adopt) an existing account into this EBICS credential for the given IBAN —
// converts a manual/other-broker account in place, keeping its history.
export async function linkEbicsAccount(credentialId: number, accountId: number, iban: string) {
  const res = await fetchWithAuth(`/api/ebics/credentials/${credentialId}/link-account/`, {
    method: 'POST',
    body: JSON.stringify({ account_id: accountId, iban }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Failed to link account');
  return data;
}

// Backfill historical daily snapshots for a credential's account(s) via a dated,
// non-consuming EBICS download. Best-effort — the bank may not re-serve past data.
export async function backfillEbicsCredential(
  credentialId: number,
  opts: { accountId?: number; days?: number } = {},
): Promise<{ status: string; backfilled: number; message: string }> {
  const res = await fetchWithAuth(`/api/ebics/credentials/${credentialId}/backfill/`, {
    method: 'POST',
    body: JSON.stringify({ account_id: opts.accountId, days: opts.days }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Backfill failed');
  return data;
}

export async function deleteEbicsCredential(id: number): Promise<void> {
  const res = await fetchWithAuth(`/api/ebics/credentials/${id}/`, { method: 'DELETE' });
  if (!res.ok && res.status !== 204) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || 'Failed to delete EBICS credential');
  }
}

// Send INI + HIA and get the initialisation letter to print, sign and mail.
export async function initializeEbicsCredential(
  id: number,
): Promise<{ status: string; ini: string; hia: string; letter: EbicsLetter; message: string }> {
  const res = await fetchWithAuth(`/api/ebics/credentials/${id}/initialize/`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) {
    const msg = data.hint ? `${data.error} ${data.hint}` : (data.error || 'Key submission failed');
    throw new Error(msg);
  }
  return data;
}

export async function getEbicsLetter(id: number): Promise<EbicsLetter> {
  const res = await fetchWithAuth(`/api/ebics/credentials/${id}/letter/`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to render letter');
  return data.letter;
}

// Verify activation: HPB + camt.053 download; returns discovered IBANs.
export async function testEbicsCredential(
  id: number,
): Promise<{ status: string; bank_key_hashes: { auth: string; enc: string }; bank_key_hashes_recorded: boolean; accounts: EbicsDiscoveredAccount[]; message: string }> {
  const res = await fetchWithAuth(`/api/ebics/credentials/${id}/test/`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Connection test failed');
  return data;
}

// Trigger a browser download of a base64-encoded letter (PDF or HTML).
export function downloadEbicsLetter(letter: EbicsLetter) {
  const bytes = base64ToBytes(letter.content_base64);
  const blob = new Blob([bytes as BlobPart], { type: letter.media_type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = letter.filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// CSV Import
export async function importCSV(
  accountId: number,
  csvData: string,
  skipDuplicates: boolean = true,
) {
  const res = await fetchWithAuth('/api/import/csv/', {
    method: 'POST',
    body: JSON.stringify({
      account_id: accountId,
      csv_data: csvData,
      skip_duplicates: skipDuplicates,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || 'Import failed');
  }
  return data;
}

// Spending / transactions API

export interface TransactionCategory {
  id: number;
  name: string;
  // Monthly spending target in the base currency; null when none is set.
  monthly_budget: string | null;
}

export interface CategoryRule {
  id: number;
  match_text: string;
  category: number | null;
  category_name: string | null;
  spread_months: number;
  position: number;
  is_regex: boolean;
  // Transfer rules mark matches as transfers instead of categorizing them.
  is_transfer: boolean;
}

export interface Transaction {
  id: number;
  account: number;
  booking_date: string;
  value_date: string | null;
  amount: string;
  currency: string;
  counterparty: string;
  counterparty_account: string;
  description: string;
  source: string;
  external_id: string;
  category: number | null;
  category_name: string | null;
  spread_months: number;
  is_transfer: boolean;
  // How much of a spread transaction the listed period actually counts. Only
  // set when the list is filtered to a period and showing the normalized
  // view — the case where the row's own amount is not what the chart used.
  period_slice: { months: number; of: number; amount: string } | null;
  created_at: string;
  // Only on the response to a classification change: the rule that classifies
  // this transaction and now disagrees with what was just set.
  stale_rule?: CategoryRule;
}

export interface SpendingMonth {
  month: string;
  income: number;
  expenses: number;
  net: number;
  by_category: Record<string, number>;
}

export interface SpendingReport {
  mode: 'normalized' | 'actual';
  granularity?: 'month' | 'quarter' | 'year';
  base_currency: string;
  categories: string[];
  // Per category, already scaled to one period of this granularity.
  budgets?: Record<string, number>;
  // One entry per period; still called months for older app builds.
  months: SpendingMonth[];
}

// `months` counts periods of the requested granularity: 12 months, 8 quarters,
// 5 years. The response keeps calling them months for older app builds.
export async function getSpendingMonthly(
  months: number,
  mode: 'normalized' | 'actual',
  granularity: 'month' | 'quarter' | 'year' = 'month',
): Promise<SpendingReport> {
  const res = await fetchWithAuth(
    `/api/spending/monthly/?months=${months}&mode=${mode}&granularity=${granularity}`);
  if (!res.ok) throw new Error('Failed to fetch spending report');
  return res.json();
}

// Sorted here rather than trusting the server's ORDER BY: only the browser
// knows where "Ärzte" belongs (with A, not after Z, which is where every
// byte-wise collation puts it). Sorting at the single fetch point keeps every
// dropdown, sheet and list in the same order.
export const compareCategoryNames = (a: string, b: string) =>
  a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });

export async function getCategories(): Promise<TransactionCategory[]> {
  const res = await fetchWithAuth('/api/spending/categories/');
  if (!res.ok) throw new Error('Failed to fetch categories');
  return unwrapResults<TransactionCategory>(await res.json())
    .sort((a, b) => compareCategoryNames(a.name, b.name));
}

export async function createCategory(name: string): Promise<TransactionCategory> {
  const res = await fetchWithAuth('/api/spending/categories/', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(Object.values(data).flat().join(' ') || 'Failed to create category');
  }
  return data;
}

export async function getCategoryRules(): Promise<CategoryRule[]> {
  const res = await fetchWithAuth('/api/spending/rules/');
  if (!res.ok) throw new Error('Failed to fetch rules');
  return unwrapResults<CategoryRule>(await res.json());
}

// Creating a rule also applies it retroactively to uncategorized transactions.
/** Set a category's monthly budget; null clears it. */
export async function setCategoryBudget(
  categoryId: number,
  monthlyBudget: number | null,
): Promise<TransactionCategory> {
  const res = await fetchWithAuth(`/api/spending/categories/${categoryId}/`, {
    method: 'PATCH',
    body: JSON.stringify({ monthly_budget: monthlyBudget }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(Object.values(data).flat().join(' ') || 'Failed to save the budget');
  }
  return data;
}

export async function createCategoryRule(fields: {
  match_text: string;
  category?: number;
  spread_months?: number;
  is_regex?: boolean;
  is_transfer?: boolean;
}): Promise<CategoryRule> {
  const res = await fetchWithAuth('/api/spending/rules/', {
    method: 'POST',
    body: JSON.stringify(fields),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(Object.values(data).flat().join(' ') || 'Failed to create rule');
  }
  return data;
}

export async function updateCategoryRule(ruleId: number, fields: {
  match_text?: string;
  category?: number | null;
  spread_months?: number;
  is_regex?: boolean;
  is_transfer?: boolean;
}): Promise<CategoryRule> {
  const res = await fetchWithAuth(`/api/spending/rules/${ruleId}/`, {
    method: 'PATCH',
    body: JSON.stringify(fields),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(Object.values(data).flat().join(' ') || 'Failed to update rule');
  }
  return data;
}

// Rules are evaluated first-match-wins, so their order matters.
export interface RulePreview {
  /** Rows the rule wins and would classify. */
  will_classify: number;
  /** Rows it matches but an earlier rule claims first. */
  shadowed: number;
  /** Rows it matches that already have a category or a manual decision. */
  already_classified: number;
  matched: number;
  examples: { booking_date: string; amount: string; currency: string; text: string }[];
}

export async function previewCategoryRule(fields: {
  match_text: string;
  is_regex?: boolean;
  is_transfer?: boolean;
  /** Set when editing, so the simulation keeps the rule's own position. */
  rule_id?: number;
}, signal?: AbortSignal): Promise<RulePreview> {
  const res = await fetchWithAuth('/api/spending/rules/preview/', {
    method: 'POST',
    body: JSON.stringify(fields),
    signal,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Failed to preview rule');
  return data;
}

export async function reorderCategoryRules(ids: number[]): Promise<CategoryRule[]> {
  const res = await fetchWithAuth('/api/spending/rules/reorder/', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  });
  if (!res.ok) throw new Error('Failed to reorder rules');
  return res.json();
}

export async function deleteCategoryRule(ruleId: number): Promise<void> {
  const res = await fetchWithAuth(`/api/spending/rules/${ruleId}/`, { method: 'DELETE' });
  if (!res.ok && res.status !== 204) throw new Error('Failed to delete rule');
}

export async function getAccountTransactions(
  accountId: number,
  page = 1,
): Promise<{ count: number; results: Transaction[] }> {
  const url = `/api/accounts/${accountId}/transactions/${page > 1 ? `?page=${page}` : ''}`;
  const res = await fetchWithAuth(url);
  if (!res.ok) throw new Error('Failed to fetch transactions');
  return res.json();
}

// All accounts in one chronological list; accountId narrows to one account.
// Sortable columns of the transaction list; the server rejects anything else.
export type TransactionSortKey = 'date' | 'amount' | 'text' | 'account' | 'category';

export async function getTransactions(
  page = 1,
  accountId?: number,
  // A category id, several comma-separated ids ("groceries plus restaurants"),
  // 'transfer' for transfers only, or 'none' for uncategorized.
  category?: number | string,
  // Period as 'YYYY', 'YYYY-Qn' or 'YYYY-MM'.
  period?: string,
  // Sort key, '-' prefixed for descending. Server-side: the list is paginated,
  // so sorting the loaded rows would only sort the page.
  ordering?: string,
  // Matches the spending report: in 'normalized' the period also holds bills
  // booked earlier whose spread reaches into it, each reporting its share.
  mode?: 'normalized' | 'actual',
): Promise<{ count: number; results: Transaction[] }> {
  const params = new URLSearchParams();
  if (page > 1) params.set('page', String(page));
  if (accountId) params.set('account', String(accountId));
  if (category === 'none') params.set('uncategorized', '1');
  else if (category) params.set('category', String(category));
  if (period) params.set('period', period);
  if (ordering) params.set('ordering', ordering);
  if (mode === 'normalized') params.set('mode', mode);
  const qs = params.toString();
  const res = await fetchWithAuth(`/api/transactions/${qs ? `?${qs}` : ''}`);
  if (!res.ok) throw new Error('Failed to fetch transactions');
  return res.json();
}

// Classification updates are allowed on every transaction (incl. imported).
export async function classifyTransaction(
  transactionId: number,
  fields: { category?: number | null; spread_months?: number; is_transfer?: boolean },
): Promise<Transaction> {
  const res = await fetchWithAuth(`/api/transactions/${transactionId}/`, {
    method: 'PATCH',
    body: JSON.stringify(fields),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(Object.values(data).flat().join(' ') || 'Failed to update transaction');
  }
  return data;
}

export async function detectTransfers(): Promise<{ marked: number }> {
  const res = await fetchWithAuth('/api/spending/detect-transfers/', { method: 'POST' });
  if (!res.ok) throw new Error('Failed to detect transfers');
  return res.json();
}

// Fetch historical transactions for an explicit date range. Returns once the
// background task finishes (same queue as sync), so the caller sees the result.
// A broker that challenges for a one-time code answers 'pending_auth': ask for
// the code and pass it to completeAccountAuth, which resumes this same backfill.
export interface BackfillOutcome {
  status: string;
  imported?: number;
  fetched?: number;
  covered_start?: string | null;
  covered_end?: string | null;
  truncated?: boolean;
  message?: string;
  error?: string;
  two_fa_type?: string;
  challenge?: { message?: string };
}

export async function backfillTransactions(
  accountId: number,
  start: string,
  end?: string,
): Promise<BackfillOutcome> {
  const res = await fetchWithAuth(`/api/accounts/${accountId}/transactions/backfill/`, {
    method: 'POST',
    body: JSON.stringify({ start, ...(end ? { end } : {}) }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((data as { error?: string }).error || 'Backfill failed');
  }
  if (data.status === 'queued' && data.task_id) {
    return pollSyncTask(data.task_id);
  }
  return data;
}

export async function importTransactionsCsv(
  file: File,
  accountId?: number,
): Promise<{
  // 'ambiguous': the file names no account and several share its currency —
  // `accounts` lists the candidates, retry with an explicit accountId.
  status: 'success' | 'ambiguous';
  format?: string;
  account_id?: number;
  account_name?: string;
  currency?: string;
  accounts?: { id: number; name: string }[];
  imported?: number;
  fetched?: number;
  skipped?: number;
  covered_start?: string | null;
  covered_end?: string | null;
  message?: string;
}> {
  const body = new FormData();
  body.append('file', file);
  const url = accountId
    ? `/api/accounts/${accountId}/transactions/import-csv/`
    : '/api/transactions/import-csv/';
  const res = await fetchWithAuth(url, { method: 'POST', body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((data as { error?: string }).error || 'CSV import failed');
  }
  return data;
}

// AI categorization (Gemini)

export interface AiPricing {
  model: string;
  display_name: string;
  input_price_per_1m: number | null;
  output_price_per_1m: number | null;
  checked_at: string;
  table_updated: string;
}

export interface AiConfig {
  configured: boolean;
  model: string;
  pricing: AiPricing | null;
  pricing_source_url: string;
  disclosed_fields: string[];
}

export interface AiModel {
  id: string;
  display_name: string;
  input_price_per_1m: number | null;
  output_price_per_1m: number | null;
}

export interface AiSuggestion {
  transaction_id: number;
  booking_date: string;
  counterparty: string;
  description: string;
  amount: string;
  currency: string;
  category: string | null;
  is_transfer?: boolean;
  is_new_category: boolean;
}

export interface AiRuleSuggestion {
  match_text: string;
  category: string | null;
  is_regex?: boolean;
  is_transfer?: boolean;
  is_new_category: boolean;
  // Set when the proposal improves an existing rule instead of adding one
  // (e.g. a regex covering spellings the old match text missed).
  replaces_rule_id?: number | null;
  replaced_match_text?: string | null;
}

export interface AiSuggestResponse {
  suggestions: AiSuggestion[];
  rules: AiRuleSuggestion[];
  sent_count: number;
  total_uncategorized: number;
  disclosed_fields: string[];
  usage?: {
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number | null;
  };
}

async function jsonOrThrow(res: Response, fallback: string) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((data as { error?: string }).error || fallback);
  }
  return data;
}

export async function getAiConfig(): Promise<AiConfig> {
  const res = await fetchWithAuth('/api/spending/ai/config/');
  return jsonOrThrow(res, 'Failed to load AI configuration');
}

export async function refreshAiPricing(): Promise<{
  pricing: AiPricing;
  changed: boolean;
  previous: AiPricing | null;
  model_still_available: boolean;
}> {
  const res = await fetchWithAuth('/api/spending/ai/refresh-pricing/', { method: 'POST' });
  return jsonOrThrow(res, 'Failed to refresh pricing');
}

export async function saveAiConfig(fields: {
  api_key?: string;
  model?: string;
  display_name?: string;
}) {
  const res = await fetchWithAuth('/api/spending/ai/config/', {
    method: 'PUT',
    body: JSON.stringify(fields),
  });
  return jsonOrThrow(res, 'Failed to save AI configuration');
}

export async function deleteAiConfig(): Promise<void> {
  const res = await fetchWithAuth('/api/spending/ai/config/', { method: 'DELETE' });
  if (!res.ok && res.status !== 204) throw new Error('Failed to remove AI configuration');
}

export async function listAiModels(apiKey?: string): Promise<AiModel[]> {
  const res = await fetchWithAuth('/api/spending/ai/models/', {
    method: 'POST',
    body: JSON.stringify(apiKey ? { api_key: apiKey } : {}),
  });
  const data = await jsonOrThrow(res, 'Failed to fetch Gemini models');
  return (data as { models: AiModel[] }).models;
}

export async function aiSuggest(mode: 'items' | 'rules'): Promise<AiSuggestResponse> {
  const res = await fetchWithAuth('/api/spending/ai/suggest/', {
    method: 'POST',
    body: JSON.stringify({ mode }),
  });
  return jsonOrThrow(res, 'Failed to get AI suggestions');
}

export async function aiApply(fields: {
  assignments: {
    transaction_id: number;
    category?: string | null;
    is_transfer?: boolean;
  }[];
  rules: {
    match_text: string;
    category?: string | null;
    is_regex?: boolean;
    is_transfer?: boolean;
    replaces_rule_id?: number | null;
  }[];
}): Promise<{
  assigned: number;
  rules_created: number;
  rules_updated?: number;
  rule_applied: number;
}> {
  const res = await fetchWithAuth('/api/spending/ai/apply/', {
    method: 'POST',
    body: JSON.stringify(fields),
  });
  return jsonOrThrow(res, 'Failed to apply suggestions');
}

// Profile API
export async function getProfile() {
  const res = await fetchWithAuth('/api/profile/');
  if (!res.ok) throw new Error('Failed to fetch profile');
  return res.json();
}

export async function updateProfile(fields: {
  base_currency?: string;
  auto_sync_enabled?: boolean;
  send_weekly_report?: boolean;
  default_chart_range?: number;
  default_chart_granularity?: 'daily' | 'monthly';
}) {
  const res = await fetchWithAuth('/api/profile/', {
    method: 'PATCH',
    body: JSON.stringify(fields),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || 'Failed to update profile');
  }
  return res.json();
}

export async function updateUser(fields: {
  first_name?: string;
  last_name?: string;
  email?: string;
}) {
  const res = await fetchWithAuth('/api/user/', {
    method: 'PATCH',
    body: JSON.stringify(fields),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || 'Failed to update user');
  }
  return res.json();
}

export async function changePassword(
  oldPassword: string,
  newPassword: string,
  newPasswordConfirm: string,
) {
  // Check if user has KEK (is migrated)
  const kek = getKEK();
  const { authSalt, kekSalt } = getSalts();

  if (kek && authSalt && kekSalt) {
    // KEK-based password change for migrated users
    // 1. Get new salts from server
    const newSaltsRes = await fetchWithAuth('/api/auth/salt/new/', {
      method: 'POST',
    });
    if (!newSaltsRes.ok) {
      throw new Error('Failed to get new salts');
    }
    const { new_auth_salt, new_kek_salt } = await newSaltsRes.json();

    // 2. Derive old and new keys
    const oldAuthHashBytes = await deriveKey(oldPassword, authSalt);
    const oldKekBytes = await deriveKey(oldPassword, kekSalt);
    const newAuthHashBytes = await deriveKey(newPassword, new_auth_salt);
    const newKekBytes = await deriveKey(newPassword, new_kek_salt);

    // 3. Call KEK password change endpoint
    const res = await fetchWithAuth('/api/auth/change-password/kek/', {
      method: 'POST',
      body: JSON.stringify({
        old_auth_hash: bytesToBase64(oldAuthHashBytes),
        new_auth_hash: bytesToBase64(newAuthHashBytes),
        old_kek: bytesToBase64(oldKekBytes),
        new_kek: bytesToBase64(newKekBytes),
        new_auth_salt: new_auth_salt,
        new_kek_salt: new_kek_salt,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to change password');
    }

    // 4. Update local KEK and salts
    setKEK(bytesToBase64(newKekBytes));
    setSalts(new_auth_salt, new_kek_salt);

    return data;
  } else {
    // Legacy password change for non-migrated users
    const res = await fetchWithAuth('/api/auth/change-password/', {
      method: 'POST',
      body: JSON.stringify({
        old_password: oldPassword,
        new_password: newPassword,
        new_password_confirm: newPasswordConfirm,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.old_password || data.new_password_confirm || data.error || 'Failed to change password');
    }
    return data;
  }
}
