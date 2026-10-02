import { CalendarEvent, Community } from '../../services/calendar-api.service';
import {
  buildMonthGrid,
  buildYearColumns,
  DEFAULT_COLOR,
  eventFallsOnDay,
  eventOverlapsMonth,
  groupEventsByColor,
  isScheduled,
  racesOnDay,
  simulatorColor,
  sortRacesByDate,
} from './calendar-events';

// Local-time ISO strings (no offset) keep the tests independent of the machine's time zone.
function race(date: string | null, endDate: string | null = null): CalendarEvent['races'][number] {
  return { date, endDate, track: null, name: null };
}

function event(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: 'e1',
    name: 'Event',
    game: 'iRacing',
    carClass: null,
    description: null,
    startDate: null,
    endDate: null,
    eventType: 'upcoming',
    source: 'custom',
    image: null,
    simgridChampionshipId: null,
    customChampionshipId: null,
    community: null,
    acceptingRegistrations: false,
    capacity: null,
    spotsTaken: null,
    registrationUrl: null,
    races: [],
    ...overrides,
  };
}

function community(id: string, color: string | null = '#123456'): Community {
  return {
    id,
    name: id.toUpperCase(),
    color,
    discordUrl: null,
    isVisible: true,
    isSkf: false,
    createdAt: '2026-01-01T00:00:00',
  };
}

describe('eventFallsOnDay', () => {
  it('matches a single-day race', () => {
    const e = event({ races: [race('2026-10-05T19:00:00')] });
    expect(eventFallsOnDay(e, 2026, 10, 5)).toBe(true);
    expect(eventFallsOnDay(e, 2026, 10, 6)).toBe(false);
  });

  it('matches every day of a multi-day race', () => {
    const e = event({ races: [race('2026-10-05T10:00:00', '2026-10-07T10:00:00')] });
    expect([4, 5, 6, 7, 8].map((d) => eventFallsOnDay(e, 2026, 10, d))).toEqual([
      false,
      true,
      true,
      true,
      false,
    ]);
  });

  it('falls back to start and end dates only when no race has a date', () => {
    const undated = event({ startDate: '2026-10-01T00:00:00', races: [race(null)] });
    expect(eventFallsOnDay(undated, 2026, 10, 1)).toBe(true);

    const dated = event({ startDate: '2026-10-01T00:00:00', races: [race('2026-10-09T19:00:00')] });
    expect(eventFallsOnDay(dated, 2026, 10, 1)).toBe(false);
  });
});

describe('eventOverlapsMonth', () => {
  it('matches races inside the month', () => {
    expect(eventOverlapsMonth(event({ races: [race('2026-10-31T20:00:00')] }), 2026, 10)).toBe(
      true,
    );
    expect(eventOverlapsMonth(event({ races: [race('2026-11-01T20:00:00')] }), 2026, 10)).toBe(
      false,
    );
  });

  it('matches a multi-day race crossing the month boundary', () => {
    const e = event({ races: [race('2026-09-29T10:00:00', '2026-10-02T10:00:00')] });
    expect(eventOverlapsMonth(e, 2026, 10)).toBe(true);
  });

  it('matches an event spanning the whole month', () => {
    const e = event({ startDate: '2026-09-01T00:00:00', endDate: '2026-12-01T00:00:00' });
    expect(eventOverlapsMonth(e, 2026, 10)).toBe(true);
  });
});

describe('buildMonthGrid', () => {
  it('lays out October 2026 as Monday-first weeks', () => {
    // 1 October 2026 is a Thursday.
    const weeks = buildMonthGrid(2026, 10, [], new Date(2026, 9, 15));
    expect(weeks).toHaveLength(5);
    expect(weeks[0].map((d) => d.dayNumber)).toEqual([28, 29, 30, 1, 2, 3, 4]);
    expect(weeks[0][0].isCurrentMonth).toBe(false);
    expect(weeks[4].map((d) => d.dayNumber)).toEqual([26, 27, 28, 29, 30, 31, 1]);
  });

  it('marks today and past days', () => {
    const days = buildMonthGrid(2026, 10, [], new Date(2026, 9, 15)).flat();
    const oct = days.filter((d) => d.isCurrentMonth);
    expect(oct.find((d) => d.isToday)?.dayNumber).toBe(15);
    expect(oct.filter((d) => d.isPast).map((d) => d.dayNumber)).toEqual(
      Array.from({ length: 14 }, (_, i) => i + 1),
    );
  });

  it('puts events on their days', () => {
    const e = event({ races: [race('2026-10-05T19:00:00')] });
    const days = buildMonthGrid(2026, 10, [e], new Date(2026, 9, 1)).flat();
    expect(days.filter((d) => d.events.length).map((d) => d.dayNumber)).toEqual([5]);
  });
});

describe('racesOnDay', () => {
  it("returns that day's races, or all races when none match", () => {
    const a = race('2026-10-05T19:00:00');
    const b = race('2026-10-12T19:00:00');
    const e = event({ races: [a, b] });
    expect(racesOnDay(e, 2026, 10, 12)).toEqual([b]);
    expect(racesOnDay(e, 2026, 10, 20)).toEqual([a, b]);
  });
});

describe('sortRacesByDate', () => {
  it('sorts dated races first, earliest first', () => {
    const races = [race(null), race('2026-10-12T19:00:00'), race('2026-10-05T19:00:00')];
    expect(sortRacesByDate(races).map((r) => r.date)).toEqual([
      '2026-10-05T19:00:00',
      '2026-10-12T19:00:00',
      null,
    ]);
  });
});

describe('isScheduled', () => {
  it('needs a start, an end or a dated race', () => {
    expect(isScheduled(event())).toBe(false);
    expect(isScheduled(event({ races: [race(null)] }))).toBe(false);
    expect(isScheduled(event({ endDate: '2026-10-01T00:00:00' }))).toBe(true);
    expect(isScheduled(event({ races: [race('2026-10-05T19:00:00')] }))).toBe(true);
  });
});

describe('groupEventsByColor', () => {
  it('groups by community colour in first-seen order, gold when missing', () => {
    const groups = groupEventsByColor([
      event({ id: 'a', community: community('x', '#111') }),
      event({ id: 'b', community: community('y', null) }),
      event({ id: 'c', community: community('x', '#111') }),
    ]);
    expect(groups.map((g) => [g.color, g.events.map((e) => e.id)])).toEqual([
      ['#111', ['a', 'c']],
      [DEFAULT_COLOR, ['b']],
    ]);
  });
});

describe('buildYearColumns', () => {
  it('keeps community order, skips empty ones and sorts events by date', () => {
    const late = event({
      id: 'late',
      community: community('b'),
      races: [race('2026-11-01T19:00:00')],
    });
    const early = event({
      id: 'early',
      community: community('b'),
      races: [race('2026-02-01T19:00:00')],
    });
    const undated = event({ id: 'undated', community: community('b') });
    const columns = buildYearColumns(
      [late, undated, early],
      [community('a'), community('b', null)],
    );
    expect(columns.map((c) => c.id)).toEqual(['b']);
    expect(columns[0].color).toBe(DEFAULT_COLOR);
    expect(columns[0].events.map((e) => e.id)).toEqual(['early', 'late', 'undated']);
  });

  it('adds empty columns for the given communities', () => {
    const e = event({ community: community('a'), races: [race('2026-02-01T19:00:00')] });
    const columns = buildYearColumns([e], [community('a')], [community('a'), community('m')]);
    expect(columns.map((c) => [c.id, c.events.length])).toEqual([
      ['a', 1],
      ['m', 0],
    ]);
  });
});

describe('simulatorColor', () => {
  it('is case-insensitive with a grey fallback', () => {
    expect(simulatorColor('iRacing')).toBe('#0153db');
    expect(simulatorColor('Unknown Sim')).toBe('#6b7280');
  });
});
