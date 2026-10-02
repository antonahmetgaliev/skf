import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { API, Schemas } from '../api';

export type BwpPoint = Schemas['BwpPointOut'];

export type PenaltyClearance = Schemas['PenaltyClearanceOut'];

export type Driver = Schemas['DriverOut'];

export type DriverUpdate = Schemas['DriverUpdate'];

export type PenaltyRule = Schemas['PenaltyRuleOut'];

export type PenaltyRuleUpdate = Schemas['PenaltyRuleUpdate'];

@Injectable({ providedIn: 'root' })
export class BwpApiService {
  private readonly http = inject(HttpClient);

  // ── Drivers ──────────────────────────────────────────────────────

  /** Judge view of every driver, including the linked account (`userId`). */
  getDrivers(): Observable<Driver[]> {
    return this.http.get<Driver[]>(`${API}/drivers`, {
      params: { include: 'account', limit: 1000 },
    });
  }

  createDriver(name: string): Observable<Driver> {
    return this.http.post<Driver>(`${API}/drivers`, { name });
  }

  updateDriver(driverId: string, patch: DriverUpdate): Observable<Driver> {
    return this.http.patch<Driver>(`${API}/drivers/${driverId}`, patch);
  }

  deleteDriver(driverId: string): Observable<void> {
    return this.http.delete<void>(`${API}/drivers/${driverId}`);
  }

  // ── Points ───────────────────────────────────────────────────────

  addPoint(
    driverId: string,
    payload: { points: number; issuedOn: string; expiresOn: string },
  ): Observable<BwpPoint> {
    return this.http.post<BwpPoint>(`${API}/drivers/${driverId}/bwp-points`, payload);
  }

  deletePoint(pointId: string): Observable<void> {
    return this.http.delete<void>(`${API}/bwp-points/${pointId}`);
  }

  expirePoint(pointId: string, note: string): Observable<BwpPoint> {
    return this.http.patch<BwpPoint>(`${API}/bwp-points/${pointId}`, { expired: true, note });
  }

  // ── Penalty Rules ────────────────────────────────────────────────

  getPenaltyRules(): Observable<PenaltyRule[]> {
    return this.http.get<PenaltyRule[]>(`${API}/penalty-rules`);
  }

  createPenaltyRule(payload: { threshold: number; label: string }): Observable<PenaltyRule> {
    return this.http.post<PenaltyRule>(`${API}/penalty-rules`, payload);
  }

  updatePenaltyRule(ruleId: string, patch: PenaltyRuleUpdate): Observable<PenaltyRule> {
    return this.http.patch<PenaltyRule>(`${API}/penalty-rules/${ruleId}`, patch);
  }

  deletePenaltyRule(ruleId: string): Observable<void> {
    return this.http.delete<void>(`${API}/penalty-rules/${ruleId}`);
  }

  // ── Penalty Clearances ───────────────────────────────────────────

  setClearance(driverId: string, ruleId: string): Observable<PenaltyClearance> {
    return this.http.put<PenaltyClearance>(`${API}/drivers/${driverId}/clearances/${ruleId}`, null);
  }

  removeClearance(driverId: string, ruleId: string): Observable<void> {
    return this.http.delete<void>(`${API}/drivers/${driverId}/clearances/${ruleId}`);
  }

  expireAllPoints(driverId: string, note: string): Observable<Driver> {
    return this.http.post<Driver>(`${API}/drivers/${driverId}/bwp-resets`, { note });
  }
}
