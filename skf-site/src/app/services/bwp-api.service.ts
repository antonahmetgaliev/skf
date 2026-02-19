import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface BwpPoint {
  id: string;
  points: number;
  issuedOn: string;
  expiresOn: string;
}

export interface Driver {
  id: string;
  name: string;
  createdAt: string;
  points: BwpPoint[];
}

export interface PenaltyRule {
  id: string;
  threshold: number;
  label: string;
  sortOrder: number;
}

@Injectable({ providedIn: 'root' })
export class BwpApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/bwp';

  // ── Drivers ──────────────────────────────────────────────────────

  getDrivers(): Observable<Driver[]> {
    return this.http.get<Driver[]>(`${this.base}/drivers`);
  }

  createDriver(name: string): Observable<Driver> {
    return this.http.post<Driver>(`${this.base}/drivers`, { name });
  }

  deleteDriver(driverId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/drivers/${driverId}`);
  }

  // ── Points ───────────────────────────────────────────────────────

  addPoint(
    driverId: string,
    payload: { points: number; issuedOn: string; expiresOn: string }
  ): Observable<BwpPoint> {
    return this.http.post<BwpPoint>(
      `${this.base}/drivers/${driverId}/points`,
      payload
    );
  }

  deletePoint(pointId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/points/${pointId}`);
  }

  // ── Penalty Rules ────────────────────────────────────────────────

  getPenaltyRules(): Observable<PenaltyRule[]> {
    return this.http.get<PenaltyRule[]>(`${this.base}/penalty-rules`);
  }

  createPenaltyRule(payload: {
    threshold: number;
    label: string;
  }): Observable<PenaltyRule> {
    return this.http.post<PenaltyRule>(`${this.base}/penalty-rules`, payload);
  }

  updatePenaltyRule(
    ruleId: string,
    patch: { threshold?: number; label?: string }
  ): Observable<PenaltyRule> {
    return this.http.patch<PenaltyRule>(
      `${this.base}/penalty-rules/${ruleId}`,
      patch
    );
  }

  deletePenaltyRule(ruleId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/penalty-rules/${ruleId}`);
  }
}
