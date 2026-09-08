import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface PublicBwpPoint {
  id: string;
  points: number;
  issuedOn: string;
  expiresOn: string;
  note: string | null;
  /** Computed server-side — the single source of truth for expiry. */
  expired: boolean;
}

export interface DriverPublic {
  id: string;
  name: string;
  simgridDriverId: number | null;
  simgridDisplayName: string | null;
  countryCode: string | null;
  photoUrl: string | null;
  createdAt: string;
  /** Sum of non-expired BWP points, computed server-side. */
  activeBwp: number;
  points: PublicBwpPoint[];
  clearances: Array<{
    id: string;
    driverId: string;
    penaltyRuleId: string;
    clearedAt: string;
  }>;
}

export interface DriverIndexEntry {
  id: string;
  name: string;
  simgridDriverId: number | null;
}

@Injectable({ providedIn: 'root' })
export class ProfileApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/profile';

  getMyDriver(): Observable<DriverPublic> {
    return this.http.get<DriverPublic>(`${this.base}/me/driver`);
  }

  /** Public driver directory (no user linkage exposed). */
  getPublicDrivers(): Observable<DriverPublic[]> {
    return this.http.get<DriverPublic[]>(`${this.base}/drivers`);
  }

  /** Slim list for mapping SimGrid ids to driver UUIDs. */
  getDriversIndex(): Observable<DriverIndexEntry[]> {
    return this.http.get<DriverIndexEntry[]>(`${this.base}/drivers-index`);
  }

  getPublicDriver(driverId: string): Observable<DriverPublic> {
    return this.http.get<DriverPublic>(`${this.base}/drivers/${driverId}`);
  }

  updateDriverPhoto(photoUrl: string | null): Observable<DriverPublic> {
    return this.http.patch<DriverPublic>(`${this.base}/me/driver-photo`, { photoUrl });
  }
}
