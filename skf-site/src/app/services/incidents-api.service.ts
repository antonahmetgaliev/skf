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
  description: string | null;
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
  lap: string | null;
  corner: string | null;
  description: string | null;
  source: string;
  status: string;
  isPublished: boolean;
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
  lap?: string | null;
  corner?: string | null;
  description?: string | null;
  drivers: string[];
}

export interface ResolveDriverIncident {
  verdict: string;
  bwpPoints?: number | null;
}

export interface BulkResolveDriverItem {
  incidentDriverId: string;
  verdict: string;
  bwpPoints?: number | null;
}

export interface BulkResolveIncident {
  description?: string | null;
  drivers: BulkResolveDriverItem[];
}

export interface VerdictRule {
  id: string;
  verdict: string;
  defaultBwp: number;
  sortOrder: number;
}

export interface VerdictRuleCreate {
  verdict: string;
  defaultBwp: number;
}

export interface DescriptionPreset {
  id: string;
  text: string;
  sortOrder: number;
}

export interface DescriptionPresetCreate {
  text: string;
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

  publishAllIncidents(windowId: string): Observable<IncidentWindowOut> {
    return this.http.post<IncidentWindowOut>(`${this.base}/windows/${windowId}/publish-all`, {});
  }

  duplicateIncident(incidentId: string): Observable<Incident> {
    return this.http.post<Incident>(`${this.base}/${incidentId}/duplicate`, {});
  }

  publishIncident(incidentId: string): Observable<Incident> {
    return this.http.post<Incident>(`${this.base}/${incidentId}/publish`, {});
  }

  addDriverToIncident(incidentId: string, driverName: string): Observable<Incident> {
    return this.http.post<Incident>(`${this.base}/${incidentId}/drivers`, { driverName });
  }

  removeDriverFromIncident(incidentDriverId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/drivers/${incidentDriverId}`);
  }

  resolveDriver(incidentDriverId: string, payload: ResolveDriverIncident): Observable<IncidentDriver> {
    return this.http.patch<IncidentDriver>(
      `${this.base}/drivers/${incidentDriverId}/resolve`,
      payload
    );
  }

  bulkResolveIncident(incidentId: string, payload: BulkResolveIncident): Observable<Incident> {
    return this.http.patch<Incident>(
      `${this.base}/${incidentId}/resolve`,
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

  // ── Verdict rules ──────────────────────────────────────────────────────

  getVerdictRules(): Observable<VerdictRule[]> {
    return this.http.get<VerdictRule[]>(`${this.base}/verdict-rules`);
  }

  createVerdictRule(payload: VerdictRuleCreate): Observable<VerdictRule> {
    return this.http.post<VerdictRule>(`${this.base}/verdict-rules`, payload);
  }

  updateVerdictRule(id: string, payload: Partial<VerdictRuleCreate>): Observable<VerdictRule> {
    return this.http.patch<VerdictRule>(`${this.base}/verdict-rules/${id}`, payload);
  }

  deleteVerdictRule(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/verdict-rules/${id}`);
  }

  // ── Description presets ─────────────────────────────────────────────────

  getDescriptionPresets(): Observable<DescriptionPreset[]> {
    return this.http.get<DescriptionPreset[]>(`${this.base}/description-presets`);
  }

  createDescriptionPreset(payload: DescriptionPresetCreate): Observable<DescriptionPreset> {
    return this.http.post<DescriptionPreset>(`${this.base}/description-presets`, payload);
  }

  updateDescriptionPreset(id: string, payload: Partial<DescriptionPresetCreate>): Observable<DescriptionPreset> {
    return this.http.patch<DescriptionPreset>(`${this.base}/description-presets/${id}`, payload);
  }

  deleteDescriptionPreset(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/description-presets/${id}`);
  }
}
