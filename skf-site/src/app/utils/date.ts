/**
 * Convert an ISO date string to a local YYYY-MM-DD string,
 * respecting the user's timezone.
 */
export function toLocalDateStr(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * Extract the local time (HH:MM) from an ISO date string.
 * Returns null if no meaningful time is present.
 */
export function toLocalTime(iso: string): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  const h = d.getHours();
  const m = d.getMinutes();
  if (h === 0 && m === 0) return null;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

/**
 * Append the browser's local timezone offset to a naive datetime-local string.
 * e.g. "2025-04-15T18:00" → "2025-04-15T18:00:00+03:00"
 */
export function withLocalTzOffset(date: string | null): string | null {
  if (!date) return null;
  const parts = date.split(':');
  const base = parts.length >= 3 ? date : `${date}:00`;
  const offset = new Date().getTimezoneOffset();
  const sign = offset <= 0 ? '+' : '-';
  const absH = String(Math.floor(Math.abs(offset) / 60)).padStart(2, '0');
  const absM = String(Math.abs(offset) % 60).padStart(2, '0');
  return `${base}${sign}${absH}:${absM}`;
}
