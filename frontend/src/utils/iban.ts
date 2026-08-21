/** IBAN lengths per country, for {@link stripLeadingIban}. */
const IBAN_LENGTHS: Record<string, number> = {
  AT: 20, BE: 16, BG: 22, CH: 21, CY: 28, CZ: 24, DE: 22,
  DK: 18, EE: 20, ES: 24, FI: 18, FR: 27, GB: 22, GR: 27,
  HR: 21, HU: 28, IE: 22, IT: 27, LI: 21, LT: 20, LU: 20,
  LV: 21, MT: 31, NL: 18, NO: 15, PL: 28, PT: 25, RO: 24,
  SE: 24, SI: 19, SK: 24,
};

/** True when `candidate` passes the IBAN mod-97 checksum. */
function isValidIban(candidate: string): boolean {
  const rearranged = candidate.slice(4) + candidate.slice(0, 4);
  let remainder = 0;
  for (const ch of rearranged) {
    let value: number;
    if (ch >= '0' && ch <= '9') value = ch.charCodeAt(0) - 48;
    else if (ch >= 'A' && ch <= 'Z') value = ch.charCodeAt(0) - 65 + 10;
    else return false;
    remainder = value < 10
      ? (remainder * 10 + value) % 97
      : (remainder * 100 + value) % 97;
  }
  return remainder === 1;
}

/**
 * Strip a leading IBAN from a counterparty string.
 *
 * Some feeds (DKB via FinTS) deliver the counterparty as `<IBAN><name>` in one
 * field. Only a checksum-valid IBAN of the country's exact length is stripped;
 * anything else stays untouched.
 */
export function stripLeadingIban(raw: string): string {
  if (raw.length < 15) return raw;
  const length = IBAN_LENGTHS[raw.slice(0, 2)];
  if (length === undefined || raw.length < length) return raw;
  const candidate = raw.slice(0, length);
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]+$/.test(candidate)) return raw;
  if (!isValidIban(candidate)) return raw;
  return raw.slice(length).trim();
}
