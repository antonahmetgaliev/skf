import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface GiveawayRound {
  id: number;
  name: string;
  startsAt: string | null;
  ended: boolean;
}

export interface RaceResultImport {
  id: string;
  championshipSimgridId: number;
  raceSimgridId: number | null;
  trackEvent: string | null;
  sessionStartedAt: string | null;
  sourceFilename: string | null;
  createdAt: string;
  entryCount: number;
  unmatchedCount: number;
}

export interface RoundBreakdown {
  roundKey: string;
  roundLabel: string;
  carClass: string;
  laps: number;
  classLeaderLaps: number;
  distancePct: number;
  qualifies: boolean;
}

export interface EligibleDriver {
  identity: string;
  displayName: string;
  carClass: string;
  qualifyingRounds: number;
  rounds: RoundBreakdown[];
}

export interface Eligibility {
  championshipSimgridId: number;
  minDistancePct: number;
  minRounds: number;
  importedRounds: number;
  carClasses: string[];
  drivers: EligibleDriver[];
}

export interface UnmatchedName {
  rawName: string;
  normalizedName: string;
  rounds: number;
  /** Ranked spelling hints. Never applied without an admin decision. */
  suggestions: string[];
}

@Injectable({ providedIn: 'root' })
export class GiveawayApiService {
  private readonly http = inject(HttpClient);

  getRounds(championshipSimgridId: number): Observable<GiveawayRound[]> {
    return this.http.get<GiveawayRound[]>('/api/giveaway/rounds', {
      params: { championshipSimgridId },
    });
  }

  getImports(championshipSimgridId: number): Observable<RaceResultImport[]> {
    return this.http.get<RaceResultImport[]>('/api/giveaway/imports', {
      params: { championshipSimgridId },
    });
  }

  uploadResults(
    championshipSimgridId: number,
    raceSimgridId: number | null,
    file: File,
  ): Observable<RaceResultImport> {
    const body = new FormData();
    body.append('file', file);
    body.append('championshipSimgridId', String(championshipSimgridId));
    if (raceSimgridId !== null) body.append('raceSimgridId', String(raceSimgridId));
    return this.http.post<RaceResultImport>('/api/giveaway/imports', body);
  }

  deleteImport(importId: string): Observable<void> {
    return this.http.delete<void>(`/api/giveaway/imports/${importId}`);
  }

  getEligibility(
    championshipSimgridId: number,
    minDistancePct: number,
    minRounds: number,
  ): Observable<Eligibility> {
    return this.http.get<Eligibility>('/api/giveaway/eligibility', {
      params: { championshipSimgridId, minDistancePct, minRounds },
    });
  }

  getUnmatched(championshipSimgridId: number): Observable<UnmatchedName[]> {
    return this.http.get<UnmatchedName[]>('/api/giveaway/unmatched', {
      params: { championshipSimgridId },
    });
  }

  createAlias(normalizedAlias: string, canonicalDisplayName: string): Observable<unknown> {
    return this.http.post('/api/giveaway/aliases', {
      normalizedAlias,
      canonicalDisplayName,
    });
  }
}
