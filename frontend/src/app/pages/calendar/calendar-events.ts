import { CalendarEvent, Community } from '../../services/calendar-api.service';
import { toLocalDateStr } from '../../utils/date';

/** Pure calendar logic: which events fall where, grid layout, grouping. */

export interface CalendarDay {
  dayNumber: number;
  isCurrentMonth: boolean;
  isToday: boolean;
  isPast: boolean;
  events: CalendarEvent[];
}

export interface EventGroup {
  color: string;
  events: CalendarEvent[];
}

export interface YearCommunityColumn {
  id: string;
  name: string;
  color: string;
  discordUrl: string | null;
  events: CalendarEvent[];
}

export const DEFAULT_COLOR = '#ffd600'; // gold fallback

const SIM_COLORS: Record<string, string> = {
  iracing: '#0153db',
  'assetto corsa competizione': '#d4132a',
  'assetto corsa': '#d4132a',
  'le mans ultimate': '#004d99',
  'rfactor 2': '#e87722',
  'automobilista 2': '#2dbe60',
  rennsport: '#8b5cf6',
  'forza motorsport': '#107c10',
  'gran turismo': '#003791',
  'ea sports wrc': '#00a2e8',
};

export function simulatorColor(game: string): string {
  return SIM_COLORS[game.toLowerCase()] ?? '#6b7280';
}

function dayKey(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

/** An event has a date if it, or any of its races, is scheduled. */
export function isScheduled(event: CalendarEvent): boolean {
  return !!(event.startDate || event.endDate || event.races.some((r) => r.date));
}

export function eventOverlapsMonth(event: CalendarEvent, year: number, month: number): boolean {
  const monthStart = new Date(year, month - 1, 1);
  const monthEnd = new Date(year, month, 0, 23, 59, 59, 999);

  for (const race of event.races) {
    if (race.date && race.endDate) {
      // Multi-day race: check range overlap with month
      const start = new Date(race.date);
      const end = new Date(race.endDate);
      if (start <= monthEnd && end >= monthStart) return true;
    } else if (race.date) {
      const d = new Date(race.date);
      if (d >= monthStart && d <= monthEnd) return true;
    }
  }

  if (event.startDate) {
    const d = new Date(event.startDate);
    if (d >= monthStart && d <= monthEnd) return true;
  }
  if (event.endDate) {
    const d = new Date(event.endDate);
    if (d >= monthStart && d <= monthEnd) return true;
  }

  // Event spans the entire month
  if (event.startDate && event.endDate) {
    const start = new Date(event.startDate);
    const end = new Date(event.endDate);
    if (start <= monthStart && end >= monthEnd) return true;
  }

  return false;
}

export function eventFallsOnDay(
  event: CalendarEvent,
  year: number,
  month: number,
  day: number,
): boolean {
  const dayStr = dayKey(year, month, day);

  // Check individual races (including multi-day ranges)
  for (const race of event.races) {
    if (race.date && race.endDate) {
      if (dayStr >= toLocalDateStr(race.date) && dayStr <= toLocalDateStr(race.endDate)) {
        return true;
      }
    } else if (race.date && toLocalDateStr(race.date) === dayStr) {
      return true;
    }
  }

  // For SimGrid championships without race-level dates, check start/end range
  if (event.races.length === 0 || event.races.every((r) => !r.date)) {
    if (event.startDate && toLocalDateStr(event.startDate) === dayStr) return true;
    if (event.endDate && toLocalDateStr(event.endDate) === dayStr) return true;
  }

  return false;
}

/** The event's races on that day; all its races when none match. */
export function racesOnDay(
  event: CalendarEvent,
  year: number,
  month: number,
  day: number,
): CalendarEvent['races'] {
  const dayStr = dayKey(year, month, day);
  const filtered = event.races.filter((r) => {
    if (r.date && r.endDate) {
      return dayStr >= toLocalDateStr(r.date) && dayStr <= toLocalDateStr(r.endDate);
    }
    return r.date && toLocalDateStr(r.date) === dayStr;
  });
  return filtered.length > 0 ? filtered : event.races;
}

/** Month grid as Monday-first weeks, padded with days of the neighbouring months. */
export function buildMonthGrid(
  year: number,
  month: number,
  events: CalendarEvent[],
  today: Date = new Date(),
): CalendarDay[][] {
  const firstDay = new Date(year, month - 1, 1);
  // Monday = 0, Sunday = 6
  let startWeekday = firstDay.getDay() - 1;
  if (startWeekday < 0) startWeekday = 6;

  const daysInMonth = new Date(year, month, 0).getDate();
  const prevMonthDays = new Date(year, month - 1, 0).getDate();

  const isCurrentMonthToday = today.getFullYear() === year && today.getMonth() + 1 === month;
  const todayDate = today.getDate();

  const cells: CalendarDay[] = [];

  // Previous month trailing days
  for (let i = startWeekday - 1; i >= 0; i--) {
    cells.push({
      dayNumber: prevMonthDays - i,
      isCurrentMonth: false,
      isToday: false,
      isPast: true,
      events: [],
    });
  }

  // Current month days
  for (let d = 1; d <= daysInMonth; d++) {
    const isPast = isCurrentMonthToday
      ? d < todayDate
      : year < today.getFullYear() ||
        (year === today.getFullYear() && month < today.getMonth() + 1);
    cells.push({
      dayNumber: d,
      isCurrentMonth: true,
      isToday: isCurrentMonthToday && todayDate === d,
      isPast,
      events: events.filter((e) => eventFallsOnDay(e, year, month, d)),
    });
  }

  // Next month leading days to fill the grid
  const remaining = 7 - (cells.length % 7);
  if (remaining < 7) {
    for (let d = 1; d <= remaining; d++) {
      cells.push({
        dayNumber: d,
        isCurrentMonth: false,
        isToday: false,
        isPast: false,
        events: [],
      });
    }
  }

  const weeks: CalendarDay[][] = [];
  for (let i = 0; i < cells.length; i += 7) {
    weeks.push(cells.slice(i, i + 7));
  }
  return weeks;
}

/** Races with a date first, earliest first. */
export function sortRacesByDate(races: CalendarEvent['races']): CalendarEvent['races'] {
  return [...races].sort((a, b) => {
    if (!a.date && !b.date) return 0;
    if (!a.date) return 1;
    if (!b.date) return -1;
    return new Date(a.date).getTime() - new Date(b.date).getTime();
  });
}

export function earliestDate(event: CalendarEvent): Date | null {
  const dates: Date[] = [];
  for (const race of event.races) {
    if (race.date) dates.push(new Date(race.date));
  }
  if (event.startDate) dates.push(new Date(event.startDate));
  if (dates.length === 0) return null;
  return dates.reduce((min, d) => (d < min ? d : min));
}

/** Keeps the order in which each colour first appears. */
export function groupEventsByColor(events: CalendarEvent[]): EventGroup[] {
  const map = new Map<string, CalendarEvent[]>();
  for (const e of events) {
    const color = e.community?.color || DEFAULT_COLOR;
    const list = map.get(color);
    if (list) {
      list.push(e);
    } else {
      map.set(color, [e]);
    }
  }
  return [...map.entries()].map(([color, evts]) => ({ color, events: evts }));
}

/**
 * Year view: one column per community that has events, in the API's order,
 * events sorted by earliest date. `emptyColumnsFor` adds columns for
 * communities without events (the ones the viewer manages).
 */
export function buildYearColumns(
  events: CalendarEvent[],
  communities: Community[],
  emptyColumnsFor: Community[] = [],
): YearCommunityColumn[] {
  const columns: YearCommunityColumn[] = [];
  const addedIds = new Set<string>();

  for (const c of communities) {
    const communityEvents = events.filter((e) => e.community?.id === c.id);
    if (communityEvents.length === 0) continue;

    const sorted = [...communityEvents].sort((a, b) => {
      const dateA = earliestDate(a);
      const dateB = earliestDate(b);
      if (!dateA && !dateB) return 0;
      if (!dateA) return 1;
      if (!dateB) return -1;
      return dateA.getTime() - dateB.getTime();
    });

    columns.push({
      id: c.id,
      name: c.name,
      color: c.color ?? DEFAULT_COLOR,
      discordUrl: c.discordUrl,
      events: sorted,
    });
    addedIds.add(c.id);
  }

  for (const c of emptyColumnsFor) {
    if (!addedIds.has(c.id)) {
      columns.push({
        id: c.id,
        name: c.name,
        color: c.color ?? DEFAULT_COLOR,
        discordUrl: c.discordUrl,
        events: [],
      });
    }
  }

  return columns;
}

/** "dd.mm.yyyy[ hh:mm][ — dd.mm.yyyy[ hh:mm]]" in the given locale; midnight means "no time". */
export function formatRaceDate(
  isoDate: string,
  isoEndDate: string | null | undefined,
  locale: string,
): string {
  const d = new Date(isoDate);
  if (isNaN(d.getTime())) return isoDate.slice(0, 10);
  const startStr = formatOne(d, isoDate, locale);

  if (isoEndDate) {
    const ed = new Date(isoEndDate);
    if (!isNaN(ed.getTime())) {
      return `${startStr} — ${formatOne(ed, isoEndDate, locale)}`;
    }
  }
  return startStr;
}

function formatOne(d: Date, iso: string, locale: string): string {
  const date = d.toLocaleDateString(locale, { day: '2-digit', month: '2-digit', year: 'numeric' });
  const hasTime = /T\d{2}:\d{2}/.test(iso) && !iso.includes('T00:00:00');
  return hasTime
    ? `${date} ${d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}`
    : date;
}
