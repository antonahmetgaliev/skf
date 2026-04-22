import { NgClass } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { AlertComponent } from '../../components/alert/alert.component';
import { BadgeComponent } from '../../components/badge/badge.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { TabsComponent } from '../../components/tabs/tabs.component';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import {
  CalendarApiService,
  CalendarEvent,
  CalendarEventType,
} from '../../services/calendar-api.service';
import { toLocalDateStr } from '../../utils/date';

interface CalendarDay {
  dayNumber: number;
  isCurrentMonth: boolean;
  isToday: boolean;
  events: CalendarEvent[];
}

interface YearMonthGroup {
  month: number;
  label: string;
  events: CalendarEvent[];
}

type ViewMode = 'month' | 'year';

const WEEK_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const VIEW_TABS: { key: string; label: string }[] = [
  { key: 'month', label: 'Month' },
  { key: 'year', label: 'Year' },
];

@Component({
  selector: 'app-calendar',
  imports: [NgClass, RouterLink, AlertComponent, BadgeComponent, BtnComponent, CardComponent, PageIntroComponent, PageLayoutComponent, SpinnerComponent, TabsComponent],
  templateUrl: './calendar.component.html',
  styleUrl: './calendar.component.scss',
})
export class CalendarComponent {
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

  readonly monthLabel = computed(() => {
    const d = new Date(this.currentYear(), this.currentMonth() - 1, 1);
    return d.toLocaleString('en-US', { month: 'long', year: 'numeric' });
  });

  readonly scheduledEvents = computed(() =>
    this.events().filter((e) => e.startDate || e.endDate || e.races.some((r) => r.date)),
  );

  readonly unscheduledEvents = computed(() =>
    this.events().filter((e) => !e.startDate && !e.endDate && !e.races.some((r) => r.date)),
  );

  readonly calendarGrid = computed<CalendarDay[][]>(() => {
    return this.buildGrid(this.currentYear(), this.currentMonth(), this.scheduledEvents());
  });

  readonly selectedDayEvents = computed<CalendarEvent[]>(() => {
    const day = this.selectedDay();
    if (day === null) return [];
    const year = this.currentYear();
    const month = this.currentMonth();
    return this.events().filter((e) => this.eventFallsOnDay(e, year, month, day));
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
    const events = this.yearEvents();
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

  constructor() {
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

  getEventTypeLabel(type: CalendarEventType): string {
    return type.charAt(0).toUpperCase() + type.slice(1);
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

  // ── Private ──

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
      });
    }

    // Current month days
    for (let d = 1; d <= daysInMonth; d++) {
      cells.push({
        dayNumber: d,
        isCurrentMonth: true,
        isToday: isCurrentMonthToday && today.getDate() === d,
        events: events.filter((e) => this.eventFallsOnDay(e, year, month, d)),
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
