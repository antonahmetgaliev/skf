import { NgClass } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';
import {
  ChampionshipDetails,
  ChampionshipRace,
  RaceResultEntry,
  RaceSessionKind,
  SimgridApiService,
  StandingEntry,
  StandingRace,
} from '../../services/simgrid-api.service';
import { API } from '../../api';
import {
  ChampionshipIncidentWindow,
  IncidentsApiService,
} from '../../services/incidents-api.service';
import { ChampionshipEntry, ChampionshipService } from '../../services/championship.service';
import { DataFreshnessService } from '../../services/data-freshness.service';
import { formatDate, formatGap, formatLapTime, formatNumber } from '../../utils/format';
import { AlertComponent } from '../../components/alert/alert.component';
import { BadgeComponent } from '../../components/badge/badge.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { EmptyComponent } from '../../components/empty/empty.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { TabsComponent } from '../../components/tabs/tabs.component';

@Component({
  selector: 'app-championships',
  imports: [
    RouterLink,
    NgClass,
    TranslocoPipe,
    AlertComponent,
    BadgeComponent,
    BtnComponent,
    CardComponent,
    EmptyComponent,
    PageIntroComponent,
    PageLayoutComponent,
    SpinnerComponent,
    TabsComponent,
  ],
  templateUrl: './championships.component.html',
  styleUrl: './championships.component.scss',
})
export class ChampionshipsComponent {
  readonly cs = inject(ChampionshipService);
  readonly freshness = inject(DataFreshnessService);
  private readonly api = inject(SimgridApiService);
  private readonly incidentsApi = inject(IncidentsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private standingsLoadToken = 0;
  private championshipsLoadToken = 0;
  /** Race to expand once the races load (from the `race` query param). */
  private pendingRaceId: number | null = null;

  readonly championships = signal<ChampionshipEntry[]>([]);
  readonly selectedChampionshipKey = signal<string | null>(null);
  readonly selectedChampionship = signal<ChampionshipDetails | null>(null);
  readonly standings = signal<StandingEntry[]>([]);
  readonly races = signal<StandingRace[]>([]);
  readonly loadingChampionships = signal(false);
  readonly loadingStandings = signal(false);
  readonly errorMessage = signal('');
  readonly activeTab = signal<'standings' | 'races' | 'participants'>('standings');
  readonly allRaces = signal<ChampionshipRace[]>([]);
  readonly loadingRaces = signal(false);
  /** The selected championship's incident windows by SimGrid race id. */
  readonly incidentWindows = signal<Map<number, ChampionshipIncidentWindow>>(new Map());

  readonly isStaleData = computed(() => {
    const key = this.selectedChampionshipKey();
    if (!key) return false;
    return this.freshness.hasStaleData(`${API}/championships`);
  });

  readonly isUpcomingChampionship = computed(() => {
    return this.cs.isChampionshipNotStarted(this.selectedChampionship());
  });

  readonly availableTabs = computed(() => {
    if (this.isUpcomingChampionship()) {
      return [
        { key: 'races', label: 'championships.races' },
        { key: 'participants', label: 'championships.participants' },
      ];
    }
    return [
      { key: 'standings', label: 'championships.standings' },
      { key: 'races', label: 'championships.races' },
    ];
  });

  readonly carClasses = computed(() => {
    const classes = [
      ...new Set(
        this.standings()
          .map((e) => e.carClass)
          .filter((c) => c.length > 0),
      ),
    ];
    return classes.sort();
  });
  readonly isMulticlass = computed(() => this.carClasses().length > 1);
  readonly selectedClass = signal<string | null>(null);
  readonly activeClass = computed(() => {
    if (!this.isMulticlass()) return null;
    return this.selectedClass() ?? this.carClasses()[0] ?? null;
  });
  readonly visibleStandings = computed(() => {
    const cls = this.activeClass();
    if (cls === null) return this.standings();
    return this.standings().filter((e) => e.carClass === cls);
  });
  readonly hasRaceBreakdown = computed(() =>
    this.standings().some((e) => e.raceResults.length > 0),
  );

  // Races tab: one expanded race at a time, results cached per race and session.
  readonly expandedRaceId = signal<number | null>(null);
  readonly raceSession = signal<RaceSessionKind>('race');
  readonly selectedRaceClass = signal<string | null>(null);
  readonly loadingRaceResults = signal(false);
  readonly raceResultsError = signal(false);
  private readonly raceResults = signal<Map<string, RaceResultEntry[]>>(new Map());

  readonly expandedResults = computed(() => {
    const raceId = this.expandedRaceId();
    return raceId === null
      ? null
      : (this.raceResults().get(`${raceId}:${this.raceSession()}`) ?? null);
  });
  readonly raceClasses = computed(() =>
    [...new Set((this.expandedResults() ?? []).map((e) => e.carClass))].sort(),
  );
  readonly activeRaceClass = computed(() => {
    const classes = this.raceClasses();
    if (classes.length < 2) return null;
    const selected = this.selectedRaceClass();
    return selected !== null && classes.includes(selected) ? selected : classes[0];
  });
  readonly visibleRaceResults = computed(() => {
    const cls = this.activeRaceClass();
    const results = this.expandedResults() ?? [];
    return cls === null ? results : results.filter((e) => e.carClass === cls);
  });

  constructor() {
    this.route.queryParams.subscribe((params) => {
      const race = Number(params['race']) || null;
      if (race !== this.expandedRaceId()) {
        this.pendingRaceId = race;
      }
      const id = params['id'];
      if (id) {
        const num = Number(id);
        if (Number.isFinite(num) && num > 0) {
          this.selectChampionship(`sg-${num}`);
        }
      }
    });
    void this.loadChampionships();
  }

  // ------------------------------------------------------------------
  // Format helpers (delegate to utils/service)
  // ------------------------------------------------------------------

  formatDate(value: string | null): string {
    return formatDate(value);
  }

  formatRaceDate(value: string | null): string {
    return formatDate(value, 'TBD');
  }

  formatNumber(value: number): string {
    return formatNumber(value);
  }

  getPosition(entry: StandingEntry, index: number): number {
    return this.cs.getPosition(entry, index, this.isMulticlass(), this.activeClass() !== null);
  }

  getRaceStatus(race: ChampionshipRace): 'completed' | 'upcoming' {
    return this.cs.getRaceStatus(race);
  }

  getClassIndex(carClass: string): number {
    return this.carClasses().indexOf(carClass);
  }

  getClassTabClasses(cls: string): Record<string, boolean> {
    const idx = this.getClassIndex(cls);
    return {
      'class-tab': true,
      active: this.activeClass() === cls,
      [`class-color-${idx}`]: true,
    };
  }

  getOverallColspan(): number {
    return 3 + (this.isMulticlass() ? 1 : 0) + (this.hasRaceBreakdown() ? this.races().length : 0);
  }

  // ------------------------------------------------------------------
  // Per-race results
  // ------------------------------------------------------------------

  /** Standings cell for one round: class position, or DNS/DNF/DQ. */
  formatRoundResult(entry: StandingEntry, raceIndex: number): string {
    const result = entry.raceResults.find((r) => r.raceIndex === raceIndex);
    if (!result) return '–';
    if (result.status !== 'classified') return result.status.toUpperCase();
    return result.position === null ? '–' : String(result.position);
  }

  roundResultClass(entry: StandingEntry, raceIndex: number): string {
    const result = entry.raceResults.find((r) => r.raceIndex === raceIndex);
    if (!result) return '';
    if (result.status !== 'classified') return 'round-out';
    return result.position !== null && result.position <= 3 ? 'round-podium' : '';
  }

  canExpandRace(race: ChampionshipRace): boolean {
    return this.getRaceStatus(race) === 'completed' && race.resultsAvailable;
  }

  toggleRace(race: ChampionshipRace): void {
    if (!this.canExpandRace(race)) return;
    const expanded = this.expandedRaceId() === race.id ? null : race.id;
    this.expandedRaceId.set(expanded);
    this.raceSession.set('race');
    this.selectedRaceClass.set(null);
    void this.router.navigate([], {
      queryParams: { race: expanded },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
    if (expanded !== null) void this.loadRaceResults();
  }

  setRaceSession(session: RaceSessionKind): void {
    this.raceSession.set(session);
    void this.loadRaceResults();
  }

  getRaceClassTabClasses(cls: string): Record<string, boolean> {
    return {
      'class-tab': true,
      active: this.activeRaceClass() === cls,
      [`class-color-${this.raceClassColor(cls)}`]: true,
    };
  }

  /** Colour of a class as in the standings, so both tabs agree. */
  raceClassColor(cls: string): number {
    const idx = this.getClassIndex(cls);
    return idx >= 0 ? idx : this.raceClasses().indexOf(cls);
  }

  formatLapTime(ms: number | null): string {
    return formatLapTime(ms);
  }

  /** Race time for the class leader, the gap for everyone on the lead lap. */
  formatResultTime(entry: RaceResultEntry, isClassLeader: boolean): string {
    if (entry.status !== 'classified') return '-';
    return isClassLeader ? formatLapTime(entry.totalTimeMs) : formatGap(entry.gapMs);
  }

  /** Qualifying gap: best lap versus the class's fastest. */
  formatQualifyingGap(entry: RaceResultEntry): string {
    const best = Math.min(
      ...this.visibleRaceResults()
        .filter((e) => e.carClass === entry.carClass && e.bestLapMs)
        .map((e) => e.bestLapMs as number),
    );
    if (!entry.bestLapMs || !Number.isFinite(best) || entry.bestLapMs === best) return '-';
    return formatGap(entry.bestLapMs - best);
  }

  // ------------------------------------------------------------------
  // Championship list & selection
  // ------------------------------------------------------------------

  async loadChampionships(): Promise<void> {
    const token = ++this.championshipsLoadToken;
    this.loadingChampionships.set(true);
    this.errorMessage.set('');

    try {
      const simgridList = await firstValueFrom(this.api.getChampionships());
      if (token !== this.championshipsLoadToken) return;

      const entries: ChampionshipEntry[] = simgridList.map((s) => ({
        key: `sg-${s.id}`,
        name: s.name,
        simgridItem: s,
      }));

      const sorted = entries.sort(
        (a, b) =>
          this.cs.getStatusOrder(a) - this.cs.getStatusOrder(b) || a.name.localeCompare(b.name),
      );
      this.championships.set(sorted);

      if (sorted.length === 0) {
        this.selectedChampionshipKey.set(null);
        this.selectedChampionship.set(null);
        this.standings.set([]);
        this.races.set([]);
        return;
      }

      const currentKey = this.selectedChampionshipKey();
      const selectedKey =
        currentKey !== null && sorted.some((e) => e.key === currentKey)
          ? currentKey
          : sorted[0].key;

      await this.selectAndLoad(selectedKey, true);
    } catch (error) {
      if (token !== this.championshipsLoadToken) return;
      this.errorMessage.set(this.cs.toErrorMessage(error));
      this.championships.set([]);
      this.selectedChampionship.set(null);
      this.standings.set([]);
      this.races.set([]);
    } finally {
      if (token === this.championshipsLoadToken) {
        this.loadingChampionships.set(false);
      }
    }
  }

  selectChampionship(key: string): void {
    if (this.selectedChampionshipKey() === key) return;
    void this.selectAndLoad(key, false);
  }

  private resetRaceResults(): void {
    this.expandedRaceId.set(null);
    this.raceResults.set(new Map());
    this.raceResultsError.set(false);
  }

  private async selectAndLoad(key: string, replaceUrl: boolean): Promise<void> {
    this.selectedChampionshipKey.set(key);
    this.selectedClass.set(null);
    this.errorMessage.set('');

    const entry = this.championships().find((e) => e.key === key);

    if (entry) {
      this.allRaces.set([]);
      this.resetRaceResults();
      const simgridId = entry.simgridItem.id;
      void this.router.navigate([], {
        queryParams: { id: simgridId, race: this.pendingRaceId },
        queryParamsHandling: 'merge',
        replaceUrl,
      });
      void this.loadIncidentWindows(simgridId);
      await this.loadStandings(simgridId);
    }
  }

  // ------------------------------------------------------------------
  // Tabs
  // ------------------------------------------------------------------

  setActiveTab(tab: 'standings' | 'races' | 'participants'): void {
    this.activeTab.set(tab);
    if (tab === 'races') {
      const simgridId = this.getSelectedSimgridId();
      if (simgridId !== null && this.allRaces().length === 0) {
        void this.loadAllRaces(simgridId);
      }
    }
  }

  openIncidents(simgridId: number): void {
    void this.router.navigate(['/incidents'], { queryParams: { championship: simgridId } });
  }

  // ------------------------------------------------------------------
  // Data loading
  // ------------------------------------------------------------------

  private getSelectedSimgridId(): number | null {
    const key = this.selectedChampionshipKey();
    if (!key || !key.startsWith('sg-')) return null;
    return Number(key.slice(3));
  }

  private async loadStandings(championshipId: number): Promise<void> {
    const token = ++this.standingsLoadToken;
    this.loadingStandings.set(true);
    this.errorMessage.set('');

    try {
      const [details, standingsData] = await Promise.all([
        firstValueFrom(this.api.getChampionshipById(championshipId)),
        firstValueFrom(this.api.getChampionshipStandings(championshipId)),
      ]);

      if (token !== this.standingsLoadToken) return;

      this.selectedChampionship.set(details);
      const isUpcoming = this.cs.isChampionshipNotStarted(details);
      this.activeTab.set(isUpcoming ? 'races' : 'standings');
      this.standings.set(standingsData.entries);
      this.races.set(standingsData.races);
      if (!isUpcoming) {
        this.cs.refreshDriverMap();
      }
      if (this.pendingRaceId !== null) {
        this.setActiveTab('races');
      } else if (isUpcoming && this.allRaces().length === 0) {
        void this.loadAllRaces(championshipId);
      }
    } catch (error) {
      if (token !== this.standingsLoadToken) return;
      this.errorMessage.set(this.cs.toErrorMessage(error));
      this.selectedChampionship.set(null);
      this.standings.set([]);
      this.races.set([]);
    } finally {
      if (token === this.standingsLoadToken) {
        this.loadingStandings.set(false);
      }
    }
  }

  private async loadIncidentWindows(championshipId: number): Promise<void> {
    this.incidentWindows.set(new Map());
    try {
      const windows = await firstValueFrom(
        this.incidentsApi.getChampionshipWindows(championshipId),
      );
      if (this.getSelectedSimgridId() === championshipId) {
        this.incidentWindows.set(new Map(windows.map((w) => [w.raceId, w])));
      }
    } catch {
      // Links to incidents are a convenience; the page works without them.
    }
  }

  private async loadAllRaces(championshipId: number): Promise<void> {
    this.loadingRaces.set(true);
    try {
      const races = await firstValueFrom(this.api.getChampionshipRaces(championshipId));
      if (this.getSelectedSimgridId() === championshipId) {
        this.allRaces.set(races);
        this.expandPendingRace(races);
      }
    } catch {
      if (this.getSelectedSimgridId() === championshipId) {
        this.allRaces.set([]);
      }
    } finally {
      this.loadingRaces.set(false);
    }
  }

  private expandPendingRace(races: ChampionshipRace[]): void {
    const race = races.find((r) => r.id === this.pendingRaceId);
    this.pendingRaceId = null;
    if (!race || !this.canExpandRace(race)) return;
    this.toggleRace(race);
    setTimeout(() =>
      document.getElementById(`race-${race.id}`)?.scrollIntoView({ block: 'start' }),
    );
  }

  private async loadRaceResults(): Promise<void> {
    const championshipId = this.getSelectedSimgridId();
    const raceId = this.expandedRaceId();
    const session = this.raceSession();
    const key = `${raceId}:${session}`;
    if (championshipId === null || raceId === null || this.raceResults().has(key)) return;

    this.loadingRaceResults.set(true);
    this.raceResultsError.set(false);
    try {
      const data = await firstValueFrom(this.api.getRaceResults(championshipId, raceId, session));
      if (this.getSelectedSimgridId() === championshipId) {
        this.raceResults.update((m) => new Map(m).set(key, data.entries));
      }
    } catch {
      if (this.expandedRaceId() === raceId) this.raceResultsError.set(true);
    } finally {
      this.loadingRaceResults.set(false);
    }
  }
}
