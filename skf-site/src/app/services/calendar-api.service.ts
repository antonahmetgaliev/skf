import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export type CalendarEventType = 'past' | 'ongoing' | 'upcoming' | 'future';

export interface CalendarRace {
  date: string | null;
  track: string | null;
  name: string | null;
}

export interface CalendarEvent {
  id: string;
  name: string;
  game: string;
  carClass: string | null;
  description: string | null;
  startDate: string | null;
  endDate: string | null;
  eventType: CalendarEventType;
  source: 'simgrid' | 'custom';
  simgridChampionshipId: number | null;
  customChampionshipId: string | null;
  races: CalendarRace[];
}

export interface CustomRaceCreate {
  date: string | null;
  track: string | null;
}

export interface CustomRaceOut {
  id: string;
  date: string | null;
  track: string | null;
  sortOrder: number;
  createdAt: string;
}

export interface CustomChampionshipCreate {
  name: string;
  game: string;
  carClass: string | null;
  description: string | null;
  races: CustomRaceCreate[];
}

export interface CustomChampionshipUpdate {
  name?: string;
  game?: string;
  carClass?: string | null;
  description?: string | null;
  isVisible?: boolean;
}

export interface CustomChampionshipOut {
  id: string;
  name: string;
  game: string;
  carClass: string | null;
  description: string | null;
  isVisible: boolean;
  races: CustomRaceOut[];
  createdByUserId: string | null;
  createdAt: string;
}

@Injectable({ providedIn: 'root' })
export class CalendarApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/calendar';

  getEvents(year: number, month: number): Observable<CalendarEvent[]> {
    return this.http.get<CalendarEvent[]>(`${this.base}/events`, {
      params: { year: String(year), month: String(month) },
    });
  }

  getCustomChampionships(): Observable<CustomChampionshipOut[]> {
    return this.http.get<CustomChampionshipOut[]>(`${this.base}/custom-championships`);
  }

  createCustomChampionship(payload: CustomChampionshipCreate): Observable<CustomChampionshipOut> {
    return this.http.post<CustomChampionshipOut>(`${this.base}/custom-championships`, payload);
  }

  updateCustomChampionship(
    id: string,
    payload: CustomChampionshipUpdate,
  ): Observable<CustomChampionshipOut> {
    return this.http.patch<CustomChampionshipOut>(
      `${this.base}/custom-championships/${id}`,
      payload,
    );
  }

  deleteCustomChampionship(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/custom-championships/${id}`);
  }

  addRace(champId: string, payload: CustomRaceCreate): Observable<CustomRaceOut> {
    return this.http.post<CustomRaceOut>(
      `${this.base}/custom-championships/${champId}/races`,
      payload,
    );
  }

  updateRace(
    champId: string,
    raceId: string,
    payload: Partial<CustomRaceCreate & { sortOrder: number }>,
  ): Observable<CustomRaceOut> {
    return this.http.patch<CustomRaceOut>(
      `${this.base}/custom-championships/${champId}/races/${raceId}`,
      payload,
    );
  }

  deleteRace(champId: string, raceId: string): Observable<void> {
    return this.http.delete<void>(
      `${this.base}/custom-championships/${champId}/races/${raceId}`,
    );
  }
}
