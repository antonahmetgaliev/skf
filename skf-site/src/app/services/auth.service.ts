import { HttpClient, HttpResponse } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { Observable } from 'rxjs';

export interface AuthUser {
  id: string;
  discordId: string;
  username: string;
  displayName: string;
  guildNickname: string | null;
  avatarUrl: string | null;
  role: string;
  blocked: boolean;
  createdAt: string;
  lastLoginAt: string | null;
  driverId: string | null;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);

  readonly user = signal<AuthUser | null>(null);
  readonly isLoggedIn = computed(() => this.user() !== null);

  /**
   * Super-admins and admins can override the effective role for previewing the site.
   * null = no override (use real role).
   */
  readonly viewAsRole = signal<string | null>(null);

  /** The role used for all permission checks (respects the viewAs override). */
  readonly effectiveRole = computed(() => {
    const u = this.user();
    if (!u) return null;
    // Admins and super-admins may preview as lower roles
    const canPreview = u.role === 'super_admin' || u.role === 'admin';
    if (canPreview && this.viewAsRole() !== null) {
      return this.viewAsRole();
    }
    return u.role;
  });

  /** True if the real (server) role is super_admin — never affected by viewAs. */
  readonly isRealSuperAdmin = computed(() => {
    const u = this.user();
    return u !== null && u.role === 'super_admin';
  });

  /** True if the real (server) role is admin or higher — never affected by viewAs. */
  readonly isRealAdmin = computed(() => {
    const u = this.user();
    return u !== null && (u.role === 'admin' || u.role === 'super_admin');
  });

  readonly isAdmin = computed(() => {
    const role = this.effectiveRole();
    return role === 'admin' || role === 'super_admin';
  });

  readonly isModerator = computed(() => {
    const role = this.effectiveRole();
    return role === 'moderator' || role === 'admin' || role === 'super_admin';
  });

  readonly isSuperAdmin = computed(() => {
    return this.effectiveRole() === 'super_admin';
  });

  readonly isJudge = computed(() => {
    const role = this.effectiveRole();
    return role === 'racing_judge' || role === 'admin' || role === 'super_admin';
  });

  /** Fetch the current session user. Call once at app startup. */
  loadUser(): void {
    this.http.get<AuthUser>('/api/auth/me', { observe: 'response' }).subscribe({
      next: (res: HttpResponse<AuthUser>) => {
        this.user.set(res.status === 204 ? null : res.body);
      },
      error: () => this.user.set(null),
    });
  }

  /** Redirect the browser to the Discord OAuth flow. */
  login(): void {
    this.http.get<{ url: string }>('/api/auth/discord').subscribe({
      next: (res) => (window.location.href = res.url),
    });
  }

  /** Re-fetch and store the user's SKF Racing Hub server nickname. */
  refreshGuildNickname(): Observable<AuthUser> {
    return this.http.post<AuthUser>('/api/auth/refresh-guild-nickname', null);
  }

  /** Manually set the user's racing/guild name. */
  updateGuildNickname(name: string): Observable<AuthUser> {
    return this.http.patch<AuthUser>('/api/auth/guild-nickname', { guildNickname: name });
  }

  /** End the current session. */
  logout(): void {
    this.http.post('/api/auth/logout', null).subscribe({
      next: () => this.user.set(null),
      error: () => this.user.set(null),
    });
  }
}
