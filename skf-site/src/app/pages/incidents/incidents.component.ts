import { DatePipe } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
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
  VerdictRule,
  DescriptionPreset,
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

  readonly verdictRules = signal<VerdictRule[]>([]);
  readonly verdictPresets = computed(() => this.verdictRules().map(r => r.verdict));

  readonly descriptionPresets = signal<DescriptionPreset[]>([]);
  readonly descriptionPresetTexts = computed(() => this.descriptionPresets().map(p => p.text));

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

  // ── Per-incident resolve state (keyed by incidentId) ──────────────
  rvDescriptions: Record<string, string> = {};
  rvIncSubmitting: Record<string, boolean> = {};
  rvIncError: Record<string, string> = {};

  ngOnInit(): void {
    this.loadWindows();
    this.loadVerdictRules();
    this.loadDescriptionPresets();
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

  initResolveFields(incident: Incident): void {
    for (const driver of incident.drivers) {
      if (this.rvVerdicts[driver.id] === undefined) {
        this.rvVerdicts[driver.id] = driver.resolution?.verdict ?? '';
        this.rvBwpPoints[driver.id] = driver.resolution?.bwpPoints ?? null;
      }
    }
    if (this.rvDescriptions[incident.id] === undefined) {
      const existing = incident.drivers.find(d => d.resolution?.description)?.resolution?.description;
      this.rvDescriptions[incident.id] = existing ?? '';
    }
  }

  onVerdictChange(driverId: string, verdict: string): void {
    const rule = this.verdictRules().find(r => r.verdict === verdict);
    if (rule) {
      this.rvBwpPoints[driverId] = rule.defaultBwp;
    }
  }

  async submitResolveIncident(incident: Incident): Promise<void> {
    const drivers = incident.drivers.map(d => ({
      incidentDriverId: d.id,
      verdict: (this.rvVerdicts[d.id] ?? '').trim(),
      bwpPoints: this.rvBwpPoints[d.id],
    }));
    const missing = drivers.filter(d => !d.verdict);
    if (missing.length > 0) {
      this.rvIncError[incident.id] = 'Verdict is required for all drivers.';
      return;
    }
    this.rvIncSubmitting[incident.id] = true;
    this.rvIncError[incident.id] = '';
    try {
      await firstValueFrom(
        this.incidentsApi.bulkResolveIncident(incident.id, {
          description: this.rvDescriptions[incident.id]?.trim() || undefined,
          drivers,
        })
      );
      for (const d of incident.drivers) {
        delete this.rvVerdicts[d.id];
        delete this.rvBwpPoints[d.id];
      }
      delete this.rvDescriptions[incident.id];
      const windowId = this.windowDetail()?.id;
      if (windowId) await this.selectWindow(windowId, true);
    } catch {
      this.rvIncError[incident.id] = 'Failed to save verdicts.';
    } finally {
      this.rvIncSubmitting[incident.id] = false;
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

  // ── Copy decisions for Discord ─────────────────────────────────────

  readonly showDiscordPreview = signal(false);
  discordPreviewText = '';
  copiedDecisions = false;

  openDiscordPreview(window: IncidentWindowOut): void {
    const lines: string[] = [window.raceName];
    for (const inc of window.incidents) {
      for (const drv of inc.drivers) {
        if (!drv.resolution) continue;
        const session = inc.sessionName ?? '';
        const time = inc.time ?? '';
        const desc = drv.resolution.description ?? '';
        const verdict = drv.resolution.verdict;
        const bwp = drv.resolution.bwpPoints
          ? `${drv.resolution.bwpPoints} BWP`
          : '-';
        lines.push(`${session} | ${time} | ${drv.driverName} | ${desc} | ${verdict} | ${bwp}`);
      }
    }
    this.discordPreviewText = lines.join('\n\n');
    this.copiedDecisions = false;
    this.showDiscordPreview.set(true);
  }

  async copyDiscordText(): Promise<void> {
    await navigator.clipboard.writeText(this.discordPreviewText);
    this.copiedDecisions = true;
    setTimeout(() => (this.copiedDecisions = false), 2000);
  }

  // ── Verdict rules CRUD ─────────────────────────────────────────────

  newRuleVerdict = '';
  newRuleDefaultBwp = 0;
  editingRuleId: string | null = null;
  editRuleVerdict = '';
  editRuleDefaultBwp = 0;

  async loadVerdictRules(): Promise<void> {
    try {
      const rules = await firstValueFrom(this.incidentsApi.getVerdictRules());
      this.verdictRules.set(rules);
    } catch { /* silent — rules are optional for page load */ }
  }

  async addVerdictRule(): Promise<void> {
    if (!this.newRuleVerdict.trim()) return;
    await firstValueFrom(
      this.incidentsApi.createVerdictRule({
        verdict: this.newRuleVerdict.trim(),
        defaultBwp: this.newRuleDefaultBwp,
      })
    );
    this.newRuleVerdict = '';
    this.newRuleDefaultBwp = 0;
    await this.loadVerdictRules();
  }

  startEditRule(rule: VerdictRule): void {
    this.editingRuleId = rule.id;
    this.editRuleVerdict = rule.verdict;
    this.editRuleDefaultBwp = rule.defaultBwp;
  }

  cancelEditRule(): void {
    this.editingRuleId = null;
  }

  async saveEditRule(): Promise<void> {
    if (!this.editingRuleId) return;
    await firstValueFrom(
      this.incidentsApi.updateVerdictRule(this.editingRuleId, {
        verdict: this.editRuleVerdict.trim(),
        defaultBwp: this.editRuleDefaultBwp,
      })
    );
    this.editingRuleId = null;
    await this.loadVerdictRules();
  }

  async deleteVerdictRule(id: string): Promise<void> {
    if (!confirm('Delete this verdict rule?')) return;
    await firstValueFrom(this.incidentsApi.deleteVerdictRule(id));
    await this.loadVerdictRules();
  }

  // ── Description presets CRUD ───────────────────────────────────────

  newPresetText = '';
  editingPresetId: string | null = null;
  editPresetText = '';

  async loadDescriptionPresets(): Promise<void> {
    try {
      const presets = await firstValueFrom(this.incidentsApi.getDescriptionPresets());
      this.descriptionPresets.set(presets);
    } catch { /* silent */ }
  }

  async addDescriptionPreset(): Promise<void> {
    if (!this.newPresetText.trim()) return;
    await firstValueFrom(
      this.incidentsApi.createDescriptionPreset({ text: this.newPresetText.trim() })
    );
    this.newPresetText = '';
    await this.loadDescriptionPresets();
  }

  startEditPreset(preset: DescriptionPreset): void {
    this.editingPresetId = preset.id;
    this.editPresetText = preset.text;
  }

  cancelEditPreset(): void {
    this.editingPresetId = null;
  }

  async saveEditPreset(): Promise<void> {
    if (!this.editingPresetId) return;
    await firstValueFrom(
      this.incidentsApi.updateDescriptionPreset(this.editingPresetId, {
        text: this.editPresetText.trim(),
      })
    );
    this.editingPresetId = null;
    await this.loadDescriptionPresets();
  }

  async deleteDescriptionPreset(id: string): Promise<void> {
    if (!confirm('Delete this description preset?')) return;
    await firstValueFrom(this.incidentsApi.deleteDescriptionPreset(id));
    await this.loadDescriptionPresets();
  }
}
