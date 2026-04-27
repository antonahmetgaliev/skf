import { DatePipe } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BtnComponent } from '../../../components/btn/btn.component';
import { FormFieldComponent } from '../../../components/form-field/form-field.component';
import { ModalComponent } from '../../../components/modal/modal.component';
import { SpinnerComponent } from '../../../components/spinner/spinner.component';
import {
  CalendarApiService,
  Community,
  CommunityCreate,
  CustomChampionshipCreate,
  CustomChampionshipOut,
  CustomRaceCreate,
} from '../../../services/calendar-api.service';

@Component({
  selector: 'app-community-manage',
  imports: [FormsModule, DatePipe, BtnComponent, FormFieldComponent, ModalComponent, SpinnerComponent],
  templateUrl: './community-manage.component.html',
  styleUrl: './community-manage.component.scss',
})
export class CommunityManageComponent implements OnInit {
  private readonly calendarApi = inject(CalendarApiService);

  readonly communities = signal<Community[]>([]);
  readonly simulators = signal<string[]>([]);
  readonly communitiesLoading = signal(false);
  readonly selectedCommunity = signal<Community | null>(null);
  readonly communityChampionships = signal<CustomChampionshipOut[]>([]);
  readonly champsLoading = signal(false);

  readonly communityForm = signal<CommunityCreate>({ name: '', color: '#f5bf24', discordUrl: null });
  readonly editingCommunityId = signal<string | null>(null);

  readonly champForm = signal<{ name: string; game: string; carClass: string | null; description: string | null }>({
    name: '', game: '', carClass: null, description: null,
  });
  readonly editingChampId = signal<string | null>(null);

  readonly raceForm = signal<{ track: string | null; date: string | null }>({ track: null, date: null });
  readonly raceChampionship = signal<CustomChampionshipOut | null>(null);

  readonly communityModalOpen = signal(false);
  readonly champModalOpen = signal(false);
  readonly raceModalOpen = signal(false);

  updateCommunityField(field: keyof CommunityCreate, value: string | null): void {
    this.communityForm.update((f) => ({ ...f, [field]: value }));
  }

  updateChampField(field: 'name' | 'game' | 'carClass' | 'description', value: string | null): void {
    this.champForm.update((f) => ({ ...f, [field]: value }));
  }

  updateRaceField(field: 'track' | 'date', value: string | null): void {
    this.raceForm.update((f) => ({ ...f, [field]: value }));
  }

  private withLocalTzOffset(date: string | null): string | null {
    if (!date) return null;
    const parts = date.split(':');
    const base = parts.length >= 3 ? date : `${date}:00`;
    const offset = new Date().getTimezoneOffset();
    const sign = offset <= 0 ? '+' : '-';
    const absH = String(Math.floor(Math.abs(offset) / 60)).padStart(2, '0');
    const absM = String(Math.abs(offset) % 60).padStart(2, '0');
    return `${base}${sign}${absH}:${absM}`;
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
    this.calendarApi.getCommunitiesAdmin().subscribe({
      next: (data) => {
        this.communities.set(data);
        this.communitiesLoading.set(false);
      },
      error: () => this.communitiesLoading.set(false),
    });
  }

  editCommunity(c: Community): void {
    this.editingCommunityId.set(c.id);
    this.communityForm.set({ name: c.name, color: c.color, discordUrl: c.discordUrl });
    this.communityModalOpen.set(true);
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
          this.communityModalOpen.set(false);
        },
      });
    }
  }

  private resetCommunityForm(): void {
    this.communityForm.set({ name: '', color: '#f5bf24', discordUrl: null });
    this.editingCommunityId.set(null);
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

  // -- Championships --

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

  openChampModal(): void {
    this.resetChampForm();
    this.champModalOpen.set(true);
  }

  private resetChampForm(): void {
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
          this.champModalOpen.set(false);
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
          this.champModalOpen.set(false);
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
    this.champModalOpen.set(true);
  }

  deleteChampionship(champ: CustomChampionshipOut): void {
    this.calendarApi.deleteCustomChampionship(champ.id).subscribe({
      next: () => this.communityChampionships.update((list) => list.filter((c) => c.id !== champ.id)),
    });
  }

  // -- Races --

  openRaceModal(champ: CustomChampionshipOut): void {
    this.raceChampionship.set(champ);
    this.raceForm.set({ track: null, date: null });
    this.raceModalOpen.set(true);
  }

  addRace(champ: CustomChampionshipOut): void {
    const form = this.raceForm();
    const payload: CustomRaceCreate = {
      track: form.track?.trim() || null,
      date: this.withLocalTzOffset(form.date),
    };
    this.calendarApi.addRace(champ.id, payload).subscribe({
      next: (race) => {
        this.communityChampionships.update((list) =>
          list.map((c) => c.id === champ.id ? { ...c, races: [...c.races, race] } : c)
        );
        this.raceForm.set({ track: null, date: null });
        this.raceModalOpen.set(false);
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
