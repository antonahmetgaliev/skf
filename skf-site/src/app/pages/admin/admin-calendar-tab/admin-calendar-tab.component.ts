import { DatePipe } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { withLocalTzOffset } from '../../../utils/date';
import { BtnComponent } from '../../../components/btn/btn.component';
import { CardComponent } from '../../../components/card/card.component';
import { FormFieldComponent } from '../../../components/form-field/form-field.component';
import { ModalComponent } from '../../../components/modal/modal.component';
import { SpinnerComponent } from '../../../components/spinner/spinner.component';
import { AlertComponent } from '../../../components/alert/alert.component';
import {
  CalendarApiService,
  Community,
  CommunityCreate,
  CustomChampionshipCreate,
  CustomChampionshipOut,
  CustomRaceCreate,
} from '../../../services/calendar-api.service';
import {
  DotdApiService,
  DotdCandidateIn,
  DotdPollOut,
} from '../../../services/dotd-api.service';
import {
  ChampionshipListItem,
  ChampionshipStandingsData,
  SimgridApiService,
} from '../../../services/simgrid-api.service';

@Component({
  selector: 'app-admin-calendar-tab',
  imports: [FormsModule, DatePipe, AlertComponent, BtnComponent, CardComponent, FormFieldComponent, ModalComponent, SpinnerComponent],
  templateUrl: './admin-calendar-tab.component.html',
  styleUrl: './admin-calendar-tab.component.scss',
})
export class AdminCalendarTabComponent implements OnInit {
  private readonly calendarApi = inject(CalendarApiService);
  private readonly dotdApi = inject(DotdApiService);
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

  readonly communityForm = signal<CommunityCreate>({ name: '', color: '#ffd600', discordUrl: null });
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

  ngOnInit(): void {
    this.loadCommunities();
    this.loadSimulators();
    this.loadDotdPolls();
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

  openCommunityModal(): void {
    this.resetCommunityForm();
    this.communityModalOpen.set(true);
  }

  resetCommunityForm(): void {
    this.communityForm.set({ name: '', color: '#ffd600', discordUrl: null });
    this.editingCommunityId.set(null);
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
    } else {
      this.calendarApi.createCommunity({
        name: form.name.trim(),
        color: form.color,
        discordUrl: form.discordUrl?.trim() || null,
      }).subscribe({
        next: (created) => {
          this.communities.update((list) => [...list, created]);
          this.resetCommunityForm();
          this.communityModalOpen.set(false);
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

  openChampModal(): void {
    this.resetChampForm();
    this.champModalOpen.set(true);
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
      date: withLocalTzOffset(form.date),
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

  // -- DOTD Polls --

  readonly dotdPolls = signal<DotdPollOut[]>([]);
  readonly dotdLoading = signal(false);
  readonly dotdModalOpen = signal(false);
  readonly dotdChampionships = signal<ChampionshipListItem[]>([]);
  readonly dotdStandings = signal<ChampionshipStandingsData | null>(null);
  readonly dotdSelectedDriverIds = signal<Set<number>>(new Set());
  readonly dotdCreating = signal(false);
  readonly dotdCreateError = signal<string | null>(null);

  dotdSelectedChampId = 0;
  dotdSelectedChampName = '';
  dotdSelectedRaceId: number | null = null;
  dotdRaceName = '';
  dotdClosesAt = '';

  loadDotdPolls(): void {
    this.dotdLoading.set(true);
    this.dotdApi.getPolls().subscribe({
      next: (list) => this.dotdPolls.set(list),
      error: () => {},
      complete: () => this.dotdLoading.set(false),
    });
  }

  openDotdModal(): void {
    this.dotdModalOpen.set(true);
    this.dotdCreateError.set(null);
    this.dotdSelectedChampId = 0;
    this.dotdSelectedChampName = '';
    this.dotdSelectedRaceId = null;
    this.dotdRaceName = '';
    const defaultClose = new Date(Date.now() + 20 * 60 * 1000);
    const pad = (n: number) => String(n).padStart(2, '0');
    this.dotdClosesAt = `${defaultClose.getFullYear()}-${pad(defaultClose.getMonth() + 1)}-${pad(defaultClose.getDate())}T${pad(defaultClose.getHours())}:${pad(defaultClose.getMinutes())}`;
    this.dotdSelectedDriverIds.set(new Set());
    this.dotdStandings.set(null);

    this.simgridApi.getChampionships().subscribe({
      next: (list) => this.dotdChampionships.set(list),
    });
  }

  onDotdChampionshipChange(): void {
    const champId = +this.dotdSelectedChampId;
    if (!champId) return;
    this.dotdSelectedChampId = champId;
    this.dotdStandings.set(null);
    this.dotdSelectedDriverIds.set(new Set());

    const champ = this.dotdChampionships().find(c => c.id === champId);
    this.dotdSelectedChampName = champ?.name ?? '';

    this.simgridApi.getChampionshipStandings(champId).subscribe({
      next: (data) => this.dotdStandings.set(data),
    });
  }

  onDotdRaceChange(): void {
    const s = this.dotdStandings();
    if (!s) return;
    const race = s.races.find(r => r.id === this.dotdSelectedRaceId);
    this.dotdRaceName = race?.displayName ?? '';
  }

  toggleDotdDriver(simgridDriverId: number): void {
    const current = new Set(this.dotdSelectedDriverIds());
    if (current.has(simgridDriverId)) {
      current.delete(simgridDriverId);
    } else {
      current.add(simgridDriverId);
    }
    this.dotdSelectedDriverIds.set(current);
  }

  isDotdDriverSelected(simgridDriverId: number): boolean {
    return this.dotdSelectedDriverIds().has(simgridDriverId);
  }

  submitDotdPoll(): void {
    this.dotdCreateError.set(null);
    const s = this.dotdStandings();
    if (!this.dotdSelectedChampId) {
      this.dotdCreateError.set('Please select a championship.');
      return;
    }
    if (!this.dotdClosesAt) {
      this.dotdCreateError.set('Please set a closing time.');
      return;
    }

    let candidates: DotdCandidateIn[];
    if (s) {
      const selected = s.entries.filter(e =>
        e.id !== null && this.dotdSelectedDriverIds().has(e.id),
      );
      if (selected.length < 2) {
        this.dotdCreateError.set('Select at least 2 drivers.');
        return;
      }
      candidates = selected.map(e => ({
        simgridDriverId: e.id,
        driverName: e.displayName,
        championshipPosition: e.position ?? undefined,
      }));
    } else {
      this.dotdCreateError.set('Championship standings not loaded.');
      return;
    }

    this.dotdCreating.set(true);
    this.dotdApi
      .createPoll({
        championshipId: +this.dotdSelectedChampId,
        championshipName: this.dotdSelectedChampName,
        raceId: this.dotdSelectedRaceId,
        raceName: this.dotdRaceName || 'Race',
        closesAt: new Date(this.dotdClosesAt).toISOString(),
        candidates,
      })
      .subscribe({
        next: (poll) => {
          this.dotdPolls.update(list => [poll, ...list]);
          this.dotdModalOpen.set(false);
        },
        error: (err) => {
          const detail = err?.error?.detail;
          let msg: string;
          if (Array.isArray(detail)) {
            msg = detail.map((e: { msg: string }) => e.msg).join('; ');
          } else if (typeof detail === 'string') {
            msg = detail;
          } else {
            msg = 'Failed to create poll.';
          }
          this.dotdCreateError.set(msg);
        },
        complete: () => this.dotdCreating.set(false),
      });
  }

  closeDotdPoll(pollId: string): void {
    this.dotdApi.closePoll(pollId).subscribe({
      next: (updated) => this.dotdPolls.update(list => list.map(p => p.id === updated.id ? updated : p)),
    });
  }

  deleteDotdPoll(pollId: string): void {
    this.dotdApi.deletePoll(pollId).subscribe({
      next: () => this.dotdPolls.update(list => list.filter(p => p.id !== pollId)),
    });
  }
}
