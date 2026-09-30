import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { forkJoin, map, Observable, shareReplay } from 'rxjs';
import { API, Schemas } from '../api';

export type CalendarEventType = Schemas['CalendarEventType'];

export type CalendarRace = Schemas['CalendarRace'];

export type CalendarEvent = Schemas['CalendarEvent'];

export type CustomRaceCreate = Schemas['CustomRaceCreate'];

export type CustomRaceSync = Schemas['CustomRaceSync'];

export type CustomRaceOut = Schemas['CustomRaceOut'];

export type CustomChampionshipCreate = Schemas['CustomChampionshipCreate'];

export type CustomChampionshipUpdate = Schemas['CustomChampionshipUpdate'];

export type CustomChampionshipOut = Schemas['CustomChampionshipOut'];

// ── Community ───────────────────────────────────────────────────────────────

export type Community = Schemas['CommunityOut'];

export type CommunityCreate = Schemas['CommunityCreate'];

export type CommunityUpdate = Schemas['CommunityUpdate'];

export type CommunityRequest = Schemas['CommunityRequestCreate'];

@Injectable({ providedIn: 'root' })
export class CalendarApiService {
  private readonly http = inject(HttpClient);
  private readonly base = API;
  private currentEvents$?: Observable<CalendarEvent[]>;

  // ── Events ──

  getEvents(year: number, month: number): Observable<CalendarEvent[]> {
    return this.http.get<CalendarEvent[]>(`${this.base}/calendar-events`, {
      params: { year: String(year), month: String(month) },
    });
  }

  getYearEvents(year: number): Observable<CalendarEvent[]> {
    return this.http.get<CalendarEvent[]>(`${this.base}/calendar-events`, {
      params: { year: String(year) },
    });
  }

  /**
   * Events relevant "around now": this year, plus next year once the season
   * rolls over (from October or when the current week crosses New Year).
   * Shared between home page widgets so the request runs once.
   */
  getCurrentEvents(): Observable<CalendarEvent[]> {
    if (!this.currentEvents$) {
      const now = new Date();
      const weekAhead = new Date(now);
      weekAhead.setDate(now.getDate() + 7);
      const years = new Set<number>([now.getFullYear(), weekAhead.getFullYear()]);
      if (now.getMonth() >= 9) years.add(now.getFullYear() + 1);

      this.currentEvents$ = forkJoin([...years].map((y) => this.getYearEvents(y))).pipe(
        map((lists) => {
          const seen = new Set<string>();
          return lists.flat().filter((ev) => !seen.has(ev.id) && !!seen.add(ev.id));
        }),
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    }
    return this.currentEvents$;
  }

  // ── Communities ──

  getCommunities(): Observable<Community[]> {
    return this.http.get<Community[]>(`${this.base}/communities`);
  }

  /** Communities the caller manages, hidden ones included (all of them for admins). */
  getCommunitiesAdmin(): Observable<Community[]> {
    return this.http.get<Community[]>(`${this.base}/communities`, {
      params: { scope: 'managed' },
    });
  }

  createCommunity(payload: CommunityCreate): Observable<Community> {
    return this.http.post<Community>(`${this.base}/communities`, payload);
  }

  updateCommunity(id: string, payload: CommunityUpdate): Observable<Community> {
    return this.http.patch<Community>(`${this.base}/communities/${id}`, payload);
  }

  deleteCommunity(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/communities/${id}`);
  }

  /** Forward a community's request to join the calendar to the SKF Discord. */
  requestCommunity(payload: CommunityRequest): Observable<void> {
    return this.http.post<void>(`${this.base}/community-requests`, payload);
  }

  // ── Simulators & Car Classes (from SimGrid) ──

  getSimulators(): Observable<string[]> {
    return this.http.get<string[]>(`${this.base}/simulators`);
  }

  getCarClasses(): Observable<string[]> {
    return this.http.get<string[]>(`${this.base}/car-classes`);
  }

  // ── Custom Championships ──

  getCustomChampionship(id: string): Observable<CustomChampionshipOut> {
    return this.http.get<CustomChampionshipOut>(`${this.base}/custom-championships/${id}`);
  }

  getCustomChampionships(communityId?: string): Observable<CustomChampionshipOut[]> {
    // The collection is paginated; the admin tab shows everything at once.
    const params: Record<string, string> = { limit: '1000' };
    if (communityId) {
      params['communityId'] = communityId;
    }
    return this.http.get<CustomChampionshipOut[]>(`${this.base}/custom-championships`, { params });
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

  // ── Custom Races ──

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
    return this.http.delete<void>(`${this.base}/custom-championships/${champId}/races/${raceId}`);
  }

  syncRaces(champId: string, races: CustomRaceSync[]): Observable<CustomRaceOut[]> {
    return this.http.put<CustomRaceOut[]>(
      `${this.base}/custom-championships/${champId}/races`,
      races,
    );
  }
}
