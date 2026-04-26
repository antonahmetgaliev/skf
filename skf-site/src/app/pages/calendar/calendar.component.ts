import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AlertComponent } from '../../components/alert/alert.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { ToggleComponent } from '../../components/toggle/toggle.component';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import {
  CalendarApiService,
  CalendarEvent,
  Community,
} from '../../services/calendar-api.service';
import { toLocalDateStr } from '../../utils/date';

interface CalendarDay {
  dayNumber: number;
  isCurrentMonth: boolean;
  isToday: boolean;
  events: CalendarEvent[];
  communityColors: string[];
}

interface YearMonthGroup {
  month: number;
  label: string;
  events: CalendarEvent[];
}

interface YearCommunityColumn {
  id: string;
  name: string;
  color: string;
  months: YearMonthGroup[];
}

type ViewMode = 'month' | 'year';

const DEFAULT_COLOR = '#f5bf24'; // gold fallback
const WEEK_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const VIEW_TABS: { key: string; label: string }[] = [
  { key: 'month', label: 'Month' },
  { key: 'year', label: 'Year' },
];

@Component({
  selector: 'app-calendar',
  imports: [FormsModule, RouterLink, AlertComponent, BtnComponent, CardComponent, PageIntroComponent, PageLayoutComponent, SpinnerComponent, ToggleComponent],

  templateUrl: './calendar.component.html',
  styleUrl: './calendar.component.scss',
})
export class CalendarComponent implements OnInit {
  private readonly calendarApi = inject(CalendarApiService);

  readonly weekDays = WEEK_DAYS;
  readonly viewTabs = VIEW_TABS;
  readonly viewMode = signal<ViewMode>('month');
  readonly currentYear = signal(new Date().getFullYear());
  readonly currentMonth = signal(new Date().getMonth() + 1); // 1-based
  readonly events = signal<CalendarEvent[]>([]);
  readonly loading = signal(false);
  readonly selectedDay = signal<number | null>(null);
  readonly errorMessage = signal('');

  // Year view state
  readonly yearEvents = signal<CalendarEvent[]>([]);
  readonly yearLoading = signal(false);
  readonly yearError = signal('');

  // Filters
  readonly communities = signal<Community[]>([]);
  readonly selectedCommunityIds = signal<Set<string>>(new Set());
  readonly filtersOpen = signal(false);
  readonly selectedSimulator = signal<string | null>(null);
  readonly selectedCarClass = signal<string | null>(null);

  readonly monthLabel = computed(() => {
    const d = new Date(this.currentYear(), this.currentMonth() - 1, 1);
    return d.toLocaleString('en-US', { month: 'long', year: 'numeric' });
  });

  readonly canGoBack = computed(() => {
    const now = new Date();
    return (
      this.currentYear() > now.getFullYear() ||
      (this.currentYear() === now.getFullYear() && this.currentMonth() > now.getMonth() + 1)
    );
  });

  // Filtered events for month view
  readonly filteredEvents = computed(() => this.applyFilters(this.events()));

  // Filtered events for year view
  readonly filteredYearEvents = computed(() => this.applyFilters(this.yearEvents()));

  readonly scheduledEvents = computed(() =>
    this.filteredEvents().filter((e) => e.startDate || e.endDate || e.races.some((r) => r.date)),
  );

  readonly unscheduledEvents = computed(() =>
    this.filteredEvents().filter((e) => !e.startDate && !e.endDate && !e.races.some((r) => r.date)),
  );

  readonly calendarGrid = computed<CalendarDay[][]>(() => {
    return this.buildGrid(this.currentYear(), this.currentMonth(), this.scheduledEvents());
  });

  readonly selectedDayEvents = computed<CalendarEvent[]>(() => {
    const day = this.selectedDay();
    if (day === null) return [];
    const year = this.currentYear();
    const month = this.currentMonth();
    return this.filteredEvents().filter((e) => this.eventFallsOnDay(e, year, month, day));
  });

  readonly selectedDayLabel = computed(() => {
    const day = this.selectedDay();
    if (day === null) return '';
    const d = new Date(this.currentYear(), this.currentMonth() - 1, day);
    return d.toLocaleDateString('en-GB', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
  });

  readonly yearLabel = computed(() => String(this.currentYear()));

  readonly yearEventsByMonth = computed<YearMonthGroup[]>(() => {
    const events = this.filteredYearEvents();
    const year = this.currentYear();
    const groups: YearMonthGroup[] = [];

    for (let m = 1; m <= 12; m++) {
      const monthEvents = events.filter((e) => this.eventFallsInMonth(e, year, m));
      if (monthEvents.length === 0) continue;
      const label = new Date(year, m - 1, 1).toLocaleString('en-US', { month: 'long' });
      groups.push({ month: m, label, events: monthEvents });
    }
    return groups;
  });

  readonly yearCommunityColumns = computed<YearCommunityColumn[]>(() => {
    const events = this.filteredYearEvents();
    const year = this.currentYear();
    const communities = this.communities();

    // Communities are returned from API with SKF first (sorted by is_skf desc, name)
    const columnDefs = communities.map((c) => ({
      id: c.id,
      name: c.name,
      color: c.color ?? DEFAULT_COLOR,
    }));

    const columns: YearCommunityColumn[] = [];

    for (const def of columnDefs) {
      const communityEvents = events.filter((e) => e.communityId === def.id);
      if (communityEvents.length === 0) continue;

      const months: YearMonthGroup[] = [];
      for (let m = 1; m <= 12; m++) {
        const monthEvents = communityEvents.filter((e) => this.eventFallsInMonth(e, year, m));
        if (monthEvents.length === 0) continue;
        const label = new Date(year, m - 1, 1).toLocaleString('en-US', { month: 'short' });
        months.push({ month: m, label, events: monthEvents });
      }

      columns.push({ id: def.id, name: def.name, color: def.color, months });
    }

    return columns;
  });


  readonly availableSimulators = computed(() => {
    const all = this.viewMode() === 'year' ? this.yearEvents() : this.events();
    const sims = new Set(all.map((e) => e.game).filter(Boolean));
    return [...sims].sort();
  });

  readonly availableCarClasses = computed(() => {
    const all = this.viewMode() === 'year' ? this.yearEvents() : this.events();
    const classes = new Set(all.map((e) => e.carClass).filter((c): c is string => !!c));
    return [...classes].sort();
  });

  ngOnInit(): void {
    this.loadCommunities();
    this.loadEvents();
  }

  navigateMonth(delta: number): void {
    let m = this.currentMonth() + delta;
    let y = this.currentYear();
    if (m < 1) {
      m = 12;
      y--;
    } else if (m > 12) {
      m = 1;
      y++;
    }
    this.currentYear.set(y);
    this.currentMonth.set(m);
    this.selectedDay.set(null);
    this.loadEvents();
  }

  goToToday(): void {
    const now = new Date();
    this.currentYear.set(now.getFullYear());
    this.currentMonth.set(now.getMonth() + 1);
    this.selectedDay.set(null);
    this.loadEvents();
  }

  selectDay(day: number): void {
    this.selectedDay.set(this.selectedDay() === day ? null : day);
  }

  setViewMode(mode: string): void {
    this.viewMode.set(mode as ViewMode);
    if (mode === 'year') {
      this.loadYearEvents();
    }
  }

  navigateYear(delta: number): void {
    this.currentYear.set(this.currentYear() + delta);
    if (this.viewMode() === 'year') {
      this.loadYearEvents();
    } else {
      this.loadEvents();
    }
  }

  sortedRaces(races: CalendarEvent['races']): CalendarEvent['races'] {
    return [...races].sort((a, b) => {
      if (!a.date && !b.date) return 0;
      if (!a.date) return 1;
      if (!b.date) return -1;
      return new Date(a.date).getTime() - new Date(b.date).getTime();
    });
  }

  formatRaceDate(isoDate: string): string {
    const d = new Date(isoDate);
    if (isNaN(d.getTime())) return isoDate.slice(0, 10);
    const date = d.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit', year: 'numeric' });
    const hasTime = /T\d{2}:\d{2}/.test(isoDate) && !isoDate.includes('T00:00:00');
    if (!hasTime) return date;
    const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    return `${date} ${time}`;
  }

  getRacesForSelectedDay(event: CalendarEvent): CalendarEvent['races'] {
    const day = this.selectedDay();
    if (day === null) return event.races;
    const dayStr = `${this.currentYear()}-${String(this.currentMonth()).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const filtered = event.races.filter((r) => r.date && toLocalDateStr(r.date) === dayStr);
    return filtered.length > 0 ? filtered : event.races;
  }

  // ── Filter methods ──

  toggleCommunity(id: string | null): void {
    if (id === null) {
      // "All" — clear selection
      this.selectedCommunityIds.set(new Set());
      return;
    }
    const current = new Set(this.selectedCommunityIds());
    if (current.has(id)) {
      current.delete(id);
    } else {
      current.add(id);
    }
    this.selectedCommunityIds.set(current);
  }

  isCommunitySelected(id: string): boolean {
    return this.selectedCommunityIds().has(id);
  }

  toggleFilters(): void {
    this.filtersOpen.update((v) => !v);
  }

  clearFilters(): void {
    this.selectedSimulator.set(null);
    this.selectedCarClass.set(null);
  }

  hasActiveFilters(): boolean {
    return this.selectedSimulator() !== null || this.selectedCarClass() !== null;
  }


  getCommunityColor(event: CalendarEvent): string {
    return event.communityColor ?? DEFAULT_COLOR;
  }

  // ── Private ──

  private async loadCommunities(): Promise<void> {
    try {
      const data = await firstValueFrom(this.calendarApi.getCommunities());
      this.communities.set(data);
    } catch {
      // Communities are non-critical; calendar still works without them
    }
  }

  private async loadYearEvents(): Promise<void> {
    this.yearLoading.set(true);
    this.yearError.set('');
    try {
      const data = await firstValueFrom(
        this.calendarApi.getYearEvents(this.currentYear()),
      );
      this.yearEvents.set(data);
    } catch {
      this.yearError.set('Failed to load calendar events.');
    } finally {
      this.yearLoading.set(false);
    }
  }

  private async loadEvents(): Promise<void> {
    this.loading.set(true);
    this.errorMessage.set('');
    try {
      const data = await firstValueFrom(
        this.calendarApi.getEvents(this.currentYear(), this.currentMonth()),
      );
      this.events.set(data);
    } catch {
      this.errorMessage.set('Failed to load calendar events.');
    } finally {
      this.loading.set(false);
    }
  }

  tileBackground(day: CalendarDay): string | null {
    if (day.communityColors.length === 0) return null;

    const opacity = 0.55;
    if (day.communityColors.length === 1) {
      return this.hexToRgba(day.communityColors[0], opacity);
    }

    // Multiple communities: vertical stripes
    const stops: string[] = [];
    const step = 100 / day.communityColors.length;
    for (let i = 0; i < day.communityColors.length; i++) {
      const color = this.hexToRgba(day.communityColors[i], opacity);
      stops.push(`${color} ${step * i}%`, `${color} ${step * (i + 1)}%`);
    }
    return `linear-gradient(to right, ${stops.join(', ')})`;
  }

  private hexToRgba(hex: string, alpha: number): string {
    const h = hex.replace('#', '');
    const r = parseInt(h.substring(0, 2), 16);
    const g = parseInt(h.substring(2, 4), 16);
    const b = parseInt(h.substring(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  private applyFilters(events: CalendarEvent[]): CalendarEvent[] {
    const communityIds = this.selectedCommunityIds();
    const simulator = this.selectedSimulator();
    const carClass = this.selectedCarClass();

    return events.filter((e) => {
      // Community filter
      if (communityIds.size > 0) {
        if (!e.communityId || !communityIds.has(e.communityId)) return false;
      }

      // Simulator filter
      if (simulator && e.game !== simulator) return false;

      // Car class filter
      if (carClass && e.carClass !== carClass) return false;

      return true;
    });
  }

  private buildGrid(year: number, month: number, events: CalendarEvent[]): CalendarDay[][] {
    const firstDay = new Date(year, month - 1, 1);
    // Monday = 0, Sunday = 6
    let startWeekday = firstDay.getDay() - 1;
    if (startWeekday < 0) startWeekday = 6;

    const daysInMonth = new Date(year, month, 0).getDate();
    const prevMonthDays = new Date(year, month - 1, 0).getDate();

    const today = new Date();
    const isCurrentMonthToday =
      today.getFullYear() === year && today.getMonth() + 1 === month;

    const cells: CalendarDay[] = [];

    // Previous month trailing days
    for (let i = startWeekday - 1; i >= 0; i--) {
      cells.push({
        dayNumber: prevMonthDays - i,
        isCurrentMonth: false,
        isToday: false,
        events: [],
        communityColors: [],
      });
    }

    // Current month days
    for (let d = 1; d <= daysInMonth; d++) {
      const dayEvents = events.filter((e) => this.eventFallsOnDay(e, year, month, d));
      // Collect unique community colors for this day
      const colorSet = new Set<string>();
      for (const e of dayEvents) {
        colorSet.add(e.communityColor ?? DEFAULT_COLOR);
      }
      cells.push({
        dayNumber: d,
        isCurrentMonth: true,
        isToday: isCurrentMonthToday && today.getDate() === d,
        events: dayEvents,
        communityColors: [...colorSet],
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
          events: [],
          communityColors: [],
        });
      }
    }

    // Split into weeks
    const weeks: CalendarDay[][] = [];
    for (let i = 0; i < cells.length; i += 7) {
      weeks.push(cells.slice(i, i + 7));
    }
    return weeks;
  }

  private eventFallsOnDay(
    event: CalendarEvent,
    year: number,
    month: number,
    day: number,
  ): boolean {
    const dayStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

    // Check individual races
    for (const race of event.races) {
      if (race.date && toLocalDateStr(race.date) === dayStr) {
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

  private eventFallsInMonth(event: CalendarEvent, year: number, month: number): boolean {
    const prefix = `${year}-${String(month).padStart(2, '0')}`;

    for (const race of event.races) {
      if (race.date && toLocalDateStr(race.date).startsWith(prefix)) {
        return true;
      }
    }

    // Check start/end date range overlap with month
    const monthStart = new Date(year, month - 1, 1);
    const monthEnd = new Date(year, month, 0, 23, 59, 59);

    const start = event.startDate ? new Date(event.startDate) : null;
    const end = event.endDate ? new Date(event.endDate) : null;

    if (start && end) return start <= monthEnd && end >= monthStart;
    if (start) return start >= monthStart && start <= monthEnd;
    if (end) return end >= monthStart && end <= monthEnd;

    return false;
  }
}
