import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API, Schemas } from '../api';

export type ChampionshipListItem = Schemas['ChampionshipSummaryOut'];

export type ChampionshipDetails = Schemas['ChampionshipOut'];

export type ChampionshipUpdate = Schemas['ChampionshipUpdate'];

/** `classified` also covers iRacing retirements: SimGrid gives no status there. */
export type RaceStatus = Schemas['DriverRaceResultOut']['status'];

export type DriverRaceResult = Schemas['DriverRaceResultOut'];

export type RaceSessionKind = Schemas['RaceSessionOut']['session'];

export type RaceResultEntry = Schemas['RaceResultEntryOut'];

export type RaceSession = Schemas['RaceSessionOut'];

export type StandingEntry = Schemas['StandingEntryOut'];

export type StandingRace = Schemas['StandingRaceOut'];

export type ChampionshipStandingsData = Schemas['ChampionshipStandingsOut'];

export type ChampionshipRace = Schemas['ChampionshipRaceOut'];

@Injectable({ providedIn: 'root' })
export class SimgridApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API}/championships`;

  /** The championships shown on the site; `includeInactive` adds the hidden ones (admin only). */
  getChampionships(options?: { includeInactive?: boolean }): Observable<ChampionshipListItem[]> {
    return this.http.get<ChampionshipListItem[]>(this.base, {
      params: options?.includeInactive ? { include: 'inactive' } : {},
    });
  }

  getChampionshipById(championshipId: number): Observable<ChampionshipDetails> {
    return this.http.get<ChampionshipDetails>(`${this.base}/${championshipId}`);
  }

  getChampionshipStandings(championshipId: number): Observable<ChampionshipStandingsData> {
    return this.http.get<ChampionshipStandingsData>(`${this.base}/${championshipId}/standings`);
  }

  getChampionshipRaces(championshipId: number): Observable<ChampionshipRace[]> {
    return this.http.get<ChampionshipRace[]>(`${this.base}/${championshipId}/races`);
  }

  getRaceResults(
    championshipId: number,
    raceId: number,
    session: RaceSessionKind,
  ): Observable<RaceSession> {
    return this.http.get<RaceSession>(`${this.base}/${championshipId}/races/${raceId}/results`, {
      params: { session },
    });
  }

  setChampionshipActive(championshipId: number, isActive: boolean): Observable<void> {
    const body: ChampionshipUpdate = { isActive };
    return this.http.patch<void>(`${this.base}/${championshipId}`, body);
  }
}
