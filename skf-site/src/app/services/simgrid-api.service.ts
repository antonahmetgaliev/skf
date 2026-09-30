import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API, Schemas } from '../api';

export type ChampionshipListItem = Schemas['ChampionshipListItem'];

export type ChampionshipDetails = Schemas['ChampionshipDetails'];

/** `classified` also covers iRacing retirements: SimGrid gives no status there. */
export type RaceStatus = Schemas['DriverRaceResult']['status'];

export type DriverRaceResult = Schemas['DriverRaceResult'];

export type RaceSessionKind = Schemas['RaceSessionOut']['session'];

export type RaceResultEntry = Schemas['RaceResultEntry'];

export type RaceSession = Schemas['RaceSessionOut'];

export type StandingEntry = Schemas['StandingEntry'];

export type StandingRace = Schemas['StandingRace'];

export type ChampionshipStandingsData = Schemas['ChampionshipStandingsData'];

export type ChampionshipRace = Schemas['ChampionshipRace'];

@Injectable({ providedIn: 'root' })
export class SimgridApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API}/championships`;
  private readonly activeBase = `${API}/active-championships`;

  getChampionships(): Observable<ChampionshipListItem[]> {
    return this.http.get<ChampionshipListItem[]>(this.base);
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

  getActiveChampionships(): Observable<number[]> {
    return this.http.get<number[]>(this.activeBase);
  }

  addActiveChampionship(simgridId: number): Observable<unknown> {
    return this.http.put(`${this.activeBase}/${simgridId}`, null);
  }

  removeActiveChampionship(simgridId: number): Observable<void> {
    return this.http.delete<void>(`${this.activeBase}/${simgridId}`);
  }
}
