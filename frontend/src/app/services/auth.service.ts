import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { computed, effect, inject, Injectable, signal, untracked } from '@angular/core';
import { catchError, firstValueFrom, Observable, of, throwError } from 'rxjs';
import { API, Schemas } from '../api';
import { AuthTokensService } from './auth-tokens.service';

export type Role = Schemas['UserRole'];

/** Names for the roles the API knows. */
export const ROLES = {
  DRIVER: 'driver',
  JUDGE: 'racing_judge',
  MODERATOR: 'moderator',
  COMMUNITY_MANAGER: 'community_manager',
  ADMIN: 'admin',
  SUPER_ADMIN: 'super_admin',
} as const satisfies Record<string, Role>;

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

export type AuthUser = Schemas['UserOut'];

const RETURN_URL_KEY = 'skf.returnUrl';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly tokens = inject(AuthTokensService);

  readonly user = signal<AuthUser | null>(null);
  /** True once it is known who the visitor is (a user or anonymous). */
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

  /** Racing judge capability — admin+ inherit it implicitly. */
  readonly isJudge = computed(() => this.hasCapability(ROLES.JUDGE));

  /** True when the effective role is community_manager (respects viewAs). */
  readonly isCommunityManager = computed(() => this.effectiveRole() === ROLES.COMMUNITY_MANAGER);

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

  constructor() {
    // The login can end underneath us: a refused refresh, or sign-out in another tab.
    effect(() => {
      if (!this.tokens.active()) untracked(() => this.clearUser());
    });
  }

  /**
   * Find out who the visitor is. Without a stored login that is "nobody",
   * and no request is made.
   */
  loadUser(): Promise<void> {
    const request = this.tokens.active()
      ? this.http.get<AuthUser>(`${API}/me`).pipe(
          // 401: the login is over. Anything else (5xx, offline) leaves the
          // stored login alone, so a reload can try again.
          catchError((err: HttpErrorResponse) =>
            err.status === 401 ? of(null) : throwError(() => err),
          ),
        )
      : of(null);
    this.loadPromise = firstValueFrom(request)
      .catch(() => null)
      .then((user) => {
        this.user.set(user);
        this.loaded.set(true);
      });
    return this.loadPromise;
  }

  /** Resolves once the visitor is known; starts loading if nobody has yet. */
  whenLoaded(): Promise<void> {
    return this.loadPromise ?? this.loadUser();
  }

  /** Send the browser through the Discord OAuth flow, then back to the current page. */
  login(): void {
    try {
      sessionStorage.setItem(RETURN_URL_KEY, location.pathname + location.search);
    } catch {
      // Without it the visitor lands on the home page.
    }
    this.http.get<Schemas['AuthUrlOut']>(`${API}/auth/discord/authorization-url`).subscribe({
      next: (res) => (window.location.href = res.url),
    });
  }

  /**
   * Finish the OAuth flow with the refresh token from the callback.
   * Resolves to whether the visitor is now signed in.
   */
  async completeLogin(refreshToken: string): Promise<boolean> {
    const token = await firstValueFrom(this.tokens.begin(refreshToken)).catch(() => null);
    if (!token) return false;
    await this.loadUser();
    return this.user() !== null;
  }

  /** The page the visitor was on when they chose to sign in; read once. */
  takeReturnUrl(): string {
    try {
      const url = sessionStorage.getItem(RETURN_URL_KEY);
      sessionStorage.removeItem(RETURN_URL_KEY);
      // Only in-app paths: never follow a stored absolute URL.
      return url && url.startsWith('/') && !url.startsWith('//') ? url : '/';
    } catch {
      return '/';
    }
  }

  /** Re-fetch and store the user's Discord server nickname. */
  refreshDiscordNickname(): Observable<AuthUser> {
    return this.http.post<AuthUser>(`${API}/me/discord-syncs`, null);
  }

  logout(): void {
    this.tokens.end();
    this.clearUser();
  }

  private clearUser(): void {
    this.user.set(null);
    this.viewAsRole.set(null);
    this.viewAsCommunityId.set(null);
  }
}
