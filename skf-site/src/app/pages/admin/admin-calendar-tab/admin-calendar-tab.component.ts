import { DatePipe } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
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
} from '../../../services/calendar-api.service';
import {
  ChampionshipListItem,
  SimgridApiService,
} from '../../../services/simgrid-api.service';

@Component({
  selector: 'app-admin-calendar-tab',
  imports: [FormsModule, DatePipe, BtnComponent, CardComponent, FormFieldComponent, SpinnerComponent],
  templateUrl: './admin-calendar-tab.component.html',
  styleUrl: './admin-calendar-tab.component.scss',
})
export class AdminCalendarTabComponent implements OnInit {
  private readonly calendarApi = inject(CalendarApiService);
  private readonly simgridApi = inject(SimgridApiService);

  readonly communities = signal<Community[]>([]);
  readonly simulators = signal<string[]>([]);
  readonly communitiesLoading = signal(false);
  readonly selectedCommunity = signal<Community | null>(null);
  readonly communityChampionships = signal<CustomChampionshipOut[]>([]);
  readonly champsLoading = signal(false);

  // SimGrid championships (shown when SKF community is selected)
  readonly simgridChampionships = signal<ChampionshipListItem[]>([]);
  readonly activeChampionshipIds = signal<Set<number>>(new Set());
  readonly simgridLoading = signal(false);

  readonly communityForm = signal<CommunityCreate>({ name: '', color: '#f5bf24', discordUrl: null });
  readonly editingCommunityId = signal<string | null>(null);

  readonly champForm = signal<{ name: string; game: string; carClass: string | null; description: string | null }>({
    name: '', game: '', carClass: null, description: null,
  });
  readonly editingChampId = signal<string | null>(null);

  readonly raceForm = signal<{ track: string | null; date: string | null }>({ track: null, date: null });

  updateCommunityField(field: keyof CommunityCreate, value: string | null): void {
    this.communityForm.update((f) => ({ ...f, [field]: value }));
  }

  updateChampField(field: 'name' | 'game' | 'carClass' | 'description', value: string | null): void {
    this.champForm.update((f) => ({ ...f, [field]: value }));
  }

  updateRaceField(field: 'track' | 'date', value: string | null): void {
    this.raceForm.update((f) => ({ ...f, [field]: value }));
  }

  ngOnInit(): void {
    this.loadCommunities();
    this.loadSimulators();
  }

  loadSimulators(): void {
    this.calendarApi.getSimulators().subscribe({
      next: (data) => this.simulators.set(data),
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
      this.simgridChampionships.set([]);
      return;
    }
    this.selectedCommunity.set(c);
    this.loadCommunityChampionships(c.id);
    this.resetChampForm();
    if (c.isSkf) {
      this.loadSimgridChampionships();
    } else {
      this.simgridChampionships.set([]);
    }
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
    this.champForm.set({ name: '', game: '', carClass: null, description: null });
    this.editingChampId.set(null);
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
        gameId: null,
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

  // -- SimGrid championships (SKF community) --

  async loadSimgridChampionships(): Promise<void> {
    this.simgridLoading.set(true);
    try {
      const [champs, activeIds] = await Promise.all([
        firstValueFrom(this.simgridApi.getChampionships()),
        firstValueFrom(this.simgridApi.getActiveChampionships()),
      ]);
      this.simgridChampionships.set(champs);
      this.activeChampionshipIds.set(new Set(activeIds));
    } catch {
      // non-critical
    } finally {
      this.simgridLoading.set(false);
    }
  }

  isSimgridActive(id: number): boolean {
    return this.activeChampionshipIds().has(id);
  }

  get activeSimgridChampionships(): ChampionshipListItem[] {
    return this.simgridChampionships().filter((c) => this.activeChampionshipIds().has(c.id));
  }

  get inactiveSimgridChampionships(): ChampionshipListItem[] {
    return this.simgridChampionships().filter((c) => !this.activeChampionshipIds().has(c.id));
  }

  async toggleSimgridActive(id: number): Promise<void> {
    const ids = this.activeChampionshipIds();
    if (ids.has(id)) {
      await firstValueFrom(this.simgridApi.removeActiveChampionship(id));
      const next = new Set(ids);
      next.delete(id);
      this.activeChampionshipIds.set(next);
    } else {
      await firstValueFrom(this.simgridApi.addActiveChampionship(id));
      this.activeChampionshipIds.set(new Set([...ids, id]));
    }
  }
}
