import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface LinkCandidate {
  id: string;
  name: string;
  simgridDisplayName: string | null;
  countryCode: string | null;
}

export interface DriverPublic {
  id: string;
  name: string;
  simgridDriverId: number | null;
  simgridDisplayName: string | null;
  countryCode: string | null;
  createdAt: string;
  points: Array<{
    id: string;
    points: number;
    issuedOn: string;
    expiresOn: string;
  }>;
  clearances: Array<{
    id: string;
    driverId: string;
    penaltyRuleId: string;
    clearedAt: string;
  }>;
}

export interface DriverChampionshipResult {
  championshipId: number;
  championshipName: string;
  position: number | null;
  score: number;
  dsq: boolean;
  startDate: string | null;
  endDate: string | null;
  acceptingRegistrations: boolean;
}

@Injectable({ providedIn: 'root' })
export class ProfileApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/profile';

  getLinkCandidates(): Observable<LinkCandidate[]> {
    return this.http.get<LinkCandidate[]>(`${this.base}/link-candidates`);
  }

  linkDriver(driverId: string): Observable<void> {
    return this.http.post<void>(`${this.base}/link-driver`, { driver_id: driverId });
  }

  unlinkDriver(): Observable<void> {
    return this.http.delete<void>(`${this.base}/unlink-driver`);
  }

  getMyDriver(): Observable<DriverPublic> {
    return this.http.get<DriverPublic>(`${this.base}/me/driver`);
  }

  getPublicDriver(driverId: string): Observable<DriverPublic> {
    return this.http.get<DriverPublic>(`${this.base}/drivers/${driverId}`);
  }

  getDriverChampionshipResults(simgridDriverId: number): Observable<DriverChampionshipResult[]> {
    return this.http.get<DriverChampionshipResult[]>(`/api/championships/driver/${simgridDriverId}/results`);
  }
}
