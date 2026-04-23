import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { BwpApiService } from './bwp-api.service';
import { formatDate } from '../utils/format';
import {
  ChampionshipDetails,
  ChampionshipListItem,
  ChampionshipRace,
  StandingEntry,
  StandingRace,
} from './simgrid-api.service';

export interface ChampionshipEntry {
  key: string; // 'sg-123'
  name: string;
  simgridItem: ChampionshipListItem;
}

export interface RaceResultRow {
  position: number | null;
  displayName: string;
  car: string;
  carClass: string;
  dns: boolean;
  driverUuid: string | null;
}

@Injectable({ providedIn: 'root' })
export class ChampionshipService {
  private readonly bwpApi = inject(BwpApiService);

  readonly driverUuidBySimgridId = signal<Map<number, string>>(new Map());
  private driverMapLoaded = false;

  ensureDriverMapLoaded(): void {
    if (this.driverMapLoaded) return;
    this.driverMapLoaded = true;
    this.bwpApi.getDrivers().subscribe({
      next: (drivers) => {
        const map = new Map<number, string>();
        for (const d of drivers) {
          if (d.simgridDriverId !== null) {
            map.set(d.simgridDriverId, d.id);
          }
        }
        this.driverUuidBySimgridId.set(map);
      },
    });
  }

  getStatusOrder(entry: ChampionshipEntry): number {
    const item = entry.simgridItem;
    const today = new Date().toISOString().slice(0, 10);
    if (item.startDate && item.startDate.slice(0, 10) > today) return 1;
    if (item.eventCompleted) return 3;
    if (item.endDate && item.endDate.slice(0, 10) < today) return 3;
    if (item.startDate && item.startDate.slice(0, 10) <= today) return 0;
    if (item.acceptingRegistrations) return 1;
    return 2;
  }

  getStatusClass(entry: ChampionshipEntry): string {
    const order = this.getStatusOrder(entry);
    if (order === 0) return 'championship--active';
    if (order === 1) return 'championship--future';
    if (order === 3) return 'championship--finished';
    return '';
  }

  getStatusLabel(entry: ChampionshipEntry): string | null {
    const order = this.getStatusOrder(entry);
    if (order === 0) return 'Active';
    if (order === 1) return 'Upcoming';
    if (order === 3) return 'Finished';
    return null;
  }

  isChampionshipNotStarted(details: ChampionshipDetails | null): boolean {
    if (!details?.startDate) return false;
    const today = new Date().toISOString().slice(0, 10);
    return details.startDate.slice(0, 10) > today;
  }

  getRaceResult(
    entry: StandingEntry,
    race: StandingRace,
    raceIndex: number,
  ): { points: number | null; position: number | null; dns: boolean } | null {
    const byId = entry.raceResults.find(
      (item) => item.raceId !== null && item.raceId === race.id,
    );
    if (byId) return byId;
    return (
      entry.raceResults.find((item) => item.raceIndex === raceIndex) ?? null
    );
  }

  getRaceResultsForRace(
    standings: StandingEntry[],
    races: StandingRace[],
    driverMap: Map<number, string>,
    race: ChampionshipRace,
    raceIndex: number,
  ): RaceResultRow[] {
    const standingRace = races.find((r) => r.id === race.id);
    if (!standingRace) return [];
    const standingRaceIndex = races.indexOf(standingRace);

    return standings
      .map((entry) => {
        const result = this.getRaceResult(entry, standingRace, standingRaceIndex);
        return {
          position: result?.position ?? null,
          displayName: entry.displayName,
          car: entry.car,
          carClass: entry.carClass,
          dns: result?.dns ?? false,
          driverUuid: driverMap.get(entry.id) ?? null,
        };
      })
      .filter((row) => row.position !== null || row.dns)
      .sort((a, b) => {
        if (a.position === null && b.position === null) return 0;
        if (a.position === null) return 1;
        if (b.position === null) return -1;
        return a.position - b.position;
      });
  }

  formatRacePosition(
    entry: StandingEntry,
    race: StandingRace,
    raceIndex: number,
  ): string {
    const result = this.getRaceResult(entry, race, raceIndex);
    if (!result || result.position === null) {
      return result?.dns ? 'DNS' : '-';
    }
    return String(result.position);
  }

  getRaceStatus(race: ChampionshipRace): 'completed' | 'upcoming' {
    return race.ended || race.resultsAvailable ? 'completed' : 'upcoming';
  }

  hasRaceResults(race: ChampionshipRace, races: StandingRace[]): boolean {
    return races.some((r) => r.id === race.id);
  }

  getRaceLabel(index: number): string {
    return `R${index + 1}`;
  }

  getRaceTitle(race: StandingRace, index: number): string {
    const datePart = race.startsAt ? formatDate(race.startsAt) : 'TBD';
    return `${this.getRaceLabel(index)} – ${race.displayName} (${datePart})`;
  }

  getPosition(
    entry: StandingEntry,
    index: number,
    isMulticlass: boolean,
    hasClassFilter: boolean,
  ): number {
    if (isMulticlass && hasClassFilter) return index + 1;
    return entry.position ?? index + 1;
  }

  computeEligibleDrivers(
    standings: StandingEntry[],
    minRaces: number,
  ): { id: number; displayName: string; racesCount: number }[] {
    return standings
      .filter((e) => !e.dsq)
      .map((e) => ({
        id: e.id,
        displayName: e.displayName,
        racesCount: e.raceResults.filter((r) => r.position !== null).length,
      }))
      .filter((e) => e.racesCount >= minRaces)
      .sort((a, b) =>
        a.racesCount !== b.racesCount
          ? b.racesCount - a.racesCount
          : a.displayName.localeCompare(b.displayName),
      );
  }

  toErrorMessage(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      if (error.status === 0) {
        return 'Unable to reach The SimGrid API. Please try again later.';
      }
      if (error.status === 429) {
        return this.extractErrorReason(error) ?? 'Minute rate limit exceeded';
      }
      return `API request failed (${error.status}).`;
    }
    return 'Failed to load standings data.';
  }

  private extractErrorReason(error: HttpErrorResponse): string | null {
    const body = error.error;
    if (body && typeof body === 'object' && typeof body.error === 'string') {
      return body.error;
    }
    if (typeof body === 'string') {
      return body;
    }
    return null;
  }
}
