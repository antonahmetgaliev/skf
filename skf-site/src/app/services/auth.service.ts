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

  /**
   * Super-admins can override the effective role for previewing the site.
   * null = no override (use real role).
   */
  readonly viewAsRole = signal<string | null>(null);

  /** The role used for all permission checks (respects the viewAs override). */
  readonly effectiveRole = computed(() => {
    const u = this.user();
    if (!u) return null;
    // Only super-admins may override
    if (u.role === 'super_admin' && this.viewAsRole() !== null) {
      return this.viewAsRole();
    }
    return u.role;
  });

  /** True if the real (server) role is super_admin — never affected by viewAs. */
  readonly isRealSuperAdmin = computed(() => {
    const u = this.user();
    return u !== null && u.role === 'super_admin';
  });

  readonly isAdmin = computed(() => {
    const role = this.effectiveRole();
    return role === 'admin' || role === 'super_admin';
  });

  readonly isSuperAdmin = computed(() => {
    return this.effectiveRole() === 'super_admin';
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
