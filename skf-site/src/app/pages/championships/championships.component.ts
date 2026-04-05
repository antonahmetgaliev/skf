import { HttpErrorResponse } from '@angular/common/http';
import { NgClass } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { Component, ElementRef, ViewChild, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import {
  ChampionshipDetails,
  ChampionshipListItem,
  ChampionshipRace,
  ParticipatingUser,
  SimgridApiService,
  StandingEntry,
  StandingRace
} from '../../services/simgrid-api.service';
import {
  CalendarApiService,
  CustomChampionshipCreate,
  CustomChampionshipOut,
  CustomRaceCreate,
} from '../../services/calendar-api.service';
import { AuthService } from '../../services/auth.service';
import { BwpApiService } from '../../services/bwp-api.service';
import { AlertComponent } from '../../components/alert/alert.component';
import { BadgeComponent } from '../../components/badge/badge.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { FormFieldComponent } from '../../components/form-field/form-field.component';
import { CardComponent } from '../../components/card/card.component';
import { EmptyComponent } from '../../components/empty/empty.component';
import { ModalComponent } from '../../components/modal/modal.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { TabsComponent } from '../../components/tabs/tabs.component';

interface RaceFormRow {
  date: string;
  track: string;
}

interface ChampionshipEntry {
  key: string; // unique: 'sg-123' or 'custom-uuid'
  source: 'simgrid' | 'custom';
  name: string;
  simgridItem?: ChampionshipListItem;
  customItem?: CustomChampionshipOut;
}

interface CachedStandingsData {
  details: ChampionshipDetails;
  entries: StandingEntry[];
  races: StandingRace[];
  fetchedAt: Date;
}

@Component({
  selector: 'app-championships',
  imports: [RouterLink, NgClass, FormsModule, AlertComponent, BadgeComponent, FormFieldComponent, PageIntroComponent, BtnComponent, CardComponent, EmptyComponent, ModalComponent, PageLayoutComponent, SpinnerComponent, TabsComponent],
  templateUrl: './championships.component.html',
  styleUrl: './championships.component.scss'
})
export class ChampionshipsComponent {
  readonly auth = inject(AuthService);
  private readonly api = inject(SimgridApiService);
  private readonly calendarApi = inject(CalendarApiService);
  private readonly bwpApi = inject(BwpApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly cacheTtlMs = 60000;
  private readonly standingsCache = new Map<number, CachedStandingsData>();
  private standingsLoadToken = 0;
  private championshipsLoadToken = 0;
  private readonly exportWidth = 1920;
  private readonly exportHeight = 1080;
  private readonly dateFormatter = new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  });

  @ViewChild('standingsExportCanvas')
  private standingsExportCanvas?: ElementRef<HTMLCanvasElement>;

  readonly championships = signal<ChampionshipEntry[]>([]);
  readonly selectedChampionshipKey = signal<string | null>(null);
  readonly selectedChampionship = signal<ChampionshipDetails | null>(null);
  readonly selectedCustomChampionship = signal<CustomChampionshipOut | null>(null);
  readonly standings = signal<StandingEntry[]>([]);
  readonly races = signal<StandingRace[]>([]);
  readonly loadingChampionships = signal(false);
  readonly loadingStandings = signal(false);
  readonly exportPreviewOpen = signal(false);
  readonly exportRendering = signal(false);
  readonly giveawayOpen = signal(false);
  readonly giveawayMinRaces = signal(1);
  readonly giveawayDrivers = signal<{ id: number; displayName: string; racesCount: number }[]>([]);
  readonly giveawayWinner = signal<string | null>(null);
  readonly errorMessage = signal('');
  readonly infoMessage = signal('');
  readonly staleWarning = signal(false);
  readonly lastUpdated = signal<Date | null>(null);
  readonly driverUuidBySimgridId = signal<Map<number, string>>(new Map());
  readonly activeTab = signal<'standings' | 'races' | 'participants'>('standings');
  readonly expandedRaceIndex = signal<number | null>(null);
  readonly allRaces = signal<ChampionshipRace[]>([]);
  readonly loadingRaces = signal(false);
  readonly deletingCustom = signal(false);
  readonly activeChampionshipIds = signal<Set<number>>(new Set());
  readonly participants = signal<ParticipatingUser[]>([]);
  readonly loadingParticipants = signal(false);

  readonly isCustomSelected = computed(() => {
    const key = this.selectedChampionshipKey();
    return key !== null && key.startsWith('custom-');
  });

  readonly isUpcomingChampionship = computed(() => {
    const entry = this.championships().find(e => e.key === this.selectedChampionshipKey());
    if (!entry || entry.source !== 'simgrid' || !entry.simgridItem) return false;
    return this.getStatusOrder(entry) === 1;
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

  // Admin: create custom championship
  readonly createModalOpen = signal(false);
  formName = '';
  formGame = '';
  formCarClass = '';
  formDescription = '';
  formRaces: RaceFormRow[] = [{ date: '', track: '' }];
  formSubmitting = false;

  readonly carClasses = computed(() => {
    const classes = [...new Set(this.standings().map(e => e.carClass).filter(c => c.length > 0))];
    return classes.sort();
  });
  readonly isMulticlass = computed(() => this.carClasses().length > 1);
  readonly selectedClass = signal<string | null>(null);
  readonly visibleStandings = computed(() => {
    const cls = this.selectedClass();
    if (!this.isMulticlass() || cls === null) return this.standings();
    return this.standings().filter(e => e.carClass === cls);
  });

  openCreateModal(): void {
    this.formName = '';
    this.formGame = '';
    this.formCarClass = '';
    this.formDescription = '';
    this.formRaces = [{ date: '', track: '' }];
    this.createModalOpen.set(true);
  }

  closeCreateModal(): void {
    this.createModalOpen.set(false);
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
      this.createModalOpen.set(false);
      void this.loadChampionships();
    } catch {
      this.errorMessage.set('Failed to create championship.');
    } finally {
      this.formSubmitting = false;
    }
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

  constructor() {
    this.route.queryParams.subscribe((params) => {
      const id = params['id'];
      if (id) {
        // Could be numeric (simgrid) or uuid (custom)
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

  private getStatusOrder(entry: ChampionshipEntry): number {
    if (entry.source === 'custom') return -1; // custom always on top
    const item = entry.simgridItem!;
    const today = new Date().toISOString().slice(0, 10);
    if (item.startDate && item.startDate.slice(0, 10) > today) return 1;
    if (item.eventCompleted) return 3;
    if (item.endDate && item.endDate.slice(0, 10) < today) return 3;
    if (item.startDate && item.startDate.slice(0, 10) <= today) return 0;
    if (item.acceptingRegistrations) return 0;
    return 2;
  }

  getChampionshipStatusClass(entry: ChampionshipEntry): string {
    if (entry.source === 'custom') return 'championship--custom';
    const order = this.getStatusOrder(entry);
    if (order === 0) return 'championship--active';
    if (order === 1) return 'championship--future';
    if (order === 3) return 'championship--finished';
    return '';
  }

  getChampionshipStatusLabel(entry: ChampionshipEntry): string | null {
    if (entry.source === 'custom') return this.auth.isAdmin() ? 'Custom' : null;
    const order = this.getStatusOrder(entry);
    if (order === 0) return 'Active';
    if (order === 1) return 'Upcoming';
    if (order === 3) return 'Finished';
    return null;
  }

  async loadChampionships(): Promise<void> {
    const token = ++this.championshipsLoadToken;
    this.loadingChampionships.set(true);
    this.errorMessage.set('');
    this.infoMessage.set('');

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
        (a, b) => this.getStatusOrder(a) - this.getStatusOrder(b)
          || a.name.localeCompare(b.name)
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
        currentKey !== null && sorted.some((e) => e.key === currentKey)
          ? currentKey
          : sorted[0].key;

      await this.selectAndLoad(selectedKey, true);
    } catch (error) {
      if (token !== this.championshipsLoadToken) return;
      this.errorMessage.set(this.toErrorMessage(error));
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
      // Show custom championship details directly
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
      this.staleWarning.set(false);
      void this.router.navigate([], {
        queryParams: { id: c.id },
        queryParamsHandling: 'merge',
        replaceUrl,
      });
    } else if (entry?.source === 'simgrid' && entry.simgridItem) {
      this.selectedCustomChampionship.set(null);
      this.participants.set([]);
      this.allRaces.set([]);
      const isUpcoming = this.getStatusOrder(entry) === 1;
      this.activeTab.set(isUpcoming ? 'races' : 'standings');
      const simgridId = entry.simgridItem.id;
      void this.router.navigate([], {
        queryParams: { id: simgridId },
        queryParamsHandling: 'merge',
        replaceUrl,
      });
      if (isUpcoming) {
        await this.loadChampionshipDetails(simgridId);
        void this.loadAllRaces(simgridId);
      } else {
        await this.loadStandings(simgridId);
      }
    }
  }

  setActiveTab(tab: 'standings' | 'races' | 'participants'): void {
    this.activeTab.set(tab);
    this.expandedRaceIndex.set(null);
    const simgridId = this.getSelectedSimgridId();
    if (simgridId === null) return;
    if (tab === 'races' && this.allRaces().length === 0) {
      void this.loadAllRaces(simgridId);
    }
    if (tab === 'participants' && this.participants().length === 0) {
      void this.loadParticipants(simgridId);
    }
  }

  toggleRaceExpansion(raceIndex: number): void {
    this.expandedRaceIndex.set(
      this.expandedRaceIndex() === raceIndex ? null : raceIndex
    );
  }

  getRaceResultsForRace(race: ChampionshipRace, raceIndex: number): { position: number | null; displayName: string; car: string; carClass: string; dns: boolean; driverUuid: string | null }[] {
    // Find the matching StandingRace by ID to extract per-driver results
    const standingRace = this.races().find((r) => r.id === race.id);
    const standingRaceIndex = standingRace ? this.races().indexOf(standingRace) : raceIndex;

    if (!standingRace) return [];

    return this.standings()
      .map((entry) => {
        const result = this.getRaceResult(entry, standingRace, standingRaceIndex);
        return {
          position: result?.position ?? null,
          displayName: entry.displayName,
          car: entry.car,
          carClass: entry.carClass,
          dns: result?.dns ?? false,
          driverUuid: this.driverUuidBySimgridId().get(entry.id) ?? null,
        };
      })
      .filter((r) => r.position !== null || r.dns)
      .sort((a, b) => {
        if (a.position === null && b.position === null) return 0;
        if (a.position === null) return 1;
        if (b.position === null) return -1;
        return a.position - b.position;
      });
  }

  formatRaceDate(value: string | null): string {
    if (!value) return 'TBD';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return this.dateFormatter.format(parsed);
  }

  getRaceStatus(race: ChampionshipRace): 'completed' | 'upcoming' {
    return race.ended || race.resultsAvailable ? 'completed' : 'upcoming';
  }

  hasRaceResults(race: ChampionshipRace): boolean {
    return this.races().some((r) => r.id === race.id);
  }


  openStandingsExportPreview(): void {
    if (this.loadingStandings() || !this.selectedChampionship() || this.standings().length === 0) {
      return;
    }

    this.exportPreviewOpen.set(true);
    setTimeout(() => {
      void this.renderStandingsExportPreview();
    }, 0);
  }

  closeStandingsExportPreview(): void {
    this.exportPreviewOpen.set(false);
  }

  downloadStandingsExportJpg(): void {
    const canvas = this.standingsExportCanvas?.nativeElement;
    if (!canvas) {
      return;
    }

    const championshipName = this.selectedChampionship()?.name ?? 'championship-standings';
    const fileName = `${this.toSlug(championshipName)}-standings.jpg`;

    canvas.toBlob((blob) => {
      if (!blob) {
        return;
      }

      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = fileName;
      link.click();
      URL.revokeObjectURL(url);
    }, 'image/jpeg', 0.93);
  }

  getPosition(entry: StandingEntry, index: number): number {
    if (this.isMulticlass() && this.selectedClass() !== null) {
      return index + 1;
    }
    return entry.position ?? index + 1;
  }

  getClassIndex(carClass: string): number {
    return this.carClasses().indexOf(carClass);
  }

  getClassTabClasses(cls: string): Record<string, boolean> {
    const idx = this.getClassIndex(cls);
    return {
      'class-tab': true,
      'active': this.selectedClass() === cls,
      [`class-color-${idx}`]: true,
    };
  }

  getOverallColspan(): number {
    return 5 + this.races().length + (this.isMulticlass() ? 1 : 0);
  }

  formatDate(value: string | null): string {
    if (!value) {
      return '-';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return value;
    }
    return this.dateFormatter.format(parsed);
  }

  formatNumber(value: number): string {
    const isWhole = Math.abs(value % 1) < 0.00001;
    return isWhole ? String(Math.trunc(value)) : value.toFixed(1);
  }

  getRaceLabel(index: number): string {
    return `R${index + 1}`;
  }

  getRaceTitle(race: StandingRace, index: number): string {
    const datePart = race.startsAt ? this.formatDate(race.startsAt) : 'TBD';
    return `${this.getRaceLabel(index)} - ${race.displayName} (${datePart})`;
  }

  formatRacePosition(entry: StandingEntry, race: StandingRace, raceIndex: number): string {
    const result = this.getRaceResult(entry, race, raceIndex);
    if (!result || result.position === null) {
      return result?.dns ? 'DNS' : '-';
    }

    return String(result.position);
  }

  // ------------------------------------------------------------------
  // Giveaway modal
  // ------------------------------------------------------------------

  openGiveawayModal(): void {
    this.giveawayMinRaces.set(1);
    this.giveawayWinner.set(null);
    this.updateGiveawayList();
    this.giveawayOpen.set(true);
  }

  closeGiveawayModal(): void {
    this.giveawayOpen.set(false);
  }

  onGiveawayMinRacesChange(event: Event): void {
    const value = parseInt((event.target as HTMLInputElement).value, 10);
    this.giveawayMinRaces.set(Number.isFinite(value) && value > 0 ? value : 1);
    this.giveawayWinner.set(null);
    this.updateGiveawayList();
  }

  pickRandomDriver(): void {
    const drivers = this.giveawayDrivers();
    if (drivers.length === 0) return;
    const index = Math.floor(Math.random() * drivers.length);
    this.giveawayWinner.set(drivers[index].displayName);
  }

  private countRacesDriven(entry: StandingEntry): number {
    return entry.raceResults.filter((r) => r.position !== null).length;
  }

  private updateGiveawayList(): void {
    const min = this.giveawayMinRaces();
    const eligible = this.standings()
      .filter((e) => !e.dsq)
      .map((e) => ({ id: e.id, displayName: e.displayName, racesCount: this.countRacesDriven(e) }))
      .filter((d) => d.racesCount >= min)
      .sort((a, b) => b.racesCount - a.racesCount || a.displayName.localeCompare(b.displayName));
    this.giveawayDrivers.set(eligible);
  }

  private getRaceResult(
    entry: StandingEntry,
    race: StandingRace,
    raceIndex: number
  ): { points: number | null; position: number | null; dns: boolean } | null {
    const byRaceId = entry.raceResults.find(
      (item) => item.raceId !== null && item.raceId === race.id
    );
    if (byRaceId) {
      return byRaceId;
    }

    return entry.raceResults.find((item) => item.raceIndex === raceIndex) ?? null;
  }

  private async renderStandingsExportPreview(): Promise<void> {
    const canvas = this.standingsExportCanvas?.nativeElement;
    const championship = this.selectedChampionship();
    if (!canvas || !championship) {
      return;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      return;
    }

    this.exportRendering.set(true);

    try {
      canvas.width = this.exportWidth;
      canvas.height = this.exportHeight;

      const [backgroundImage, logoImage, lightTextureImage, yellowTextureImage, darkTextureImage] =
        await Promise.all([
          this.loadImage('skf-background.png'),
          this.loadImage('skf-logo.png'),
          this.loadImage('skf-poly-light.png'),
          this.loadImage('skf-poly-yellow.png'),
          this.loadImage('skf-poly-dark.png')
        ]);

      const { leagueName, seasonName } = this.splitLeagueAndSeason(championship.name);
      const roundName = this.getPosterRoundName();

      const width = canvas.width;
      const height = canvas.height;

      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = '#eceff2';
      ctx.fillRect(0, 0, width, height);

      if (lightTextureImage) {
        this.drawImageCover(ctx, lightTextureImage, 0, 0, width, height, 0.78);
      } else {
        this.drawLowPolyLayer(
          ctx,
          0,
          0,
          width,
          height,
          134,
          ['#ffffff', '#f1f2f4', '#e6e8ec', '#d8dce2'],
          0.72
        );
      }

      if (backgroundImage) {
        this.drawImageCover(ctx, backgroundImage, 0, 0, width, height, 0.12);
      }

      const bandPath = new Path2D();
      bandPath.moveTo(-220, 320);
      bandPath.lineTo(width + 180, 130);
      bandPath.lineTo(width + 180, 870);
      bandPath.lineTo(-220, 1060);
      bandPath.closePath();

      ctx.fillStyle = '#0d121b';
      ctx.fill(bandPath);

      ctx.save();
      ctx.clip(bandPath);
      if (darkTextureImage) {
        this.drawImageCover(ctx, darkTextureImage, -160, 80, width + 320, height + 180, 0.9);
      } else {
        this.drawLowPolyLayer(
          ctx,
          -120,
          130,
          width + 260,
          height + 160,
          114,
          ['#0b0f16', '#101722', '#18202d', '#080d13'],
          0.95
        );
      }
      ctx.restore();

      const topYellowPath = new Path2D();
      topYellowPath.moveTo(-230, 296);
      topYellowPath.lineTo(width + 190, 112);
      topYellowPath.lineTo(width + 190, 192);
      topYellowPath.lineTo(-230, 376);
      topYellowPath.closePath();
      ctx.fillStyle = '#f5be2d';
      ctx.fill(topYellowPath);

      ctx.save();
      ctx.clip(topYellowPath);
      if (yellowTextureImage) {
        this.drawImageCover(ctx, yellowTextureImage, -140, 24, width + 280, 430, 0.42);
      } else {
        this.drawLowPolyLayer(
          ctx,
          -150,
          0,
          width + 300,
          420,
          98,
          ['#f8d646', '#f5be2d', '#e8ad11', '#ffd63a'],
          0.44
        );
      }
      ctx.restore();

      const bottomYellowPath = new Path2D();
      bottomYellowPath.moveTo(-230, 938);
      bottomYellowPath.lineTo(width + 190, 756);
      bottomYellowPath.lineTo(width + 190, 834);
      bottomYellowPath.lineTo(-230, 1020);
      bottomYellowPath.closePath();
      ctx.fillStyle = '#f5be2d';
      ctx.fill(bottomYellowPath);

      ctx.save();
      ctx.clip(bottomYellowPath);
      if (yellowTextureImage) {
        this.drawImageCover(ctx, yellowTextureImage, -160, 680, width + 320, 420, 0.4);
      } else {
        this.drawLowPolyLayer(
          ctx,
          -160,
          650,
          width + 320,
          450,
          98,
          ['#f8d646', '#f5be2d', '#e8ad11', '#ffd63a'],
          0.42
        );
      }
      ctx.restore();

      const titlePlatePath = new Path2D();
      titlePlatePath.moveTo(0, 0);
      titlePlatePath.lineTo(990, 0);
      titlePlatePath.lineTo(922, 284);
      titlePlatePath.lineTo(0, 412);
      titlePlatePath.closePath();

      ctx.fillStyle = 'rgba(247, 249, 252, 0.95)';
      ctx.fill(titlePlatePath);

      if (lightTextureImage) {
        ctx.save();
        ctx.clip(titlePlatePath);
        this.drawImageCover(ctx, lightTextureImage, -40, -20, 1120, 460, 0.38);
        ctx.restore();
      }

      ctx.fillStyle = '#0d1118';
      ctx.font = '900 162px "Bahnschrift", "Arial Black", sans-serif';
      ctx.fillText('STANDINGS', 70, 204);

      ctx.fillStyle = '#111823';
      ctx.font = '800 58px "Bahnschrift", "Segoe UI", sans-serif';
      const leagueBottomY = this.drawWrappedText(
        ctx,
        leagueName.toUpperCase(),
        80,
        274,
        900,
        64,
        2
      );

      if (seasonName.length > 0) {
        ctx.fillStyle = '#f2bf2d';
        ctx.font = '900 76px "Bahnschrift", "Segoe UI", sans-serif';
        ctx.fillText(seasonName, 80, leagueBottomY + 82);
      }

      const roundBadgeText = this.truncateText(ctx, this.getPosterRoundLabel(roundName), 360);
      ctx.font = '800 40px "Bahnschrift", "Segoe UI", sans-serif';
      const roundTextWidth = ctx.measureText(roundBadgeText).width;
      const roundBadgeWidth = roundTextWidth + 62;
      const roundBadgeX = width - roundBadgeWidth - 96;
      const roundBadgeY = 236;

      if (roundBadgeText.length > 0) {
        ctx.fillStyle = '#121925';
        this.fillRoundedRect(ctx, roundBadgeX, roundBadgeY, roundBadgeWidth, 62, 14);
        ctx.strokeStyle = 'rgba(245, 190, 26, 0.85)';
        ctx.lineWidth = 2;
        this.strokeRoundedRect(ctx, roundBadgeX, roundBadgeY, roundBadgeWidth, 62, 14);

        ctx.fillStyle = '#f5be2d';
        ctx.fillText(roundBadgeText, roundBadgeX + 28, roundBadgeY + 44);
      }

      if (logoImage) {
        const logoSize = 176;
        const logoX = width - logoSize - 76;
        const logoY = 26;
        const radius = logoSize / 2;

        ctx.save();
        ctx.beginPath();
        ctx.arc(logoX + radius, logoY + radius, radius, 0, Math.PI * 2);
        ctx.closePath();
        ctx.clip();
        ctx.drawImage(logoImage, logoX, logoY, logoSize, logoSize);
        ctx.restore();

        ctx.strokeStyle = 'rgba(255, 255, 255, 0.72)';
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.arc(logoX + radius, logoY + radius, radius - 2, 0, Math.PI * 2);
        ctx.stroke();
      }

      const panelX = 60;
      const panelY = 392;
      const panelWidth = width - panelX * 2;
      const panelHeight = height - panelY - 54;

      const panelGradient = ctx.createLinearGradient(panelX, panelY, panelX, panelY + panelHeight);
      panelGradient.addColorStop(0, 'rgba(7, 11, 18, 0.96)');
      panelGradient.addColorStop(1, 'rgba(10, 14, 21, 0.96)');
      ctx.fillStyle = panelGradient;
      this.fillRoundedRect(ctx, panelX, panelY, panelWidth, panelHeight, 24);
      ctx.strokeStyle = 'rgba(245, 190, 26, 0.68)';
      ctx.lineWidth = 2;
      this.strokeRoundedRect(ctx, panelX, panelY, panelWidth, panelHeight, 24);

      ctx.fillStyle = '#f5c22f';
      ctx.font = '800 34px "Bahnschrift", "Segoe UI", sans-serif';
      ctx.fillText('POSITIONS', panelX + 24, panelY + 52);

      const standings = this.standings();
      const splitIndex = Math.ceil(standings.length / 2);
      const leftEntries = standings.slice(0, splitIndex);
      const rightEntries = standings.slice(splitIndex);

      const columnsGap = 26;
      const columnsX = panelX + 22;
      const columnsY = panelY + 80;
      const columnsHeight = panelHeight - 100;
      const columnWidth = (panelWidth - 44 - columnsGap) / 2;

      this.drawStandingsColumn(ctx, columnsX, columnsY, columnWidth, columnsHeight, leftEntries, 0);
      this.drawStandingsColumn(
        ctx,
        columnsX + columnWidth + columnsGap,
        columnsY,
        columnWidth,
        columnsHeight,
        rightEntries,
        splitIndex
      );
    } finally {
      this.exportRendering.set(false);
    }
  }

  private drawStandingsColumn(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    entries: StandingEntry[],
    globalOffset: number
  ): void {
    const races = this.races().slice(0, 4);
    const raceCount = races.length;

    const headerHeight = 46;
    const rowCount = Math.max(entries.length, 1);
    const rowHeight = Math.max(28, Math.floor((height - headerHeight - 8) / rowCount));

    const innerPadding = 12;
    const posWidth = 62;
    const scoreWidth = 76;
    const raceCellWidth = raceCount > 0 ? 44 : 0;
    const raceAreaWidth = raceCellWidth * raceCount;
    const driverWidth = width - innerPadding * 2 - posWidth - scoreWidth - raceAreaWidth - 26;

    const posX = x + innerPadding;
    const driverX = posX + posWidth + 9;
    const scoreX = driverX + driverWidth + 8;
    const raceX = scoreX + scoreWidth + 8;

    ctx.fillStyle = 'rgba(255, 255, 255, 0.07)';
    this.fillRoundedRect(ctx, x, y, width, height, 16);

    ctx.fillStyle = 'rgba(255, 255, 255, 0.2)';
    this.fillRoundedRect(ctx, x, y, width, headerHeight, 12);

    ctx.fillStyle = '#f5f9ff';
    ctx.font = '800 16px "Bahnschrift", "Segoe UI", sans-serif';
    ctx.fillText('POS', posX + 7, y + 30);
    ctx.fillText('DRIVER', driverX, y + 30);
    this.drawCenteredText(ctx, 'SCORE', scoreX + scoreWidth / 2, y + 30);

    races.forEach((_, raceIndex) => {
      this.drawCenteredText(
        ctx,
        this.getRaceLabel(raceIndex),
        raceX + raceCellWidth * raceIndex + raceCellWidth / 2,
        y + 30
      );
    });

    entries.forEach((entry, rowIndex) => {
      const rowY = y + headerHeight + rowIndex * rowHeight;
      ctx.fillStyle = rowIndex % 2 === 0 ? 'rgba(255, 255, 255, 0.05)' : 'rgba(255, 255, 255, 0.1)';
      ctx.fillRect(x + 1, rowY, width - 2, rowHeight);

      const rank = this.getPosition(entry, globalOffset + rowIndex);
      const badgeColor =
        rank === 1
          ? '#f5be2d'
          : rank === 2
            ? '#cfd7e1'
            : rank === 3
              ? '#d19a5c'
              : '#2d3950';

      const badgeX = posX;
      const badgeY = rowY + 5;
      const badgeWidth = posWidth - 8;
      const badgeHeight = rowHeight - 10;

      ctx.fillStyle = badgeColor;
      this.fillRoundedRect(ctx, badgeX, badgeY, badgeWidth, badgeHeight, 9);

      ctx.fillStyle = rank <= 3 ? '#0f1621' : '#f4f8ff';
      const rankFontSize = Math.max(14, Math.min(18, badgeHeight - 2));
      ctx.font = `800 ${rankFontSize}px "Segoe UI", sans-serif`;
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(rank), badgeX + badgeWidth / 2, badgeY + badgeHeight / 2 + 0.5);
      ctx.restore();

      ctx.fillStyle = '#f6f9ff';
      ctx.font = '600 21px "Segoe UI", sans-serif';
      const driverName = this.truncateText(ctx, entry.displayName, Math.max(120, driverWidth - (entry.dsq ? 54 : 4)));
      ctx.fillText(driverName, driverX, rowY + rowHeight * 0.69);

      if (entry.dsq) {
        const nameWidth = ctx.measureText(driverName).width;
        const dsqX = driverX + nameWidth + 6;
        const dsqY = rowY + rowHeight * 0.69 - 13;
        const dsqW = 40;
        const dsqH = 18;
        ctx.fillStyle = '#c0392b';
        this.fillRoundedRect(ctx, dsqX, dsqY, dsqW, dsqH, 4);
        ctx.fillStyle = '#ffffff';
        ctx.font = '800 11px "Segoe UI", sans-serif';
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('DSQ', dsqX + dsqW / 2, dsqY + dsqH / 2 + 0.5);
        ctx.restore();
      }

      ctx.fillStyle = '#f5be2d';
      ctx.font = '800 20px "Segoe UI", sans-serif';
      this.drawCenteredText(
        ctx,
        this.formatNumber(entry.score),
        scoreX + scoreWidth / 2,
        rowY + rowHeight * 0.69
      );

      races.forEach((race, raceIndex) => {
        const value = this.formatRacePosition(entry, race, raceIndex);
        const numericValue = Number(value);
        const isPodium = Number.isFinite(numericValue) && numericValue > 0 && numericValue <= 3;

        ctx.fillStyle = isPodium ? '#f5be2d' : '#f4f8ff';
        ctx.font = '700 19px "Segoe UI", sans-serif';
        this.drawCenteredText(
          ctx,
          value,
          raceX + raceCellWidth * raceIndex + raceCellWidth / 2,
          rowY + rowHeight * 0.69
        );
      });
    });
  }

  private drawLowPolyLayer(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    cellSize: number,
    palette: readonly string[],
    alpha: number
  ): void {
    const cols = Math.ceil(width / cellSize) + 1;
    const rows = Math.ceil(height / cellSize) + 1;

    ctx.save();
    ctx.globalAlpha = alpha;

    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const x0 = x + col * cellSize;
        const y0 = y + row * cellSize;
        const x1 = x0 + cellSize;
        const y1 = y0 + cellSize;

        const wiggleX = (((col * 29 + row * 17) % 9) - 4) * 2.2;
        const wiggleY = (((col * 11 + row * 23) % 9) - 4) * 2.2;
        const mx = x0 + cellSize / 2 + wiggleX;
        const my = y0 + cellSize / 2 + wiggleY;

        const colorA = palette[Math.abs(col * 13 + row * 7) % palette.length];
        const colorB = palette[Math.abs(col * 5 + row * 19 + 3) % palette.length];

        ctx.fillStyle = colorA;
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y0);
        ctx.lineTo(mx, my);
        ctx.closePath();
        ctx.fill();

        ctx.fillStyle = colorB;
        ctx.beginPath();
        ctx.moveTo(x0, y1);
        ctx.lineTo(x1, y1);
        ctx.lineTo(mx, my);
        ctx.closePath();
        ctx.fill();
      }
    }

    ctx.restore();
  }

  private splitLeagueAndSeason(name: string): { leagueName: string; seasonName: string } {
    const normalized = name.replace(/\s+/g, ' ').trim();
    const seasonMatch = normalized.match(/^(.*?)(\d{4}\s*S\d+)\s*$/i);

    if (seasonMatch) {
      return {
        leagueName: seasonMatch[1].trim(),
        seasonName: seasonMatch[2].toUpperCase()
      };
    }

    return {
      leagueName: normalized,
      seasonName: ''
    };
  }

  private getPosterRoundName(): string {
    const races = [...this.races()];
    if (races.length === 0) {
      return 'ROUND TBD';
    }

    const toTime = (value: string | null): number => {
      if (!value) {
        return Number.NEGATIVE_INFINITY;
      }
      const parsed = new Date(value).getTime();
      return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
    };

    const byDateDesc = (a: StandingRace, b: StandingRace): number => toTime(b.startsAt) - toTime(a.startsAt);

    const concludedRace = races.filter((race) => race.resultsAvailable || race.ended).sort(byDateDesc)[0];
    const latestRace = races.sort(byDateDesc)[0];
    const targetRace = concludedRace ?? latestRace;

    const roundName = targetRace?.displayName?.trim();
    return roundName && roundName.length > 0 ? roundName.toUpperCase() : 'ROUND TBD';
  }

  private getPosterRoundLabel(roundName: string): string {
    const roundMatch = roundName.match(/\bround\s*\d+\b/i);
    if (roundMatch) {
      return roundMatch[0].toUpperCase();
    }

    const cleaned = roundName
      .replace(/\s*[-:|]\s*/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();

    return cleaned.length > 0 ? cleaned.toUpperCase() : 'ROUND TBD';
  }

  private drawImageCover(
    ctx: CanvasRenderingContext2D,
    image: HTMLImageElement,
    x: number,
    y: number,
    width: number,
    height: number,
    alpha: number
  ): void {
    const imageWidth = Math.max(image.width, 1);
    const imageHeight = Math.max(image.height, 1);
    const imageAspect = imageWidth / imageHeight;
    const targetAspect = width / height;

    let drawWidth = width;
    let drawHeight = height;
    let drawX = x;
    let drawY = y;

    if (imageAspect > targetAspect) {
      drawHeight = height;
      drawWidth = height * imageAspect;
      drawX = x - (drawWidth - width) / 2;
    } else {
      drawWidth = width;
      drawHeight = width / imageAspect;
      drawY = y - (drawHeight - height) / 2;
    }

    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.drawImage(image, drawX, drawY, drawWidth, drawHeight);
    ctx.restore();
  }


  private drawWrappedText(
    ctx: CanvasRenderingContext2D,
    text: string,
    x: number,
    y: number,
    maxWidth: number,
    lineHeight: number,
    maxLines: number
  ): number {
    const words = text.split(/\s+/).filter((word) => word.length > 0);
    let line = '';
    let currentY = y;
    let lineIndex = 0;

    for (let i = 0; i < words.length; i += 1) {
      const testLine = line.length > 0 ? `${line} ${words[i]}` : words[i];
      const testWidth = ctx.measureText(testLine).width;
      const isLastWord = i === words.length - 1;

      if (testWidth > maxWidth && line.length > 0) {
        ctx.fillText(line, x, currentY);
        lineIndex += 1;
        if (lineIndex >= maxLines) {
          return currentY;
        }
        currentY += lineHeight;
        line = words[i];
      } else {
        line = testLine;
      }

      if (isLastWord) {
        if (lineIndex >= maxLines) {
          return currentY;
        }
        const finalLine = lineIndex === maxLines - 1 ? this.truncateText(ctx, line, maxWidth) : line;
        ctx.fillText(finalLine, x, currentY);
      }
    }

    return currentY;
  }

  private drawCenteredText(
    ctx: CanvasRenderingContext2D,
    text: string,
    centerX: number,
    baselineY: number
  ): void {
    const width = ctx.measureText(text).width;
    ctx.fillText(text, centerX - width / 2, baselineY);
  }

  private truncateText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
    if (ctx.measureText(text).width <= maxWidth) {
      return text;
    }

    let shortened = text;
    while (shortened.length > 1 && ctx.measureText(`${shortened}...`).width > maxWidth) {
      shortened = shortened.slice(0, -1);
    }

    return `${shortened}...`;
  }

  private fillRoundedRect(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    radius: number
  ): void {
    const clippedRadius = Math.min(radius, width / 2, height / 2);

    ctx.beginPath();
    ctx.moveTo(x + clippedRadius, y);
    ctx.lineTo(x + width - clippedRadius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + clippedRadius);
    ctx.lineTo(x + width, y + height - clippedRadius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - clippedRadius, y + height);
    ctx.lineTo(x + clippedRadius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - clippedRadius);
    ctx.lineTo(x, y + clippedRadius);
    ctx.quadraticCurveTo(x, y, x + clippedRadius, y);
    ctx.closePath();
    ctx.fill();
  }

  private strokeRoundedRect(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    radius: number
  ): void {
    const clippedRadius = Math.min(radius, width / 2, height / 2);

    ctx.beginPath();
    ctx.moveTo(x + clippedRadius, y);
    ctx.lineTo(x + width - clippedRadius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + clippedRadius);
    ctx.lineTo(x + width, y + height - clippedRadius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - clippedRadius, y + height);
    ctx.lineTo(x + clippedRadius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - clippedRadius);
    ctx.lineTo(x, y + clippedRadius);
    ctx.quadraticCurveTo(x, y, x + clippedRadius, y);
    ctx.closePath();
    ctx.stroke();
  }

  private async loadImage(src: string): Promise<HTMLImageElement | null> {
    return new Promise((resolve) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => resolve(null);
      image.src = src;
    });
  }

  private toSlug(value: string): string {
    return value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 80);
  }

  private getSelectedSimgridId(): number | null {
    const key = this.selectedChampionshipKey();
    if (!key || !key.startsWith('sg-')) return null;
    return Number(key.slice(3));
  }

  private async loadStandings(championshipId: number, force = false): Promise<void> {
    const token = ++this.standingsLoadToken;
    const cached = this.standingsCache.get(championshipId);

    if (!force && cached && !this.isCacheExpired(cached)) {
      this.errorMessage.set('');
      this.infoMessage.set('');
      this.selectedChampionship.set(cached.details);
      this.standings.set(cached.entries);
      this.races.set(cached.races);
      this.lastUpdated.set(cached.fetchedAt);
      return;
    }

    this.loadingStandings.set(true);
    this.errorMessage.set('');
    this.infoMessage.set('');

    try {
      const detailsPromise = cached
        ? Promise.resolve(cached.details)
        : firstValueFrom(this.api.getChampionshipById(championshipId));

      const [details, standingsData] = await Promise.all([
        detailsPromise,
        firstValueFrom(this.api.getChampionshipStandings(championshipId))
      ]);

      if (token !== this.standingsLoadToken) {
        return;
      }

      const fetchedAt = new Date();
      this.selectedChampionship.set(details);
      this.standings.set(standingsData.entries);
      this.races.set(standingsData.races);
      this.staleWarning.set(standingsData.stale ?? false);
      this.lastUpdated.set(fetchedAt);
      this.ensureDriverMapLoaded();

      this.standingsCache.set(championshipId, {
        details,
        entries: standingsData.entries,
        races: standingsData.races,
        fetchedAt
      });

      if (this.exportPreviewOpen()) {
        setTimeout(() => {
          void this.renderStandingsExportPreview();
        }, 0);
      }
    } catch (error) {
      if (token !== this.standingsLoadToken) {
        return;
      }

      if (this.isRateLimitError(error) && cached) {
        this.selectedChampionship.set(cached.details);
        this.standings.set(cached.entries);
        this.races.set(cached.races);
        this.lastUpdated.set(cached.fetchedAt);
        this.errorMessage.set('');
        this.infoMessage.set(this.toRateLimitCacheMessage(error, cached.fetchedAt));
        return;
      }

      this.errorMessage.set(this.toErrorMessage(error));
      this.selectedChampionship.set(null);
      this.standings.set([]);
      this.races.set([]);
    } finally {
      if (token === this.standingsLoadToken) {
        this.loadingStandings.set(false);
      }
    }
  }

  private async loadChampionshipDetails(championshipId: number): Promise<void> {
    this.loadingStandings.set(true);
    this.errorMessage.set('');
    try {
      const details = await firstValueFrom(this.api.getChampionshipById(championshipId));
      if (this.getSelectedSimgridId() === championshipId) {
        this.selectedChampionship.set(details);
        this.standings.set([]);
        this.races.set([]);
      }
    } catch (error) {
      if (this.getSelectedSimgridId() === championshipId) {
        this.errorMessage.set(this.toErrorMessage(error));
        this.selectedChampionship.set(null);
      }
    } finally {
      this.loadingStandings.set(false);
    }
  }

  private async loadParticipants(championshipId: number): Promise<void> {
    this.loadingParticipants.set(true);
    try {
      const users = await firstValueFrom(this.api.getChampionshipParticipants(championshipId));
      if (this.getSelectedSimgridId() === championshipId) {
        this.participants.set(users);
      }
    } catch {
      if (this.getSelectedSimgridId() === championshipId) {
        this.participants.set([]);
      }
    } finally {
      this.loadingParticipants.set(false);
    }
  }

  private driverMapLoaded = false;

  private ensureDriverMapLoaded(): void {
    if (this.driverMapLoaded) return;
    this.driverMapLoaded = true;
    this.bwpApi.getDrivers().subscribe({
      next: (drivers) => {
        const m = new Map<number, string>();
        for (const d of drivers) {
          if (d.simgridDriverId != null) m.set(d.simgridDriverId, d.id);
        }
        this.driverUuidBySimgridId.set(m);
      },
    });
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

  private isCacheExpired(cache: CachedStandingsData): boolean {
    return Date.now() - cache.fetchedAt.getTime() > this.cacheTtlMs;
  }

  private isRateLimitError(error: unknown): error is HttpErrorResponse {
    return error instanceof HttpErrorResponse && error.status === 429;
  }

  private toRateLimitCacheMessage(error: HttpErrorResponse, cachedAt: Date): string {
    const reason = this.extractErrorReason(error) ?? 'Minute rate limit exceeded';
    return `${reason}. Showing cached data from ${cachedAt.toLocaleTimeString()}. Try Refresh in about 1 minute.`;
  }

  private extractErrorReason(error: HttpErrorResponse): string | null {
    const payload = error.error;
    if (payload && typeof payload === 'object') {
      const candidate = (payload as { error?: unknown }).error;
      if (typeof candidate === 'string' && candidate.trim().length > 0) {
        return candidate;
      }
    }

    if (typeof payload === 'string' && payload.trim().length > 0) {
      return payload;
    }

    return null;
  }

  private toErrorMessage(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      if (error.status === 0) {
        return 'Unable to reach The SimGrid API. If you run locally, use ng serve with the proxy config.';
      }
      if (error.status === 200) {
        return 'API returned HTML instead of JSON (proxy not applied). Restart `npm start` and retry.';
      }
      if (error.status === 429) {
        const reason = this.extractErrorReason(error) ?? 'Minute rate limit exceeded';
        return `${reason}. Please wait about 1 minute and try again.`;
      }
      return `API request failed (${error.status}).`;
    }
    return 'Failed to load standings data.';
  }
}
