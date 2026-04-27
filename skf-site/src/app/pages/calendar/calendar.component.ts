import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AlertComponent } from '../../components/alert/alert.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { FormFieldComponent } from '../../components/form-field/form-field.component';
import { ModalComponent } from '../../components/modal/modal.component';
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
  CustomChampionshipCreate,
  CustomRaceOut,
} from '../../services/calendar-api.service';
import { AuthService } from '../../services/auth.service';
import { toLocalDateStr } from '../../utils/date';

interface CalendarDay {
  dayNumber: number;
  isCurrentMonth: boolean;
  isToday: boolean;
  events: CalendarEvent[];
}

interface EventGroup {
  color: string;
  events: CalendarEvent[];
}

interface YearCommunityColumn {
  id: string;
  name: string;
  color: string;
  discordUrl: string | null;
  events: CalendarEvent[];
}

type ViewMode = 'month' | 'year';

const DEFAULT_COLOR = '#f5bf24'; // gold fallback
const WEEK_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const WEEK_DAYS_SHORT = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
const VIEW_TABS: { key: string; label: string }[] = [
  { key: 'month', label: 'Month' },
  { key: 'year', label: 'Year' },
];

@Component({
  selector: 'app-calendar',
  imports: [FormsModule, RouterLink, AlertComponent, BtnComponent, CardComponent, FormFieldComponent, ModalComponent, PageIntroComponent, PageLayoutComponent, SpinnerComponent, ToggleComponent],

  templateUrl: './calendar.component.html',
  styleUrl: './calendar.component.scss',
})
export class CalendarComponent implements OnInit {
  private readonly calendarApi = inject(CalendarApiService);
  readonly auth = inject(AuthService);

  readonly weekDays = WEEK_DAYS;
  readonly weekDaysShort = WEEK_DAYS_SHORT;
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

  readonly yearCommunityColumns = computed<YearCommunityColumn[]>(() => {
    const events = this.filteredYearEvents();
    const communities = this.communities();
    const managedCommunities = this.managedCommunities();

    // Communities are returned from API with SKF first (sorted by is_skf desc, name)
    const columns: YearCommunityColumn[] = [];
    const addedIds = new Set<string>();

    for (const c of communities) {
      const communityEvents = events.filter((e) => e.communityId === c.id);
      if (communityEvents.length === 0) continue;

      // Sort by earliest race date or start date
      const sorted = [...communityEvents].sort((a, b) => {
        const dateA = this.getEarliestDate(a);
        const dateB = this.getEarliestDate(b);
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

    // Add empty columns for managed communities with no events
    for (const mc of managedCommunities) {
      if (!addedIds.has(mc.id)) {
        columns.push({
          id: mc.id,
          name: mc.name,
          color: mc.color ?? DEFAULT_COLOR,
          discordUrl: mc.discordUrl,
          events: [],
        });
      }
    }

    return columns;
  });


  readonly availableSimulators = computed(() => {
    const all = this.viewMode() === 'year' ? this.yearEvents() : this.events();
    const sims = new Set(all.map((e) => e.game).filter(Boolean));
    return [...sims].sort();
  });


  ngOnInit(): void {
    this.loadCommunities();
    this.loadEvents();
    this.loadManagedCommunities();
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
  }

  hasActiveFilters(): boolean {
    return this.selectedSimulator() !== null;
  }


  getCommunityColor(event: CalendarEvent): string {
    return event.communityColor ?? DEFAULT_COLOR;
  }

  groupEventsByColor(events: CalendarEvent[]): EventGroup[] {
    const map = new Map<string, CalendarEvent[]>();
    for (const e of events) {
      const color = e.communityColor || DEFAULT_COLOR;
      const list = map.get(color);
      if (list) {
        list.push(e);
      } else {
        map.set(color, [e]);
      }
    }
    return [...map.entries()].map(([color, evts]) => ({ color, events: evts }));
  }

  getCommunityDiscordUrl(event: CalendarEvent): string | null {
    if (!event.communityId) return null;
    const community = this.communities().find((c) => c.id === event.communityId);
    return community?.discordUrl ?? null;
  }

  // ── Community management (year view) ──

  readonly allCommunitiesAdmin = signal<Community[]>([]);
  readonly managedCommunities = computed<Community[]>(() => {
    const user = this.auth.user();
    if (!user) return [];
    // Admin viewing as community_manager — show only the selected community
    if (this.auth.isRealAdmin() && this.auth.isCommunityManager()) {
      const viewId = this.auth.viewAsCommunityId();
      if (!viewId) return [];
      return this.communities().filter((c) => c.id === viewId);
    }
    // Real community manager — show assigned communities
    if (user.role === 'community_manager') {
      return this.allCommunitiesAdmin();
    }
    return [];
  });
  readonly simulators = signal<string[]>([]);
  readonly champForm = signal<{ name: string; game: string; carClass: string | null; description: string | null; races: { id?: string; track: string; date: string }[] }>({
    name: '', game: '', carClass: null, description: null, races: [],
  });
  readonly editingChampId = signal<string | null>(null);
  readonly champCommunityId = signal<string | null>(null);
  readonly champModalOpen = signal(false);
  private originalRaceIds: string[] = [];

  canManageCommunity(communityId: string | null): boolean {
    const user = this.auth.user();
    if (!user) return false;
    // Admin viewing as community_manager — check viewAsCommunityId
    if (this.auth.isRealAdmin() && this.auth.isCommunityManager()) {
      return communityId ? this.auth.viewAsCommunityId() === communityId : false;
    }
    if (this.auth.isAdmin()) return true;
    if (!communityId) return false;
    return user.role === 'community_manager' && (user.managedCommunityIds?.includes(communityId) ?? false);
  }

  openAddChampionship(communityId: string): void {
    this.champForm.set({ name: '', game: '', carClass: null, description: null, races: [] });
    this.editingChampId.set(null);
    this.champCommunityId.set(communityId);
    this.champModalOpen.set(true);
    if (this.simulators().length === 0) {
      this.calendarApi.getSimulators().subscribe({ next: (d) => this.simulators.set(d) });
    }
  }

  editChampionship(event: CalendarEvent): void {
    this.editingChampId.set(event.customChampionshipId);
    this.champCommunityId.set(event.communityId);
    this.champForm.set({
      name: event.name,
      game: event.game,
      carClass: event.carClass,
      description: event.description,
      races: [],
    });
    this.originalRaceIds = [];
    this.champModalOpen.set(true);
    if (this.simulators().length === 0) {
      this.calendarApi.getSimulators().subscribe({ next: (d) => this.simulators.set(d) });
    }
    // Load full championship to get races with IDs
    if (event.communityId) {
      this.calendarApi.getCustomChampionships(event.communityId).subscribe({
        next: (champs) => {
          const champ = champs.find((c) => c.id === event.customChampionshipId);
          if (champ) {
            const races = champ.races.map((r) => ({
              id: r.id,
              track: r.track ?? '',
              date: r.date ? r.date.slice(0, 16) : '',
            }));
            this.originalRaceIds = champ.races.map((r) => r.id);
            this.champForm.update((f) => ({ ...f, races }));
          }
        },
      });
    }
  }

  saveChampionship(): void {
    const form = this.champForm();
    if (!form.name.trim() || !form.game.trim()) return;

    const editId = this.editingChampId();
    if (editId) {
      this.calendarApi.updateCustomChampionship(editId, {
        name: form.name.trim(),
        game: form.game.trim(),
        carClass: form.carClass?.trim() || null,
        description: form.description?.trim() || null,
      }).subscribe({
        next: () => {
          // Reconcile races: delete removed, add new
          const currentIds = form.races.filter((r) => r.id).map((r) => r.id!);
          const toDelete = this.originalRaceIds.filter((id) => !currentIds.includes(id));
          const toAdd = form.races.filter((r) => !r.id && (r.track.trim() || r.date));

          const ops: Promise<unknown>[] = [];
          for (const id of toDelete) {
            ops.push(firstValueFrom(this.calendarApi.deleteRace(editId, id)));
          }
          for (const r of toAdd) {
            ops.push(firstValueFrom(this.calendarApi.addRace(editId, {
              track: r.track.trim() || null,
              date: this.withLocalTzOffset(r.date || null),
            })));
          }
          Promise.all(ops).finally(() => {
            this.champModalOpen.set(false);
            this.reloadCalendar();
          });
        },
      });
    } else {
      const communityId = this.champCommunityId();
      if (!communityId) return;
      const payload: CustomChampionshipCreate = {
        name: form.name.trim(),
        game: form.game.trim(),
        communityId,
        gameId: null,
        carClass: form.carClass?.trim() || null,
        description: form.description?.trim() || null,
        races: form.races
          .filter((r) => r.track.trim() || r.date)
          .map((r) => ({
            track: r.track.trim() || null,
            date: this.withLocalTzOffset(r.date || null),
          })),
      };
      this.calendarApi.createCustomChampionship(payload).subscribe({
        next: () => {
          this.champModalOpen.set(false);
          this.reloadCalendar();
        },
      });
    }
  }

  deleteChampionship(event: CalendarEvent): void {
    if (!event.customChampionshipId) return;
    if (!window.confirm(`Delete "${event.name}"?`)) return;
    this.calendarApi.deleteCustomChampionship(event.customChampionshipId).subscribe({
      next: () => this.reloadCalendar(),
    });
  }

  private reloadCalendar(): void {
    this.loadEvents();
    if (this.viewMode() === 'year') {
      this.loadYearEvents();
    }
  }

  updateChampField(field: 'name' | 'game' | 'carClass' | 'description', value: string | null): void {
    this.champForm.update((f) => ({ ...f, [field]: value }));
  }

  addRaceRow(): void {
    this.champForm.update((f) => ({ ...f, races: [...f.races, { track: '', date: '' }] }));
  }

  updateRaceRow(index: number, field: 'track' | 'date', value: string): void {
    this.champForm.update((f) => {
      const races = [...f.races];
      races[index] = { ...races[index], [field]: value };
      return { ...f, races };
    });
  }

  removeRaceRow(index: number): void {
    this.champForm.update((f) => ({ ...f, races: f.races.filter((_, i) => i !== index) }));
  }

  private withLocalTzOffset(date: string | null): string | null {
    if (!date) return null;
    const parts = date.split(':');
    const base = parts.length >= 3 ? date : `${date}:00`;
    const offset = new Date().getTimezoneOffset();
    const sign = offset <= 0 ? '+' : '-';
    const absH = String(Math.floor(Math.abs(offset) / 60)).padStart(2, '0');
    const absM = String(Math.abs(offset) % 60).padStart(2, '0');
    return `${base}${sign}${absH}:${absM}`;
  }

  private getEarliestDate(event: CalendarEvent): Date | null {
    const dates: Date[] = [];
    for (const race of event.races) {
      if (race.date) dates.push(new Date(race.date));
    }
    if (event.startDate) dates.push(new Date(event.startDate));
    if (dates.length === 0) return null;
    return dates.reduce((min, d) => (d < min ? d : min));
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

  private async loadManagedCommunities(): Promise<void> {
    const user = this.auth.user();
    if (user?.role !== 'community_manager') return;
    try {
      const data = await firstValueFrom(this.calendarApi.getCommunitiesAdmin());
      this.allCommunitiesAdmin.set(data);
    } catch {
      // non-critical
    }
  }

  async loadYearEvents(): Promise<void> {
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


  private applyFilters(events: CalendarEvent[]): CalendarEvent[] {
    const communityIds = this.selectedCommunityIds();
    const simulator = this.selectedSimulator();

    return events.filter((e) => {
      // Community filter
      if (communityIds.size > 0) {
        if (!e.communityId || !communityIds.has(e.communityId)) return false;
      }

      // Simulator filter
      if (simulator && e.game !== simulator) return false;

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
      });
    }

    // Current month days
    for (let d = 1; d <= daysInMonth; d++) {
      const dayEvents = events.filter((e) => this.eventFallsOnDay(e, year, month, d));
      cells.push({
        dayNumber: d,
        isCurrentMonth: true,
        isToday: isCurrentMonthToday && today.getDate() === d,
        events: dayEvents,
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

}
