import { DatePipe } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BtnComponent } from '../../../components/btn/btn.component';
import { CardComponent } from '../../../components/card/card.component';
import { FormFieldComponent } from '../../../components/form-field/form-field.component';
import { SpinnerComponent } from '../../../components/spinner/spinner.component';
import {
  CalendarApiService,
  Community,
  CommunityCreate,
  CustomChampionshipCreate,
  CustomChampionshipOut,
  CustomRaceCreate,
  Game,
} from '../../../services/calendar-api.service';

@Component({
  selector: 'app-admin-calendar-tab',
  imports: [FormsModule, DatePipe, BtnComponent, CardComponent, FormFieldComponent, SpinnerComponent],
  templateUrl: './admin-calendar-tab.component.html',
  styleUrl: './admin-calendar-tab.component.scss',
})
export class AdminCalendarTabComponent implements OnInit {
  private readonly calendarApi = inject(CalendarApiService);

  readonly communities = signal<Community[]>([]);
  readonly simulators = signal<Game[]>([]);
  readonly communitiesLoading = signal(false);
  readonly selectedCommunity = signal<Community | null>(null);
  readonly communityChampionships = signal<CustomChampionshipOut[]>([]);
  readonly champsLoading = signal(false);

  readonly communityForm = signal<CommunityCreate>({ name: '', color: '#f5bf24', discordUrl: null });
  readonly editingCommunityId = signal<string | null>(null);

  readonly newSimulatorName = signal('');

  readonly champForm = signal<{ name: string; game: string; gameId: string | null; carClass: string | null; description: string | null }>({
    name: '', game: '', gameId: null, carClass: null, description: null,
  });
  readonly editingChampId = signal<string | null>(null);

  readonly raceForm = signal<{ track: string | null; date: string | null }>({ track: null, date: null });

  updateCommunityField(field: keyof CommunityCreate, value: string | null): void {
    this.communityForm.update((f) => ({ ...f, [field]: value }));
  }

  updateChampField(field: 'name' | 'game' | 'gameId' | 'carClass' | 'description', value: string | null): void {
    this.champForm.update((f) => ({ ...f, [field]: value }));
  }

  updateRaceField(field: 'track' | 'date', value: string | null): void {
    this.raceForm.update((f) => ({ ...f, [field]: value }));
  }

  ngOnInit(): void {
    this.loadCommunities();
    this.loadSimulators();
  }

  // -- Simulators --

  loadSimulators(): void {
    this.calendarApi.getGames().subscribe({
      next: (data) => this.simulators.set(data),
    });
  }

  addSimulator(): void {
    const name = this.newSimulatorName().trim();
    if (!name) return;
    this.calendarApi.createGame({ name }).subscribe({
      next: (sim) => {
        this.simulators.update((list) => [...list, sim].sort((a, b) => a.name.localeCompare(b.name)));
        this.newSimulatorName.set('');
      },
    });
  }

  deleteSimulator(sim: Game): void {
    this.calendarApi.deleteGame(sim.id).subscribe({
      next: () => this.simulators.update((list) => list.filter((g) => g.id !== sim.id)),
    });
  }

  // -- Communities --

  loadCommunities(): void {
    this.communitiesLoading.set(true);
    this.calendarApi.getCommunities().subscribe({
      next: (data) => {
        this.communities.set(data);
        this.communitiesLoading.set(false);
      },
      error: () => this.communitiesLoading.set(false),
    });
  }

  resetCommunityForm(): void {
    this.communityForm.set({ name: '', color: '#f5bf24', discordUrl: null });
    this.editingCommunityId.set(null);
  }

  editCommunity(c: Community): void {
    this.editingCommunityId.set(c.id);
    this.communityForm.set({ name: c.name, color: c.color, discordUrl: c.discordUrl });
  }

  saveCommunity(): void {
    const form = this.communityForm();
    if (!form.name.trim()) return;

    const editId = this.editingCommunityId();
    if (editId) {
      this.calendarApi.updateCommunity(editId, {
        name: form.name.trim(),
        color: form.color,
        discordUrl: form.discordUrl?.trim() || null,
      }).subscribe({
        next: (updated) => {
          this.communities.update((list) => list.map((c) => c.id === updated.id ? updated : c));
          this.resetCommunityForm();
        },
      });
    } else {
      this.calendarApi.createCommunity({
        name: form.name.trim(),
        color: form.color,
        discordUrl: form.discordUrl?.trim() || null,
      }).subscribe({
        next: (created) => {
          this.communities.update((list) => [...list, created]);
          this.resetCommunityForm();
        },
      });
    }
  }

  deleteCommunity(c: Community): void {
    this.calendarApi.deleteCommunity(c.id).subscribe({
      next: () => {
        this.communities.update((list) => list.filter((x) => x.id !== c.id));
        if (this.selectedCommunity()?.id === c.id) {
          this.selectedCommunity.set(null);
          this.communityChampionships.set([]);
        }
      },
    });
  }

  selectCommunity(c: Community): void {
    if (this.selectedCommunity()?.id === c.id) {
      this.selectedCommunity.set(null);
      this.communityChampionships.set([]);
      return;
    }
    this.selectedCommunity.set(c);
    this.loadCommunityChampionships(c.id);
    this.resetChampForm();
  }

  // -- Championships (per community) --

  loadCommunityChampionships(communityId: string): void {
    this.champsLoading.set(true);
    this.calendarApi.getCustomChampionships(communityId).subscribe({
      next: (data) => {
        this.communityChampionships.set(data);
        this.champsLoading.set(false);
      },
      error: () => this.champsLoading.set(false),
    });
  }

  resetChampForm(): void {
    this.champForm.set({ name: '', game: '', gameId: null, carClass: null, description: null });
    this.editingChampId.set(null);
  }

  onSimulatorSelect(gameId: string): void {
    const sim = this.simulators().find((g) => g.id === gameId);
    this.champForm.update((f) => ({ ...f, gameId: gameId || null, game: sim?.name ?? '' }));
  }

  saveChampionship(): void {
    const form = this.champForm();
    const community = this.selectedCommunity();
    if (!form.name.trim() || !form.game.trim() || !community) return;

    const editId = this.editingChampId();
    if (editId) {
      this.calendarApi.updateCustomChampionship(editId, {
        name: form.name.trim(),
        game: form.game.trim(),
        gameId: form.gameId,
        carClass: form.carClass?.trim() || null,
        description: form.description?.trim() || null,
      }).subscribe({
        next: (updated) => {
          this.communityChampionships.update((list) => list.map((c) => c.id === updated.id ? updated : c));
          this.resetChampForm();
        },
      });
    } else {
      const payload: CustomChampionshipCreate = {
        name: form.name.trim(),
        game: form.game.trim(),
        communityId: community.id,
        gameId: form.gameId,
        carClass: form.carClass?.trim() || null,
        description: form.description?.trim() || null,
        races: [],
      };
      this.calendarApi.createCustomChampionship(payload).subscribe({
        next: (created) => {
          this.communityChampionships.update((list) => [...list, created]);
          this.resetChampForm();
        },
      });
    }
  }

  editChampionship(champ: CustomChampionshipOut): void {
    this.editingChampId.set(champ.id);
    this.champForm.set({
      name: champ.name,
      game: champ.game,
      gameId: champ.gameId,
      carClass: champ.carClass,
      description: champ.description,
    });
  }

  deleteChampionship(champ: CustomChampionshipOut): void {
    this.calendarApi.deleteCustomChampionship(champ.id).subscribe({
      next: () => this.communityChampionships.update((list) => list.filter((c) => c.id !== champ.id)),
    });
  }

  // -- Races --

  addRace(champ: CustomChampionshipOut): void {
    const form = this.raceForm();
    const payload: CustomRaceCreate = {
      track: form.track?.trim() || null,
      date: form.date || null,
    };
    this.calendarApi.addRace(champ.id, payload).subscribe({
      next: (race) => {
        this.communityChampionships.update((list) =>
          list.map((c) => c.id === champ.id ? { ...c, races: [...c.races, race] } : c)
        );
        this.raceForm.set({ track: null, date: null });
      },
    });
  }

  deleteRace(champ: CustomChampionshipOut, raceId: string): void {
    this.calendarApi.deleteRace(champ.id, raceId).subscribe({
      next: () => {
        this.communityChampionships.update((list) =>
          list.map((c) => c.id === champ.id ? { ...c, races: c.races.filter((r) => r.id !== raceId) } : c)
        );
      },
    });
  }
}
