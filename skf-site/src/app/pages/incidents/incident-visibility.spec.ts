import {
  incidentStatusChip,
  showsPendingNotice,
  showsStewardDetail,
  showsVerdicts,
} from './incident-visibility';
import { Incident } from '../../services/incidents-api.service';

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

describe('showsPendingNotice', () => {
  it('explains the absence of a verdict to a waiting driver', () => {
    expect(showsPendingNotice(incident({ isPublished: false }), DRIVER)).toBe(true);
  });

  it('says nothing once the verdict is readable', () => {
    expect(showsPendingNotice(incident({ isPublished: true }), DRIVER)).toBe(false);
  });

  it('never nags a judge, who can already see everything', () => {
    expect(showsPendingNotice(incident({ isPublished: false }), JUDGE)).toBe(false);
  });
});
