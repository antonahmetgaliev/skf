import { Component, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BtnComponent } from '../btn/btn.component';
import { FormFieldComponent } from '../form-field/form-field.component';

export interface ChampionshipFormRace {
  id?: string;
  track: string;
  date: string;
  endDate: string;
}

export interface ChampionshipFormData {
  name: string;
  game: string;
  carClass: string | null;
  description: string | null;
  races: ChampionshipFormRace[];
}

@Component({
  selector: 'app-championship-form',
  standalone: true,
  imports: [FormsModule, BtnComponent, FormFieldComponent],
  templateUrl: './championship-form.component.html',
  styleUrl: './championship-form.component.scss',
})
export class ChampionshipFormComponent {
  readonly simulators = input.required<string[]>();
  readonly initialData = input<ChampionshipFormData | null>(null);
  readonly isEditing = input(false);

  readonly save = output<ChampionshipFormData>();

  readonly form = signal<ChampionshipFormData>({
    name: '', game: '', carClass: null, description: null, races: [],
  });
  readonly multiDay = signal(false);

  constructor() {
    effect(() => {
      const data = this.initialData();
      if (data) {
        this.form.set({ ...data, races: data.races.map((r) => ({ ...r })) });
        this.multiDay.set(data.races.some((r) => !!r.endDate));
      } else {
        this.form.set({ name: '', game: '', carClass: null, description: null, races: [] });
        this.multiDay.set(false);
      }
    });
  }

  updateField(field: 'name' | 'game' | 'carClass' | 'description', value: string | null): void {
    this.form.update((f) => ({ ...f, [field]: value }));
  }

  addRaceRow(): void {
    this.form.update((f) => ({ ...f, races: [...f.races, { track: '', date: '', endDate: '' }] }));
  }

  updateRaceRow(index: number, field: 'track' | 'date' | 'endDate', value: string): void {
    this.form.update((f) => {
      const races = [...f.races];
      races[index] = { ...races[index], [field]: value };
      return { ...f, races };
    });
  }

  removeRaceRow(index: number): void {
    this.form.update((f) => ({ ...f, races: f.races.filter((_, i) => i !== index) }));
  }

  onSave(): void {
    const f = this.form();
    if (!f.name.trim() || !f.game.trim()) return;

    const data: ChampionshipFormData = {
      ...f,
      races: f.races.map((r) => ({
        ...r,
        endDate: this.multiDay() ? r.endDate : '',
      })),
    };
    this.save.emit(data);
  }
}
