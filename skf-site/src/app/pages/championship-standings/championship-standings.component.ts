import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  ChampionshipDetails,
  ChampionshipListItem,
  SimgridApiService,
  StandingEntry,
  StandingRace
} from '../../services/simgrid-api.service';

interface CachedStandingsData {
  details: ChampionshipDetails;
  entries: StandingEntry[];
  races: StandingRace[];
  fetchedAt: Date;
}

@Component({
  selector: 'app-championship-standings',
  templateUrl: './championship-standings.component.html',
  styleUrl: './championship-standings.component.scss'
})
export class ChampionshipStandingsComponent {
  private readonly api = inject(SimgridApiService);
  private readonly cacheTtlMs = 60000;
  private readonly standingsCache = new Map<number, CachedStandingsData>();
  private standingsLoadToken = 0;
  private championshipsLoadToken = 0;
  private readonly dateFormatter = new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  });

  readonly championships = signal<ChampionshipListItem[]>([]);
  readonly selectedChampionshipId = signal<number | null>(null);
  readonly selectedChampionship = signal<ChampionshipDetails | null>(null);
  readonly standings = signal<StandingEntry[]>([]);
  readonly races = signal<StandingRace[]>([]);
  readonly loadingChampionships = signal(false);
  readonly loadingStandings = signal(false);
  readonly errorMessage = signal('');
  readonly infoMessage = signal('');
  readonly lastUpdated = signal<Date | null>(null);

  constructor() {
    void this.loadChampionships();
  }

  async loadChampionships(): Promise<void> {
    const token = ++this.championshipsLoadToken;
    this.loadingChampionships.set(true);
    this.errorMessage.set('');
    this.infoMessage.set('');

    try {
      const list = await firstValueFrom(this.api.getChampionships());
      if (token !== this.championshipsLoadToken) {
        return;
      }

      const sorted = [...list].sort((a, b) => b.id - a.id);
      this.championships.set(sorted);

      if (sorted.length === 0) {
        this.selectedChampionshipId.set(null);
        this.selectedChampionship.set(null);
        this.standings.set([]);
        this.races.set([]);
        return;
      }

      const currentSelectedId = this.selectedChampionshipId();
      const selectedId =
        currentSelectedId !== null && sorted.some((item) => item.id === currentSelectedId)
          ? currentSelectedId
          : sorted[0].id;

      this.selectedChampionshipId.set(selectedId);
      await this.loadStandings(selectedId);
    } catch (error) {
      if (token !== this.championshipsLoadToken) {
        return;
      }
      this.errorMessage.set(this.toErrorMessage(error));
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

  selectChampionship(championshipId: number): void {
    if (this.selectedChampionshipId() === championshipId && this.standings().length > 0) {
      return;
    }
    this.selectedChampionshipId.set(championshipId);
    void this.loadStandings(championshipId);
  }

  refreshSelectedChampionship(): void {
    const championshipId = this.selectedChampionshipId();
    if (championshipId === null) {
      return;
    }
    void this.loadStandings(championshipId, true);
  }

  getPosition(entry: StandingEntry, index: number): number {
    return entry.position ?? index + 1;
  }

  getOverallColspan(): number {
    return 5 + this.races().length;
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
      return '-';
    }

    return String(result.position);
  }

  private getRaceResult(
    entry: StandingEntry,
    race: StandingRace,
    raceIndex: number
  ): { points: number | null; position: number | null } | null {
    const byRaceId = entry.raceResults.find(
      (item) => item.raceId !== null && item.raceId === race.id
    );
    if (byRaceId) {
      return byRaceId;
    }

    return entry.raceResults.find((item) => item.raceIndex === raceIndex) ?? null;
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
      this.lastUpdated.set(fetchedAt);
      this.standingsCache.set(championshipId, {
        details,
        entries: standingsData.entries,
        races: standingsData.races,
        fetchedAt
      });
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
