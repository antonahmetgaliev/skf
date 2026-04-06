import { Component, computed, inject, model, input, signal } from '@angular/core';
import { StandingEntry } from '../../services/simgrid-api.service';
import { ChampionshipService } from '../../services/championship.service';
import { BtnComponent } from '../btn/btn.component';
import { EmptyComponent } from '../empty/empty.component';

@Component({
  selector: 'app-giveaway-modal',
  standalone: true,
  imports: [BtnComponent, EmptyComponent],
  templateUrl: './giveaway-modal.component.html',
  styleUrl: './giveaway-modal.component.scss',
})
export class GiveawayModalComponent {
  private readonly cs = inject(ChampionshipService);

  readonly standings = input.required<StandingEntry[]>();
  readonly open = model.required<boolean>();

  readonly minRaces = signal(1);
  readonly winner = signal<string | null>(null);
  readonly drivers = computed(() => this.cs.computeEligibleDrivers(this.standings(), this.minRaces()));

  close(): void {
    this.open.set(false);
  }

  onMinRacesChange(event: Event): void {
    const value = parseInt((event.target as HTMLInputElement).value, 10);
    this.minRaces.set(Number.isFinite(value) && value > 0 ? value : 1);
    this.winner.set(null);
  }

  pickRandom(): void {
    const list = this.drivers();
    if (list.length === 0) return;
    this.winner.set(list[Math.floor(Math.random() * list.length)].displayName);
  }
}
