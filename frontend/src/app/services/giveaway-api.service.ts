import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { API, Schemas } from '../api';

export type RoundBreakdown = Schemas['RoundBreakdownOut'];

export type EligibleDriver = Schemas['EligibleDriverOut'];

export type Eligibility = Schemas['GiveawayEligibilityOut'];

export type UnmatchedName = Schemas['UnmatchedDriverNameOut'];

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
