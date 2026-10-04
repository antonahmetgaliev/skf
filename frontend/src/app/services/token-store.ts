/** Where the login's tokens live in the browser. */

export interface StoredTokens {
  accessToken: string;
  refreshToken: string;
  /** Epoch milliseconds at which the access token stops working. */
  expiresAt: number;
}

export const TOKENS_KEY = 'skf.auth';

// Used when localStorage is unavailable (private mode, blocked site data):
// the login then lasts until the tab is reloaded.
let fallback: StoredTokens | null = null;

function isStoredTokens(value: unknown): value is StoredTokens {
  const v = value as Partial<StoredTokens> | null;
  return (
    !!v &&
    typeof v.accessToken === 'string' &&
    typeof v.refreshToken === 'string' &&
    typeof v.expiresAt === 'number'
  );
}

export function readTokens(): StoredTokens | null {
  try {
    const raw = localStorage.getItem(TOKENS_KEY);
    if (raw === null) return fallback;
    const parsed: unknown = JSON.parse(raw);
    return isStoredTokens(parsed) ? parsed : null;
  } catch {
    return fallback;
  }
}

export function writeTokens(tokens: StoredTokens): void {
  fallback = tokens;
  try {
    localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
  } catch {
    // Kept in memory only.
  }
}

export function clearTokens(): void {
  fallback = null;
  try {
    localStorage.removeItem(TOKENS_KEY);
  } catch {
    // Nothing was stored.
  }
}
