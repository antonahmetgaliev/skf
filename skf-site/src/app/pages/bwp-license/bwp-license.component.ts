import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { InputDirective } from '../../directives/input.directive';
import { SelectDirective } from '../../directives/select.directive';
import { CardComponent } from '../../components/card/card.component';
import { EmptyComponent } from '../../components/empty/empty.component';
import { FormFieldComponent } from '../../components/form-field/form-field.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { BtnComponent } from '../../components/btn/btn.component';
import { ModalComponent } from '../../components/modal/modal.component';
import { RouterLink } from '@angular/router';
import {
  BwpApiService,
  BwpPoint,
  Driver,
  PenaltyRule
} from '../../services/bwp-api.service';
import { AuthService } from '../../services/auth.service';
import { ConfirmDialogService } from '../../services/confirm-dialog.service';

type SortMode = 'bwp-desc' | 'bwp-asc' | 'name-asc' | 'name-desc';

@Component({
  selector: 'app-bwp-license',
  imports: [FormsModule, RouterLink, TranslocoPipe, InputDirective, SelectDirective, CardComponent, EmptyComponent, FormFieldComponent, PageIntroComponent, PageLayoutComponent, BtnComponent, ModalComponent],
  templateUrl: './bwp-license.component.html',
  styleUrl: './bwp-license.component.scss'
})
export class BwpLicenseComponent {
  private readonly api = inject(BwpApiService);
  private readonly confirmSvc = inject(ConfirmDialogService);
  private readonly transloco = inject(TranslocoService);
  readonly auth = inject(AuthService);

  readonly drivers = signal<Driver[]>([]);
  readonly sortedDrivers = computed(() =>
    [...this.drivers()].sort((a, b) => a.name.localeCompare(b.name))
  );
  readonly penaltyRules = signal<PenaltyRule[]>([]);
  readonly sortedPenaltyRules = computed(() =>
    [...this.penaltyRules()]
      .filter((rule) => Number.isFinite(rule.threshold) && rule.threshold > 0)
      .sort((a, b) => a.threshold - b.threshold)
  );
  readonly maxThreshold = computed(() => {
    const rules = this.sortedPenaltyRules();
    return rules.length > 0 ? rules[rules.length - 1].threshold : 0;
  });
  readonly penaltySummary = computed(() => {
    const thresholds = this.sortedPenaltyRules().map((rule) => rule.threshold);
    if (thresholds.length === 0) {
      return 'No penalty rules set';
    }
    return `Penalty tiers: ${thresholds.join(' / ')} BWP`;
  });
  readonly displayDrivers = computed(() => {
    const term = this.nameFilter().trim().toLowerCase();
    let list = this.drivers();
    if (term) {
      list = list.filter((driver) => driver.name.toLowerCase().includes(term));
    }
    const sorted = [...list];
    const mode = this.sortMode();
    sorted.sort((a, b) => {
      if (mode === 'name-asc') return a.name.localeCompare(b.name);
      if (mode === 'name-desc') return b.name.localeCompare(a.name);
      if (mode === 'bwp-asc') {
        const diff = this.getTotalPoints(a) - this.getTotalPoints(b);
        return diff !== 0 ? diff : a.name.localeCompare(b.name);
      }
      const diff = this.getTotalPoints(b) - this.getTotalPoints(a);
      return diff !== 0 ? diff : a.name.localeCompare(b.name);
    });
    return sorted;
  });

  newDriverSelection = signal<string>('__none__'); // '__none__' | '__new__' | driverId
  newDriverNameOverride = '';
  selectedDriverId = '';
  pointDriverFilter = signal('');
  readonly filteredSelectDrivers = computed(() => {
    const q = this.pointDriverFilter().trim().toLowerCase();
    return q
      ? this.sortedDrivers().filter((d) => d.name.toLowerCase().includes(q))
      : this.sortedDrivers();
  });
  pointValue = 3;
  pointDate = this.formatInputDate(new Date());

  driverError = '';
  pointError = '';
  nameFilter = signal('');
  sortMode = signal<SortMode>('bwp-desc');
  collapsedDrivers = signal<Set<string>>(new Set());
  hiddenExpiredDrivers = signal<Set<string>>(new Set());
  rulesModalOpen = signal(false);
  loading = signal(true);

  constructor() {
    this.loadData();

    effect((onCleanup) => {
      if (typeof document === 'undefined') return;
      document.body.style.overflow = this.rulesModalOpen() ? 'hidden' : '';
      onCleanup(() => {
        document.body.style.overflow = '';
      });
    });
  }

  // ── Data loading ─────────────────────────────────────────────────

  private loadData(): void {
    this.api.getDrivers().subscribe({
      next: (drivers) => {
        this.drivers.set(drivers);
        this.collapsedDrivers.set(new Set(drivers.map((d) => d.id)));
        if (drivers.length > 0 && !this.selectedDriverId) {
          this.selectedDriverId = [...drivers].sort((a, b) =>
            a.name.localeCompare(b.name)
          )[0].id;
        }
        this.loading.set(false);
      },
      error: () => this.loading.set(false)
    });

    this.api.getPenaltyRules().subscribe({
      next: (rules) => this.penaltyRules.set(rules)
    });
  }

  private refreshDrivers(): void {
    this.api.getDrivers().subscribe({
      next: (drivers) => this.drivers.set(drivers)
    });
  }

  // ── Drivers ──────────────────────────────────────────────────────

  addDriver(): void {
    const selection = this.newDriverSelection();

    if (selection === '__new__') {
      const name = this.newDriverNameOverride.trim();
      if (!name) {
        this.driverError = 'Enter a driver name to continue.';
        return;
      }
      this.driverError = '';
      this.api.createDriver(name).subscribe({
        next: (driver) => {
          this.drivers.update((list) => [...list, driver]);
          this.collapsedDrivers.update((set) => {
            const next = new Set(set);
            next.add(driver.id);
            return next;
          });
          this.newDriverNameOverride = '';
          this.newDriverSelection.set('__none__');
          this.selectedDriverId = driver.id;
        },
        error: (err) => {
          this.driverError = err?.error?.detail ?? 'Failed to add driver.';
        }
      });
    } else if (selection !== '__none__') {
      // Driver already in DB — just set them as selected for the points form
      this.selectedDriverId = selection;
      this.newDriverSelection.set('__none__');
      this.driverError = '';
    } else {
      this.driverError = 'Select a driver or choose \'Add new driver\'.';
    }
  }

  async deleteDriver(driverId: string): Promise<void> {
    const driver = this.drivers().find((d) => d.id === driverId);
    if (!driver) return;
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('bwp.deleteDriverConfirm', { name: driver.name }),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;

    this.api.deleteDriver(driverId).subscribe({
      next: () => {
        this.drivers.update((list) =>
          list.filter((d) => d.id !== driverId)
        );
      }
    });
  }

  renameDriver(driverId: string): void {
    const driver = this.drivers().find((d) => d.id === driverId);
    if (!driver) return;

    const input = window.prompt('Enter new driver name', driver.name);
    if (input === null) return;

    const nextName = input.trim();
    if (!nextName) {
      this.driverError = 'Driver name cannot be empty.';
      return;
    }
    if (nextName === driver.name) return;

    this.driverError = '';
    this.api.updateDriver(driverId, { name: nextName }).subscribe({
      next: (updated) => {
        this.drivers.update((list) =>
          list.map((d) => (d.id === driverId ? updated : d))
        );
      },
      error: (err) => {
        this.driverError = err?.error?.detail ?? 'Failed to rename driver.';
      }
    });
  }

  setSimgridId(driverId: string): void {
    const driver = this.drivers().find((d) => d.id === driverId);
    if (!driver) return;

    const current = driver.simgridDriverId ? String(driver.simgridDriverId) : '';
    const input = window.prompt('Enter SimGrid driver ID (numeric):', current);
    if (input === null) return;

    const trimmed = input.trim();
    const parsed = trimmed === '' ? null : Number(trimmed);
    if (trimmed !== '' && (!Number.isInteger(parsed) || (parsed as number) <= 0)) {
      this.driverError = 'SimGrid ID must be a positive integer.';
      return;
    }
    if (parsed === driver.simgridDriverId) return;

    this.driverError = '';
    this.api.updateDriver(driverId, { name: driver.name, simgridDriverId: parsed }).subscribe({
      next: (updated) => {
        this.drivers.update((list) =>
          list.map((d) => (d.id === driverId ? updated : d))
        );
      },
      error: (err) => {
        this.driverError = err?.error?.detail ?? 'Failed to update SimGrid ID.';
      }
    });
  }

  // ── Points ───────────────────────────────────────────────────────

  addPoint(): void {
    const driverId = this.selectedDriverId;
    const points = Number(this.pointValue);
    if (!driverId) {
      this.pointError = 'Select a driver before adding points.';
      return;
    }
    if (!Number.isFinite(points) || points <= 0) {
      this.pointError = 'Point value must be a positive number.';
      return;
    }

    const issuedDate = this.parseDate(this.pointDate);
    if (!issuedDate) {
      this.pointError = 'Choose a valid issued date.';
      return;
    }

    const expiresDate = this.addMonths(issuedDate, 3);
    this.pointError = '';

    this.api
      .addPoint(driverId, {
        points,
        issuedOn: this.formatInputDate(issuedDate),
        expiresOn: this.formatInputDate(expiresDate)
      })
      .subscribe({
        next: () => this.refreshDrivers(),
        error: () => {
          this.pointError = 'Failed to add point.';
        }
      });
  }

  async deletePoint(driverId: string, pointId: string): Promise<void> {
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('bwp.deletePointConfirm'),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;

    this.api.deletePoint(pointId).subscribe({
      next: () => this.refreshDrivers()
    });
  }

  expirePoint(pointId: string): void {
    this.api.expirePoint(pointId, '').subscribe({
      next: () => this.refreshDrivers()
    });
  }

  // ── Penalty Rules ────────────────────────────────────────────────

  addPenaltyRule(): void {
    const rules = this.penaltyRules();
    const maxThreshold = rules.reduce(
      (max, r) => Math.max(max, r.threshold),
      0
    );
    const next = maxThreshold > 0 ? maxThreshold + 3 : 3;

    this.api.createPenaltyRule({ threshold: next, label: 'New penalty' }).subscribe({
      next: (rule) => this.penaltyRules.update((list) => [...list, rule])
    });
  }

  updatePenaltyRule(ruleId: string, patch: { threshold?: number; label?: string }): void {
    // Optimistic local update
    this.penaltyRules.update((rules) =>
      rules.map((r) => {
        if (r.id !== ruleId) return r;
        const updated = { ...r };
        if (patch.threshold !== undefined) {
          const t = Number(patch.threshold);
          if (Number.isFinite(t) && t > 0) updated.threshold = Math.floor(t);
        }
        if (patch.label !== undefined) updated.label = String(patch.label);
        return updated;
      })
    );

    const apiPatch: { threshold?: number; label?: string } = {};
    if (patch.threshold !== undefined) {
      const t = Number(patch.threshold);
      if (Number.isFinite(t) && t > 0) apiPatch.threshold = Math.floor(t);
    }
    if (patch.label !== undefined) apiPatch.label = patch.label;

    if (Object.keys(apiPatch).length > 0) {
      this.api.updatePenaltyRule(ruleId, apiPatch).subscribe();
    }
  }

  async deletePenaltyRule(ruleId: string): Promise<void> {
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('bwp.deletePenaltyRuleConfirm'),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;
    this.api.deletePenaltyRule(ruleId).subscribe({
      next: () =>
        this.penaltyRules.update((list) =>
          list.filter((r) => r.id !== ruleId)
        )
    });
  }

  expireAllDriverPoints(driverId: string): void {
    if (!window.confirm('Expire all active BWP points for this driver?')) return;
    this.api.expireAllPoints(driverId, '').subscribe({
      next: () => this.refreshDrivers()
    });
  }

  // ── Penalty Clearances ───────────────────────────────────────────

  isClearedPenalty(driver: Driver, ruleId: string): boolean {
    return driver.clearances?.some((c) => c.penaltyRuleId === ruleId) ?? false;
  }

  toggleClearance(driver: Driver, ruleId: string): void {
    const isCleared = this.isClearedPenalty(driver, ruleId);
    if (isCleared) {
      this.api.removeClearance(driver.id, ruleId).subscribe({
        next: () => this.refreshDrivers()
      });
    } else {
      this.api.setClearance(driver.id, ruleId).subscribe({
        next: () => {
          // Check if ALL penalty rules are now cleared
          const allRuleIds = this.penaltyRules().map((r) => r.id);
          const alreadyCleared = driver.clearances.map((c) => c.penaltyRuleId);
          const nowCleared = new Set([...alreadyCleared, ruleId]);
          const allCleared = allRuleIds.every((id) => nowCleared.has(id));

          if (allCleared) {
            this.api.expireAllPoints(driver.id, '').subscribe({
              next: () => this.refreshDrivers()
            });
          } else {
            this.refreshDrivers();
          }
        }
      });
    }
  }

  /** Get the highest un-cleared penalty the driver has reached. */
  getActivePenalty(driver: Driver): PenaltyRule | null {
    const total = this.getTotalPoints(driver);
    if (total <= 0) return null;
    const rules = [...this.sortedPenaltyRules()].reverse();
    for (const rule of rules) {
      if (total >= rule.threshold && !this.isClearedPenalty(driver, rule.id)) {
        return { ...rule, label: rule.label.trim() || 'Penalty' };
      }
    }
    return null;
  }

  /** Progress percentage (0–100) for the bar. */
  getProgressPercent(driver: Driver): number {
    const max = this.maxThreshold();
    if (max <= 0) return 0;
    const total = this.getTotalPoints(driver);
    return Math.min(100, (total / max) * 100);
  }

  /** Threshold position as percentage on the bar. */
  getThresholdPercent(threshold: number): number {
    const max = this.maxThreshold();
    if (max <= 0) return 0;
    return (threshold / max) * 100;
  }

  // ── UI helpers ───────────────────────────────────────────────────

  toggleExpiredVisibility(driverId: string): void {
    this.hiddenExpiredDrivers.update((set) => {
      const next = new Set(set);
      next.has(driverId) ? next.delete(driverId) : next.add(driverId);
      return next;
    });
  }

  isExpiredHidden(driverId: string): boolean {
    return this.hiddenExpiredDrivers().has(driverId);
  }

  toggleDriverCollapse(driverId: string): void {
    this.collapsedDrivers.update((set) => {
      const next = new Set(set);
      next.has(driverId) ? next.delete(driverId) : next.add(driverId);
      return next;
    });
  }

  isDriverCollapsed(driverId: string): boolean {
    return this.collapsedDrivers().has(driverId);
  }

  getActivePoints(driver: Driver): BwpPoint[] {
    return driver.points.filter((p) => !this.isExpired(p));
  }

  getTotalPoints(driver: Driver): number {
    return this.getActivePoints(driver).reduce((sum, p) => sum + p.points, 0);
  }

  getPenalty(driver: Driver): PenaltyRule | null {
    const total = this.getTotalPoints(driver);
    if (total <= 0) return null;
    let match: PenaltyRule | null = null;
    for (const rule of this.sortedPenaltyRules()) {
      if (total >= rule.threshold) match = rule;
      else break;
    }
    return match ? { ...match, label: match.label.trim() || 'Penalty' } : null;
  }

  sortedPoints(driver: Driver): BwpPoint[] {
    return [...driver.points].sort((a, b) => a.issuedOn.localeCompare(b.issuedOn));
  }

  getVisiblePoints(driver: Driver): BwpPoint[] {
    const points = this.sortedPoints(driver);
    if (!this.isExpiredHidden(driver.id)) return points;
    return points.filter((p) => !this.isExpired(p));
  }

  isExpired(point: BwpPoint): boolean {
    const expires = this.parseDate(point.expiresOn);
    if (!expires) return false;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return expires.getTime() < today.getTime();
  }

  formatDate(value: string): string {
    const date = this.parseDate(value);
    if (!date) return value;
    const day = `${date.getDate()}`.padStart(2, '0');
    const month = `${date.getMonth() + 1}`.padStart(2, '0');
    return `${day}.${month}.${date.getFullYear()}`;
  }

  private parseDate(value: string): Date | null {
    if (!value) return null;
    const [year, month, day] = value.split('-').map(Number);
    if (!year || !month || !day) return null;
    return new Date(year, month - 1, day);
  }

  private formatInputDate(date: Date): string {
    const day = `${date.getDate()}`.padStart(2, '0');
    const month = `${date.getMonth() + 1}`.padStart(2, '0');
    return `${date.getFullYear()}-${month}-${day}`;
  }

  private addMonths(date: Date, months: number): Date {
    const result = new Date(date);
    const day = result.getDate();
    result.setDate(1);
    result.setMonth(result.getMonth() + months);
    const daysInMonth = new Date(
      result.getFullYear(),
      result.getMonth() + 1,
      0
    ).getDate();
    result.setDate(Math.min(day, daysInMonth));
    return result;
  }
}
