import { DatePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService, AuthUser } from '../../services/auth.service';

@Component({
  selector: 'app-admin-users',
  imports: [FormsModule, DatePipe],
  templateUrl: './admin-users.component.html',
  styleUrl: './admin-users.component.scss',
})
export class AdminUsersComponent implements OnInit {
  readonly auth = inject(AuthService);
  private readonly http = inject(HttpClient);

  readonly users = signal<AuthUser[]>([]);
  readonly filter = signal('');
  readonly loading = signal(false);

  ngOnInit(): void {
    this.loadUsers();
  }

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

  /** Prevent admins from editing super_admins in the UI. */
  canEdit(target: AuthUser): boolean {
    const me = this.auth.user();
    if (!me) return false;
    if (target.role === 'super_admin' && me.role !== 'super_admin') return false;
    return true;
  }

  /** Only super-admin can see the super_admin option in the role dropdown. */
  availableRoles(): string[] {
    if (this.auth.isSuperAdmin()) {
      return ['driver', 'admin', 'super_admin'];
    }
    return ['driver', 'admin'];
  }
}
