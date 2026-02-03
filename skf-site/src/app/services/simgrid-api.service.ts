import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable, catchError, map, of, switchMap } from 'rxjs';

export interface ChampionshipListItem {
  id: number;
  name: string;
}

export interface ChampionshipDetails {
  id: number;
  name: string;
  start_date: string | null;
  end_date: string | null;
  capacity: number | null;
  spots_taken: number | null;
  accepting_registrations: boolean;
  host_name: string;
  game_name: string;
  url: string;
}

export interface DriverRaceResult {
  raceId: number | null;
  raceIndex: number;
  points: number | null;
  position: number | null;
}

export interface StandingEntry {
  id: number;
  position: number | null;
  displayName: string;
  countryCode: string;
  car: string;
  points: number;
  penalties: number;
  score: number;
  raceResults: DriverRaceResult[];
}

export interface StandingRace {
  id: number;
  displayName: string;
  startsAt: string | null;
  resultsAvailable: boolean;
  ended: boolean;
}

export interface ChampionshipStandingsData {
  entries: StandingEntry[];
  races: StandingRace[];
}

interface RawStandingEntry {
  id?: number;
  position_cache?: number | null;
  display_name?: string | null;
  car?: string | null;
  championship_points?: number | null;
  championship_penalties?: number | null;
  championship_score?: number | null;
  partial_standings?: unknown[] | null;
  overall_partial_standings?: unknown[] | null;
  participant?: {
    country_code?: string | null;
  } | null;
}

interface RawStandingRace {
  id?: number;
  display_name?: string | null;
  race_name?: string | null;
  starts_at?: string | null;
  results_available?: boolean | null;
  ended?: boolean | null;
}

interface RawRaceResultItem {
  race_id?: number | null;
  raceId?: number | null;
  id?: number | null;
  points?: number | null;
  championship_points?: number | null;
  score?: number | null;
  championship_score?: number | null;
  position?: number | null;
  position_cache?: number | null;
  rank?: number | null;
}

interface HtmlRaceColumn {
  raceId: number | null;
  raceIndex: number;
}

interface HtmlStandingRow {
  normalizedName: string;
  position: number | null;
  racePositions: Array<number | null>;
}

interface HtmlStandingsSnapshot {
  raceColumns: HtmlRaceColumn[];
  rows: HtmlStandingRow[];
}

@Injectable({ providedIn: 'root' })
export class SimgridApiService {
  private readonly http = inject(HttpClient);
  private readonly apiKey = '';
  private readonly apiBaseUrl = '/simgrid-api/v1';
  private readonly siteBaseUrl = '/simgrid-site';
  private readonly defaultHeaders = new HttpHeaders({
    Authorization: `Bearer ${this.apiKey}`
  });

  getChampionships(limit = 200): Observable<ChampionshipListItem[]> {
    const params = new HttpParams().set('limit', String(limit)).set('offset', '0');
    return this.http.get<ChampionshipListItem[]>(`${this.apiBaseUrl}/championships`, {
      headers: this.defaultHeaders,
      params
    });
  }

  getChampionshipById(championshipId: number): Observable<ChampionshipDetails> {
    return this.http.get<ChampionshipDetails>(
      `${this.apiBaseUrl}/championships/${championshipId}`,
      { headers: this.defaultHeaders }
    );
  }

  getChampionshipStandings(championshipId: number): Observable<ChampionshipStandingsData> {
    return this.http
      .get<unknown[]>(`${this.apiBaseUrl}/championships/${championshipId}/standings`, {
        headers: this.defaultHeaders
      })
      .pipe(
        map((payload) => this.parseStandings(payload)),
        switchMap((standings) => {
          if (this.hasRacePositions(standings) || standings.races.length === 0) {
            return of(standings);
          }

          return this.http
            .get(`${this.siteBaseUrl}/championships/${championshipId}/standings`, {
              responseType: 'text'
            })
            .pipe(
              map((html) => this.mergeHtmlRacePositions(standings, html)),
              catchError(() => of(standings))
            );
        })
      );
  }

  private parseStandings(payload: unknown[]): ChampionshipStandingsData {
    if (!Array.isArray(payload)) {
      return { entries: [], races: [] };
    }

    const races = this.parseRaces(payload[1]);
    const entriesRaw = Array.isArray(payload[0]) ? (payload[0] as RawStandingEntry[]) : [];
    const entries = entriesRaw
      .map((entry) => this.parseStandingEntry(entry, races))
      .sort((a, b) => this.sortStandings(a, b));

    return { entries, races };
  }

  private parseStandingEntry(entry: RawStandingEntry, races: StandingRace[]): StandingEntry {
    const partialResults =
      Array.isArray(entry.partial_standings) && entry.partial_standings.length > 0
        ? entry.partial_standings
        : entry.overall_partial_standings;

    return {
      id: this.toNumber(entry.id),
      position: this.toNullableNumber(entry.position_cache),
      displayName: this.toText(entry.display_name, 'Unknown driver'),
      countryCode: this.toText(entry.participant?.country_code, ''),
      car: this.toText(entry.car, ''),
      points: this.toNumber(entry.championship_points),
      penalties: this.toNumber(entry.championship_penalties),
      score: this.toNumber(entry.championship_score),
      raceResults: this.parseRaceResults(partialResults, races)
    };
  }

  private parseRaces(value: unknown): StandingRace[] {
    if (!Array.isArray(value)) {
      return [];
    }

    return value.map((item) => {
      const race = item as RawStandingRace;
      return {
        id: this.toNumber(race.id),
        displayName: this.toText(race.display_name ?? race.race_name, 'Race'),
        startsAt: this.toNullableText(race.starts_at),
        resultsAvailable: Boolean(race.results_available),
        ended: Boolean(race.ended)
      };
    });
  }

  private parseRaceResults(value: unknown, races: StandingRace[]): DriverRaceResult[] {
    if (!Array.isArray(value)) {
      return [];
    }

    return value.map((item, index) => {
      if (typeof item === 'number') {
        return {
          raceId: races[index]?.id ?? null,
          raceIndex: index,
          points: null,
          position: this.toNullableNumber(item)
        };
      }

      const raw = item as RawRaceResultItem;
      const pointsCandidate =
        raw.points ??
        raw.championship_points ??
        raw.score ??
        raw.championship_score ??
        null;
      const raceIdCandidate = raw.race_id ?? raw.raceId ?? raw.id ?? races[index]?.id ?? null;
      const positionCandidate = raw.position ?? raw.position_cache ?? raw.rank ?? null;

      return {
        raceId: this.toNullableNumber(raceIdCandidate),
        raceIndex: index,
        points: this.toNullableNumber(pointsCandidate),
        position: this.toNullableNumber(positionCandidate)
      };
    });
  }

  private hasRacePositions(data: ChampionshipStandingsData): boolean {
    return data.entries.some((entry) => entry.raceResults.some((result) => result.position !== null));
  }

  private mergeHtmlRacePositions(
    data: ChampionshipStandingsData,
    html: string
  ): ChampionshipStandingsData {
    const snapshot = this.extractHtmlStandings(html);
    if (!snapshot || snapshot.raceColumns.length === 0 || snapshot.rows.length === 0) {
      return data;
    }

    const races = this.mergeRaces(data.races, snapshot.raceColumns);
    const usedRowIndexes = new Set<number>();
    const entries = data.entries.map((entry, entryIndex) => {
      const rowIndex = this.findHtmlRowIndex(entry, entryIndex, snapshot.rows, usedRowIndexes);
      if (rowIndex < 0) {
        return entry;
      }

      usedRowIndexes.add(rowIndex);
      const row = snapshot.rows[rowIndex];
      const raceResults = this.mergeRaceResults(entry.raceResults, row.racePositions, races);
      return { ...entry, raceResults };
    });

    return { entries, races };
  }

  private extractHtmlStandings(html: string): HtmlStandingsSnapshot | null {
    const tableMatch = html.match(
      /<table[^>]*class="[^"]*table-results[^"]*table-v2[^"]*"[^>]*>[\s\S]*?<\/table>/i
    );
    if (!tableMatch) {
      return null;
    }

    const tableHtml = tableMatch[0];
    const raceColumns: HtmlRaceColumn[] = [];
    const seenRaceIds = new Set<number>();

    for (const match of tableHtml.matchAll(/race_id=(\d+)/g)) {
      const raceId = this.toNullableNumber(match[1]);
      if (raceId === null || seenRaceIds.has(raceId)) {
        continue;
      }

      seenRaceIds.add(raceId);
      raceColumns.push({ raceId, raceIndex: raceColumns.length });
    }

    const rows: HtmlStandingRow[] = [];
    for (const rowMatch of tableHtml.matchAll(/<tr[\s\S]*?<\/tr>/gi)) {
      const rowHtml = rowMatch[0];
      if (!rowHtml.includes('entrant-name')) {
        continue;
      }

      const nameMatch = rowHtml.match(/class="entrant-name[^"]*"[^>]*>([\s\S]*?)<\/a>/i);
      const normalizedName = this.normalizeName(this.stripHtml(nameMatch?.[1] ?? ''));

      const positionMatch = rowHtml.match(
        /class="[^"]*result-position[^"]*"[^>]*>[\s\S]*?<strong>\s*([^<]+)\s*<\/strong>/i
      );
      const position = this.parseHtmlNumeric(positionMatch?.[1] ?? null);

      const racePositionMatches = [
        ...rowHtml.matchAll(/<span class="show_positions">([\s\S]*?)<\/span>/gi)
      ];
      const racePositions = raceColumns.map((_, raceIndex) => {
        const value = this.stripHtml(racePositionMatches[raceIndex]?.[1] ?? '');
        return this.parseHtmlRacePosition(value);
      });

      rows.push({
        normalizedName,
        position,
        racePositions
      });
    }

    return rows.length > 0 ? { raceColumns, rows } : null;
  }

  private mergeRaces(current: StandingRace[], raceColumns: HtmlRaceColumn[]): StandingRace[] {
    if (raceColumns.length <= current.length) {
      return current;
    }

    const merged = [...current];
    raceColumns.forEach((column, index) => {
      if (index < merged.length) {
        return;
      }

      merged.push({
        id: column.raceId ?? -(index + 1),
        displayName: `Race ${index + 1}`,
        startsAt: null,
        resultsAvailable: false,
        ended: false
      });
    });

    return merged;
  }

  private findHtmlRowIndex(
    entry: StandingEntry,
    entryIndex: number,
    rows: HtmlStandingRow[],
    usedRows: Set<number>
  ): number {
    const byName = rows.findIndex(
      (row, index) =>
        !usedRows.has(index) && row.normalizedName === this.normalizeName(entry.displayName)
    );
    if (byName >= 0) {
      return byName;
    }

    if (entry.position !== null) {
      const byPosition = rows.findIndex(
        (row, index) => !usedRows.has(index) && row.position === entry.position
      );
      if (byPosition >= 0) {
        return byPosition;
      }
    }

    return entryIndex < rows.length && !usedRows.has(entryIndex) ? entryIndex : -1;
  }

  private mergeRaceResults(
    current: DriverRaceResult[],
    htmlRacePositions: Array<number | null>,
    races: StandingRace[]
  ): DriverRaceResult[] {
    const byRaceIndex = new Map<number, DriverRaceResult>();
    current.forEach((result) => byRaceIndex.set(result.raceIndex, result));

    htmlRacePositions.forEach((position, raceIndex) => {
      const existing = byRaceIndex.get(raceIndex);
      if (existing) {
        byRaceIndex.set(raceIndex, {
          ...existing,
          raceId: existing.raceId ?? races[raceIndex]?.id ?? null,
          position: existing.position ?? position
        });
        return;
      }

      if (position === null) {
        return;
      }

      byRaceIndex.set(raceIndex, {
        raceId: races[raceIndex]?.id ?? null,
        raceIndex,
        points: null,
        position
      });
    });

    return [...byRaceIndex.values()].sort((a, b) => a.raceIndex - b.raceIndex);
  }

  private stripHtml(value: string): string {
    return value
      .replace(/<[^>]*>/g, ' ')
      .replace(/&nbsp;/gi, ' ')
      .replace(/&#160;/gi, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  private normalizeName(value: string): string {
    return value
      .normalize('NFKD')
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, ' ')
      .trim()
      .replace(/\s+/g, ' ');
  }

  private parseHtmlNumeric(value: string | null): number | null {
    if (!value) {
      return null;
    }

    const match = value.match(/-?\d+/);
    return match ? this.toNullableNumber(match[0]) : null;
  }

  private parseHtmlRacePosition(value: string | null): number | null {
    if (!value) {
      return null;
    }

    const normalized = value
      .replace(/[\u200B-\u200F\uFEFF]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
    if (normalized.length === 0 || normalized === '-' || normalized === '\u2014') {
      return null;
    }

    // SimGrid race cells may contain extra values after the finishing position.
    // We only accept a numeric token at the start as the race position.
    const leadingPosition = normalized.match(/^-?\d+/);
    return leadingPosition ? this.toNullableNumber(leadingPosition[0]) : null;
  }

  private sortStandings(a: StandingEntry, b: StandingEntry): number {
    const aPos = a.position ?? Number.POSITIVE_INFINITY;
    const bPos = b.position ?? Number.POSITIVE_INFINITY;
    if (aPos !== bPos) {
      return aPos - bPos;
    }
    if (a.score !== b.score) {
      return b.score - a.score;
    }
    return a.displayName.localeCompare(b.displayName);
  }

  private toNumber(value: unknown): number {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  private toNullableNumber(value: unknown): number | null {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  private toText(value: unknown, fallback: string): string {
    return typeof value === 'string' && value.trim().length > 0 ? value : fallback;
  }

  private toNullableText(value: unknown): string | null {
    return typeof value === 'string' && value.trim().length > 0 ? value : null;
  }
}

