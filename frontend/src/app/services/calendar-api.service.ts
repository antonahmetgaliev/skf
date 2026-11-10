import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable, shareReplay, tap } from 'rxjs';
import { API, Schemas } from '../api';

export type CalendarEventType = Schemas['CalendarEventType'];

export type CalendarRace = Schemas['CalendarRaceOut'];

export type CalendarEvent = Schemas['CalendarEventOut'];

export type CustomRaceCreate = Schemas['CustomRaceCreate'];

export type CustomRaceSync = Schemas['CustomRaceUpsert'];

export type CustomRaceUpdate = Schemas['CustomRaceUpdate'];

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
  private communities$?: Observable<Community[]>;

  // ── Events ──

  /** Events between two `YYYY-MM-DD` dates, both included. */
  getEvents(from: string, to: string): Observable<CalendarEvent[]> {
    return this.http.get<CalendarEvent[]>(`${this.base}/calendar-events`, {
      params: { from, to },
    });
  }

  getYearEvents(year: number): Observable<CalendarEvent[]> {
    return this.getEvents(`${year}-01-01`, `${year}-12-31`);
  }

  /**
   * Events relevant "around now": this year, plus next year once the season
   * rolls over (from October or when the current week crosses New Year).
   * Shared between home page widgets so the request runs once; edits to custom
   * championships drop the cache.
   */
  getCurrentEvents(): Observable<CalendarEvent[]> {
    if (!this.currentEvents$) {
      const now = new Date();
      const weekAhead = new Date(now);
      weekAhead.setDate(now.getDate() + 7);
      const lastYear = now.getMonth() >= 9 ? now.getFullYear() + 1 : weekAhead.getFullYear();

      this.currentEvents$ = this.getEvents(`${now.getFullYear()}-01-01`, `${lastYear}-12-31`).pipe(
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    }
    return this.currentEvents$;
  }

  // ── Communities ──

  /**
   * Visible communities, the same for every visitor. Fetched once and shared by
   * the header, home page, calendar and admin; community edits drop the cache.
   */
  getCommunities(): Observable<Community[]> {
    this.communities$ ??= this.http
      .get<Community[]>(`${this.base}/communities`)
      .pipe(shareReplay({ bufferSize: 1, refCount: false }));
    return this.communities$;
  }

  /** Communities the caller manages, hidden ones included (all of them for admins). */
  getCommunitiesAdmin(): Observable<Community[]> {
    return this.http.get<Community[]>(`${this.base}/communities`, {
      params: { scope: 'managed' },
    });
  }

  createCommunity(payload: CommunityCreate): Observable<Community> {
    return this.http
      .post<Community>(`${this.base}/communities`, payload)
      .pipe(tap(() => (this.communities$ = undefined)));
  }

  updateCommunity(id: string, payload: CommunityUpdate): Observable<Community> {
    return this.http
      .patch<Community>(`${this.base}/communities/${id}`, payload)
      .pipe(tap(() => (this.communities$ = undefined)));
  }

  deleteCommunity(id: string): Observable<void> {
    return this.http
      .delete<void>(`${this.base}/communities/${id}`)
      .pipe(tap(() => (this.communities$ = undefined)));
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
    return this.http
      .post<CustomChampionshipOut>(`${this.base}/custom-championships`, payload)
      .pipe(this.dropCurrentEvents());
  }

  updateCustomChampionship(
    id: string,
    payload: CustomChampionshipUpdate,
  ): Observable<CustomChampionshipOut> {
    return this.http
      .patch<CustomChampionshipOut>(`${this.base}/custom-championships/${id}`, payload)
      .pipe(this.dropCurrentEvents());
  }

  deleteCustomChampionship(id: string): Observable<void> {
    return this.http
      .delete<void>(`${this.base}/custom-championships/${id}`)
      .pipe(this.dropCurrentEvents());
  }

  // ── Custom Races ──

  addRace(champId: string, payload: CustomRaceCreate): Observable<CustomRaceOut> {
    return this.http
      .post<CustomRaceOut>(`${this.base}/custom-championships/${champId}/races`, payload)
      .pipe(this.dropCurrentEvents());
  }

  updateRace(
    champId: string,
    raceId: string,
    payload: CustomRaceUpdate,
  ): Observable<CustomRaceOut> {
    return this.http
      .patch<CustomRaceOut>(`${this.base}/custom-championships/${champId}/races/${raceId}`, payload)
      .pipe(this.dropCurrentEvents());
  }

  deleteRace(champId: string, raceId: string): Observable<void> {
    return this.http
      .delete<void>(`${this.base}/custom-championships/${champId}/races/${raceId}`)
      .pipe(this.dropCurrentEvents());
  }

  syncRaces(champId: string, races: CustomRaceSync[]): Observable<CustomRaceOut[]> {
    return this.http
      .put<CustomRaceOut[]>(`${this.base}/custom-championships/${champId}/races`, races)
      .pipe(this.dropCurrentEvents());
  }

  private dropCurrentEvents<T>() {
    return tap<T>(() => (this.currentEvents$ = undefined));
  }
}
