import { computed, inject, Injectable, signal } from '@angular/core';
import { TranslocoService } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';
import { ConfirmDialogService } from '../../services/confirm-dialog.service';
import {
  DescriptionPreset,
  IncidentsApiService,
  VerdictRule,
} from '../../services/incidents-api.service';

/**
 * Verdict rules and description presets for the incidents page. The page reads
 * them to judge incidents; the settings modal edits them. Provided by the page,
 * so both share one instance.
 */
@Injectable()
export class IncidentRulesStore {
  private readonly api = inject(IncidentsApiService);
  private readonly confirmSvc = inject(ConfirmDialogService);
  private readonly transloco = inject(TranslocoService);

  readonly verdictRules = signal<VerdictRule[]>([]);

  /** The verdict pre-selected for every unresolved driver. */
  readonly defaultRule = computed(() => this.verdictRules().find((r) => r.isDefault) ?? null);

  readonly descriptionPresets = signal<DescriptionPreset[]>([]);
  readonly descriptionPresetTexts = computed(() => this.descriptionPresets().map((p) => p.text));

  // ── Verdict rules ──────────────────────────────────────────────────

  async loadVerdictRules(): Promise<void> {
    try {
      this.verdictRules.set(await firstValueFrom(this.api.getVerdictRules()));
    } catch {
      /* silent — rules are optional for page load */
    }
  }

  async addVerdictRule(verdict: string, defaultBwp: number): Promise<void> {
    await firstValueFrom(this.api.createVerdictRule({ verdict, defaultBwp }));
    await this.loadVerdictRules();
  }

  async saveRuleVerdict(rule: VerdictRule, verdict: string): Promise<void> {
    const trimmed = verdict.trim();
    if (!trimmed || trimmed === rule.verdict) return;
    await firstValueFrom(this.api.updateVerdictRule(rule.id, { verdict: trimmed }));
    await this.loadVerdictRules();
  }

  async saveRuleBwp(rule: VerdictRule, value: string): Promise<void> {
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed < 0 || parsed === rule.defaultBwp) return;
    await firstValueFrom(this.api.updateVerdictRule(rule.id, { defaultBwp: parsed }));
    await this.loadVerdictRules();
  }

  async setDefaultRule(rule: VerdictRule): Promise<void> {
    if (rule.isDefault) return;
    await firstValueFrom(this.api.updateVerdictRule(rule.id, { isDefault: true }));
    await this.loadVerdictRules();
  }

  /** Move a rule one slot; sort_order has existed all along with no way to set it. */
  async moveRule(index: number, delta: number): Promise<void> {
    const ids = this.verdictRules().map((r) => r.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    await firstValueFrom(this.api.reorderVerdictRules(ids));
    await this.loadVerdictRules();
  }

  async deleteVerdictRule(id: string): Promise<void> {
    if (!(await this.confirmDelete('incidents.deleteVerdictRuleConfirm'))) return;
    await firstValueFrom(this.api.deleteVerdictRule(id));
    await this.loadVerdictRules();
  }

  // ── Description presets ────────────────────────────────────────────

  async loadDescriptionPresets(): Promise<void> {
    try {
      this.descriptionPresets.set(await firstValueFrom(this.api.getDescriptionPresets()));
    } catch {
      /* silent */
    }
  }

  async addDescriptionPreset(text: string): Promise<void> {
    await firstValueFrom(this.api.createDescriptionPreset({ text }));
    await this.loadDescriptionPresets();
  }

  async savePresetText(preset: DescriptionPreset, text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed || trimmed === preset.text) return;
    await firstValueFrom(this.api.updateDescriptionPreset(preset.id, { text: trimmed }));
    await this.loadDescriptionPresets();
  }

  async deleteDescriptionPreset(id: string): Promise<void> {
    if (!(await this.confirmDelete('incidents.deleteDescriptionPresetConfirm'))) return;
    await firstValueFrom(this.api.deleteDescriptionPreset(id));
    await this.loadDescriptionPresets();
  }

  private confirmDelete(messageKey: string): Promise<boolean> {
    return this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate(messageKey),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
  }
}
