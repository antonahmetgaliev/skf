import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

/** Simulators whose result file the backend can parse. */
export type RaceSim = 'lmu' | 'iracing';

/** File each simulator's upload expects. */
export const SIM_FILE_ACCEPT: Record<RaceSim, string> = {
  lmu: '.xml,text/xml,application/xml',
  iracing: '.bin',
};

export const SIM_LABELS: Record<RaceSim, string> = {
  lmu: 'LMU',
  iracing: 'iRacing',
};

export interface RaceImport {
  id: string;
  sim: RaceSim;
  trackEvent: string | null;
  sessionStartedAt: string | null;
  sourceFilename: string | null;
  fileSize: number | null;
  /** The original file is kept in the bucket. */
  hasFile: boolean;
  entryCount: number;
  unmatchedCount: number;
  contactsCount: number;
  autoGrouped: boolean;
  createdAt: string;
}

export interface RoundWindow {
  id: string;
  isOpen: boolean;
  closesAt: string;
  incidentsCount: number;
}

export interface RaceRound {
  raceId: number;
  name: string;
  startsAt: string | null;
  ended: boolean;
  raceImport: RaceImport | null;
  window: RoundWindow | null;
}

export interface RaceRounds {
  championshipId: number;
  championshipName: string;
  gameName: string;
  /** Null when the championship's game has no supported result file. */
  sim: RaceSim | null;
  storageEnabled: boolean;
  rounds: RaceRound[];
}

export interface ImportResult {
  raceImport: RaceImport;
  windowId: string | null;
  incidentsCreated: number;
  incidentsKept: number;
}

@Injectable({ providedIn: 'root' })
export class RaceResultsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/race-results';

  getRounds(championshipSimgridId: number): Observable<RaceRounds> {
    return this.http.get<RaceRounds>(`${this.base}/rounds`, {
      params: { championshipSimgridId },
    });
  }

  upload(
    championshipSimgridId: number,
    raceSimgridId: number,
    file: File,
    createIncidents: boolean,
  ): Observable<ImportResult> {
    const body = new FormData();
    body.append('file', file);
    body.append('championshipSimgridId', String(championshipSimgridId));
    body.append('raceSimgridId', String(raceSimgridId));
    body.append('createIncidents', String(createIncidents));
    return this.http.post<ImportResult>(`${this.base}/imports`, body);
  }

  reparse(importId: string): Observable<ImportResult> {
    return this.http.post<ImportResult>(`${this.base}/imports/${importId}/reparse`, null);
  }

  download(importId: string): Observable<Blob> {
    return this.http.get(`${this.base}/imports/${importId}/file`, { responseType: 'blob' });
  }

  deleteImport(importId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/imports/${importId}`);
  }
}
