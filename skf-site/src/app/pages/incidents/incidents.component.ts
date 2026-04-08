import { DatePipe } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BadgeComponent, BadgeVariant } from '../../components/badge/badge.component';
import { CardComponent } from '../../components/card/card.component';
import { DetailListComponent } from '../../components/detail-list/detail-list.component';
import { FormFieldComponent } from '../../components/form-field/form-field.component';
import { EmptyComponent } from '../../components/empty/empty.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { ModalComponent } from '../../components/modal/modal.component';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../../services/auth.service';
import { BwpApiService, Driver } from '../../services/bwp-api.service';
import {
  ChampionshipListItem,
  SimgridApiService,
  StandingRace,
} from '../../services/simgrid-api.service';
import {
  Incident,
  IncidentDriver,
  IncidentWindowListItem,
  IncidentWindowOut,
  IncidentsApiService,
} from '../../services/incidents-api.service';

@Component({
  selector: 'app-incidents',
  imports: [FormsModule, DatePipe, BadgeComponent, CardComponent, DetailListComponent, EmptyComponent, FormFieldComponent, PageIntroComponent, PageLayoutComponent, SpinnerComponent, BtnComponent, ModalComponent],
  templateUrl: './incidents.component.html',
  styleUrl: './incidents.component.scss',
})
export class IncidentsComponent implements OnInit {
  readonly auth = inject(AuthService);
  private readonly incidentsApi = inject(IncidentsApiService);
  private readonly simgridApi = inject(SimgridApiService);
  private readonly bwpApi = inject(BwpApiService);

  readonly verdictPresets = ['NFA', 'Warning', '5s Time Penalty', '10s Time Penalty', 'Drive Through', 'Stop & Go', 'DSQ'];

  // ── Data ──────────────────────────────────────────────────────────
  readonly windows = signal<IncidentWindowListItem[]>([]);
  readonly loadingWindows = signal(false);
  readonly windowDetail = signal<IncidentWindowOut | null>(null);
  readonly loadingDetail = signal(false);
  readonly bwpDrivers = signal<Driver[]>([]);
  readonly championships = signal<ChampionshipListItem[]>([]);
  readonly availableRaces = signal<StandingRace[]>([]);
  readonly loadingRaces = signal(false);

  // ── Modal visibility ──────────────────────────────────────────────
  readonly showNewWindowModal = signal(false);
  readonly showNewIncidentModal = signal(false);
  readonly showDetailModal = signal(false);
  readonly detailIncident = signal<Incident | null>(null);

  // ── Expanded incidents (for inline resolution) ────────────────────
  readonly expandedIncidentId = signal<string | null>(null);

  // ── New Window form fields ────────────────────────────────────────
  nwChampId: number | null = null;
  nwChampName = '';
  nwRaceId: number | null = null;
  nwRaceName = '';
  nwIntervalHours = 24;
  nwSubmitting = false;
  nwError = '';

  // ── File Incident form fields ──────────────────────────────────────
  niDriverNames: string[] = ['', ''];
  niSessionName = '';
  niTime = '';
  niDescription = '';
  niSubmitting = false;
  niError = '';

  // ── Per-driver resolve state (keyed by incidentDriverId) ──────────
  rvVerdicts: Record<string, string> = {};
  rvBwpPoints: Record<string, number | null> = {};
  rvSubmitting: Record<string, boolean> = {};
  rvError: Record<string, string> = {};

  ngOnInit(): void {
    this.loadWindows();
    firstValueFrom(this.bwpApi.getDrivers()).then((ds) =>
      this.bwpDrivers.set(ds)
    );
    firstValueFrom(this.simgridApi.getChampionships()).then((cs) =>
      this.championships.set(cs)
    );
  }

  // ── Windows ───────────────────────────────────────────────────────

  async loadWindows(): Promise<void> {
    this.loadingWindows.set(true);
    try {
      const ws = await firstValueFrom(this.incidentsApi.getWindows());
      this.windows.set(ws);
    } finally {
      this.loadingWindows.set(false);
    }
  }

  async selectWindow(id: string, forceReload = false): Promise<void> {
    if (this.windowDetail()?.id === id && !forceReload) return;
    this.loadingDetail.set(true);
    this.windowDetail.set(null);
    try {
      const detail = await firstValueFrom(this.incidentsApi.getWindow(id));
      this.windowDetail.set(detail);
    } finally {
      this.loadingDetail.set(false);
    }
  }

  closesIn(closesAt: string): string {
    const ms = new Date(closesAt).getTime() - Date.now();
    if (ms <= 0) return 'Closed';
    const h = Math.floor(ms / 3_600_000);
    const m = Math.floor((ms % 3_600_000) / 60_000);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  // ── New Window ────────────────────────────────────────────────────

  openNewWindowModal(): void {
    this.nwChampId = null;
    this.nwChampName = '';
    this.nwRaceId = null;
    this.nwRaceName = '';
    this.nwIntervalHours = 24;
    this.nwError = '';
    this.availableRaces.set([]);
    this.showNewWindowModal.set(true);
  }

  async onChampionshipChange(id: string): Promise<void> {
    const champId = Number(id);
    const champ = this.championships().find((c) => c.id === champId);
    this.nwChampId = champId || null;
    this.nwChampName = champ?.name ?? '';
    this.nwRaceId = null;
    this.nwRaceName = '';
    if (!champId) return;
    this.loadingRaces.set(true);
    try {
      const data = await firstValueFrom(
        this.simgridApi.getChampionshipStandings(champId)
      );
      this.availableRaces.set(data.races);
    } finally {
      this.loadingRaces.set(false);
    }
  }

  onRaceChange(id: string): void {
    const raceId = Number(id);
    const race = this.availableRaces().find((r) => r.id === raceId);
    this.nwRaceId = raceId || null;
    this.nwRaceName = race?.displayName ?? '';
  }

  async submitNewWindow(): Promise<void> {
    if (!this.nwRaceName.trim()) {
      this.nwError = 'Race name is required.';
      return;
    }
    this.nwSubmitting = true;
    this.nwError = '';
    try {
      await firstValueFrom(
        this.incidentsApi.createWindow({
          championshipId: this.nwChampId,
          championshipName: this.nwChampName,
          raceId: this.nwRaceId,
          raceName: this.nwRaceName,
          intervalHours: this.nwIntervalHours,
        })
      );
      this.showNewWindowModal.set(false);
      await this.loadWindows();
    } catch {
      this.nwError = 'Failed to create window. Please try again.';
    } finally {
      this.nwSubmitting = false;
    }
  }

  async closeWindow(windowId: string): Promise<void> {
    await firstValueFrom(
      this.incidentsApi.updateWindow(windowId, { isManuallyClosed: true })
    );
    await this.loadWindows();
    const detail = this.windowDetail();
    if (detail?.id === windowId) {
      await this.selectWindow(windowId, true);
    }
  }

  async deleteWindow(windowId: string): Promise<void> {
    if (!confirm('Delete this incident window and all its incidents?')) return;
    await firstValueFrom(this.incidentsApi.deleteWindow(windowId));
    if (this.windowDetail()?.id === windowId) {
      this.windowDetail.set(null);
    }
    await this.loadWindows();
  }

  // ── File Incident ─────────────────────────────────────────────────

  openNewIncidentModal(): void {
    this.niDriverNames = ['', ''];
    this.niSessionName = '';
    this.niTime = '';
    this.niDescription = '';
    this.niError = '';
    this.showNewIncidentModal.set(true);
  }

  addDriver(): void {
    this.niDriverNames = [...this.niDriverNames, ''];
  }

  removeDriver(index: number): void {
    if (this.niDriverNames.length <= 1) return;
    this.niDriverNames = this.niDriverNames.filter((_, i) => i !== index);
  }

  trackByIndex(index: number): number {
    return index;
  }

  async submitIncident(): Promise<void> {
    const windowId = this.windowDetail()?.id;
    if (!windowId) return;
    const drivers = this.niDriverNames.map((n) => n.trim()).filter(Boolean);
    if (drivers.length === 0) {
      this.niError = 'At least one driver is required.';
      return;
    }
    this.niSubmitting = true;
    this.niError = '';
    try {
      await firstValueFrom(
        this.incidentsApi.fileIncident(windowId, {
          sessionName: this.niSessionName.trim() || undefined,
          time: this.niTime.trim() || undefined,
          description: this.niDescription.trim() || undefined,
          drivers,
        })
      );
      this.showNewIncidentModal.set(false);
      await this.selectWindow(windowId, true);
    } catch {
      this.niError = 'Failed to file incident. Please try again.';
    } finally {
      this.niSubmitting = false;
    }
  }

  // ── Expand / Collapse incidents ────────────────────────────────────

  toggleIncident(incidentId: string): void {
    this.expandedIncidentId.set(
      this.expandedIncidentId() === incidentId ? null : incidentId
    );
  }

  // ── Per-driver resolve ─────────────────────────────────────────────

  initResolveFields(driver: IncidentDriver): void {
    if (this.rvVerdicts[driver.id] === undefined) {
      this.rvVerdicts[driver.id] = driver.resolution?.verdict ?? '';
      this.rvBwpPoints[driver.id] = driver.resolution?.bwpPoints ?? null;
    }
  }

  async submitResolveDriver(driverId: string): Promise<void> {
    const verdict = (this.rvVerdicts[driverId] ?? '').trim();
    if (!verdict) {
      this.rvError[driverId] = 'Verdict is required.';
      return;
    }
    this.rvSubmitting[driverId] = true;
    this.rvError[driverId] = '';
    try {
      await firstValueFrom(
        this.incidentsApi.resolveDriver(driverId, {
          verdict,
          bwpPoints: this.rvBwpPoints[driverId],
        })
      );
      delete this.rvVerdicts[driverId];
      delete this.rvBwpPoints[driverId];
      const windowId = this.windowDetail()?.id;
      if (windowId) await this.selectWindow(windowId, true);
    } catch {
      this.rvError[driverId] = 'Failed to save verdict.';
    } finally {
      this.rvSubmitting[driverId] = false;
    }
  }

  // ── Apply / Discard BWP ────────────────────────────────────────────

  async applyDriverBwp(driverId: string): Promise<void> {
    await firstValueFrom(this.incidentsApi.applyDriverBwp(driverId));
    const windowId = this.windowDetail()?.id;
    if (windowId) await this.selectWindow(windowId, true);
  }

  async discardDriverBwp(driverId: string): Promise<void> {
    if (!confirm('Discard BWP points for this driver?')) return;
    await firstValueFrom(this.incidentsApi.discardDriverBwp(driverId));
    const windowId = this.windowDetail()?.id;
    if (windowId) await this.selectWindow(windowId, true);
  }

  // ── Detail modal ───────────────────────────────────────────────────

  openDetailModal(incident: Incident): void {
    this.detailIncident.set(incident);
    this.showDetailModal.set(true);
  }

  // ── Helpers ───────────────────────────────────────────────────────

  driverNames(incident: Incident): string {
    return incident.drivers.map((d) => d.driverName).join(' vs ');
  }

  driverStatusBadge(driver: IncidentDriver): { variant: BadgeVariant; label: string } {
    if (!driver.resolution) return { variant: 'pending', label: 'Open' };
    if (driver.resolution.verdict === 'NFA') return { variant: 'resolved', label: 'NFA' };
    if (driver.resolution.bwpApplied) return { variant: 'applied', label: 'BWP Applied' };
    if (driver.resolution.bwpPoints) return { variant: 'bwp-pending', label: 'BWP Pending' };
    return { variant: 'resolved', label: 'Resolved' };
  }
}
