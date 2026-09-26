import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API } from '../api';

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

  getEligibility(
    championshipId: number,
    minDistancePct: number,
    minRounds: number,
  ): Observable<Eligibility> {
    return this.http.get<Eligibility>(
      `${API}/championships/${championshipId}/giveaway-eligibility`,
      { params: { minDistancePct, minRounds } },
    );
  }

  getUnmatched(championshipId: number): Observable<UnmatchedName[]> {
    return this.http.get<UnmatchedName[]>(
      `${API}/championships/${championshipId}/unmatched-driver-names`,
    );
  }

  /** Upsert keyed by the alias spelling (201 created, 200 updated). */
  createAlias(normalizedAlias: string, canonicalDisplayName: string): Observable<unknown> {
    return this.http.post(`${API}/driver-aliases`, {
      normalizedAlias,
      canonicalDisplayName,
    });
  }
}
