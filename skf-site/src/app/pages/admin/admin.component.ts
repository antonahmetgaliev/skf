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
import { AdminCalendarTabComponent } from './admin-calendar-tab/admin-calendar-tab.component';

type AdminTab = 'users' | 'site' | 'calendar';

@Component({
  selector: 'app-admin',
  imports: [FormsModule, DatePipe, AdminCalendarTabComponent, BtnComponent, CardComponent, FormFieldComponent, PageIntroComponent, PageLayoutComponent, SpinnerComponent, TabsComponent],
  templateUrl: './admin.component.html',
  styleUrl: './admin.component.scss',
})
export class AdminComponent implements OnInit {
  readonly auth = inject(AuthService);
  private readonly http = inject(HttpClient);

  readonly activeTab = signal<AdminTab>('users');
  readonly users = signal<AuthUser[]>([]);
  readonly filter = signal('');
  readonly loading = signal(false);
  readonly clearingCache = signal(false);
  readonly cacheMessage = signal('');

  ngOnInit(): void {
    this.loadUsers();
  }

  setActiveTab(tab: AdminTab): void {
    this.activeTab.set(tab);
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
}
