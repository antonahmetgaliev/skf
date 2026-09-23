import { describe, expect, it } from 'vitest';
import { IncidentWindowListItem } from '../../../services/incidents-api.service';
import { closesIn, groupWindows, OTHER_GROUP_KEY } from './window-groups';

const win = (over: Partial<IncidentWindowListItem>): IncidentWindowListItem => ({
  id: over.id ?? Math.random().toString(),
  championshipId: null,
  championshipName: null,
  raceId: null,
  raceName: 'Race',
  date: null,
  intervalHours: 24,
  openedAt: '2026-09-01T00:00:00Z',
  closesAt: '2026-09-02T00:00:00Z',
  openedByUserId: null,
  isManuallyClosed: false,
  isOpen: false,
  ...over,
});

describe('groupWindows', () => {
  it('groups rounds by championship in race order', () => {
    const groups = groupWindows([
      win({ id: 'r2', championshipId: 1, championshipName: 'Hyper', date: '2026-09-12' }),
      win({ id: 'r1', championshipId: 1, championshipName: 'Hyper', date: '2026-09-05' }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].name).toBe('Hyper');
    expect(groups[0].windows.map((w) => w.id)).toEqual(['r1', 'r2']);
  });

  it('puts championships with open windows first and "other" last', () => {
    const groups = groupWindows([
      win({ championshipId: null, openedAt: '2026-09-20T00:00:00Z', isOpen: true }),
      win({ championshipId: 1, championshipName: 'Recent', openedAt: '2026-09-15T00:00:00Z' }),
      win({ championshipId: 2, championshipName: 'Open', openedAt: '2026-08-01T00:00:00Z', isOpen: true }),
      win({ championshipId: 3, championshipName: 'Old', openedAt: '2026-07-01T00:00:00Z' }),
    ]);
    expect(groups.map((g) => g.name ?? g.key)).toEqual(['Open', 'Recent', 'Old', OTHER_GROUP_KEY]);
    expect(groups[0].openCount).toBe(1);
  });

  it('falls back to the id when the championship name is unknown', () => {
    expect(groupWindows([win({ championshipId: 7 })])[0].name).toBe('#7');
  });
});

describe('closesIn', () => {
  it('formats the time left', () => {
    const now = Date.parse('2026-09-01T00:00:00Z');
    expect(closesIn('2026-09-01T05:12:00Z', now)).toBe('5h 12m');
    expect(closesIn('2026-09-01T00:30:00Z', now)).toBe('30m');
    expect(closesIn('2026-08-31T00:00:00Z', now)).toBe('Closed');
  });
});
