import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API } from '../api';

export interface ChampionshipListItem {
  id: number;
  name: string;
  startDate: string | null;
  endDate: string | null;
  acceptingRegistrations: boolean;
  eventCompleted: boolean;
}

export interface ChampionshipDetails {
  id: number;
  name: string;
  image: string | null;
  startDate: string | null;
  endDate: string | null;
  capacity: number | null;
  spotsTaken: number | null;
  acceptingRegistrations: boolean;
  hostName: string;
  gameName: string;
  url: string;
  resultsUrl: string;
  discordUrl: string;
  roundNumber: number | null;
  allRoundsNumber: number | null;
}

/** `classified` also covers iRacing retirements: SimGrid gives no status there. */
export type RaceStatus = 'classified' | 'dnf' | 'dq' | 'dns';

export interface DriverRaceResult {
  raceId: number;
  /** Index into the standings' `races`. */
  raceIndex: number;
  points: number | null;
  /** Position within the car class. */
  position: number | null;
  status: RaceStatus;
}

export type RaceSessionKind = 'race' | 'qualifying';

export interface RaceResultEntry {
  userId: number | null;
  displayName: string;
  car: string;
  carNumber: number | null;
  carClass: string;
  /** Overall position; LMU only. */
  position: number | null;
  classPosition: number | null;
  /** Grid slot within the class; LMU only. */
  startPosition: number | null;
  laps: number | null;
  bestLapMs: number | null;
  isClassBestLap: boolean;
  totalTimeMs: number | null;
  /** Gap to the class leader on the same lap. */
  gapMs: number | null;
  lapsDown: number;
  penaltyS: number;
  points: number | null;
  status: RaceStatus;
  ratingChange: number | null;
}

export interface RaceSession {
  raceId: number;
  session: RaceSessionKind;
  /** Ordered by class, then class position. */
  entries: RaceResultEntry[];
}

export interface StandingEntry {
  /** SimGrid user id; null when the standings payload lacks one. */
  id: number | null;
  position: number | null;
  displayName: string;
  countryCode: string;
  car: string;
  carClass: string;
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

export interface ChampionshipRace {
  id: number;
  displayName: string;
  startsAt: string | null;
  track: string | null;
  resultsAvailable: boolean;
  ended: boolean;
}

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
