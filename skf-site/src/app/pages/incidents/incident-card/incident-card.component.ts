import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  linkedSignal,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { BadgeComponent, BadgeVariant } from '../../../components/badge/badge.component';
import { BtnComponent } from '../../../components/btn/btn.component';
import { InputDirective } from '../../../directives/input.directive';
import { Driver } from '../../../services/bwp-api.service';
import {
  BulkResolveIncident,
  Incident,
  IncidentDriver,
  VerdictRule,
} from '../../../services/incidents-api.service';
import {
  driverStatusBadge,
  incidentPenalties,
  incidentStatusChip,
  sharedDecisionDescription,
  showsStewardDetail,
  showsVerdicts,
  StatusChip,
} from '../incident-visibility';

interface DriverDraft {
  verdict: string;
  bwpPoints: number | null;
}

@Component({
  selector: 'app-incident-card',
  standalone: true,
  imports: [FormsModule, DatePipe, TranslocoPipe, InputDirective, BadgeComponent, BtnComponent],
  templateUrl: './incident-card.component.html',
  styleUrl: './incident-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class IncidentCardComponent {
  readonly incident = input.required<Incident>();
  readonly index = input.required<number>();
  readonly expanded = input(false);
  readonly verdictRules = input<VerdictRule[]>([]);
  readonly defaultRule = input<VerdictRule | null>(null);
  readonly descriptionPresets = input<string[]>([]);
  readonly knownDrivers = input<Driver[]>([]);
  readonly canJudge = input(false);
  readonly submitting = input(false);
  readonly error = input('');

  readonly toggle = output<void>();
  readonly resolve = output<BulkResolveIncident>();
  readonly addDriver = output<string>();
  readonly removeDriver = output<string>();
  readonly duplicate = output<void>();

  /** Chips with the default pinned first, so muscle memory has a stable target. */
  readonly orderedRules = computed(() =>
    [...this.verdictRules()].sort(
      (a, b) => Number(b.isDefault) - Number(a.isDefault) || a.sortOrder - b.sortOrder,
    ),
  );

  /** Draft verdicts, reseeded whenever the incident is reloaded from the server.
   *
   * Unresolved drivers start on the default verdict, so pressing Save without
   * touching anything resolves the whole incident correctly.
   */
  readonly drafts = linkedSignal<
    { incident: Incident; fallback: VerdictRule | null },
    Record<string, DriverDraft>
  >({
    // Keyed on the default rule as well as the incident: verdict rules load
    // asynchronously, and seeding before they arrive would leave every driver
    // blank with no second chance to pre-select.
    source: () => ({ incident: this.incident(), fallback: this.defaultRule() }),
    computation: ({ incident, fallback }) => {
      const seeded: Record<string, DriverDraft> = {};
      for (const d of incident.drivers) {
        seeded[d.id] = {
          verdict: d.resolution?.verdict ?? fallback?.verdict ?? '',
          bwpPoints: d.resolution?.bwpPoints ?? fallback?.defaultBwp ?? null,
        };
      }
      return seeded;
    },
  });

  readonly description = linkedSignal<Incident, string>({
    source: this.incident,
    computation: (incident) =>
      incident.drivers.find((d) => d.resolution?.description)?.resolution?.description ?? '',
  });

  readonly addDriverShown = signal(false);
  readonly addDriverName = signal('');
  readonly menuOpen = signal(false);

  // ── Verdict selection ─────────────────────────────────────────────

  draftFor(driverId: string): DriverDraft {
    return this.drafts()[driverId] ?? { verdict: '', bwpPoints: null };
  }

  isSelected(driverId: string, rule: VerdictRule): boolean {
    return this.draftFor(driverId).verdict === rule.verdict;
  }

  /** Picking a chip is an explicit choice, so it resets BWP to the rule's price. */
  selectVerdict(driverId: string, rule: VerdictRule): void {
    this.patch(driverId, { verdict: rule.verdict, bwpPoints: rule.defaultBwp });
  }

  setBwp(driverId: string, value: number | null): void {
    this.patch(driverId, { bwpPoints: value });
  }

  setCustomVerdict(driverId: string, verdict: string): void {
    this.patch(driverId, { verdict });
  }

  private patch(driverId: string, change: Partial<DriverDraft>): void {
    this.drafts.update((all) => ({
      ...all,
      [driverId]: { ...this.draftFor(driverId), ...change },
    }));
  }

  /** True when the chosen verdict is off-list, i.e. typed by hand. */
  isCustom(driverId: string): boolean {
    const v = this.draftFor(driverId).verdict;
    return !!v && !this.verdictRules().some((r) => r.verdict === v);
  }

  /** BWP only earns a field when it is actually non-zero. */
  showsBwp(driverId: string): boolean {
    return !!this.draftFor(driverId).bwpPoints;
  }

  // ── Display helpers ───────────────────────────────────────────────

  readonly driverNames = computed(() =>
    this.incident().drivers.map((d) => d.driverName).join(', '),
  );

  /** Penalties only, and nothing at all while the round is withheld. */
  readonly penalties = computed(() =>
    incidentPenalties(this.incident(), this.defaultRule()?.verdict, this.canJudge()),
  );

  /** The incident status as this viewer should understand it. */
  readonly statusChip = computed(() => incidentStatusChip(this.incident(), this.canJudge()));

  /** Row chrome that only means something to a steward. */
  readonly showsStewardDetail = computed(() => showsStewardDetail(this.canJudge()));

  /** True when this viewer may read verdicts on this incident at all. */
  readonly showsVerdicts = computed(() => showsVerdicts(this.incident(), this.canJudge()));

  /** The decision reason, printed once per card instead of once per driver. */
  readonly decisionDescription = computed(() => sharedDecisionDescription(this.incident()));

  /** Labels the verdict rows for a reader. Judges get the authoring footer
   *  instead, and an unjudged incident has nothing to head. */
  readonly decisionSectionShown = computed(
    () =>
      !this.canJudge() &&
      this.showsVerdicts() &&
      this.incident().drivers.some((d) => d.resolution),
  );

  /** Null when a badge would only repeat the chip row or the card header. */
  statusBadge(driver: IncidentDriver): StatusChip | null {
    return driverStatusBadge(driver, this.incident());
  }

  // ── Actions ───────────────────────────────────────────────────────

  submit(): void {
    const drafts = this.drafts();
    this.resolve.emit({
      description: this.description().trim() || undefined,
      // A blank verdict goes out as undefined so the server applies the default.
      drivers: this.incident().drivers.map((d) => {
        const verdict = (drafts[d.id]?.verdict ?? '').trim();
        return {
          incidentDriverId: d.id,
          verdict: verdict || undefined,
          bwpPoints: verdict ? drafts[d.id]?.bwpPoints : undefined,
        };
      }),
    });
  }

  confirmAddDriver(): void {
    const name = this.addDriverName().trim();
    if (!name) return;
    this.addDriver.emit(name);
    this.addDriverName.set('');
    this.addDriverShown.set(false);
  }
}
