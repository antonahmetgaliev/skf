import { DatePipe } from '@angular/common';
import { Component, computed, effect, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BadgeComponent } from '../../components/badge/badge.component';
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
  readonly showResolveModal = signal(false);
  readonly showDetailModal = signal(false);
  readonly detailIncident = signal<Incident | null>(null);
  readonly rvIncident = signal<Incident | null>(null);

  // ── New Window form fields ────────────────────────────────────────
  nwChampId: number | null = null;
  nwChampName = '';
  nwRaceId: number | null = null;
  nwRaceName = '';
  nwIntervalHours = 24;
  nwSubmitting = false;
  nwError = '';

  // ── New Incident form fields ───────────────────────────────────────
  niDriver1Name = '';
  niDriver1Id: string | null = null;
  niDriver2Name = '';
  niDriver2Id: string | null = null;
  niLap: number | null = null;
  niTurn = '';
  niDescription = '';
  niSubmitting = false;
  niError = '';

  // ── Resolve form fields ───────────────────────────────────────────
  rvIncidentId: string | null = null;
  rvVerdict = '';
  rvTimePenalty: number | null = null;
  rvBwpPoints: number | null = null;
  rvSubmitting = false;
  rvError = '';

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
    if (!this.nwChampId || !this.nwRaceId) {
      this.nwError = 'Please select a championship and race.';
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
    this.niDriver1Name = '';
    this.niDriver1Id = null;
    this.niDriver2Name = '';
    this.niDriver2Id = null;
    this.niLap = null;
    this.niTurn = '';
    this.niDescription = '';
    this.niError = '';
    this.showNewIncidentModal.set(true);
  }

  onDriver1Change(): void {
    const match = this.bwpDrivers().find(
      (d) => d.name === this.niDriver1Name
    );
    this.niDriver1Id = match?.id ?? null;
  }

  onDriver2Change(): void {
    const match = this.bwpDrivers().find(
      (d) => d.name === this.niDriver2Name
    );
    this.niDriver2Id = match?.id ?? null;
  }

  async submitIncident(): Promise<void> {
    const windowId = this.windowDetail()?.id;
    if (!windowId) return;
    if (!this.niDriver1Name.trim()) {
      this.niError = 'Driver 1 name is required.';
      return;
    }
    if (!this.niDescription.trim()) {
      this.niError = 'Description is required.';
      return;
    }
    this.niSubmitting = true;
    this.niError = '';
    try {
      await firstValueFrom(
        this.incidentsApi.fileIncident(windowId, {
          driver1Name: this.niDriver1Name.trim(),
          driver1DriverId: this.niDriver1Id,
          driver2Name: this.niDriver2Name.trim() || null,
          driver2DriverId: this.niDriver2Id,
          lapNumber: this.niLap,
          turn: this.niTurn.trim() || null,
          description: this.niDescription.trim(),
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

  // ── Resolve Incident ───────────────────────────────────────────────

  openResolveModal(incident: Incident): void {
    this.rvIncident.set(incident);
    this.rvIncidentId = incident.id;
    this.rvVerdict = incident.resolution?.verdict ?? '';
    this.rvTimePenalty = incident.resolution?.timePenaltySeconds ?? null;
    this.rvBwpPoints = incident.resolution?.bwpPoints ?? null;
    this.rvError = '';
    this.showResolveModal.set(true);
  }

  async submitResolve(): Promise<void> {
    if (!this.rvIncidentId) return;
    if (!this.rvVerdict.trim()) {
      this.rvError = 'Verdict is required.';
      return;
    }
    this.rvSubmitting = true;
    this.rvError = '';
    try {
      await firstValueFrom(
        this.incidentsApi.resolveIncident(this.rvIncidentId, {
          verdict: this.rvVerdict.trim(),
          timePenaltySeconds: this.rvTimePenalty,
          bwpPoints: this.rvBwpPoints,
        })
      );
      this.showResolveModal.set(false);
      const windowId = this.windowDetail()?.id;
      if (windowId) await this.selectWindow(windowId, true);
    } catch {
      this.rvError = 'Failed to submit resolution. Please try again.';
    } finally {
      this.rvSubmitting = false;
    }
  }

  // ── Apply / Unapply BWP ────────────────────────────────────────────

  async applyBwp(incidentId: string): Promise<void> {
    await firstValueFrom(this.incidentsApi.applyBwp(incidentId));
    const windowId = this.windowDetail()?.id;
    if (windowId) await this.selectWindow(windowId, true);
  }

  async unapplyBwp(incidentId: string): Promise<void> {
    if (!confirm('Remove the BWP Applied mark from this incident?')) return;
    await firstValueFrom(this.incidentsApi.unapplyBwp(incidentId));
    const windowId = this.windowDetail()?.id;
    if (windowId) await this.selectWindow(windowId, true);
  }

  // ── Detail modal ───────────────────────────────────────────────────

  openDetailModal(incident: Incident): void {
    this.detailIncident.set(incident);
    this.showDetailModal.set(true);
  }

  // ── Helpers ───────────────────────────────────────────────────────

  formatPenalty(seconds: number | null): string {
    if (seconds === null) return '—';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  }
}
