import { HttpClient } from '@angular/common/http';
import { TranslocoPipe } from '@jsverse/transloco';
import { BtnComponent } from '../../components/btn/btn.component';
import { FormFieldComponent } from '../../components/form-field/form-field.component';
import { CardComponent } from '../../components/card/card.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { TabsComponent } from '../../components/tabs/tabs.component';
import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { InputDirective } from '../../directives/input.directive';
import { API, Schemas } from '../../api';
import { AuthService, AuthUser, ROLES, Role } from '../../services/auth.service';
import { BwpApiService, Driver } from '../../services/bwp-api.service';
import { CalendarApiService, Community } from '../../services/calendar-api.service';
import { DriverAdminApiService } from '../../services/driver-admin-api.service';
import { AdminCalendarTabComponent } from './admin-calendar-tab/admin-calendar-tab.component';
import { AdminDriversTabComponent } from './admin-drivers-tab/admin-drivers-tab.component';
import { AdminGiveawayTabComponent } from './admin-giveaway-tab/admin-giveaway-tab.component';
import { AdminRaceResultsTabComponent } from './admin-race-results-tab/admin-race-results-tab.component';
import { AdminRegulationsTabComponent } from './admin-regulations-tab/admin-regulations-tab.component';
import { AdminTranslationsTabComponent } from './admin-translations-tab/admin-translations-tab.component';
import { UserItemComponent } from './user-item/user-item.component';

type AdminTab =
  | 'users'
  | 'drivers'
  | 'site'
  | 'calendar'
  | 'translations'
  | 'regulations'
  | 'raceResults'
  | 'giveaway';

@Component({
  selector: 'app-admin',
  imports: [
    FormsModule,
    TranslocoPipe,
    InputDirective,
    AdminCalendarTabComponent,
    AdminDriversTabComponent,
    AdminGiveawayTabComponent,
    AdminRaceResultsTabComponent,
    AdminRegulationsTabComponent,
    AdminTranslationsTabComponent,
    BtnComponent,
    CardComponent,
    FormFieldComponent,
    PageIntroComponent,
    PageLayoutComponent,
    SpinnerComponent,
    TabsComponent,
    UserItemComponent,
  ],
  templateUrl: './admin.component.html',
  styleUrl: './admin.component.scss',
})
export class AdminComponent implements OnInit {
  readonly auth = inject(AuthService);
  private readonly http = inject(HttpClient);
  private readonly calendarApi = inject(CalendarApiService);
  private readonly bwpApi = inject(BwpApiService);
  private readonly driverAdminApi = inject(DriverAdminApiService);

  readonly activeTab = signal<AdminTab>('users');
  readonly users = signal<AuthUser[]>([]);
  readonly filter = signal('');
  readonly loading = signal(false);
  readonly clearingCache = signal(false);
  readonly cacheMessage = signal('');

  readonly allCommunities = signal<Community[]>([]);
  readonly allDrivers = signal<Driver[]>([]);
  readonly userError = signal('');
  readonly editingUserIds = signal(new Set<string>());

  ngOnInit(): void {
    this.loadUsers();
    this.loadAllCommunities();
    this.loadDrivers();
  }

  /** Users and drivers, after the drivers tab changed who is linked to whom. */
  reloadPeople(): void {
    this.loadUsers();
    this.loadDrivers();
  }

  private loadDrivers(): void {
    this.bwpApi.getDrivers().subscribe({ next: (drivers) => this.allDrivers.set(drivers) });
  }

  private loadAllCommunities(): void {
    this.calendarApi.getCommunitiesAdmin().subscribe({
      next: (data) => this.allCommunities.set(data),
    });
  }

  setActiveTab(tab: AdminTab): void {
    this.activeTab.set(tab);
  }

  // -- Users --

  loadUsers(): void {
    this.loading.set(true);
    this.http.get<AuthUser[]>(`${API}/users`, { params: { limit: 1000 } }).subscribe({
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
        u.discordId.includes(q),
    );
  }

  changeRole(user: AuthUser, newRole: Role): void {
    this.http.patch<AuthUser>(`${API}/users/${user.id}`, { role: newRole }).subscribe({
      next: (updated) => {
        this.users.update((list) => list.map((u) => (u.id === updated.id ? updated : u)));
        this.exitEdit(user.id);
      },
    });
  }

  isEditing(user: AuthUser): boolean {
    return this.editingUserIds().has(user.id);
  }

  toggleEdit(user: AuthUser): void {
    this.editingUserIds.update((set) => {
      const next = new Set(set);
      if (next.has(user.id)) next.delete(user.id);
      else next.add(user.id);
      return next;
    });
  }

  private exitEdit(userId: string): void {
    this.editingUserIds.update((set) => {
      if (!set.has(userId)) return set;
      const next = new Set(set);
      next.delete(userId);
      return next;
    });
  }

  toggleBlock(user: AuthUser): void {
    this.http.patch<AuthUser>(`${API}/users/${user.id}`, { blocked: !user.blocked }).subscribe({
      next: (updated) => {
        this.users.update((list) => list.map((u) => (u.id === updated.id ? updated : u)));
      },
    });
  }

  /** Link the account to a driver by hand; an empty id unlinks it. */
  linkDriver(user: AuthUser, driverId: string): void {
    this.userError.set('');
    const replace = (updated: AuthUser) =>
      this.users.update((list) => list.map((u) => (u.id === updated.id ? updated : u)));
    const fail = (err: { error?: { detail?: string } }) =>
      this.userError.set(err?.error?.detail ?? 'Failed to update the driver link.');

    if (driverId) {
      this.driverAdminApi
        .setUserDriver(user.id, driverId)
        .subscribe({ next: replace, error: fail });
    } else {
      this.driverAdminApi.clearUserDriver(user.id).subscribe({
        next: () => replace({ ...user, driverId: null, driverLinkSource: 'admin' }),
        error: fail,
      });
    }
  }

  forceLogout(user: AuthUser): void {
    this.http.delete(`${API}/users/${user.id}/tokens`).subscribe();
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
      return [ROLES.DRIVER, ROLES.JUDGE, ROLES.COMMUNITY_MANAGER, ROLES.ADMIN, ROLES.SUPER_ADMIN];
    }
    return [ROLES.DRIVER, ROLES.JUDGE, ROLES.COMMUNITY_MANAGER, ROLES.ADMIN];
  }

  assignCommunity(user: AuthUser, communityId: string): void {
    const ids = communityId ? [communityId] : [];
    this.http
      .put<Schemas['ManagedCommunitiesOut']>(`${API}/users/${user.id}/managed-communities`, {
        communityIds: ids,
      })
      .subscribe({
        next: ({ communityIds }) => {
          this.users.update((list) =>
            list.map((u) => (u.id === user.id ? { ...u, managedCommunityIds: communityIds } : u)),
          );
          this.exitEdit(user.id);
        },
      });
  }

  // -- Site --

  clearCache(domain?: string): void {
    if (this.clearingCache()) return;
    this.clearingCache.set(true);
    this.cacheMessage.set('');
    this.http.delete(domain ? `${API}/caches/${domain}` : `${API}/caches`).subscribe({
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
}
