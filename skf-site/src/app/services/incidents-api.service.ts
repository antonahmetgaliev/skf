import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

// ── Output types ───────────────────────────────────────────────────────────

export interface IncidentResolution {
  id: string;
  incidentDriverId: string;
  judgeUserId: string | null;
  verdict: string;
  bwpPoints: number | null;
  bwpApplied: boolean;
  resolvedAt: string;
}

export interface IncidentDriver {
  id: string;
  driverName: string;
  driverId: string | null;
  sortOrder: number;
  resolution: IncidentResolution | null;
}

export interface Incident {
  id: string;
  windowId: string;
  reporterUserId: string | null;
  sessionName: string | null;
  time: string | null;
  description: string | null;
  status: string;
  createdAt: string;
  drivers: IncidentDriver[];
}

export interface IncidentWindowListItem {
  id: string;
  championshipId: number | null;
  championshipName: string | null;
  raceId: number | null;
  raceName: string;
  date: string | null;
  intervalHours: number;
  openedAt: string;
  closesAt: string;
  openedByUserId: string | null;
  isManuallyClosed: boolean;
  isOpen: boolean;
}

export interface IncidentWindowOut extends IncidentWindowListItem {
  incidents: Incident[];
}

// ── Input types ────────────────────────────────────────────────────────────

export interface IncidentWindowCreate {
  championshipId?: number | null;
  championshipName?: string | null;
  raceId?: number | null;
  raceName: string;
  date?: string | null;
  intervalHours?: number;
}

export interface IncidentFileCreate {
  sessionName?: string | null;
  time?: string | null;
  description?: string | null;
  drivers: string[];
}

export interface ResolveDriverIncident {
  verdict: string;
  bwpPoints?: number | null;
}

// ── Service ────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class IncidentsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/incidents';

  getWindows(): Observable<IncidentWindowListItem[]> {
    return this.http.get<IncidentWindowListItem[]>(`${this.base}/windows`);
  }

  createWindow(payload: IncidentWindowCreate): Observable<IncidentWindowOut> {
    return this.http.post<IncidentWindowOut>(`${this.base}/windows`, payload);
  }

  getWindow(windowId: string): Observable<IncidentWindowOut> {
    return this.http.get<IncidentWindowOut>(`${this.base}/windows/${windowId}`);
  }

  closeWindow(windowId: string): Observable<IncidentWindowOut> {
    return this.http.patch<IncidentWindowOut>(
      `${this.base}/windows/${windowId}`,
      { isManuallyClosed: true }
    );
  }

  updateWindow(
    windowId: string,
    payload: Partial<{ isManuallyClosed: boolean; intervalHours: number }>
  ): Observable<IncidentWindowOut> {
    return this.http.patch<IncidentWindowOut>(
      `${this.base}/windows/${windowId}`,
      payload
    );
  }

  deleteWindow(windowId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/windows/${windowId}`);
  }

  fileIncident(windowId: string, payload: IncidentFileCreate): Observable<Incident> {
    return this.http.post<Incident>(
      `${this.base}/windows/${windowId}/incidents`,
      payload
    );
  }

  resolveDriver(incidentDriverId: string, payload: ResolveDriverIncident): Observable<IncidentDriver> {
    return this.http.patch<IncidentDriver>(
      `${this.base}/drivers/${incidentDriverId}/resolve`,
      payload
    );
  }

  applyDriverBwp(incidentDriverId: string): Observable<IncidentDriver> {
    return this.http.patch<IncidentDriver>(
      `${this.base}/drivers/${incidentDriverId}/apply-bwp`,
      {}
    );
  }

  discardDriverBwp(incidentDriverId: string): Observable<IncidentDriver> {
    return this.http.patch<IncidentDriver>(
      `${this.base}/drivers/${incidentDriverId}/discard`,
      {}
    );
  }
}
