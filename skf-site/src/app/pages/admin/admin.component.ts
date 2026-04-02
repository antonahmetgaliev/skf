import { DatePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { BtnComponent } from '../../components/btn/btn.component';
import { CardComponent } from '../../components/card/card.component';
import { PageIntroComponent } from '../../components/page-intro/page-intro.component';
import { PageLayoutComponent } from '../../components/page-layout/page-layout.component';
import { SpinnerComponent } from '../../components/spinner/spinner.component';
import { TabsComponent } from '../../components/tabs/tabs.component';
import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService, AuthUser } from '../../services/auth.service';

@Component({
  selector: 'app-admin',
  imports: [FormsModule, DatePipe, BtnComponent, CardComponent, PageIntroComponent, PageLayoutComponent, SpinnerComponent, TabsComponent],
  templateUrl: './admin.component.html',
  styleUrl: './admin.component.scss',
})
export class AdminComponent implements OnInit {
  readonly auth = inject(AuthService);
  private readonly http = inject(HttpClient);

  readonly activeTab = signal<'users' | 'site'>('users');
  readonly users = signal<AuthUser[]>([]);
  readonly filter = signal('');
  readonly loading = signal(false);
  readonly clearingCache = signal(false);
  readonly cacheMessage = signal('');

  ngOnInit(): void {
    this.loadUsers();
  }

  setActiveTab(tab: 'users' | 'site'): void {
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

  changeRole(user: AuthUser, newRole: string): void {
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
    if (target.role === 'super_admin' && me.role !== 'super_admin') return false;
    return true;
  }

  availableRoles(): string[] {
    if (this.auth.isSuperAdmin()) {
      return ['driver', 'racing_judge', 'admin', 'super_admin'];
    }
    return ['driver', 'racing_judge', 'admin'];
  }

  // -- Site --

  clearCache(): void {
    if (this.clearingCache()) return;
    this.clearingCache.set(true);
    this.cacheMessage.set('');
    this.http.post('/api/admin/clear-cache', {}).subscribe({
      next: () => {
        this.cacheMessage.set('Cache cleared successfully.');
        this.clearingCache.set(false);
      },
      error: () => {
        this.cacheMessage.set('Failed to clear cache.');
        this.clearingCache.set(false);
      },
    });
  }
}
