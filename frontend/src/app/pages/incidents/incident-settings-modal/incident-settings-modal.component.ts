import { Component, computed, inject, model, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';
import { BadgeComponent } from '../../../components/badge/badge.component';
import { BtnComponent } from '../../../components/btn/btn.component';
import { EmptyComponent } from '../../../components/empty/empty.component';
import { ModalComponent } from '../../../components/modal/modal.component';
import { TabsComponent } from '../../../components/tabs/tabs.component';
import { InputDirective } from '../../../directives/input.directive';
import { AuthService } from '../../../services/auth.service';
import {
  BwpAuditEntry,
  BwpBackfillResult,
  IncidentsApiService,
} from '../../../services/incidents-api.service';
import { IncidentRulesStore } from '../incident-rules.store';

/** Stewarding settings: verdict rules, description presets and (admins) the BWP audit. */
@Component({
  selector: 'app-incident-settings-modal',
  imports: [
    FormsModule,
    TranslocoPipe,
    BadgeComponent,
    BtnComponent,
    EmptyComponent,
    ModalComponent,
    TabsComponent,
    InputDirective,
  ],
  templateUrl: './incident-settings-modal.component.html',
  styleUrl: './incident-settings-modal.component.scss',
})
export class IncidentSettingsModalComponent {
  readonly auth = inject(AuthService);
  readonly rules = inject(IncidentRulesStore);
  private readonly incidentsApi = inject(IncidentsApiService);

  readonly open = model(false);

  readonly tab = signal('verdicts');
  // Judges share this modal with admins, but the BWP audit is admin-only work.
  // Offering them the tab would just open an empty panel.
  readonly tabs = computed(() => [
    { key: 'verdicts', label: 'incidents.tabVerdicts' },
    { key: 'descriptions', label: 'incidents.tabDescriptions' },
    ...(this.auth.isAdmin() ? [{ key: 'unlinked', label: 'incidents.unlinkedPenalties' }] : []),
  ]);

  // Config is read-only until Edit is pressed: a stray click must not be able
  // to rewrite the rules the whole league is judged against. Inside the mode
  // every change saves immediately, so Done only locks it back.
  readonly rulesEditMode = signal(false);
  readonly presetsEditMode = signal(false);

  newRuleVerdict = '';
  newRuleDefaultBwp = 0;
  newPresetText = '';

  async addVerdictRule(): Promise<void> {
    if (!this.newRuleVerdict.trim()) return;
    await this.rules.addVerdictRule(this.newRuleVerdict.trim(), this.newRuleDefaultBwp);
    this.newRuleVerdict = '';
    this.newRuleDefaultBwp = 0;
  }

  async addDescriptionPreset(): Promise<void> {
    if (!this.newPresetText.trim()) return;
    await this.rules.addDescriptionPreset(this.newPresetText.trim());
    this.newPresetText = '';
  }

  // ── BWP audit ──────────────────────────────────────────────────────

  readonly bwpAuditEntries = signal<BwpAuditEntry[] | null>(null);
  readonly backfillRunning = signal(false);
  readonly backfillResult = signal<BwpBackfillResult | null>(null);
  readonly hasMatchableAuditEntries = computed(() =>
    (this.bwpAuditEntries() ?? []).some((e) => e.matchedDriverId !== null),
  );

  async loadBwpAudit(): Promise<void> {
    this.bwpAuditEntries.set(await firstValueFrom(this.incidentsApi.getBwpAudit()));
    this.backfillResult.set(null);
  }

  async runBwpBackfill(): Promise<void> {
    this.backfillRunning.set(true);
    try {
      this.backfillResult.set(await firstValueFrom(this.incidentsApi.runBwpBackfill()));
      // Refresh audit list to reflect fixes
      this.bwpAuditEntries.set(await firstValueFrom(this.incidentsApi.getBwpAudit()));
    } finally {
      this.backfillRunning.set(false);
    }
  }
}
