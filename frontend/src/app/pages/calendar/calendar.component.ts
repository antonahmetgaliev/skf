import { NgTemplateOutlet } from '@angular/common';
import {
  AfterViewInit,
  Component,
  computed,
  effect,
  ElementRef,
  HostListener,
  inject,
  OnDestroy,
  OnInit,
  signal,
  viewChild,
} from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { AlertComponent } from '../../components/alert/alert.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { ToggleComponent } from '../../components/toggle/toggle.component';
import { TooltipDirective } from '../../directives/tooltip.directive';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { CalendarApiService, CalendarEvent, Community } from '../../services/calendar-api.service';
import { AuthService } from '../../services/auth.service';
import { LocaleService } from '../../services/locale.service';
import { CalendarSidebarComponent } from './calendar-sidebar/calendar-sidebar.component';
import { ChampionshipEditorComponent } from './championship-editor/championship-editor.component';
import { CommunityRequestModalComponent } from './community-request-modal/community-request-modal.component';
import {
  buildMonthGrid,
  buildYearColumns,
  CalendarDay,
  DEFAULT_COLOR,
  eventFallsOnDay,
  eventOverlapsMonth,
  formatRaceDate,
  groupEventsByColor,
  isScheduled,
  racesOnDay,
  simulatorColor,
  sortRacesByDate,
  YearCommunityColumn,
} from './calendar-events';

type ViewMode = 'month' | 'year';

const WEEK_DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const VIEW_TABS: { key: string; label: string }[] = [
  { key: 'month', label: 'calendar.month' },
  { key: 'year', label: 'calendar.year' },
];

@Component({
  selector: 'app-calendar',
  imports: [
    NgTemplateOutlet,
    RouterLink,
    TranslocoPipe,
    TooltipDirective,
    AlertComponent,
    BtnComponent,
    CalendarSidebarComponent,
    CardComponent,
    CommunityRequestModalComponent,
    ChampionshipEditorComponent,
    PageLayoutComponent,
    SpinnerComponent,
    ToggleComponent,
  ],

  templateUrl: './calendar.component.html',
  styleUrl: './calendar.component.scss',
})
export class CalendarComponent implements OnInit, AfterViewInit, OnDestroy {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly calendarApi = inject(CalendarApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly locale = inject(LocaleService);
  readonly auth = inject(AuthService);

  private chromeObserver?: ResizeObserver;
  private gridChrome = '';

  readonly weekDays = WEEK_DAY_KEYS.map((d) => `calendar.day.${d}`);
  readonly weekDaysShort = WEEK_DAY_KEYS.map((d) => `calendar.dayShort.${d}`);
  readonly viewTabs = VIEW_TABS;
  readonly viewMode = signal<ViewMode>('month');
  readonly currentYear = signal(new Date().getFullYear());
  readonly currentMonth = signal(new Date().getMonth() + 1); // 1-based
  readonly yearEvents = signal<CalendarEvent[]>([]);
  readonly loading = signal(false);
  readonly errorMessage = signal('');
  readonly selectedDay = signal<number | null>(null);

  // Month events derived from year events
  readonly events = computed(() => {
    const year = this.currentYear();
    const month = this.currentMonth();
    return this.yearEvents().filter((e) => eventOverlapsMonth(e, year, month));
  });

  // Filters
  readonly communities = signal<Community[]>([]);
  readonly selectedCommunityIds = signal<Set<string>>(new Set());
  readonly filtersOpen = signal(false);
  readonly selectedSimulator = signal<string | null>(null);

  readonly hasActiveFilters = computed(
    () => this.selectedCommunityIds().size > 0 || this.selectedSimulator() !== null,
  );

  readonly monthLabel = computed(() => {
    const d = new Date(this.currentYear(), this.currentMonth() - 1, 1);
    return d.toLocaleString(this.locale.locale, { month: 'long', year: 'numeric' });
  });

  readonly canGoBack = computed(() => {
    const now = new Date();
    return (
      this.currentYear() > now.getFullYear() ||
      (this.currentYear() === now.getFullYear() && this.currentMonth() > now.getMonth() + 1)
    );
  });

  readonly canNavigateBack = computed(() => (this.viewMode() === 'year' ? true : this.canGoBack()));

  // Filtered events for month view
  readonly filteredEvents = computed(() => this.applyFilters(this.events()));

  // Filtered events for year view
  readonly filteredYearEvents = computed(() => this.applyFilters(this.yearEvents()));

  readonly yearLoading = this.loading;
  readonly yearError = this.errorMessage;

  readonly scheduledEvents = computed(() => this.filteredEvents().filter(isScheduled));

  readonly unscheduledEvents = computed(() => this.filteredEvents().filter((e) => !isScheduled(e)));

  readonly calendarGrid = computed<CalendarDay[][]>(() => {
    return buildMonthGrid(this.currentYear(), this.currentMonth(), this.scheduledEvents());
  });

  readonly selectedDayEvents = computed<CalendarEvent[]>(() => {
    const day = this.selectedDay();
    if (day === null) return [];
    const year = this.currentYear();
    const month = this.currentMonth();
    return this.filteredEvents().filter((e) => eventFallsOnDay(e, year, month, day));
  });

  readonly selectedDayLabel = computed(() => {
    const day = this.selectedDay();
    if (day === null) return '';
    const d = new Date(this.currentYear(), this.currentMonth() - 1, day);
    return d.toLocaleDateString(this.locale.locale, {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
  });

  readonly yearLabel = computed(() => String(this.currentYear()));

  /** Label for the shared top bar — month name or year, per active view. */
  readonly periodLabel = computed(() =>
    this.viewMode() === 'month' ? this.monthLabel() : this.yearLabel(),
  );

  readonly yearCommunityColumns = computed<YearCommunityColumn[]>(() =>
    buildYearColumns(
      this.filteredYearEvents(),
      this.communities(),
      // Empty columns for the communities a manager runs. Skipped for plain
      // admins, who manage every community: each would get an empty column.
      this.auth.isAdmin() ? [] : this.managedCommunities(),
    ),
  );

  readonly availableSimulators = computed(() => {
    const sims = new Set(
      this.yearEvents()
        .map((e) => e.game)
        .filter(Boolean),
    );
    return [...sims].sort();
  });

  private managedCommunitiesLoaded = false;

  constructor() {
    effect(() => {
      const user = this.auth.user();
      if (user?.role === 'community_manager' && !this.managedCommunitiesLoaded) {
        this.managedCommunitiesLoaded = true;
        this.loadManagedCommunities();
      }
    });
  }

  ngOnInit(): void {
    this.loadCommunities();
    this.loadYearEvents();
    // Deep link from the home page "add your community" prompt
    if (this.route.snapshot.queryParamMap.get('request') === 'community') {
      // On a direct page load the user is not known yet.
      this.auth.whenLoaded().then(() => {
        if (this.auth.user()) this.openRequestModal();
      });
    }
  }

  ngAfterViewInit(): void {
    if (typeof ResizeObserver === 'undefined') return;
    this.chromeObserver = new ResizeObserver(() => this.syncGridHeight());
    this.chromeObserver.observe(this.host.nativeElement);
  }

  ngOnDestroy(): void {
    this.chromeObserver?.disconnect();
  }

  // The month grid fills exactly what the viewport has left, so it never scrolls.
  // Measured instead of hardcoded: everything above it — site header, admin
  // "view as" bar, page padding, top bar — changes height with role, locale and
  // wrapping, and any guess is wrong for somebody.
  private syncGridHeight(): void {
    const grid = this.host.nativeElement.querySelector<HTMLElement>('.calendar-grid');
    if (!grid) return;

    const above = grid.getBoundingClientRect().top + window.scrollY;
    let below = 0;
    for (let el = grid.parentElement; el && el !== document.body; el = el.parentElement) {
      const cs = getComputedStyle(el);
      below +=
        parseFloat(cs.paddingBottom) +
        parseFloat(cs.borderBottomWidth) +
        parseFloat(cs.marginBottom);
    }

    // Round up: a sub-pixel shortfall is enough to bring the scrollbar back.
    const chrome = `${Math.ceil(above + below)}px`;
    if (chrome === this.gridChrome) return; // guard the observer's own feedback loop
    this.gridChrome = chrome;
    this.host.nativeElement.style.setProperty('--calendar-chrome', chrome);
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
    const yearChanged = y !== this.currentYear();
    this.currentYear.set(y);
    this.currentMonth.set(m);
    this.selectedDay.set(null);
    if (yearChanged) {
      this.loadYearEvents();
    }
  }

  goToToday(): void {
    const now = new Date();
    const yearChanged = now.getFullYear() !== this.currentYear();
    this.currentYear.set(now.getFullYear());
    this.currentMonth.set(now.getMonth() + 1);
    this.selectedDay.set(null);
    if (yearChanged) {
      this.loadYearEvents();
    }
  }

  selectDay(day: number): void {
    this.selectedDay.set(this.selectedDay() === day ? null : day);
  }

  setViewMode(mode: string): void {
    this.viewMode.set(mode as ViewMode);
  }

  navigateYear(delta: number): void {
    this.currentYear.set(this.currentYear() + delta);
    this.loadYearEvents();
  }

  /** Single entry point for the shared top bar — dispatches on the active view. */
  navigatePeriod(delta: number): void {
    if (delta < 0 && !this.canNavigateBack()) return;
    if (this.viewMode() === 'year') {
      this.navigateYear(delta);
    } else {
      this.navigateMonth(delta);
    }
  }

  readonly sortedRaces = sortRacesByDate;
  readonly groupEventsByColor = groupEventsByColor;
  readonly getSimulatorColor = simulatorColor;

  formatRaceDate(isoDate: string, isoEndDate?: string | null): string {
    return formatRaceDate(isoDate, isoEndDate, this.locale.locale);
  }

  getRacesForSelectedDay(event: CalendarEvent): CalendarEvent['races'] {
    const day = this.selectedDay();
    if (day === null) return event.races;
    return racesOnDay(event, this.currentYear(), this.currentMonth(), day);
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
    this.selectedCommunityIds.set(new Set());
  }

  getCommunityColor(event: CalendarEvent): string {
    return event.community?.color ?? DEFAULT_COLOR;
  }

  getCommunityDiscordUrl(event: CalendarEvent): string | null {
    const id = event.community?.id;
    if (!id) return null;
    return this.communities().find((c) => c.id === id)?.discordUrl ?? null;
  }

  // ── Community management (year view) ──

  readonly fetchedManagedCommunities = signal<Community[]>([]);
  readonly managedCommunities = computed<Community[]>(() => {
    const user = this.auth.user();
    if (!user) return [];
    // Admin viewing as community_manager — show only the selected community
    if (this.auth.isRealAdmin() && this.auth.isCommunityManager()) {
      const viewId = this.auth.viewAsCommunityId();
      if (!viewId) return [];
      return this.communities().filter((c) => c.id === viewId);
    }
    // Admin (not impersonating) — outranks community manager, can manage every community
    if (this.auth.isAdmin()) {
      return this.communities();
    }
    // Real community manager — show assigned communities
    if (user.role === 'community_manager') {
      return this.fetchedManagedCommunities();
    }
    return [];
  });
  readonly addMenuOpen = signal(false);
  readonly champEditor = viewChild.required(ChampionshipEditorComponent);

  // ── Community join request ──
  readonly requestModalOpen = signal(false);
  /** Open the request form, sending the user through Discord login first if needed. */
  openRequestModal(): void {
    if (!this.auth.user()) {
      this.auth.login();
      return;
    }
    this.requestModalOpen.set(true);
  }

  toggleAddMenu(): void {
    this.addMenuOpen.update((v) => !v);
  }

  selectAddCommunity(communityId: string): void {
    this.addMenuOpen.set(false);
    this.champEditor().openAdd(communityId);
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.addMenuOpen()) return;
    const target = event.target as HTMLElement | null;
    if (!target?.closest('.add-menu')) this.addMenuOpen.set(false);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    // Modals own Escape while they are open.
    if (this.champEditor().open() || this.requestModalOpen()) return;
    if (this.addMenuOpen()) {
      this.addMenuOpen.set(false);
      return;
    }
    if (this.selectedDay() !== null) {
      this.selectedDay.set(null);
      return;
    }
    this.filtersOpen.set(false);
  }

  canManageCommunity(communityId: string | null): boolean {
    const user = this.auth.user();
    if (!user) return false;
    // Admin viewing as community_manager — check viewAsCommunityId
    if (this.auth.isRealAdmin() && this.auth.isCommunityManager()) {
      return communityId ? this.auth.viewAsCommunityId() === communityId : false;
    }
    if (this.auth.isAdmin()) return true;
    if (!communityId) return false;
    return (
      user.role === 'community_manager' &&
      (user.managedCommunityIds?.includes(communityId) ?? false)
    );
  }

  reloadCalendar(): void {
    this.loadYearEvents();
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
    try {
      const data = await firstValueFrom(this.calendarApi.getCommunitiesAdmin());
      this.fetchedManagedCommunities.set(data);
    } catch {
      // non-critical
    }
  }

  private async loadYearEvents(): Promise<void> {
    this.loading.set(true);
    this.errorMessage.set('');
    try {
      const data = await firstValueFrom(this.calendarApi.getYearEvents(this.currentYear()));
      this.yearEvents.set(data);
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
        if (!e.community || !communityIds.has(e.community.id)) return false;
      }

      // Simulator filter
      if (simulator && e.game !== simulator) return false;

      return true;
    });
  }
}
