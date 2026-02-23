import { HttpClient } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';

export interface AuthUser {
  id: string;
  discordId: string;
  username: string;
  displayName: string;
  avatarUrl: string | null;
  role: string;
  blocked: boolean;
  createdAt: string;
  lastLoginAt: string | null;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);

  readonly user = signal<AuthUser | null>(null);
  readonly isLoggedIn = computed(() => this.user() !== null);
  readonly isAdmin = computed(() => {
    const u = this.user();
    return u !== null && (u.role === 'admin' || u.role === 'super_admin');
  });
  readonly isSuperAdmin = computed(() => {
    const u = this.user();
    return u !== null && u.role === 'super_admin';
  });

  /** Fetch the current session user. Call once at app startup. */
  loadUser(): void {
    this.http.get<AuthUser>('/api/auth/me').subscribe({
      next: (user) => this.user.set(user),
      error: () => this.user.set(null),
    });
  }

  /** Redirect the browser to the Discord OAuth flow. */
  login(): void {
    this.http.get<{ url: string }>('/api/auth/discord').subscribe({
      next: (res) => (window.location.href = res.url),
    });
  }

  /** End the current session. */
  logout(): void {
    this.http.post('/api/auth/logout', null).subscribe({
      next: () => this.user.set(null),
      error: () => this.user.set(null),
    });
  }
}
