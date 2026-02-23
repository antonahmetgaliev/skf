import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface ChampionshipListItem {
  id: number;
  name: string;
}

export interface ChampionshipDetails {
  id: number;
  name: string;
  startDate: string | null;
  endDate: string | null;
  capacity: number | null;
  spotsTaken: number | null;
  acceptingRegistrations: boolean;
  hostName: string;
  gameName: string;
  url: string;
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

@Injectable({ providedIn: 'root' })
export class SimgridApiService {
  private readonly http = inject(HttpClient);
  private readonly apiBase = '/api/championships';

  getChampionships(limit = 200): Observable<ChampionshipListItem[]> {
    return this.http.get<ChampionshipListItem[]>(this.apiBase, {
      params: { limit: String(limit) }
    });
  }

  getChampionshipById(championshipId: number): Observable<ChampionshipDetails> {
    return this.http.get<ChampionshipDetails>(`${this.apiBase}/${championshipId}`);
  }

  getChampionshipStandings(championshipId: number): Observable<ChampionshipStandingsData> {
    return this.http.get<ChampionshipStandingsData>(
      `${this.apiBase}/${championshipId}/standings`
    );
  }

  refreshCache(championshipId: number): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(
      `${this.apiBase}/${championshipId}/refresh-cache`, {}
    );
  }
}


