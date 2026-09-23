import { IncidentWindowListItem } from '../../../services/incidents-api.service';

/** Windows with no championship collect under this key. */
export const OTHER_GROUP_KEY = 'other';

export interface WindowGroup {
  /** `c-<SimGrid id>` or `OTHER_GROUP_KEY`. */
  key: string;
  championshipId: number | null;
  /** Null for the "other" group, whose label is translated by the view. */
  name: string | null;
  /** Rounds in race order (R1 first). */
  windows: IncidentWindowListItem[];
  openCount: number;
}

export const groupKeyFor = (championshipId: number | null): string =>
  championshipId === null ? OTHER_GROUP_KEY : `c-${championshipId}`;

const raceOrder = (w: IncidentWindowListItem): string => `${w.date ?? ''}|${w.openedAt}`;

/**
 * Protest windows grouped by championship.
 *
 * Championships with an open window come first, then the most recently
 * active ones; windows without a championship go last.
 */
export function groupWindows(windows: IncidentWindowListItem[]): WindowGroup[] {
  const groups = new Map<string, WindowGroup>();
  for (const w of windows) {
    const key = groupKeyFor(w.championshipId);
    let group = groups.get(key);
    if (!group) {
      group = { key, championshipId: w.championshipId, name: null, windows: [], openCount: 0 };
      groups.set(key, group);
    }
    group.name ??= w.championshipName ?? (w.championshipId !== null ? `#${w.championshipId}` : null);
    group.windows.push(w);
    if (w.isOpen) group.openCount++;
  }

  const latest = (g: WindowGroup) => g.windows.reduce((max, w) => (w.openedAt > max ? w.openedAt : max), '');
  for (const g of groups.values()) {
    g.windows.sort((a, b) => raceOrder(a).localeCompare(raceOrder(b)));
  }
  return [...groups.values()].sort(
    (a, b) =>
      Number(a.key === OTHER_GROUP_KEY) - Number(b.key === OTHER_GROUP_KEY) ||
      Number(b.openCount > 0) - Number(a.openCount > 0) ||
      latest(b).localeCompare(latest(a)),
  );
}

/** "5h 12m" until the window closes, or "Closed". */
export function closesIn(closesAt: string, now = Date.now()): string {
  const ms = new Date(closesAt).getTime() - now;
  if (ms <= 0) return 'Closed';
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}
