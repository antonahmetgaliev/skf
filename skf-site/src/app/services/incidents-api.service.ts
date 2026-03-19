import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export interface IncidentResolution {
  id: string;
  incidentId: string;
  judgeUserId: string | null;
  verdict: string;
  timePenaltySeconds: number | null;
  bwpPoints: number | null;
  bwpApplied: boolean;
  resolvedAt: string;
}

export interface Incident {
  id: string;
  windowId: string;
  reporterUserId: string | null;
  driver1Name: string;
  driver1DriverId: string | null;
  driver2Name: string | null;
  driver2DriverId: string | null;
  lapNumber: number | null;
  turn: string | null;
  description: string;
  status: string;
  createdAt: string;
  resolution: IncidentResolution | null;
}

export interface IncidentWindowListItem {
  id: string;
  championshipId: number;
  championshipName: string;
  raceId: number;
  raceName: string;
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

export interface IncidentWindowCreate {
  championshipId: number;
  championshipName: string;
  raceId: number;
  raceName: string;
  intervalHours: number;
}

export interface IncidentCreate {
  driver1Name: string;
  driver1DriverId: string | null;
  driver2Name: string | null;
  driver2DriverId: string | null;
  lapNumber: number | null;
  turn: string | null;
  description: string;
}

export interface ResolveIncident {
  verdict: string;
  timePenaltySeconds: number | null;
  bwpPoints: number | null;
}

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

  fileIncident(windowId: string, payload: IncidentCreate): Observable<Incident> {
    return this.http.post<Incident>(
      `${this.base}/windows/${windowId}/incidents`,
      payload
    );
  }

  resolveIncident(incidentId: string, payload: ResolveIncident): Observable<Incident> {
    return this.http.patch<Incident>(
      `/api/incidents/${incidentId}/resolve`,
      payload
    );
  }

  applyBwp(incidentId: string): Observable<Incident> {
    return this.http.patch<Incident>(
      `/api/incidents/${incidentId}/apply-bwp`,
      {}
    );
  }
}
