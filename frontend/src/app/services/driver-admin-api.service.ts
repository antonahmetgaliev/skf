import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { API, Schemas } from '../api';

export type DriverIssue = Schemas['DriverIssueOut'];
export type DriverSyncResult = Schemas['DriverSyncOut'];
export type DriverLink = Schemas['DriverLinkOut'];

/** Keeping drivers one-per-person and linked to the right account. */
@Injectable({ providedIn: 'root' })
export class DriverAdminApiService {
  private readonly http = inject(HttpClient);

  /** Drivers without a SimGrid id, or sharing one with another row. */
  getIssues(): Observable<DriverIssue[]> {
    return this.http.get<DriverIssue[]>(`${API}/driver-issues`);
  }

  /** Refresh drivers and account links from every active championship. */
  sync(): Observable<DriverSyncResult> {
    return this.http.post<DriverSyncResult>(`${API}/driver-syncs`, null);
  }

  /** Fold `sourceId` into `targetId`; the source row is deleted. */
  merge(targetId: string, sourceId: string): Observable<Schemas['DriverOut']> {
    return this.http.post<Schemas['DriverOut']>(`${API}/drivers/${targetId}/merges`, {
      sourceDriverId: sourceId,
    });
  }

  setUserDriver(userId: string, driverId: string): Observable<Schemas['UserOut']> {
    return this.http.put<Schemas['UserOut']>(`${API}/users/${userId}/driver`, { driverId });
  }

  clearUserDriver(userId: string): Observable<void> {
    return this.http.delete<void>(`${API}/users/${userId}/driver`);
  }

  /** Look the signed-in user up on SimGrid; links their driver or says why there is none. */
  linkMyDriver(): Observable<DriverLink> {
    return this.http.post<DriverLink>(`${API}/me/driver-links`, null);
  }
}
