import { NgClass } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import {
  ChampionshipDetails,
  ChampionshipRace,
  SimgridApiService,
  StandingEntry,
  StandingRace,
} from '../../services/simgrid-api.service';
import {
  CalendarApiService,
  CustomChampionshipOut,
} from '../../services/calendar-api.service';
import { AuthService } from '../../services/auth.service';
import { ChampionshipEntry, ChampionshipService } from '../../services/championship.service';
import { formatDate, formatNumber } from '../../utils/format';
import { AlertComponent } from '../../components/alert/alert.component';
import { BadgeComponent } from '../../components/badge/badge.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { CustomChampionshipFormComponent } from '../../components/custom-championship-form/custom-championship-form.component';
import { EmptyComponent } from '../../components/empty/empty.component';
import { GiveawayModalComponent } from '../../components/giveaway-modal/giveaway-modal.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { StandingsExportComponent } from '../../components/standings-export/standings-export.component';
import { TabsComponent } from '../../components/tabs/tabs.component';

@Component({
  selector: 'app-championships',
  imports: [
    RouterLink,
    NgClass,
    AlertComponent,
    BadgeComponent,
    BtnComponent,
    CardComponent,
    CustomChampionshipFormComponent,
    EmptyComponent,
    GiveawayModalComponent,
    PageIntroComponent,
    PageLayoutComponent,
    SpinnerComponent,
    StandingsExportComponent,
    TabsComponent,
  ],
  templateUrl: './championships.component.html',
  styleUrl: './championships.component.scss',
})
export class ChampionshipsComponent {
  readonly auth = inject(AuthService);
  readonly cs = inject(ChampionshipService);
  private readonly api = inject(SimgridApiService);
  private readonly calendarApi = inject(CalendarApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private standingsLoadToken = 0;
  private championshipsLoadToken = 0;

  readonly championships = signal<ChampionshipEntry[]>([]);
  readonly selectedChampionshipKey = signal<string | null>(null);
  readonly selectedChampionship = signal<ChampionshipDetails | null>(null);
  readonly selectedCustomChampionship = signal<CustomChampionshipOut | null>(null);
  readonly standings = signal<StandingEntry[]>([]);
  readonly races = signal<StandingRace[]>([]);
  readonly loadingChampionships = signal(false);
  readonly loadingStandings = signal(false);
  readonly errorMessage = signal('');
  readonly lastUpdated = signal<Date | null>(null);
  readonly activeTab = signal<'standings' | 'races' | 'participants'>('standings');
  readonly expandedRaceIndex = signal<number | null>(null);
  readonly allRaces = signal<ChampionshipRace[]>([]);
  readonly loadingRaces = signal(false);
  readonly deletingCustom = signal(false);
  readonly activeChampionshipIds = signal<Set<number>>(new Set());

  // Modal states
  readonly exportPreviewOpen = signal(false);
  readonly giveawayOpen = signal(false);
  readonly createModalOpen = signal(false);

  readonly isCustomSelected = computed(() => {
    const key = this.selectedChampionshipKey();
    return key !== null && key.startsWith('custom-');
  });

  readonly isUpcomingChampionship = computed(() => {
    return this.cs.isChampionshipNotStarted(this.selectedChampionship());
  });

  readonly availableTabs = computed(() => {
    if (this.isUpcomingChampionship()) {
      return [
        { key: 'races', label: 'Races' },
        { key: 'participants', label: 'Participants' },
      ];
    }
    return [
      { key: 'standings', label: 'Standings' },
      { key: 'races', label: 'Races' },
    ];
  });

  readonly carClasses = computed(() => {
    const classes = [...new Set(this.standings().map((e) => e.carClass).filter((c) => c.length > 0))];
    return classes.sort();
  });
  readonly isMulticlass = computed(() => this.carClasses().length > 1);
  readonly selectedClass = signal<string | null>(null);
  readonly visibleStandings = computed(() => {
    const cls = this.selectedClass();
    if (!this.isMulticlass() || cls === null) return this.standings();
    return this.standings().filter((e) => e.carClass === cls);
  });

  constructor() {
    this.route.queryParams.subscribe((params) => {
      const id = params['id'];
      if (id) {
        const num = Number(id);
        if (Number.isFinite(num) && num > 0) {
          this.selectChampionship(`sg-${num}`);
        } else {
          this.selectChampionship(`custom-${id}`);
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
    return this.cs.getPosition(entry, index, this.isMulticlass(), this.selectedClass() !== null);
  }

  formatRacePosition(entry: StandingEntry, race: StandingRace, raceIndex: number): string {
    return this.cs.formatRacePosition(entry, race, raceIndex);
  }

  getRaceLabel(index: number): string {
    return this.cs.getRaceLabel(index);
  }

  getRaceTitle(race: StandingRace, index: number): string {
    return this.cs.getRaceTitle(race, index);
  }

  getRaceStatus(race: ChampionshipRace): 'completed' | 'upcoming' {
    return this.cs.getRaceStatus(race);
  }

  hasRaceResults(race: ChampionshipRace): boolean {
    return this.cs.hasRaceResults(race, this.races());
  }

  getRaceResultsForRace(race: ChampionshipRace, raceIndex: number) {
    return this.cs.getRaceResultsForRace(
      this.standings(), this.races(), this.cs.driverUuidBySimgridId(), race, raceIndex,
    );
  }

  getClassIndex(carClass: string): number {
    return this.carClasses().indexOf(carClass);
  }

  getClassTabClasses(cls: string): Record<string, boolean> {
    const idx = this.getClassIndex(cls);
    return {
      'class-tab': true,
      active: this.selectedClass() === cls,
      [`class-color-${idx}`]: true,
    };
  }

  getOverallColspan(): number {
    return 5 + this.races().length + (this.isMulticlass() ? 1 : 0);
  }

  // ------------------------------------------------------------------
  // Championship list & selection
  // ------------------------------------------------------------------

  async loadChampionships(): Promise<void> {
    const token = ++this.championshipsLoadToken;
    this.loadingChampionships.set(true);
    this.errorMessage.set('');

    try {
      const [simgridList, customList, activeIds] = await Promise.all([
        firstValueFrom(this.api.getChampionships()),
        this.auth.isAdmin()
          ? firstValueFrom(this.calendarApi.getCustomChampionships())
          : Promise.resolve([] as CustomChampionshipOut[]),
        firstValueFrom(this.api.getActiveChampionships()),
      ]);
      if (token !== this.championshipsLoadToken) return;
      this.activeChampionshipIds.set(new Set(activeIds));

      const entries: ChampionshipEntry[] = [
        ...customList.map((c) => ({
          key: `custom-${c.id}`,
          source: 'custom' as const,
          name: c.name,
          customItem: c,
        })),
        ...simgridList.map((s) => ({
          key: `sg-${s.id}`,
          source: 'simgrid' as const,
          name: s.name,
          simgridItem: s,
        })),
      ];

      const sorted = entries.sort(
        (a, b) => this.cs.getStatusOrder(a) - this.cs.getStatusOrder(b) || a.name.localeCompare(b.name),
      );
      this.championships.set(sorted);

      if (sorted.length === 0) {
        this.selectedChampionshipKey.set(null);
        this.selectedChampionship.set(null);
        this.selectedCustomChampionship.set(null);
        this.standings.set([]);
        this.races.set([]);
        return;
      }

      const currentKey = this.selectedChampionshipKey();
      const selectedKey =
        currentKey !== null && sorted.some((e) => e.key === currentKey) ? currentKey : sorted[0].key;

      await this.selectAndLoad(selectedKey, true);
    } catch (error) {
      if (token !== this.championshipsLoadToken) return;
      this.errorMessage.set(this.cs.toErrorMessage(error));
      this.championships.set([]);
      this.selectedChampionship.set(null);
      this.selectedCustomChampionship.set(null);
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

  private async selectAndLoad(key: string, replaceUrl: boolean): Promise<void> {
    this.selectedChampionshipKey.set(key);
    this.selectedClass.set(null);
    this.expandedRaceIndex.set(null);
    this.errorMessage.set('');

    const entry = this.championships().find((e) => e.key === key);

    if (entry?.source === 'custom' && entry.customItem) {
      const c = entry.customItem;
      this.selectedChampionship.set(null);
      this.selectedCustomChampionship.set(c);
      this.standings.set([]);
      this.races.set([]);
      this.activeTab.set('races');
      this.allRaces.set(
        c.races.map((r, i) => ({
          id: i,
          displayName: r.track ?? `Race ${i + 1}`,
          startsAt: r.date,
          track: r.track,
          resultsAvailable: false,
          ended: false,
        })),
      );
      this.lastUpdated.set(null);
      void this.router.navigate([], {
        queryParams: { id: c.id },
        queryParamsHandling: 'merge',
        replaceUrl,
      });
    } else if (entry?.source === 'simgrid' && entry.simgridItem) {
      this.selectedCustomChampionship.set(null);
      this.allRaces.set([]);
      const simgridId = entry.simgridItem.id;
      void this.router.navigate([], {
        queryParams: { id: simgridId },
        queryParamsHandling: 'merge',
        replaceUrl,
      });
      await this.loadStandings(simgridId);
    }
  }

  // ------------------------------------------------------------------
  // Tabs
  // ------------------------------------------------------------------

  setActiveTab(tab: 'standings' | 'races' | 'participants'): void {
    this.activeTab.set(tab);
    this.expandedRaceIndex.set(null);
    if (tab === 'races') {
      const simgridId = this.getSelectedSimgridId();
      if (simgridId !== null && this.allRaces().length === 0) {
        void this.loadAllRaces(simgridId);
      }
    }
  }

  toggleRaceExpansion(raceIndex: number): void {
    this.expandedRaceIndex.set(this.expandedRaceIndex() === raceIndex ? null : raceIndex);
  }

  // ------------------------------------------------------------------
  // Admin actions
  // ------------------------------------------------------------------

  async toggleActive(simgridId: number): Promise<void> {
    const ids = this.activeChampionshipIds();
    try {
      if (ids.has(simgridId)) {
        await firstValueFrom(this.api.removeActiveChampionship(simgridId));
        const next = new Set(ids);
        next.delete(simgridId);
        this.activeChampionshipIds.set(next);
      } else {
        await firstValueFrom(this.api.addActiveChampionship(simgridId));
        this.activeChampionshipIds.set(new Set([...ids, simgridId]));
      }
      void this.loadChampionships();
    } catch {
      this.errorMessage.set('Failed to update active status.');
    }
  }

  isChampionshipActive(simgridId: number): boolean {
    return this.activeChampionshipIds().has(simgridId);
  }

  async deleteCustomChampionship(): Promise<void> {
    const custom = this.selectedCustomChampionship();
    if (!custom || this.deletingCustom()) return;
    this.deletingCustom.set(true);
    try {
      await firstValueFrom(this.calendarApi.deleteCustomChampionship(custom.id));
      this.selectedCustomChampionship.set(null);
      this.selectedChampionshipKey.set(null);
      void this.loadChampionships();
    } catch {
      this.errorMessage.set('Failed to delete championship.');
    } finally {
      this.deletingCustom.set(false);
    }
  }

  openStandingsExportPreview(): void {
    if (this.loadingStandings() || !this.selectedChampionship() || this.standings().length === 0) return;
    this.exportPreviewOpen.set(true);
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
      this.activeTab.set(this.cs.isChampionshipNotStarted(details) ? 'races' : 'standings');
      this.standings.set(standingsData.entries);
      this.races.set(standingsData.races);
      this.lastUpdated.set(new Date());
      if (!this.cs.isChampionshipNotStarted(details)) {
        this.cs.ensureDriverMapLoaded();
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

  private async loadAllRaces(championshipId: number): Promise<void> {
    this.loadingRaces.set(true);
    try {
      const races = await firstValueFrom(this.api.getChampionshipRaces(championshipId));
      if (this.getSelectedSimgridId() === championshipId) {
        this.allRaces.set(races);
      }
    } catch {
      if (this.getSelectedSimgridId() === championshipId) {
        this.allRaces.set([]);
      }
    } finally {
      this.loadingRaces.set(false);
    }
  }
}
