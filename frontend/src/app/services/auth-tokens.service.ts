import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { catchError, finalize, map, Observable, of, shareReplay, throwError } from 'rxjs';
import { API, Schemas } from '../api';
import { clearTokens, readTokens, StoredTokens, TOKENS_KEY, writeTokens } from './token-store';

/** Refresh this long before the access token expires, so a request never leaves with a dying one. */
const EXPIRY_MARGIN_MS = 30_000;

/**
 * The tokens of the current login: hands out a valid access token and replaces
 * the pair when it runs out. Storage is shared between tabs, so every read goes
 * to it rather than to a copy in memory.
 */
@Injectable({ providedIn: 'root' })
export class AuthTokensService {
  private readonly http = inject(HttpClient);

  /** Whether this browser holds a login. Turns false when the login ends, here or in another tab. */
  readonly active = signal(readTokens() !== null);

  private refreshing: Observable<string | null> | null = null;

  constructor() {
    if (typeof window !== 'undefined') {
      window.addEventListener('storage', (event) => {
        if (event.key === TOKENS_KEY) this.active.set(readTokens() !== null);
      });
    }
  }

  /** A usable access token, refreshed first if needed; `null` when nobody is signed in. */
  accessToken(): Observable<string | null> {
    const tokens = readTokens();
    if (!tokens) return of(null);
    if (tokens.expiresAt - EXPIRY_MARGIN_MS > Date.now()) return of(tokens.accessToken);
    return this.refresh();
  }

  /**
   * Replace the token pair. Concurrent callers share one request.
   * Emits `null` when the login is over; errors when the server could not be asked.
   *
   * `rejected` is the access token the server just refused: if another tab has
   * replaced it meanwhile, its token is used instead of refreshing again.
   */
  refresh(rejected?: string): Observable<string | null> {
    const tokens = readTokens();
    if (!tokens) return of(null);
    if (rejected && tokens.accessToken !== rejected) return of(tokens.accessToken);

    this.refreshing ??= this.exchange(tokens.refreshToken).pipe(
      finalize(() => (this.refreshing = null)),
      shareReplay(1),
    );
    return this.refreshing;
  }

  /** Start a login from the refresh token the OAuth callback handed over. */
  begin(refreshToken: string): Observable<string | null> {
    return this.exchange(refreshToken);
  }

  /** End the login on the server and forget it here. */
  end(): void {
    const tokens = readTokens();
    this.forget();
    if (tokens) {
      this.http
        .post(`${API}/auth/token-revocations`, { refreshToken: tokens.refreshToken })
        .subscribe({ error: () => undefined });
    }
  }

  private exchange(refreshToken: string): Observable<string | null> {
    return this.http.post<Schemas['TokenOut']>(`${API}/auth/tokens`, { refreshToken }).pipe(
      map((res) => {
        this.store({
          accessToken: res.accessToken,
          refreshToken: res.refreshToken,
          expiresAt: Date.now() + res.expiresIn * 1000,
        });
        return res.accessToken;
      }),
      catchError((err: HttpErrorResponse) => {
        if (err.status !== 401) return throwError(() => err);
        this.forget();
        return of(null);
      }),
    );
  }

  private store(tokens: StoredTokens): void {
    writeTokens(tokens);
    this.active.set(true);
  }

  private forget(): void {
    clearTokens();
    this.active.set(false);
  }
}
