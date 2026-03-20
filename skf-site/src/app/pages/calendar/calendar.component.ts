import { NgClass } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../../services/auth.service';
import {
  CalendarApiService,
  CalendarEvent,
  CalendarEventType,
  CustomChampionshipCreate,
  CustomRaceCreate,
} from '../../services/calendar-api.service';

interface CalendarDay {
  dayNumber: number;
  isCurrentMonth: boolean;
  isToday: boolean;
  events: CalendarEvent[];
}

interface RaceFormRow {
  date: string;
  track: string;
}

const WEEK_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

@Component({
  selector: 'app-calendar',
  imports: [NgClass, FormsModule, RouterLink],
  templateUrl: './calendar.component.html',
  styleUrl: './calendar.component.scss',
})
export class CalendarComponent {
  readonly auth = inject(AuthService);
  private readonly calendarApi = inject(CalendarApiService);

  readonly weekDays = WEEK_DAYS;
  readonly currentYear = signal(new Date().getFullYear());
  readonly currentMonth = signal(new Date().getMonth() + 1); // 1-based
  readonly events = signal<CalendarEvent[]>([]);
  readonly loading = signal(false);
  readonly selectedDay = signal<number | null>(null);
  readonly errorMessage = signal('');

  // Admin modal
  readonly showCreateModal = signal(false);
  formName = '';
  formGame = '';
  formCarClass = '';
  formDescription = '';
  formRaces: RaceFormRow[] = [{ date: '', track: '' }];
  formSubmitting = false;

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
    const filtered = event.races.filter((r) => r.date && r.date.slice(0, 10) === dayStr);
    return filtered.length > 0 ? filtered : event.races;
  }

  // ── Admin: create custom championship ──

  openCreateModal(): void {
    this.formName = '';
    this.formGame = '';
    this.formCarClass = '';
    this.formDescription = '';
    this.formRaces = [{ date: '', track: '' }];
    this.showCreateModal.set(true);
  }

  closeCreateModal(): void {
    this.showCreateModal.set(false);
  }

  addRaceRow(): void {
    this.formRaces.push({ date: '', track: '' });
  }

  removeRaceRow(index: number): void {
    this.formRaces.splice(index, 1);
  }

  async submitCreate(): Promise<void> {
    if (!this.formName.trim() || !this.formGame.trim()) return;
    this.formSubmitting = true;

    const races: CustomRaceCreate[] = this.formRaces
      .filter((r) => r.date || r.track)
      .map((r) => ({
        date: r.date ? new Date(r.date).toISOString() : null,
        track: r.track || null,
      }));

    const payload: CustomChampionshipCreate = {
      name: this.formName.trim(),
      game: this.formGame.trim(),
      carClass: this.formCarClass.trim() || null,
      description: this.formDescription.trim() || null,
      races,
    };

    try {
      await firstValueFrom(this.calendarApi.createCustomChampionship(payload));
      this.showCreateModal.set(false);
      this.loadEvents();
    } catch {
      this.errorMessage.set('Failed to create championship.');
    } finally {
      this.formSubmitting = false;
    }
  }

  // ── Private ──

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
      if (race.date && race.date.slice(0, 10) === dayStr) {
        return true;
      }
    }

    // For SimGrid championships without race-level dates, check start/end range
    if (event.races.length === 0 || event.races.every((r) => !r.date)) {
      if (event.startDate && event.startDate.slice(0, 10) === dayStr) return true;
      if (event.endDate && event.endDate.slice(0, 10) === dayStr) return true;
    }

    return false;
  }
}
