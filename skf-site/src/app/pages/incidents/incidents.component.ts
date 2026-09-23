import { DatePipe } from '@angular/common';
import { Component, computed, effect, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { InputDirective } from '../../directives/input.directive';
import { SelectDirective } from '../../directives/select.directive';
import { TextareaDirective } from '../../directives/textarea.directive';
import { BadgeComponent, BadgeVariant } from '../../components/badge/badge.component';
import { CardComponent } from '../../components/card/card.component';
import { FormFieldComponent } from '../../components/form-field/form-field.component';
import { EmptyComponent } from '../../components/empty/empty.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { ModalComponent } from '../../components/modal/modal.component';
import { TabsComponent } from '../../components/tabs/tabs.component';
import { IncidentCardComponent } from './incident-card/incident-card.component';
import { IncidentWindowGroupsComponent } from './incident-window-groups/incident-window-groups.component';
import { closesIn, groupKeyFor, groupWindows } from './incident-window-groups/window-groups';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../../services/auth.service';
import { BwpApiService, Driver } from '../../services/bwp-api.service';
import { ConfirmDialogService } from '../../services/confirm-dialog.service';
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
  BulkResolveIncident,
  BwpAuditEntry,
  BwpBackfillResult,
} from '../../services/incidents-api.service';

/** A penalty about to be written to a licence by publishing. */
export interface PendingPenalty {
  driverName: string;
  session: string;
  verdict: string;
  bwpPoints: number;
  linked: boolean;
  incidentDriverId: string;
}

@Component({
  selector: 'app-incidents',
  imports: [FormsModule, DatePipe, TranslocoPipe, InputDirective, SelectDirective, TextareaDirective, BadgeComponent, CardComponent, EmptyComponent, FormFieldComponent, PageIntroComponent, PageLayoutComponent, SpinnerComponent, BtnComponent, ModalComponent, TabsComponent, IncidentCardComponent, IncidentWindowGroupsComponent],
  templateUrl: './incidents.component.html',
  styleUrl: './incidents.component.scss',
})
export class IncidentsComponent implements OnInit {
  readonly auth = inject(AuthService);
  private readonly incidentsApi = inject(IncidentsApiService);
  private readonly simgridApi = inject(SimgridApiService);
  private readonly bwpApi = inject(BwpApiService);
  private readonly confirmSvc = inject(ConfirmDialogService);
  private readonly transloco = inject(TranslocoService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly verdictRules = signal<VerdictRule[]>([]);
  readonly verdictPresets = computed(() => this.verdictRules().map(r => r.verdict));

  /** The verdict pre-selected for every unresolved driver. */
  readonly defaultRule = computed(
    () => this.verdictRules().find(r => r.isDefault) ?? null
  );

  /** Verdict chips, default pinned first so muscle memory has a stable target. */
  readonly orderedRules = computed(() =>
    [...this.verdictRules()].sort(
      (a, b) => Number(b.isDefault) - Number(a.isDefault) || a.sortOrder - b.sortOrder
    )
  );

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

  // ── BWP audit ─────────────────────────────────────────────────────
  readonly bwpAuditEntries = signal<BwpAuditEntry[] | null>(null);
  readonly backfillRunning = signal(false);
  readonly backfillResult = signal<BwpBackfillResult | null>(null);
  readonly hasMatchableAuditEntries = computed(() =>
    (this.bwpAuditEntries() ?? []).some(e => e.matchedDriverId !== null)
  );

  // ── Window groups (championship → rounds) ─────────────────────────
  readonly windowGroups = computed(() => groupWindows(this.windows()));
  /** Expanded championships; `?championship=<id>` opens one from a link. */
  readonly expandedGroups = signal<ReadonlySet<string>>(new Set());

  // ── Grouped incidents (Heat sessions first, then Feature) ──────────────────
  // Within each session: auto incidents sorted by time, then filed sorted by lap → corner.
  readonly groupedIncidents = computed(() => {
    const incidents = this.windowDetail()?.incidents ?? [];

    const groups = new Map<string, Incident[]>();
    for (const inc of incidents) {
      const key = inc.sessionName ?? '';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(inc);
    }

    const sortByTime = (a: Incident, b: Incident) => {
      if (!a.time && !b.time) return 0;
      if (!a.time) return 1;
      if (!b.time) return -1;
      return a.time.localeCompare(b.time);
    };

    const sortByLapCorner = (a: Incident, b: Incident) => {
      const lapA = parseInt(a.lap ?? '', 10);
      const lapB = parseInt(b.lap ?? '', 10);
      if (!isNaN(lapA) && !isNaN(lapB) && lapA !== lapB) return lapA - lapB;
      return (a.corner ?? '').localeCompare(b.corner ?? '');
    };

    const sessionOrder = (name: string): number => {
      const upper = name.toUpperCase();
      const heatMatch = upper.match(/^HEAT\s*(\d+)$/);
      if (heatMatch) return parseInt(heatMatch[1], 10);
      if (upper.startsWith('FEATURE')) return 1000;
      return 2000;
    };

    return [...groups.entries()]
      .sort(([a], [b]) => sessionOrder(a) - sessionOrder(b))
      .map(([session, items]) => ({
        session,
        autoItems: items.filter(i => i.source !== 'filed').sort(sortByTime),
        filedItems: items.filter(i => i.source === 'filed').sort(sortByLapCorner),
      }));
  });

  readonly resolvingRemaining = signal(false);

  // ── Publish preview ───────────────────────────────────────────────
  readonly showPublishPreview = signal(false);
  readonly publishing = signal(false);
  readonly publishPenalties = signal<PendingPenalty[]>([]);
  readonly publishBwpTotal = signal(0);
  readonly publishVerdictCount = signal(0);
  readonly publishNoPenaltyCount = signal(0);
  readonly hasUnlinkedPenalty = computed(() =>
    this.publishPenalties().some(p => !p.linked)
  );

  // ── Modal visibility ──────────────────────────────────────────────
  readonly showNewWindowModal = signal(false);
  readonly showNewIncidentModal = signal(false);

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
  niLap = '';
  niCorner = '';
  niDescription = '';
  niSubmitting = false;
  niError = '';

  // ── Per-incident request state (drafts live inside the card) ──────
  rvIncSubmitting: Record<string, boolean> = {};
  rvIncError: Record<string, string> = {};

  private judgeDataLoaded = false;
  private adminDataLoaded = false;

  constructor() {
    effect(() => {
      const canJudge = this.auth.isJudge();
      const canAdmin = this.auth.isAdmin();

      if (canJudge && !this.judgeDataLoaded) {
        this.judgeDataLoaded = true;
        // Presets are an authoring aid; only a judge ever types a decision.
        void this.loadDescriptionPresets();
      }

      if (canAdmin && !this.adminDataLoaded) {
        this.adminDataLoaded = true;
        firstValueFrom(this.bwpApi.getDrivers()).then((ds) =>
          this.bwpDrivers.set(ds)
        );
        firstValueFrom(this.simgridApi.getChampionships()).then((cs) =>
          this.championships.set(cs)
        );
      }
    });
  }

  ngOnInit(): void {
    const params = this.route.snapshot.queryParamMap;
    const championship = Number(params.get('championship'));
    const windowId = params.get('window');
    void this.loadWindows().then(() => {
      const initial = new Set<string>();
      if (Number.isFinite(championship) && championship > 0) {
        initial.add(groupKeyFor(championship));
      }
      if (!windowId && initial.size === 0) {
        // Nothing linked: show where protests can be filed right now.
        this.windowGroups().filter(g => g.openCount > 0).forEach(g => initial.add(g.key));
      }
      this.expandedGroups.set(initial);
      if (windowId) void this.selectWindow(windowId);
    });
    // Every viewer needs the default verdict to tell a penalty from "no action"
    // on an incident tile, so the rules are not judge-only data.
    void this.loadVerdictRules();
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
      this.expandGroup(groupKeyFor(detail.championshipId));
      // Keep the open window in the URL so it can be linked to directly.
      if (this.route.snapshot.queryParamMap.get('window') !== id) {
        void this.router.navigate([], {
          queryParams: { window: id },
          queryParamsHandling: 'merge',
          replaceUrl: true,
        });
      }
    } finally {
      this.loadingDetail.set(false);
    }
  }

  /** Expanding a championship puts it in the URL, so the view can be linked. */
  toggleGroup(key: string): void {
    const next = new Set(this.expandedGroups());
    const group = this.windowGroups().find(g => g.key === key);
    const opening = !next.has(key);
    if (opening) next.add(key);
    else next.delete(key);
    this.expandedGroups.set(next);

    const current = this.route.snapshot.queryParamMap.get('championship');
    const id = group?.championshipId ?? null;
    let championship: number | null | undefined;
    if (opening && id !== null) championship = id;
    else if (!opening && current !== null && Number(current) === id) championship = null;
    if (championship !== undefined) {
      void this.router.navigate([], {
        queryParams: { championship },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      });
    }
  }

  private expandGroup(key: string): void {
    if (this.expandedGroups().has(key)) return;
    this.expandedGroups.set(new Set([...this.expandedGroups(), key]));
  }

  readonly closesIn = closesIn;

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
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('incidents.deleteWindowConfirm'),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;
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
    this.niLap = '';
    this.niCorner = '';
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
          lap: this.niLap.trim() || undefined,
          corner: this.niCorner.trim() || undefined,
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

  async submitResolveIncident(incident: Incident, payload: BulkResolveIncident): Promise<void> {
    this.rvIncSubmitting[incident.id] = true;
    this.rvIncError[incident.id] = '';
    try {
      await firstValueFrom(this.incidentsApi.bulkResolveIncident(incident.id, payload));
      const windowId = this.windowDetail()?.id;
      if (windowId) await this.selectWindow(windowId, true);
    } catch {
      this.rvIncError[incident.id] = this.transloco.translate('incidents.saveFailed');
    } finally {
      this.rvIncSubmitting[incident.id] = false;
    }
  }


  // ── Publish / Duplicate / Add-Remove Driver ────────────────────────

  hasUnpublished(w: IncidentWindowOut): boolean {
    return w.incidents.some(inc => !inc.isPublished);
  }

  unresolvedCount(w: IncidentWindowOut): number {
    return w.incidents.filter(inc => inc.status !== 'resolved').length;
  }

  resolvedCount(w: IncidentWindowOut): number {
    return w.incidents.length - this.unresolvedCount(w);
  }

  /** Every penalty that publishing would irreversibly write to a licence. */
  pendingPenalties(w: IncidentWindowOut): PendingPenalty[] {
    const rows: PendingPenalty[] = [];
    for (const inc of w.incidents) {
      for (const drv of inc.drivers) {
        const res = drv.resolution;
        if (!res || !res.bwpPoints || res.bwpApplied) continue;
        rows.push({
          driverName: drv.driverName,
          session: inc.sessionName ?? '',
          verdict: res.verdict,
          bwpPoints: res.bwpPoints,
          linked: drv.driverId !== null,
          incidentDriverId: drv.id,
        });
      }
    }
    return rows;
  }

  /** Verdicts going public that carry no penalty — named, not listed. */
  pendingWithoutPenalty(w: IncidentWindowOut): number {
    let count = 0;
    for (const inc of w.incidents) {
      for (const drv of inc.drivers) {
        const res = drv.resolution;
        if (res && !res.bwpPoints) count++;
      }
    }
    return count;
  }

  totalPendingBwp(w: IncidentWindowOut): number {
    return this.pendingPenalties(w)
      .filter(p => p.linked)
      .reduce((sum, p) => sum + p.bwpPoints, 0);
  }

  openPublishPreview(w: IncidentWindowOut): void {
    this.publishPenalties.set(this.pendingPenalties(w));
    this.publishBwpTotal.set(this.totalPendingBwp(w));
    this.publishVerdictCount.set(
      w.incidents.reduce((n, i) => n + i.drivers.filter(d => d.resolution).length, 0)
    );
    this.publishNoPenaltyCount.set(this.pendingWithoutPenalty(w));
    this.showPublishPreview.set(true);
  }

  async confirmPublish(): Promise<void> {
    const windowId = this.windowDetail()?.id;
    if (!windowId) return;
    this.publishing.set(true);
    try {
      await firstValueFrom(this.incidentsApi.publishAllIncidents(windowId));
      this.showPublishPreview.set(false);
      await this.selectWindow(windowId, true);
    } finally {
      this.publishing.set(false);
    }
  }

  /** Attach an unmatched name to a real driver so the penalty can be issued. */
  async linkPenaltyDriver(row: PendingPenalty, driverName: string): Promise<void> {
    const driver = this.bwpDrivers().find(d => d.name === driverName);
    if (!driver) return;
    await firstValueFrom(
      this.incidentsApi.linkIncidentDriver(row.incidentDriverId, driver.id)
    );
    const windowId = this.windowDetail()?.id;
    if (windowId) {
      await this.selectWindow(windowId, true);
      const w = this.windowDetail();
      if (w) this.openPublishPreview(w);
    }
  }

  /** Resolve every driver still lacking a verdict, using the default rule.
   *
   * One request for the whole round: the server walks the window, so a steward
   * closing out a race weekend is not firing dozens of calls.
   */
  async resolveRemaining(w: IncidentWindowOut): Promise<void> {
    this.resolvingRemaining.set(true);
    try {
      await firstValueFrom(this.incidentsApi.resolveRemaining(w.id));
      await this.selectWindow(w.id, true);
    } finally {
      this.resolvingRemaining.set(false);
    }
  }


  async duplicateIncident(incidentId: string): Promise<void> {
    await firstValueFrom(this.incidentsApi.duplicateIncident(incidentId));
    const windowId = this.windowDetail()?.id;
    if (windowId) await this.selectWindow(windowId, true);
  }

  async addIncidentDriver(incidentId: string, name: string): Promise<void> {
    if (!name.trim()) return;
    await firstValueFrom(this.incidentsApi.addDriverToIncident(incidentId, name.trim()));
    const windowId = this.windowDetail()?.id;
    if (windowId) await this.selectWindow(windowId, true);
  }


  async removeIncidentDriver(incidentDriverId: string): Promise<void> {
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.title'),
      message: this.transloco.translate('incidents.removeDriverConfirm'),
      confirmLabel: this.transloco.translate('common.confirm.confirm'),
      danger: true,
    });
    if (!ok) return;
    await firstValueFrom(this.incidentsApi.removeDriverFromIncident(incidentDriverId));
    const windowId = this.windowDetail()?.id;
    if (windowId) await this.selectWindow(windowId, true);
  }

  // ── Helpers ───────────────────────────────────────────────────────

  // ── Copy decisions for Discord ─────────────────────────────────────

  readonly showDiscordPreview = signal(false);
  discordPreviewText = '';
  copiedDecisions = false;

  openDiscordPreview(window: IncidentWindowOut): void {
    const lines: string[] = [window.raceName];
    for (const inc of window.incidents) {
      for (const drv of inc.drivers) {
        if (!drv.resolution) continue;
        const parts: string[] = [];
        if (inc.sessionName) parts.push(inc.sessionName);
        if (inc.time) parts.push(inc.time);
        if (inc.lap) parts.push(`Lap ${inc.lap}`);
        if (inc.corner) parts.push(inc.corner);
        parts.push(drv.driverName);
        const desc = drv.resolution.description ?? '';
        if (desc) parts.push(desc);
        parts.push(drv.resolution.verdict);
        const bwp = drv.resolution.bwpPoints
          ? `${drv.resolution.bwpPoints} BWP`
          : '-';
        parts.push(bwp);
        lines.push(parts.join(' | '));
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

  // Config is read-only until Edit is pressed: a stray click must not be able
  // to rewrite the rules the whole league is judged against. Inside the mode
  // every change saves immediately, so Done only locks it back.
  readonly rulesEditMode = signal(false);
  readonly presetsEditMode = signal(false);

  readonly showSettingsModal = signal(false);
  readonly settingsTab = signal('verdicts');
  // Judges share this modal with admins, but the BWP audit is admin-only work.
  // Offering them the tab would just open an empty panel.
  readonly settingsTabs = computed(() => [
    { key: 'verdicts', label: 'incidents.tabVerdicts' },
    { key: 'descriptions', label: 'incidents.tabDescriptions' },
    ...(this.auth.isAdmin() ? [{ key: 'unlinked', label: 'incidents.unlinkedPenalties' }] : []),
  ]);

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

  async saveRuleVerdict(rule: VerdictRule, verdict: string): Promise<void> {
    const trimmed = verdict.trim();
    if (!trimmed || trimmed === rule.verdict) return;
    await firstValueFrom(this.incidentsApi.updateVerdictRule(rule.id, { verdict: trimmed }));
    await this.loadVerdictRules();
  }

  async saveRuleBwp(rule: VerdictRule, value: string): Promise<void> {
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed < 0 || parsed === rule.defaultBwp) return;
    await firstValueFrom(this.incidentsApi.updateVerdictRule(rule.id, { defaultBwp: parsed }));
    await this.loadVerdictRules();
  }

  async setDefaultRule(rule: VerdictRule): Promise<void> {
    if (rule.isDefault) return;
    await firstValueFrom(this.incidentsApi.updateVerdictRule(rule.id, { isDefault: true }));
    await this.loadVerdictRules();
  }

  /** Move a rule one slot; sort_order has existed all along with no way to set it. */
  async moveRule(index: number, delta: number): Promise<void> {
    const ids = this.verdictRules().map(r => r.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    await firstValueFrom(this.incidentsApi.reorderVerdictRules(ids));
    await this.loadVerdictRules();
  }

  async savePresetText(preset: DescriptionPreset, text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed || trimmed === preset.text) return;
    await firstValueFrom(this.incidentsApi.updateDescriptionPreset(preset.id, { text: trimmed }));
    await this.loadDescriptionPresets();
  }

  async deleteVerdictRule(id: string): Promise<void> {
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('incidents.deleteVerdictRuleConfirm'),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;
    await firstValueFrom(this.incidentsApi.deleteVerdictRule(id));
    await this.loadVerdictRules();
  }

  // ── Description presets CRUD ───────────────────────────────────────

  newPresetText = '';

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

  async deleteDescriptionPreset(id: string): Promise<void> {
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('incidents.deleteDescriptionPresetConfirm'),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;
    await firstValueFrom(this.incidentsApi.deleteDescriptionPreset(id));
    await this.loadDescriptionPresets();
  }

  // ── BWP audit ────────────────────────────────────────────────────────

  async loadBwpAudit(): Promise<void> {
    const entries = await firstValueFrom(this.incidentsApi.getBwpAudit());
    this.bwpAuditEntries.set(entries);
    this.backfillResult.set(null);
  }

  async runBwpBackfill(): Promise<void> {
    this.backfillRunning.set(true);
    try {
      const result = await firstValueFrom(this.incidentsApi.runBwpBackfill());
      this.backfillResult.set(result);
      // Refresh audit list to reflect fixes
      const entries = await firstValueFrom(this.incidentsApi.getBwpAudit());
      this.bwpAuditEntries.set(entries);
    } finally {
      this.backfillRunning.set(false);
    }
  }
}
