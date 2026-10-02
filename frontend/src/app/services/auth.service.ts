import { HttpClient } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { catchError, firstValueFrom, Observable, of } from 'rxjs';
import { API, Schemas } from '../api';

/** Canonical role names. Mirrors backend `ROLE_*` constants in `models/user.py`. */
export const ROLES = {
  DRIVER: 'driver',
  JUDGE: 'racing_judge',
  MODERATOR: 'moderator',
  COMMUNITY_MANAGER: 'community_manager',
  ADMIN: 'admin',
  SUPER_ADMIN: 'super_admin',
} as const;

export type Role = (typeof ROLES)[keyof typeof ROLES];

/**
 * Linear rank for the admin tier — higher = more authority.
 * `moderator` and `racing_judge` are sibling capability roles at the same level
 * as `driver`; admin+ implicitly inherit them via `hasCapability`.
 */
const ROLE_RANK: Record<Role, number> = {
  [ROLES.DRIVER]: 0,
  [ROLES.JUDGE]: 0,
  [ROLES.MODERATOR]: 0,
  [ROLES.COMMUNITY_MANAGER]: 0,
  [ROLES.ADMIN]: 1,
  [ROLES.SUPER_ADMIN]: 2,
};

/** The backend types `role` as a plain string; the UI narrows it to the known roles. */
export type AuthUser = Omit<Schemas['UserOut'], 'role'> & { role: Role };

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);

  readonly user = signal<AuthUser | null>(null);
  /** True once the initial `/me` request has resolved (with a user or as anonymous). */
  readonly loaded = signal(false);
  private loadPromise: Promise<void> | null = null;
  readonly isLoggedIn = computed(() => this.user() !== null);

  /**
   * Super-admins and admins can override the effective role for previewing the site.
   * null = no override (use real role).
   */
  readonly viewAsRole = signal<Role | null>(null);

  /** The role used for all permission checks (respects the viewAs override). */
  readonly effectiveRole = computed<Role | null>(() => {
    const u = this.user();
    if (!u) return null;
    const view = this.viewAsRole();
    // Admins and super-admins may preview as lower roles
    if (view !== null && ROLE_RANK[u.role] >= ROLE_RANK[ROLES.ADMIN]) {
      return view;
    }
    return u.role;
  });

  /** True if the real (server) role is super_admin — never affected by viewAs. */
  readonly isRealSuperAdmin = computed(() => this.user()?.role === ROLES.SUPER_ADMIN);

  /** True if the real (server) role is admin or higher — never affected by viewAs. */
  readonly isRealAdmin = computed(() => {
    const u = this.user();
    return u !== null && ROLE_RANK[u.role] >= ROLE_RANK[ROLES.ADMIN];
  });

  readonly isSuperAdmin = computed(() => this.hasRankAtLeast(ROLES.SUPER_ADMIN));
  readonly isAdmin = computed(() => this.hasRankAtLeast(ROLES.ADMIN));

  /** Moderator capability — admin+ inherit it implicitly. */
  readonly isModerator = computed(() => this.hasCapability(ROLES.MODERATOR));

  /** Racing judge capability — admin+ inherit it implicitly. */
  readonly isJudge = computed(() => this.hasCapability(ROLES.JUDGE));

  /** True when the effective role is community_manager (respects viewAs). */
  readonly isCommunityManager = computed(() => this.effectiveRole() === ROLES.COMMUNITY_MANAGER);

  /** True when the user can access the admin panel (admin+ or community manager). */
  readonly canAccessAdmin = computed(() => this.isAdmin() || this.isCommunityManager());

  /**
   * When an admin previews as community_manager, this holds the community ID they're impersonating.
   * null = no override.
   */
  readonly viewAsCommunityId = signal<string | null>(null);

  /** True when the effective role's rank meets or exceeds `min`. */
  private hasRankAtLeast(min: Role): boolean {
    const r = this.effectiveRole();
    return r !== null && ROLE_RANK[r] >= ROLE_RANK[min];
  }

  /** True when the effective role is `role`, or any admin-tier role that inherits it. */
  private hasCapability(role: Role): boolean {
    const r = this.effectiveRole();
    if (r === null) return false;
    return r === role || ROLE_RANK[r] >= ROLE_RANK[ROLES.ADMIN];
  }

  /**
   * Fetch the current session user. Call once at app startup.
   * `/me` answers 401 for anonymous visitors — that simply means "not logged in".
   */
  loadUser(): Promise<void> {
    this.loadPromise = firstValueFrom(
      this.http.get<AuthUser>(`${API}/me`).pipe(catchError(() => of(null))),
    ).then((user) => {
      this.user.set(user);
      this.loaded.set(true);
    });
    return this.loadPromise;
  }

  /** Resolves once the session user is known; starts loading it if nobody has yet. */
  whenLoaded(): Promise<void> {
    return this.loadPromise ?? this.loadUser();
  }

  /** Redirect the browser to the Discord OAuth flow. */
  login(): void {
    this.http.get<{ url: string }>(`${API}/auth/discord/authorization-url`).subscribe({
      next: (res) => (window.location.href = res.url),
    });
  }

  /** Re-fetch and store the user's Discord server nickname. */
  refreshDiscordNickname(): Observable<AuthUser> {
    return this.http.post<AuthUser>(`${API}/me/discord-syncs`, null);
  }

  /** End the current session. */
  logout(): void {
    this.http.delete(`${API}/auth/session`).subscribe({
      next: () => this.user.set(null),
      error: () => this.user.set(null),
    });
  }
}
