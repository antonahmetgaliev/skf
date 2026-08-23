import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { BwpApiService } from './bwp-api.service';
import {
  ChampionshipDetails,
  ChampionshipListItem,
  ChampionshipRace,
  StandingEntry,
} from './simgrid-api.service';

export interface ChampionshipEntry {
  key: string; // 'sg-123'
  name: string;
  simgridItem: ChampionshipListItem;
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

  getRaceStatus(race: ChampionshipRace): 'completed' | 'upcoming' {
    return race.ended || race.resultsAvailable ? 'completed' : 'upcoming';
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
