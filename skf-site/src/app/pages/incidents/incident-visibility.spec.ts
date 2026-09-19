import {
  driverStatusBadge,
  incidentPenalties,
  incidentStatusChip,
  sharedDecisionDescription,
  showsStewardDetail,
  showsVerdicts,
} from './incident-visibility';
import { Incident, IncidentDriver } from '../../services/incidents-api.service';

function incident(overrides: Partial<Incident> = {}): Incident {
  return {
    id: 'inc-1',
    windowId: 'win-1',
    reporterUserId: null,
    sessionName: 'RACE',
    time: '03:05',
    lap: null,
    corner: null,
    description: null,
    source: 'ingested',
    status: 'resolved',
    isPublished: false,
    createdAt: '2026-09-12T23:57:00Z',
    drivers: [],
    ...overrides,
  };
}

const JUDGE = true;
const DRIVER = false;

describe('incidentStatusChip', () => {
  describe('as a driver', () => {
    it('reads "under review" while unpublished, even once judged', () => {
      // The regression this exists to prevent: the card claimed Resolved while
      // every driver row claimed Open, and no verdict was anywhere to be seen.
      const chip = incidentStatusChip(
        incident({ status: 'resolved', isPublished: false }),
        DRIVER,
      );
      expect(chip.label).toBe('incidents.underReview');
      expect(chip.variant).toBe('pending');
    });

    it('does not shift as the stewards make progress', () => {
      const open = incidentStatusChip(incident({ status: 'open', isPublished: false }), DRIVER);
      const judged = incidentStatusChip(
        incident({ status: 'resolved', isPublished: false }),
        DRIVER,
      );
      expect(open.label).toBe(judged.label);
    });

    it('becomes resolved once the round is published', () => {
      const chip = incidentStatusChip(
        incident({ status: 'resolved', isPublished: true }),
        DRIVER,
      );
      expect(chip.label).toBe('incidents.resolved');
      expect(chip.variant).toBe('resolved');
    });

    it('still reads "under review" if a published round gains a new driver', () => {
      // Adding a driver reopens the incident; the driver should not see a bare
      // "Open" next to verdicts that are already public.
      const chip = incidentStatusChip(incident({ status: 'open', isPublished: true }), DRIVER);
      expect(chip.label).toBe('incidents.statusOpen');
    });
  });

  describe('as a judge', () => {
    it('reports the real state of an unpublished incident', () => {
      expect(
        incidentStatusChip(incident({ status: 'resolved', isPublished: false }), JUDGE).label,
      ).toBe('incidents.resolved');
    });

    it('reports one still awaiting a verdict', () => {
      expect(
        incidentStatusChip(incident({ status: 'open', isPublished: false }), JUDGE).label,
      ).toBe('incidents.statusOpen');
    });
  });
});

describe('showsVerdicts', () => {
  it('lets a judge read verdicts before publication', () => {
    expect(showsVerdicts(incident({ isPublished: false }), JUDGE)).toBe(true);
  });

  it('withholds them from a driver until publication', () => {
    expect(showsVerdicts(incident({ isPublished: false }), DRIVER)).toBe(false);
    expect(showsVerdicts(incident({ isPublished: true }), DRIVER)).toBe(true);
  });
});

describe('showsStewardDetail', () => {
  it('keeps row badges and the unlinked flag to stewards', () => {
    expect(showsStewardDetail(JUDGE)).toBe(true);
    expect(showsStewardDetail(DRIVER)).toBe(false);
  });
});

describe('incidentPenalties', () => {
  const penalised = {
    id: 'drv-2',
    driverName: 'Oleksandr Dovmat',
    driverId: 'driver-2',
    sortOrder: 1,
    resolution: {
      id: 'res-2',
      incidentDriverId: 'drv-2',
      judgeUserId: null,
      verdict: 'TP +15s',
      bwpPoints: 2,
      description: null,
      bwpApplied: false,
      resolvedAt: '2026-09-13T10:00:00Z',
    },
  };

  const withVerdict = (id: string, name: string, verdict: string): IncidentDriver => ({
    ...penalised,
    id,
    driverName: name,
    resolution: { ...penalised.resolution, incidentDriverId: id, verdict },
  });

  it('names the penalties on a published round', () => {
    const penalties = incidentPenalties(
      incident({ isPublished: true, drivers: [penalised] }),
      'NFA',
      DRIVER,
    );
    expect(penalties).toEqual([{ driverName: 'Oleksandr Dovmat', verdict: 'TP +15s' }]);
  });

  it('stays silent when everyone got the default', () => {
    const nfa = {
      ...penalised,
      resolution: { ...penalised.resolution, verdict: 'NFA', bwpPoints: null },
    };
    expect(incidentPenalties(incident({ isPublished: true, drivers: [nfa] }), 'NFA', DRIVER))
      .toEqual([]);
  });

  it('names only the driver who was penalised, not the rest of the incident', () => {
    // The complaint this exists to prevent: a five-driver incident printing
    // "NFA" four times to say one driver got a time penalty.
    const drivers = [
      withVerdict('drv-1', 'Bohdan Tseliuk', 'NFA'),
      penalised,
      withVerdict('drv-3', 'Andrii Mochulskyi', 'NFA'),
    ];
    expect(incidentPenalties(incident({ isPublished: true, drivers }), 'NFA', DRIVER))
      .toEqual([{ driverName: 'Oleksandr Dovmat', verdict: 'TP +15s' }]);
  });

  it('skips drivers nobody has judged', () => {
    const unjudged = { ...penalised, id: 'drv-9', driverName: 'Arsen Budzyk', resolution: null };
    expect(
      incidentPenalties(incident({ isPublished: true, drivers: [penalised, unjudged] }), 'NFA', DRIVER),
    ).toEqual([{ driverName: 'Oleksandr Dovmat', verdict: 'TP +15s' }]);
  });

  it('leaks nothing from a withheld round', () => {
    // Role preview is a client-side simulation, so an admin previewing as a
    // driver still holds real resolutions in memory. The header must not print
    // what the card body is refusing to show.
    expect(
      incidentPenalties(incident({ isPublished: false, drivers: [penalised] }), 'NFA', DRIVER),
    ).toEqual([]);
  });

  it('still shows a judge the penalties before publication', () => {
    expect(
      incidentPenalties(incident({ isPublished: false, drivers: [penalised] }), 'NFA', JUDGE),
    ).toEqual([{ driverName: 'Oleksandr Dovmat', verdict: 'TP +15s' }]);
  });

  describe('with no default verdict to compare against', () => {
    it('says nothing when one verdict covers everyone', () => {
      // A league can delete the rule flagged default, and the rules request can
      // simply fail. Neither should resurrect the row of repeated NFAs.
      const drivers = [
        withVerdict('drv-1', 'Kostiantyn Kryvenko', 'NFA'),
        withVerdict('drv-2', 'Bohdan Hulobov', 'NFA'),
      ];
      expect(incidentPenalties(incident({ isPublished: true, drivers }), undefined, DRIVER))
        .toEqual([]);
    });

    it('names everyone when the decision was split', () => {
      // Without a baseline there is no telling which half is the penalty, and
      // hiding a real one is the worse failure.
      const drivers = [withVerdict('drv-1', 'Bohdan Tseliuk', 'NFA'), penalised];
      expect(incidentPenalties(incident({ isPublished: true, drivers }), undefined, DRIVER))
        .toEqual([
          { driverName: 'Bohdan Tseliuk', verdict: 'NFA' },
          { driverName: 'Oleksandr Dovmat', verdict: 'TP +15s' },
        ]);
    });
  });
});

describe('sharedDecisionDescription', () => {
  const judged = (id: string, description: string | null): IncidentDriver => ({
    id,
    driverName: `Driver ${id}`,
    driverId: `driver-${id}`,
    sortOrder: 0,
    resolution: {
      id: `res-${id}`,
      incidentDriverId: id,
      judgeUserId: null,
      verdict: 'NFA',
      bwpPoints: null,
      description,
      bwpApplied: false,
      resolvedAt: '2026-09-13T10:00:00Z',
    },
  });

  it('returns the reason the whole incident shares', () => {
    // The server copies one authored reason onto every driver's row, so the
    // card prints it once instead of once per driver.
    const drivers = [judged('a', 'Avoidable contact'), judged('b', 'Avoidable contact')];
    expect(sharedDecisionDescription(incident({ drivers }))).toBe('Avoidable contact');
  });

  it('returns null when no reason was given', () => {
    expect(sharedDecisionDescription(incident({ drivers: [judged('a', null)] }))).toBeNull();
  });

  it('returns null when the rows disagree, leaving them to speak for themselves', () => {
    const drivers = [judged('a', 'Avoidable contact'), judged('b', 'Unsafe rejoin')];
    expect(sharedDecisionDescription(incident({ drivers }))).toBeNull();
  });
});

describe('driverStatusBadge', () => {
  function driver(resolution: IncidentDriver['resolution'] = null): IncidentDriver {
    return {
      id: 'drv-1',
      driverName: 'Bohdan Tseliuk',
      driverId: 'driver-1',
      sortOrder: 0,
      resolution,
    };
  }

  function resolution(over: Partial<NonNullable<IncidentDriver['resolution']>> = {}) {
    return {
      id: 'res-1',
      incidentDriverId: 'drv-1',
      judgeUserId: null,
      verdict: 'NFA',
      bwpPoints: null,
      description: null,
      bwpApplied: false,
      resolvedAt: '2026-09-13T10:00:00Z',
      ...over,
    };
  }

  it('says nothing for a judged driver with no penalty', () => {
    // The chip row already shows the verdict and the header already says
    // Resolved; a third "Resolved" here was pure repetition.
    expect(driverStatusBadge(driver(resolution()), incident())).toBeNull();
  });

  it('says nothing for an unjudged driver in an open incident', () => {
    expect(driverStatusBadge(driver(), incident({ status: 'open' }))).toBeNull();
  });

  it('flags a driver left unjudged inside a resolved incident', () => {
    // The one case the row cannot otherwise reveal: it contradicts the header.
    const badge = driverStatusBadge(driver(), incident({ status: 'resolved' }));
    expect(badge?.label).toBe('incidents.statusOpen');
  });

  it('reports a penalty still to reach the licence', () => {
    const badge = driverStatusBadge(driver(resolution({ bwpPoints: 2 })), incident());
    expect(badge?.label).toBe('incidents.bwpPending');
  });

  it('reports a penalty already issued', () => {
    const badge = driverStatusBadge(
      driver(resolution({ bwpPoints: 2, bwpApplied: true })),
      incident(),
    );
    expect(badge?.label).toBe('incidents.bwpApplied');
  });
});
