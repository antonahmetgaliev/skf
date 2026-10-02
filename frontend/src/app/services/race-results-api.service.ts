import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API, Schemas } from '../api';

/** Simulators whose result file the backend can parse. */
export type RaceSim = Schemas['RaceResultImportOut']['sim'];

/** File each simulator's upload expects. */
export const SIM_FILE_ACCEPT: Record<RaceSim, string> = {
  lmu: '.xml,text/xml,application/xml',
  iracing: '.bin',
};

export const SIM_LABELS: Record<RaceSim, string> = {
  lmu: 'LMU',
  iracing: 'iRacing',
};

export type RaceImport = Schemas['RaceResultImportOut'];

export type RoundWindow = Schemas['IncidentWindowStatusOut'];

export type RaceRound = Schemas['RoundOut'];

export type RaceRounds = Schemas['RoundsOut'];

export type ImportResult = Schemas['RaceResultImportResultOut'];

@Injectable({ providedIn: 'root' })
export class RaceResultsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API}/race-result-imports`;

  getRounds(championshipId: number): Observable<RaceRounds> {
    return this.http.get<RaceRounds>(`${API}/championships/${championshipId}/rounds`);
  }

  upload(
    championshipId: number,
    raceId: number,
    file: File,
    createIncidents: boolean,
  ): Observable<ImportResult> {
    const body = new FormData();
    body.append('file', file);
    body.append('championshipId', String(championshipId));
    body.append('raceId', String(raceId));
    body.append('createIncidents', String(createIncidents));
    return this.http.post<ImportResult>(this.base, body);
  }

  /** Re-run the parser on the stored original; the import gets a new id. */
  reparse(importId: string): Observable<ImportResult> {
    return this.http.post<ImportResult>(`${this.base}/${importId}/parse-runs`, null);
  }

  download(importId: string): Observable<Blob> {
    return this.http.get(`${this.base}/${importId}/file`, { responseType: 'blob' });
  }

  deleteImport(importId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${importId}`);
  }
}
