import { DatePipe } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { BadgeComponent } from '../../../components/badge/badge.component';
import { BtnComponent } from '../../../components/btn/btn.component';
import { CardComponent } from '../../../components/card/card.component';
import { EmptyComponent } from '../../../components/empty/empty.component';
import { FormFieldComponent } from '../../../components/form-field/form-field.component';
import { SpinnerComponent } from '../../../components/spinner/spinner.component';
import { SelectDirective } from '../../../directives/select.directive';
import { ConfirmDialogService } from '../../../services/confirm-dialog.service';
import {
  ImportResult,
  RaceImport,
  RaceResultsApiService,
  RaceRound,
  RaceRounds,
  SIM_FILE_ACCEPT,
  SIM_LABELS,
} from '../../../services/race-results-api.service';
import {
  ChampionshipListItem,
  SimgridApiService,
} from '../../../services/simgrid-api.service';

/**
 * Admin tab for each round's game-server result file.
 *
 * One upload per SimGrid round (LMU .xml, iRacing .bin) feeds both the
 * giveaway and the round's Auto incidents. The simulator, and so the file
 * type, follows from the championship's game.
 */
@Component({
  selector: 'app-admin-race-results-tab',
  imports: [FormsModule, DatePipe, RouterLink, TranslocoPipe, SelectDirective, BadgeComponent, BtnComponent, CardComponent, EmptyComponent, FormFieldComponent, SpinnerComponent],
  templateUrl: './admin-race-results-tab.component.html',
  styleUrl: './admin-race-results-tab.component.scss',
})
export class AdminRaceResultsTabComponent implements OnInit {
  private readonly api = inject(RaceResultsApiService);
  private readonly simgridApi = inject(SimgridApiService);
  private readonly confirmSvc = inject(ConfirmDialogService);
  private readonly transloco = inject(TranslocoService);

  readonly championships = signal<ChampionshipListItem[]>([]);
  readonly championshipsLoading = signal(false);
  readonly selectedChampionshipId = signal<number | null>(null);

  readonly data = signal<RaceRounds | null>(null);
  readonly loading = signal(false);
  readonly loadError = signal('');

  readonly createIncidents = signal(true);
  /** Round whose upload, re-parse or delete is in flight. */
  readonly busyRoundId = signal<number | null>(null);
  readonly error = signal('');
  readonly lastResult = signal<ImportResult | null>(null);

  readonly simLabels = SIM_LABELS;
  readonly accept = computed(() => {
    const sim = this.data()?.sim;
    return sim ? SIM_FILE_ACCEPT[sim] : '';
  });
  readonly fileExtension = computed(() => (this.data()?.sim === 'iracing' ? '.bin' : '.xml'));

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

  selectChampionship(id: number | null): void {
    this.selectedChampionshipId.set(id);
    this.data.set(null);
    this.lastResult.set(null);
    this.error.set('');
    if (id !== null) this.load(id);
  }

  private load(championshipId: number): void {
    this.loading.set(true);
    this.loadError.set('');
    this.api.getRounds(championshipId).subscribe({
      next: (data) => {
        if (this.selectedChampionshipId() !== championshipId) return;
        this.data.set(data);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(err?.error?.detail ?? 'Failed to load rounds');
      },
    });
  }

  private reload(): void {
    const id = this.selectedChampionshipId();
    if (id !== null) this.load(id);
  }

  onFileSelected(round: RaceRound, event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    // Clear the picker so re-uploading the same filename still fires.
    input.value = '';
    const championshipId = this.selectedChampionshipId();
    if (!file || championshipId === null) return;

    this.run(round, this.api.upload(championshipId, round.raceId, file, this.createIncidents()));
  }

  reparse(round: RaceRound, record: RaceImport): void {
    this.run(round, this.api.reparse(record.id));
  }

  download(record: RaceImport): void {
    this.api.download(record.id).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = record.sourceFilename ?? `${record.id}${this.fileExtension()}`;
        link.click();
        URL.revokeObjectURL(url);
      },
      error: (err) => this.error.set(err?.error?.detail ?? 'Download failed'),
    });
  }

  async deleteImport(round: RaceRound, record: RaceImport): Promise<void> {
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('raceImports.deleteConfirm', { name: round.name }),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;
    this.busyRoundId.set(round.raceId);
    this.error.set('');
    this.api.deleteImport(record.id).subscribe({
      next: () => {
        this.busyRoundId.set(null);
        this.lastResult.set(null);
        this.reload();
      },
      error: (err) => {
        this.busyRoundId.set(null);
        this.error.set(err?.error?.detail ?? 'Delete failed');
      },
    });
  }

  private run(round: RaceRound, request: ReturnType<RaceResultsApiService['upload']>): void {
    this.busyRoundId.set(round.raceId);
    this.error.set('');
    this.lastResult.set(null);
    request.subscribe({
      next: (result) => {
        this.busyRoundId.set(null);
        this.lastResult.set(result);
        this.reload();
      },
      error: (err) => {
        this.busyRoundId.set(null);
        this.error.set(err?.error?.detail ?? 'Upload failed');
      },
    });
  }

  formatSize(bytes: number | null): string {
    if (!bytes) return '';
    return bytes >= 1024 * 1024
      ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
      : `${Math.round(bytes / 1024)} KB`;
  }
}
