import { DatePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { BtnComponent } from '../../components/btn/btn.component';
import { FormFieldComponent } from '../../components/form-field/form-field.component';
import { CardComponent } from '../../components/card/card.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { TabsComponent } from '../../components/tabs/tabs.component';
import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService, AuthUser, ROLES, Role } from '../../services/auth.service';
import {
  CalendarApiService,
  Community,
  CommunityCreate,
  CustomChampionshipCreate,
  CustomChampionshipOut,
  CustomRaceCreate,
  Game,
  GameCreate,
} from '../../services/calendar-api.service';

type AdminTab = 'users' | 'site' | 'communities';

@Component({
  selector: 'app-admin',
  imports: [FormsModule, DatePipe, BtnComponent, CardComponent, FormFieldComponent, PageIntroComponent, PageLayoutComponent, SpinnerComponent, TabsComponent],
  templateUrl: './admin.component.html',
  styleUrl: './admin.component.scss',
})
export class AdminComponent implements OnInit {
  readonly auth = inject(AuthService);
  private readonly http = inject(HttpClient);
  private readonly calendarApi = inject(CalendarApiService);

  readonly activeTab = signal<AdminTab>('users');
  readonly users = signal<AuthUser[]>([]);
  readonly filter = signal('');
  readonly loading = signal(false);
  readonly clearingCache = signal(false);
  readonly cacheMessage = signal('');

  // Communities tab
  readonly communities = signal<Community[]>([]);
  readonly games = signal<Game[]>([]);
  readonly communitiesLoading = signal(false);
  readonly selectedCommunity = signal<Community | null>(null);
  readonly communityChampionships = signal<CustomChampionshipOut[]>([]);
  readonly champsLoading = signal(false);

  // Community form
  readonly communityForm = signal<CommunityCreate>({ name: '', color: '#f5bf24', discordUrl: null });
  readonly editingCommunityId = signal<string | null>(null);

  // Game form
  readonly newGameName = signal('');

  // Championship form
  readonly champForm = signal<{ name: string; game: string; gameId: string | null; carClass: string | null; description: string | null }>({
    name: '', game: '', gameId: null, carClass: null, description: null,
  });
  readonly editingChampId = signal<string | null>(null);

  // Race form
  readonly raceForm = signal<{ track: string | null; date: string | null }>({ track: null, date: null });

  // Form field updaters (avoids inline lambdas in template that cause strict typing issues)
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
    this.loadUsers();
  }

  setActiveTab(tab: AdminTab): void {
    this.activeTab.set(tab);
    if (tab === 'communities' && this.communities().length === 0) {
      this.loadCommunities();
      this.loadGames();
    }
  }

  // -- Users --

  loadUsers(): void {
    this.loading.set(true);
    this.http.get<AuthUser[]>('/api/users').subscribe({
      next: (users) => {
        this.users.set(users);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  filteredUsers(): AuthUser[] {
    const q = this.filter().toLowerCase();
    if (!q) return this.users();
    return this.users().filter(
      (u) =>
        u.displayName.toLowerCase().includes(q) ||
        u.username.toLowerCase().includes(q) ||
        u.discordId.includes(q)
    );
  }

  changeRole(user: AuthUser, newRole: Role): void {
    this.http
      .patch<AuthUser>(`/api/users/${user.id}`, { role: newRole })
      .subscribe({
        next: (updated) => {
          this.users.update((list) =>
            list.map((u) => (u.id === updated.id ? updated : u))
          );
        },
      });
  }

  toggleBlock(user: AuthUser): void {
    this.http
      .patch<AuthUser>(`/api/users/${user.id}`, { blocked: !user.blocked })
      .subscribe({
        next: (updated) => {
          this.users.update((list) =>
            list.map((u) => (u.id === updated.id ? updated : u))
          );
        },
      });
  }

  forceLogout(user: AuthUser): void {
    this.http.delete(`/api/users/${user.id}/sessions`).subscribe({
      next: () => {},
    });
  }

  canEdit(target: AuthUser): boolean {
    const me = this.auth.user();
    if (!me) return false;
    if (target.role === ROLES.SUPER_ADMIN && me.role !== ROLES.SUPER_ADMIN) return false;
    if (target.role === ROLES.ADMIN && me.role !== ROLES.SUPER_ADMIN) return false;
    return true;
  }

  availableRoles(): Role[] {
    if (this.auth.isSuperAdmin()) {
      return [ROLES.DRIVER, ROLES.JUDGE, ROLES.ADMIN, ROLES.SUPER_ADMIN];
    }
    return [ROLES.DRIVER, ROLES.JUDGE, ROLES.ADMIN];
  }

  // -- Site --

  clearCache(domain?: string): void {
    if (this.clearingCache()) return;
    this.clearingCache.set(true);
    this.cacheMessage.set('');
    const params = domain ? { params: { domain } } : {};
    this.http.post('/api/admin/clear-cache', {}, params).subscribe({
      next: () => {
        const label = domain ?? 'All';
        this.cacheMessage.set(`${label} cache cleared.`);
        this.clearingCache.set(false);
      },
      error: () => {
        this.cacheMessage.set('Failed to clear cache.');
        this.clearingCache.set(false);
      },
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

  loadGames(): void {
    this.calendarApi.getGames().subscribe({
      next: (data) => this.games.set(data),
    });
  }

  // Game CRUD

  addGame(): void {
    const name = this.newGameName().trim();
    if (!name) return;
    this.calendarApi.createGame({ name }).subscribe({
      next: (game) => {
        this.games.update((list) => [...list, game].sort((a, b) => a.name.localeCompare(b.name)));
        this.newGameName.set('');
      },
    });
  }

  deleteGame(game: Game): void {
    this.calendarApi.deleteGame(game.id).subscribe({
      next: () => this.games.update((list) => list.filter((g) => g.id !== game.id)),
    });
  }

  // Community CRUD

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

  // Championship CRUD (per community)

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

  onGameSelect(gameId: string): void {
    const game = this.games().find((g) => g.id === gameId);
    this.champForm.update((f) => ({ ...f, gameId: gameId || null, game: game?.name ?? '' }));
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

  // Race CRUD

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
