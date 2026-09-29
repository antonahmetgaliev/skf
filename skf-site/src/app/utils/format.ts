const dateFormatter = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
});

export function formatDate(value: string | null, fallback = '-'): string {
  if (!value) return fallback;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return dateFormatter.format(parsed);
}

export function formatNumber(value: number): string {
  const isWhole = Math.abs(value % 1) < 0.00001;
  return isWhole ? String(Math.trunc(value)) : value.toFixed(1);
}

export function toSlug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
}

/** Lap or race time from milliseconds: `1:33.485`, `1:10:38.798`. */
export function formatLapTime(ms: number | null, fallback = '-'): string {
  if (ms === null || ms <= 0) return fallback;
  const totalSeconds = Math.floor(ms / 1000);
  const millis = String(ms % 1000).padStart(3, '0');
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);
  const ss = String(seconds).padStart(2, '0');
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${ss}.${millis}`
    : `${minutes}:${ss}.${millis}`;
}

/** Gap to the leader from milliseconds: `+0.220`, `+1:05.310`. */
export function formatGap(ms: number | null, fallback = '-'): string {
  if (ms === null || ms < 0) return fallback;
  if (ms < 60_000) return `+${(ms / 1000).toFixed(3)}`;
  return `+${formatLapTime(ms)}`;
}
