import { Component, inject, output, signal } from '@angular/core';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { BtnComponent } from '../../../components/btn/btn.component';
import {
  ChampionshipFormComponent,
  ChampionshipFormData,
} from '../../../components/championship-form/championship-form.component';
import { ModalComponent } from '../../../components/modal/modal.component';
import {
  CalendarApiService,
  CalendarEvent,
  CustomChampionshipCreate,
} from '../../../services/calendar-api.service';
import { ConfirmDialogService } from '../../../services/confirm-dialog.service';
import { toLocalDatetimeLocal, withLocalTzOffset } from '../../../utils/date';

/**
 * Create, edit and delete a community's custom championships.
 * The calendar calls `openAdd` / `edit` / `delete` and reloads on `changed`.
 */
@Component({
  selector: 'app-championship-editor',
  imports: [TranslocoPipe, BtnComponent, ChampionshipFormComponent, ModalComponent],
  templateUrl: './championship-editor.component.html',
})
export class ChampionshipEditorComponent {
  private readonly calendarApi = inject(CalendarApiService);
  private readonly confirmSvc = inject(ConfirmDialogService);
  private readonly transloco = inject(TranslocoService);

  /** Emitted after a championship was created, updated or deleted. */
  readonly changed = output<void>();

  readonly open = signal(false);
  readonly simulators = signal<string[]>([]);
  readonly formData = signal<ChampionshipFormData | null>(null);
  readonly editingId = signal<string | null>(null);
  private readonly communityId = signal<string | null>(null);

  openAdd(communityId: string): void {
    this.formData.set({ name: '', game: '', carClass: null, description: null, races: [] });
    this.editingId.set(null);
    this.communityId.set(communityId);
    this.open.set(true);
    if (this.simulators().length === 0) {
      this.calendarApi.getSimulators().subscribe({ next: (d) => this.simulators.set(d) });
    }
  }

  edit(event: CalendarEvent): void {
    if (!event.customChampionshipId) return;
    this.editingId.set(event.customChampionshipId);
    this.communityId.set(event.community?.id ?? null);
    this.formData.set({
      name: event.name,
      game: event.game,
      carClass: event.carClass,
      description: event.description,
      races: [],
    });
    this.open.set(true);
    if (this.simulators().length === 0) {
      this.calendarApi.getSimulators().subscribe({ next: (d) => this.simulators.set(d) });
    }
    this.calendarApi.getCustomChampionship(event.customChampionshipId).subscribe({
      next: (champ) => {
        this.formData.set({
          name: champ.name,
          game: champ.game,
          carClass: champ.carClass,
          description: champ.description,
          races: champ.races.map((r) => ({
            id: r.id,
            track: r.track ?? '',
            date: r.date ? toLocalDatetimeLocal(r.date) : '',
            endDate: r.endDate ? toLocalDatetimeLocal(r.endDate) : '',
          })),
        });
      },
    });
  }

  save(form: ChampionshipFormData): void {
    const editId = this.editingId();
    if (editId) {
      this.calendarApi
        .updateCustomChampionship(editId, {
          name: form.name.trim(),
          game: form.game.trim(),
          carClass: form.carClass?.trim() || null,
          description: form.description?.trim() || null,
        })
        .subscribe({
          next: () => {
            const racesToSync = form.races
              .filter((r) => r.id || r.track.trim() || r.date)
              .map((r) => ({
                id: r.id,
                track: r.track.trim() || null,
                date: withLocalTzOffset(r.date || null),
                endDate: withLocalTzOffset(r.endDate || null),
              }));
            this.calendarApi.syncRaces(editId, racesToSync).subscribe({
              next: () => {
                this.open.set(false);
                this.changed.emit();
              },
            });
          },
        });
    } else {
      const communityId = this.communityId();
      if (!communityId) return;
      const payload: CustomChampionshipCreate = {
        name: form.name.trim(),
        game: form.game.trim(),
        communityId,
        gameId: null,
        carClass: form.carClass?.trim() || null,
        description: form.description?.trim() || null,
        races: form.races
          .filter((r) => r.track.trim() || r.date)
          .map((r) => ({
            track: r.track.trim() || null,
            date: withLocalTzOffset(r.date || null),
            endDate: withLocalTzOffset(r.endDate || null),
          })),
      };
      this.calendarApi.createCustomChampionship(payload).subscribe({
        next: () => {
          this.open.set(false);
          this.changed.emit();
        },
      });
    }
  }

  async delete(event: CalendarEvent): Promise<void> {
    if (!event.customChampionshipId) return;
    const ok = await this.confirmSvc.confirm({
      title: this.transloco.translate('common.confirm.deleteTitle'),
      message: this.transloco.translate('calendar.deleteChampionshipConfirm', { name: event.name }),
      confirmLabel: this.transloco.translate('common.confirm.delete'),
      danger: true,
    });
    if (!ok) return;
    this.calendarApi.deleteCustomChampionship(event.customChampionshipId).subscribe({
      next: () => this.changed.emit(),
    });
  }
}
