import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { API } from '../api';

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

export interface ChampionshipIncidentWindow {
  raceId: number;
  windowId: string;
  isOpen: boolean;
  incidentsCount: number;
}

export interface IncidentWindowOut extends IncidentWindowListItem {
  incidents: Incident[];
}

export interface ResolveRemainingResult extends IncidentWindowOut {
  /** How many drivers the default verdict was just applied to. */
  resolvedCount: number;
}

export interface PublishWindowResult extends IncidentWindowOut {
  /** Penalties that reached no licence because the driver name never matched. */
  unlinkedCount: number;
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
  /** Omit to let the server apply the default verdict rule. */
  verdict?: string | null;
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
  /** Pre-selected for every driver in every incident. Exactly one rule has it. */
  isDefault: boolean;
}

export interface VerdictRuleCreate {
  verdict: string;
  defaultBwp: number;
  isDefault?: boolean;
}

export interface DescriptionPreset {
  id: string;
  text: string;
  sortOrder: number;
}

export interface DescriptionPresetCreate {
  text: string;
}

export interface BwpAuditEntry {
  incidentDriverId: string;
  driverName: string;
  bwpPoints: number;
  matchedDriverId: string | null;
  matchedDriverName: string | null;
}

export interface BwpBackfillResult {
  fixed: number;
  unmatched: string[];
}

// ── Service ────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class IncidentsApiService {
  private readonly http = inject(HttpClient);
  private readonly windows = `${API}/incident-windows`;

  getWindows(): Observable<IncidentWindowListItem[]> {
    return this.http.get<IncidentWindowListItem[]>(this.windows);
  }

  /** A championship's windows, one per round, keyed by SimGrid race id. */
  getChampionshipWindows(championshipId: number): Observable<ChampionshipIncidentWindow[]> {
    return this.http.get<ChampionshipIncidentWindow[]>(
      `${API}/championships/${championshipId}/incident-windows`,
    );
  }

  createWindow(payload: IncidentWindowCreate): Observable<IncidentWindowOut> {
    return this.http.post<IncidentWindowOut>(this.windows, payload);
  }

  getWindow(windowId: string): Observable<IncidentWindowOut> {
    return this.http.get<IncidentWindowOut>(`${this.windows}/${windowId}`);
  }

  closeWindow(windowId: string): Observable<IncidentWindowOut> {
    return this.updateWindow(windowId, { isManuallyClosed: true });
  }

  updateWindow(
    windowId: string,
    payload: Partial<{ isManuallyClosed: boolean; intervalHours: number }>,
  ): Observable<IncidentWindowOut> {
    return this.http.patch<IncidentWindowOut>(`${this.windows}/${windowId}`, payload);
  }

  deleteWindow(windowId: string): Observable<void> {
    return this.http.delete<void>(`${this.windows}/${windowId}`);
  }

  fileIncident(windowId: string, payload: IncidentFileCreate): Observable<Incident> {
    return this.http.post<Incident>(`${this.windows}/${windowId}/incidents`, payload);
  }

  /** Applies the default verdict to everyone in the window still awaiting one. */
  resolveRemaining(windowId: string): Observable<ResolveRemainingResult> {
    return this.http.post<ResolveRemainingResult>(
      `${this.windows}/${windowId}/default-resolutions`,
      {},
    );
  }

  /** Reveals every verdict in the window and issues the BWP they carry. */
  publishAllIncidents(windowId: string): Observable<PublishWindowResult> {
    return this.http.patch<PublishWindowResult>(`${this.windows}/${windowId}/incidents`, {
      isPublished: true,
    });
  }

  /** A fresh, unresolved and unpublished copy of the incident. */
  duplicateIncident(incidentId: string): Observable<Incident> {
    return this.http.post<Incident>(`${API}/incidents/${incidentId}/copies`, {});
  }

  /** Returns the driver that was added. */
  addDriverToIncident(incidentId: string, driverName: string): Observable<IncidentDriver> {
    return this.http.post<IncidentDriver>(`${API}/incidents/${incidentId}/drivers`, { driverName });
  }

  removeDriverFromIncident(incidentDriverId: string): Observable<void> {
    return this.http.delete<void>(`${API}/incident-drivers/${incidentDriverId}`);
  }

  resolveDriver(
    incidentDriverId: string,
    payload: ResolveDriverIncident,
  ): Observable<IncidentDriver> {
    return this.http.put<IncidentDriver>(
      `${API}/incident-drivers/${incidentDriverId}/resolution`,
      payload,
    );
  }

  bulkResolveIncident(incidentId: string, payload: BulkResolveIncident): Observable<Incident> {
    return this.http.put<Incident>(`${API}/incidents/${incidentId}/resolution`, payload);
  }

  /** Attach a free-text incident driver to a real driver record. */
  linkIncidentDriver(incidentDriverId: string, driverId: string): Observable<IncidentDriver> {
    return this.http.patch<IncidentDriver>(`${API}/incident-drivers/${incidentDriverId}`, {
      driverId,
    });
  }

  // ── Verdict rules ──────────────────────────────────────────────────────

  getVerdictRules(): Observable<VerdictRule[]> {
    return this.http.get<VerdictRule[]>(`${API}/verdict-rules`);
  }

  createVerdictRule(payload: VerdictRuleCreate): Observable<VerdictRule> {
    return this.http.post<VerdictRule>(`${API}/verdict-rules`, payload);
  }

  /** Reassign sort_order to match the given id order. */
  reorderVerdictRules(ids: string[]): Observable<VerdictRule[]> {
    return this.http.put<VerdictRule[]>(`${API}/verdict-rules/order`, { ids });
  }

  updateVerdictRule(id: string, payload: Partial<VerdictRuleCreate>): Observable<VerdictRule> {
    return this.http.patch<VerdictRule>(`${API}/verdict-rules/${id}`, payload);
  }

  deleteVerdictRule(id: string): Observable<void> {
    return this.http.delete<void>(`${API}/verdict-rules/${id}`);
  }

  // ── Description presets ─────────────────────────────────────────────────

  getDescriptionPresets(): Observable<DescriptionPreset[]> {
    return this.http.get<DescriptionPreset[]>(`${API}/description-presets`);
  }

  createDescriptionPreset(payload: DescriptionPresetCreate): Observable<DescriptionPreset> {
    return this.http.post<DescriptionPreset>(`${API}/description-presets`, payload);
  }

  updateDescriptionPreset(
    id: string,
    payload: Partial<DescriptionPresetCreate>,
  ): Observable<DescriptionPreset> {
    return this.http.patch<DescriptionPreset>(`${API}/description-presets/${id}`, payload);
  }

  deleteDescriptionPreset(id: string): Observable<void> {
    return this.http.delete<void>(`${API}/description-presets/${id}`);
  }

  // ── BWP repair ──────────────────────────────────────────────────────────

  getBwpAudit(): Observable<BwpAuditEntry[]> {
    return this.http.get<BwpAuditEntry[]>(`${API}/bwp-audit-entries`);
  }

  runBwpBackfill(): Observable<BwpBackfillResult> {
    return this.http.post<BwpBackfillResult>(`${API}/bwp-backfills`, {});
  }
}
