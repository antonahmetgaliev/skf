import { Component, computed, effect, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

interface BwpPoint {
  id: string;
  points: number;
  issuedOn: string;
  expiresOn: string;
}

interface Driver {
  id: string;
  name: string;
  points: BwpPoint[];
}

type SortMode = 'bwp-desc' | 'bwp-asc' | 'name-asc' | 'name-desc';

interface PenaltyRule {
  id: string;
  threshold: number;
  label: string;
}

@Component({
  selector: 'app-bwp-license',
  imports: [FormsModule],
  templateUrl: './bwp-license.component.html',
  styleUrl: './bwp-license.component.scss'
})
export class BwpLicenseComponent {
  private readonly storageKey = 'skf-bwp-drivers-v1';
  private readonly settingsKey = 'skf-bwp-settings-v1';
  private readonly defaultPenaltyRules: PenaltyRule[] = [
    {
      id: 'rule-6',
      threshold: 6,
      label: 'Disqualification from the next qualifying session'
    },
    {
      id: 'rule-9',
      threshold: 9,
      label: 'Stop & Go penalty in the next race'
    },
    {
      id: 'rule-12',
      threshold: 12,
      label: 'Skip the next race'
    }
  ];
  private readonly settings = this.loadSettings();

  readonly drivers = signal<Driver[]>(this.loadDrivers());
  readonly sortedDrivers = computed(() =>
    [...this.drivers()].sort((a, b) => a.name.localeCompare(b.name))
  );
  readonly penaltyRules = signal<PenaltyRule[]>(this.settings.penaltyRules);
  readonly sortedPenaltyRules = computed(() =>
    [...this.penaltyRules()]
      .filter((rule) => Number.isFinite(rule.threshold) && rule.threshold > 0)
      .sort((a, b) => a.threshold - b.threshold)
  );
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
      if (mode === 'name-asc') {
        return a.name.localeCompare(b.name);
      }
      if (mode === 'name-desc') {
        return b.name.localeCompare(a.name);
      }
      if (mode === 'bwp-asc') {
        const diff = this.getTotalPoints(a) - this.getTotalPoints(b);
        if (diff !== 0) {
          return diff;
        }
        return a.name.localeCompare(b.name);
      }
      const diff = this.getTotalPoints(b) - this.getTotalPoints(a);
      if (diff !== 0) {
        return diff;
      }
      return a.name.localeCompare(b.name);
    });
    return sorted;
  });

  newDriverName = '';
  selectedDriverId = '';
  pointValue = 3;
  pointDate = this.formatInputDate(new Date());

  driverError = '';
  pointError = '';
  nameFilter = signal('');
  sortMode = signal<SortMode>(this.settings.sortMode);
  collapsedDrivers = signal<Set<string>>(new Set());
  hiddenExpiredDrivers = signal<Set<string>>(new Set());
  rulesModalOpen = signal(false);

  constructor() {
    effect(() => {
      this.saveDrivers(this.drivers());
    });

    effect(() => {
      this.saveSettings({
        penaltyRules: this.penaltyRules(),
        sortMode: this.sortMode()
      });
    });

    effect((onCleanup) => {
      if (typeof document === 'undefined') {
        return;
      }
      document.body.style.overflow = this.rulesModalOpen() ? 'hidden' : '';
      onCleanup(() => {
        document.body.style.overflow = '';
      });
    });

    this.collapsedDrivers.set(new Set(this.drivers().map((driver) => driver.id)));

    effect(() => {
      const current = this.selectedDriverId;
      const drivers = this.sortedDrivers();
      if (drivers.length === 0) {
        this.selectedDriverId = '';
        return;
      }
      if (!current || !drivers.some((driver) => driver.id === current)) {
        this.selectedDriverId = drivers[0].id;
      }
    });
  }

  addDriver(): void {
    const name = this.newDriverName.trim();
    if (!name) {
      this.driverError = 'Enter a driver name to continue.';
      return;
    }
    const exists = this.drivers().some(
      (driver) => driver.name.toLowerCase() === name.toLowerCase()
    );
    if (exists) {
      this.driverError = 'Driver name already exists.';
      return;
    }

    const nextDriver: Driver = {
      id: this.createId(),
      name,
      points: []
    };

    this.drivers.update((drivers) => [...drivers, nextDriver]);
    this.collapsedDrivers.update((current) => {
      const next = new Set(current);
      next.add(nextDriver.id);
      return next;
    });
    this.newDriverName = '';
    this.driverError = '';
    this.selectedDriverId = nextDriver.id;
  }

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
    const newPoint: BwpPoint = {
      id: this.createId(),
      points,
      issuedOn: this.formatInputDate(issuedDate),
      expiresOn: this.formatInputDate(expiresDate)
    };

    this.drivers.update((drivers) =>
      drivers.map((driver) =>
        driver.id === driverId
          ? { ...driver, points: [...driver.points, newPoint] }
          : driver
      )
    );
    this.pointError = '';
  }

  addPenaltyRule(): void {
    const rules = this.penaltyRules();
    const maxThreshold = rules.reduce((max, rule) => Math.max(max, rule.threshold), 0);
    const nextThreshold = maxThreshold > 0 ? maxThreshold + 3 : 3;
    const nextRule: PenaltyRule = {
      id: this.createId(),
      threshold: nextThreshold,
      label: 'New penalty'
    };
    this.penaltyRules.update((items) => [...items, nextRule]);
  }

  updatePenaltyRule(ruleId: string, patch: Partial<PenaltyRule>): void {
    this.penaltyRules.update((rules) =>
      rules.map((rule) => {
        if (rule.id !== ruleId) {
          return rule;
        }
        const nextRule: PenaltyRule = { ...rule };
        if (patch.threshold !== undefined) {
          const threshold = Number(patch.threshold);
          if (Number.isFinite(threshold) && threshold > 0) {
            nextRule.threshold = Math.floor(threshold);
          }
        }
        if (patch.label !== undefined) {
          nextRule.label = String(patch.label);
        }
        return nextRule;
      })
    );
  }

  deletePenaltyRule(ruleId: string): void {
    this.penaltyRules.update((rules) => rules.filter((rule) => rule.id !== ruleId));
  }

  toggleExpiredVisibility(driverId: string): void {
    this.hiddenExpiredDrivers.update((current) => {
      const next = new Set(current);
      if (next.has(driverId)) {
        next.delete(driverId);
      } else {
        next.add(driverId);
      }
      return next;
    });
  }

  isExpiredHidden(driverId: string): boolean {
    return this.hiddenExpiredDrivers().has(driverId);
  }

  toggleDriverCollapse(driverId: string): void {
    this.collapsedDrivers.update((current) => {
      const next = new Set(current);
      if (next.has(driverId)) {
        next.delete(driverId);
      } else {
        next.add(driverId);
      }
      return next;
    });
  }

  isDriverCollapsed(driverId: string): boolean {
    return this.collapsedDrivers().has(driverId);
  }

  deleteDriver(driverId: string): void {
    const driver = this.drivers().find((item) => item.id === driverId);
    if (!driver) {
      return;
    }
    if (!window.confirm(`Delete driver ${driver.name}?`)) {
      return;
    }
    this.drivers.update((drivers) => drivers.filter((item) => item.id !== driverId));
    this.collapsedDrivers.update((current) => {
      if (!current.has(driverId)) {
        return current;
      }
      const next = new Set(current);
      next.delete(driverId);
      return next;
    });
    this.hiddenExpiredDrivers.update((current) => {
      if (!current.has(driverId)) {
        return current;
      }
      const next = new Set(current);
      next.delete(driverId);
      return next;
    });
  }

  deletePoint(driverId: string, pointId: string): void {
    const driver = this.drivers().find((item) => item.id === driverId);
    if (!driver) {
      return;
    }
    if (!window.confirm('Delete this point?')) {
      return;
    }
    this.drivers.update((drivers) =>
      drivers.map((item) =>
        item.id === driverId
          ? { ...item, points: item.points.filter((point) => point.id !== pointId) }
          : item
      )
    );
  }

  getActivePoints(driver: Driver): BwpPoint[] {
    return driver.points.filter((point) => !this.isExpired(point));
  }

  getTotalPoints(driver: Driver): number {
    return this.getActivePoints(driver).reduce((sum, point) => sum + point.points, 0);
  }

  getPenalty(driver: Driver): PenaltyRule | null {
    const total = this.getTotalPoints(driver);
    if (total <= 0) {
      return null;
    }
    let match: PenaltyRule | null = null;
    for (const rule of this.sortedPenaltyRules()) {
      if (total >= rule.threshold) {
        match = rule;
      } else {
        break;
      }
    }
    if (!match) {
      return null;
    }
    const label = match.label.trim() || 'Penalty';
    return { ...match, label };
  }

  sortedPoints(driver: Driver): BwpPoint[] {
    return [...driver.points].sort((a, b) => a.issuedOn.localeCompare(b.issuedOn));
  }

  getVisiblePoints(driver: Driver): BwpPoint[] {
    const points = this.sortedPoints(driver);
    if (!this.isExpiredHidden(driver.id)) {
      return points;
    }
    return points.filter((point) => !this.isExpired(point));
  }

  isExpired(point: BwpPoint): boolean {
    const expires = this.parseDate(point.expiresOn);
    if (!expires) {
      return false;
    }
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return expires.getTime() < today.getTime();
  }

  formatDate(value: string): string {
    const date = this.parseDate(value);
    if (!date) {
      return value;
    }
    const day = `${date.getDate()}`.padStart(2, '0');
    const month = `${date.getMonth() + 1}`.padStart(2, '0');
    return `${day}.${month}.${date.getFullYear()}`;
  }

  private parseDate(value: string): Date | null {
    if (!value) {
      return null;
    }
    const [year, month, day] = value.split('-').map((part) => Number(part));
    if (!year || !month || !day) {
      return null;
    }
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
    const daysInMonth = new Date(result.getFullYear(), result.getMonth() + 1, 0).getDate();
    result.setDate(Math.min(day, daysInMonth));
    return result;
  }

  private createId(): string {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
      return crypto.randomUUID();
    }
    return `id-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
  }

  private loadDrivers(): Driver[] {
    if (typeof window === 'undefined') {
      return [];
    }
    try {
      const raw = localStorage.getItem(this.storageKey);
      if (!raw) {
        return [];
      }
      const parsed = JSON.parse(raw) as Driver[];
      if (!Array.isArray(parsed)) {
        return [];
      }
      return parsed
        .filter((driver) => driver && typeof driver.name === 'string')
        .map((driver) => ({
          id: driver.id ?? this.createId(),
          name: driver.name,
          points: Array.isArray(driver.points)
            ? driver.points
                .map((point) => ({
                  id: point?.id ?? this.createId(),
                  points: Number(point?.points ?? 0),
                  issuedOn: String(point?.issuedOn ?? ''),
                  expiresOn: String(point?.expiresOn ?? '')
                }))
                .filter(
                  (point) =>
                    Number.isFinite(point.points) &&
                    point.points > 0 &&
                    Boolean(point.issuedOn) &&
                    Boolean(point.expiresOn)
                )
            : []
        }));
    } catch {
      return [];
    }
  }

  private loadSettings(): { penaltyRules: PenaltyRule[]; sortMode: SortMode } {
    const defaults = {
      penaltyRules: this.defaultPenaltyRules.map((rule) => ({ ...rule })),
      sortMode: 'bwp-desc' as SortMode
    };
    if (typeof window === 'undefined') {
      return defaults;
    }
    try {
      const raw = localStorage.getItem(this.settingsKey);
      if (!raw) {
        return defaults;
      }
      const parsed = JSON.parse(raw) as Partial<{
        penaltyRules: PenaltyRule[];
        sortMode: SortMode;
      }>;
      const penaltyRules = Array.isArray(parsed.penaltyRules)
        ? parsed.penaltyRules
            .map((rule) => ({
              id: rule?.id ?? this.createId(),
              threshold: Number(rule?.threshold ?? 0),
              label: String(rule?.label ?? '')
            }))
            .filter((rule) => Number.isFinite(rule.threshold) && rule.threshold > 0)
        : defaults.penaltyRules;
      const sortMode = this.isSortMode(parsed.sortMode) ? parsed.sortMode : defaults.sortMode;
      return { penaltyRules, sortMode };
    } catch {
      return defaults;
    }
  }

  private saveSettings(settings: { penaltyRules: PenaltyRule[]; sortMode: SortMode }): void {
    if (typeof window === 'undefined') {
      return;
    }
    localStorage.setItem(this.settingsKey, JSON.stringify(settings));
  }

  private saveDrivers(drivers: Driver[]): void {
    if (typeof window === 'undefined') {
      return;
    }
    localStorage.setItem(this.storageKey, JSON.stringify(drivers));
  }

  private isSortMode(value: unknown): value is SortMode {
    return value === 'bwp-desc' || value === 'bwp-asc' || value === 'name-asc' || value === 'name-desc';
  }
}
