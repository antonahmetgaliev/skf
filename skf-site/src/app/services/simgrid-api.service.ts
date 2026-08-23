import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

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

export interface DriverRaceResult {
  raceId: number | null;
  raceIndex: number;
  points: number | null;
  position: number | null;
  dns: boolean;
}

export interface StandingEntry {
  id: number;
  position: number | null;
  displayName: string;
  countryCode: string;
  car: string;
  carClass: string;
  points: number;
  penalties: number;
  score: number;
  dsq: boolean;
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
  private readonly base = '/api/championships';

  getChampionships(limit = 200): Observable<ChampionshipListItem[]> {
    return this.http.get<ChampionshipListItem[]>(this.base, {
      params: { limit: String(limit) }
    });
  }

  getChampionshipById(championshipId: number): Observable<ChampionshipDetails> {
    return this.http.get<ChampionshipDetails>(`${this.base}/${championshipId}`);
  }

  getChampionshipStandings(championshipId: number): Observable<ChampionshipStandingsData> {
    return this.http.get<ChampionshipStandingsData>(
      `${this.base}/${championshipId}/standings`
    );
  }

  getChampionshipRaces(championshipId: number): Observable<ChampionshipRace[]> {
    return this.http.get<ChampionshipRace[]>(
      `${this.base}/${championshipId}/races`
    );
  }

  getActiveChampionships(): Observable<number[]> {
    return this.http.get<number[]>(`${this.base}/active`);
  }

  addActiveChampionship(simgridId: number): Observable<void> {
    return this.http.put<void>(`${this.base}/active/${simgridId}`, null);
  }

  removeActiveChampionship(simgridId: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/active/${simgridId}`);
  }

}


