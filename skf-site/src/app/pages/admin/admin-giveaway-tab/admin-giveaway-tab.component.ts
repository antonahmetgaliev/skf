import { DatePipe } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { BtnComponent } from '../../../components/btn/btn.component';
import { CardComponent } from '../../../components/card/card.component';
import { EmptyComponent } from '../../../components/empty/empty.component';
import { FormFieldComponent } from '../../../components/form-field/form-field.component';
import { SpinnerComponent } from '../../../components/spinner/spinner.component';
import { InputDirective } from '../../../directives/input.directive';
import { SelectDirective } from '../../../directives/select.directive';
import { ConfirmDialogService } from '../../../services/confirm-dialog.service';
import {
  Eligibility,
  EligibleDriver,
  GiveawayApiService,
  GiveawayRound,
  RaceResultImport,
  UnmatchedName,
} from '../../../services/giveaway-api.service';
import {
  ChampionshipListItem,
  SimgridApiService,
} from '../../../services/simgrid-api.service';
import { classesOf, driversInClass, hasEnoughRounds, pickWinner } from './giveaway-eligibility';

/**
 * Admin tab for the championship giveaway.
 *
 * SimGrid exposes no per-race results, so the laps each driver covered are
 * imported from the game server's own result XML. Everything below reads that
 * imported data; no draw costs a SimGrid request.
 */
@Component({
  selector: 'app-admin-giveaway-tab',
  imports: [FormsModule, DatePipe, TranslocoPipe, InputDirective, SelectDirective, BtnComponent, CardComponent, EmptyComponent, FormFieldComponent, SpinnerComponent],
  templateUrl: './admin-giveaway-tab.component.html',
  styleUrl: './admin-giveaway-tab.component.scss',
})
export class AdminGiveawayTabComponent implements OnInit {
  private readonly api = inject(GiveawayApiService);
  private readonly simgridApi = inject(SimgridApiService);
  private readonly confirmSvc = inject(ConfirmDialogService);
  private readonly transloco = inject(TranslocoService);

  readonly championships = signal<ChampionshipListItem[]>([]);
  readonly championshipsLoading = signal(false);
  readonly selectedChampionshipId = signal<number | null>(null);

  readonly rounds = signal<GiveawayRound[]>([]);
  readonly imports = signal<RaceResultImport[]>([]);
  readonly unmatched = signal<UnmatchedName[]>([]);
  readonly dataLoading = signal(false);

  readonly uploadRoundId = signal<number | null>(null);
  readonly uploading = signal(false);
  readonly uploadError = signal('');

  // Defaults mirror the regulation: >=50% of the distance in 3 of 5 rounds.
  readonly minDistancePct = signal(50);
  readonly minRounds = signal(3);

  readonly eligibility = signal<Eligibility | null>(null);
  readonly eligibilityLoading = signal(false);
  readonly selectedClass = signal<string | null>(null);
  readonly winner = signal<EligibleDriver | null>(null);

  readonly aliasTarget = signal<UnmatchedName | null>(null);
  readonly aliasCanonical = signal('');

  readonly carClasses = computed(() => classesOf(this.eligibility()?.drivers ?? []));

  readonly poolForSelectedClass = computed(() => {
    const drivers = this.eligibility()?.drivers ?? [];
    const carClass = this.selectedClass();
    return carClass ? driversInClass(drivers, carClass) : drivers;
  });

  /** True when fewer rounds have been imported than the threshold demands. */
  readonly notEnoughRounds = computed(() => {
    const data = this.eligibility();
    return data !== null && !hasEnoughRounds(data.importedRounds, data.minRounds);
  });

  ngOnInit(): void {
    this.championshipsLoading.set(true);
    this.simgridApi.getChampionships().subscribe({
      next: (list) => {
        this.championships.set(list);
        this.championshipsLoading.set(false);
      },
      error: () => this.championshipsLoading.set(false),
    });
  }

  selectChampionship(value: string): void {
    const id = value ? Number(value) : null;
    this.selectedChampionshipId.set(id);
    this.resetDraw();
    this.eligibility.set(null);
    this.rounds.set([]);
    this.imports.set([]);
    this.unmatched.set([]);
    if (id !== null) this.loadChampionshipData(id);
  }

  private loadChampionshipData(championshipId: number): void {
    this.dataLoading.set(true);
    this.api.getRounds(championshipId).subscribe({
      next: (rounds) => this.rounds.set(rounds),
    });
    this.api.getImports(championshipId).subscribe({
      next: (imports) => {
        this.imports.set(imports);
        this.dataLoading.set(false);
        this.loadEligibility();
      },
      error: () => this.dataLoading.set(false),
    });
    this.api.getUnmatched(championshipId).subscribe({
      next: (names) => this.unmatched.set(names),
    });
  }

  /** The import covering a round, if one has been uploaded. */
  importForRound(roundId: number): RaceResultImport | null {
    return this.imports().find((i) => i.raceSimgridId === roundId) ?? null;
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    const championshipId = this.selectedChampionshipId();
    if (!file || championshipId === null) return;

    this.uploading.set(true);
    this.uploadError.set('');
    this.api.uploadResults(championshipId, this.uploadRoundId(), file).subscribe({
      next: () => {
        this.uploading.set(false);
        // Clear the picker so re-uploading the same filename still fires.
        input.value = '';
        this.resetDraw();
        this.loadChampionshipData(championshipId);
      },
      error: (err) => {
        this.uploading.set(false);
        input.value = '';
        this.uploadError.set(err?.error?.detail ?? 'Upload failed');
      },
    });
  }

  async deleteImport(record: RaceResultImport): Promise<void> {
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('giveaway.deleteImportConfirm', {
        name: record.trackEvent ?? record.sourceFilename ?? '',
      }),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;
    const championshipId = this.selectedChampionshipId();
    this.api.deleteImport(record.id).subscribe({
      next: () => {
        this.resetDraw();
        if (championshipId !== null) this.loadChampionshipData(championshipId);
      },
    });
  }

  loadEligibility(): void {
    const championshipId = this.selectedChampionshipId();
    if (championshipId === null) return;
    this.eligibilityLoading.set(true);
    this.api
      .getEligibility(championshipId, this.minDistancePct(), this.minRounds())
      .subscribe({
        next: (data) => {
          this.eligibility.set(data);
          this.eligibilityLoading.set(false);
          const classes = this.carClasses();
          if (this.selectedClass() === null || !classes.includes(this.selectedClass()!)) {
            this.selectedClass.set(classes[0] ?? null);
          }
        },
        error: () => this.eligibilityLoading.set(false),
      });
  }

  /** Changing the rules invalidates the winner they produced. */
  onRulesChanged(): void {
    this.resetDraw();
    this.loadEligibility();
  }

  selectClass(carClass: string): void {
    this.selectedClass.set(carClass);
    this.resetDraw();
  }

  draw(): void {
    this.winner.set(pickWinner(this.poolForSelectedClass()));
  }

  private resetDraw(): void {
    this.winner.set(null);
  }

  // -- Name merging --

  startAlias(name: UnmatchedName): void {
    this.aliasTarget.set(name);
    this.aliasCanonical.set(name.suggestions[0] ?? '');
  }

  cancelAlias(): void {
    this.aliasTarget.set(null);
    this.aliasCanonical.set('');
  }

  confirmAlias(): void {
    const target = this.aliasTarget();
    const canonical = this.aliasCanonical().trim();
    const championshipId = this.selectedChampionshipId();
    if (!target || !canonical || championshipId === null) return;
    this.api.createAlias(target.normalizedName, canonical).subscribe({
      next: () => {
        this.cancelAlias();
        this.resetDraw();
        this.loadChampionshipData(championshipId);
      },
    });
  }
}
