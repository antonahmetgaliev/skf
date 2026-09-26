import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';
import { API } from '../api';

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

/** The signed-in user's own driver: the public view plus the account link. */
export interface MyDriver extends DriverPublic {
  userId: string | null;
}

/**
 * Upper bound the backend allows per page. The directory is fetched in one
 * request; `X-Total-Count` would tell if it ever outgrows this.
 */
const ALL_DRIVERS = 1000;

@Injectable({ providedIn: 'root' })
export class ProfileApiService {
  private readonly http = inject(HttpClient);

  getMyDriver(): Observable<MyDriver> {
    return this.http.get<MyDriver>(`${API}/me/driver`);
  }

  /** Public driver directory (no user linkage exposed). */
  getPublicDrivers(): Observable<DriverPublic[]> {
    return this.http.get<DriverPublic[]>(`${API}/drivers`, {
      params: { limit: ALL_DRIVERS },
    });
  }

  /** SimGrid driver id → driver UUID, for linking standings to profiles. */
  getDriverUuidsBySimgridId(): Observable<Map<number, string>> {
    return this.getPublicDrivers().pipe(
      map((drivers) => {
        const bySimgridId = new Map<number, string>();
        for (const d of drivers) {
          if (d.simgridDriverId) bySimgridId.set(d.simgridDriverId, d.id);
        }
        return bySimgridId;
      })
    );
  }

  /**
   * One public profile. Route ids are UUIDs; an all-digits id is treated as a
   * SimGrid driver id (old links) and resolved through `?simgridId=`.
   */
  getPublicDriver(driverId: string): Observable<DriverPublic> {
    if (/^\d+$/.test(driverId)) {
      return this.http
        .get<DriverPublic[]>(`${API}/drivers`, { params: { simgridId: driverId, limit: 1 } })
        .pipe(
          map((drivers) => {
            if (!drivers.length) throw new Error('Driver not found.');
            return drivers[0];
          })
        );
    }
    return this.http.get<DriverPublic>(`${API}/drivers/${driverId}`);
  }

  /** Set (https only) or clear (`null`) the signed-in user's driver photo. */
  updateDriverPhoto(photoUrl: string | null): Observable<MyDriver> {
    return this.http.patch<MyDriver>(`${API}/me/driver`, { photoUrl });
  }
}
