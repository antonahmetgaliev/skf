import { Incident, IncidentDriver, IncidentWindowOut } from '../../services/incidents-api.service';
import {
  discordDecisionsText,
  groupBySession,
  pendingPenalties,
  publishPreview,
  unresolvedCount,
} from './incident-summary';

let seq = 0;

function driver(
  name: string,
  verdict?: { verdict: string; bwpPoints: number; bwpApplied?: boolean; description?: string },
  linked = true,
): IncidentDriver {
  const id = `d${++seq}`;
  return {
    id,
    driverName: name,
    driverId: linked ? `drv-${name}` : null,
    sortOrder: 0,
    resolution: verdict
      ? {
          id: `r${seq}`,
          incidentDriverId: id,
          judgeUserId: null,
          verdict: verdict.verdict,
          bwpPoints: verdict.bwpPoints,
          description: verdict.description ?? null,
          bwpApplied: verdict.bwpApplied ?? false,
          resolvedAt: '2026-09-29T20:00:00',
        }
      : null,
  };
}

function incident(overrides: Partial<Incident> = {}): Incident {
  return {
    id: `i${++seq}`,
    windowId: 'w',
    reporterUserId: null,
    sessionName: 'Race',
    time: null,
    lap: null,
    corner: null,
    description: null,
    source: 'auto',
    status: 'open',
    isPublished: false,
    createdAt: '2026-09-29T20:00:00',
    drivers: [],
    ...overrides,
  };
}

function window(incidents: Incident[]): IncidentWindowOut {
  return {
    id: 'w',
    championshipId: 1,
    championshipName: 'Cup',
    raceId: 2,
    raceName: 'Round 1',
    date: null,
    intervalHours: 24,
    openedAt: '2026-09-29T20:00:00',
    closesAt: '2026-09-30T20:00:00',
    openedByUserId: null,
    isManuallyClosed: false,
    isOpen: true,
    incidents,
  };
}

describe('groupBySession', () => {
  it('orders heats by number, then Feature, then anything else', () => {
    const names = ['Race', 'FEATURE', 'Heat 2', 'Heat 1'];
    const groups = groupBySession(names.map((sessionName) => incident({ sessionName })));
    expect(groups.map((g) => g.session)).toEqual(['Heat 1', 'Heat 2', 'FEATURE', 'Race']);
  });

  it('sorts auto incidents by time and filed ones by lap, then corner', () => {
    const groups = groupBySession([
      incident({ id: 'a2', time: '00:10:00' }),
      incident({ id: 'a1', time: '00:02:00' }),
      incident({ id: 'f3', source: 'filed', lap: '10', corner: 'T1' }),
      incident({ id: 'f2', source: 'filed', lap: '2', corner: 'T5' }),
      incident({ id: 'f1', source: 'filed', lap: '2', corner: 'T1' }),
    ]);
    expect(groups[0].autoItems.map((i) => i.id)).toEqual(['a1', 'a2']);
    expect(groups[0].filedItems.map((i) => i.id)).toEqual(['f1', 'f2', 'f3']);
  });
});

describe('publish preview', () => {
  const w = window([
    incident({
      status: 'resolved',
      drivers: [
        driver('Alice', { verdict: 'Penalty', bwpPoints: 2 }),
        driver('Bob', { verdict: 'No action', bwpPoints: 0 }),
      ],
    }),
    incident({
      drivers: [
        driver('Carol', { verdict: 'Penalty', bwpPoints: 3 }, false),
        driver('Dave', { verdict: 'Penalty', bwpPoints: 1, bwpApplied: true }),
        driver('Eve'),
      ],
    }),
  ]);

  it('lists only penalties not yet on a licence', () => {
    expect(pendingPenalties(w).map((p) => [p.driverName, p.bwpPoints, p.linked])).toEqual([
      ['Alice', 2, true],
      ['Carol', 3, false],
    ]);
  });

  it('counts only linked penalties towards the BWP total', () => {
    const preview = publishPreview(w);
    expect(preview.bwpTotal).toBe(2);
    expect(preview.verdictCount).toBe(4);
    expect(preview.noPenaltyCount).toBe(1);
  });

  it('counts unresolved incidents', () => {
    expect(unresolvedCount(w)).toBe(1);
  });
});

describe('discordDecisionsText', () => {
  it('writes one line per verdict under the race name', () => {
    const w = window([
      incident({
        sessionName: 'Race',
        lap: '3',
        corner: 'T1',
        drivers: [
          driver('Alice', { verdict: 'Warning', bwpPoints: 0, description: 'Late braking' }),
          driver('Bob'),
          driver('Carol', { verdict: 'Penalty', bwpPoints: 2 }),
        ],
      }),
    ]);
    expect(discordDecisionsText(w)).toBe(
      [
        'Round 1',
        'Race | Lap 3 | T1 | Alice | Late braking | Warning | -',
        'Race | Lap 3 | T1 | Carol | Penalty | 2 BWP',
      ].join('\n\n'),
    );
  });
});
