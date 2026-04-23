import { Component, inject, model, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import {
  CalendarApiService,
  CustomChampionshipCreate,
  CustomRaceCreate,
} from '../../services/calendar-api.service';
import { BtnComponent } from '../btn/btn.component';
import { FormFieldComponent } from '../form-field/form-field.component';
import { ModalComponent } from '../modal/modal.component';

interface RaceFormRow {
  date: string;
  track: string;
}

@Component({
  selector: 'app-custom-championship-form',
  standalone: true,
  imports: [FormsModule, BtnComponent, FormFieldComponent, ModalComponent],
  templateUrl: './custom-championship-form.component.html',
  styleUrl: './custom-championship-form.component.scss',
})
export class CustomChampionshipFormComponent {
  private readonly calendarApi = inject(CalendarApiService);

  readonly open = model.required<boolean>();
  readonly created = output<void>();

  name = '';
  game = '';
  carClass = '';
  description = '';
  races: RaceFormRow[] = [{ date: '', track: '' }];
  submitting = false;

  resetForm(): void {
    this.name = '';
    this.game = '';
    this.carClass = '';
    this.description = '';
    this.races = [{ date: '', track: '' }];
  }

  addRaceRow(): void {
    this.races.push({ date: '', track: '' });
  }

  removeRaceRow(index: number): void {
    this.races.splice(index, 1);
  }

  async submit(): Promise<void> {
    if (!this.name.trim() || !this.game.trim()) return;
    this.submitting = true;

    const racePayloads: CustomRaceCreate[] = this.races
      .filter((r) => r.date || r.track)
      .map((r) => ({
        date: r.date ? new Date(r.date).toISOString() : null,
        track: r.track || null,
      }));

    const payload: CustomChampionshipCreate = {
      name: this.name.trim(),
      game: this.game.trim(),
      carClass: this.carClass.trim() || null,
      description: this.description.trim() || null,
      communityId: null,
      gameId: null,
      races: racePayloads,
    };

    try {
      await firstValueFrom(this.calendarApi.createCustomChampionship(payload));
      this.open.set(false);
      this.created.emit();
    } catch {
      // Error is handled by the parent via loadChampionships refresh
    } finally {
      this.submitting = false;
    }
  }
}
