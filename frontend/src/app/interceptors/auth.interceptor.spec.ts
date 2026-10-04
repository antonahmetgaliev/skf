import { provideHttpClient, withInterceptors, HttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { API } from '../api';
import { AuthTokensService } from '../services/auth-tokens.service';
import { clearTokens, readTokens, writeTokens } from '../services/token-store';
import { authInterceptor } from './auth.interceptor';

const TOKENS_URL = `${API}/auth/tokens`;
const fresh = (accessToken: string, refreshToken: string) => ({
  accessToken,
  refreshToken,
  expiresIn: 900,
});

function setup(stored?: { accessToken: string; expiresInMs: number }) {
  if (stored) {
    writeTokens({
      accessToken: stored.accessToken,
      refreshToken: 'refresh-1',
      expiresAt: Date.now() + stored.expiresInMs,
    });
  }
  TestBed.configureTestingModule({
    providers: [provideHttpClient(withInterceptors([authInterceptor])), provideHttpClientTesting()],
  });
  return {
    http: TestBed.inject(HttpClient),
    backend: TestBed.inject(HttpTestingController),
    tokens: TestBed.inject(AuthTokensService),
  };
}

describe('authInterceptor', () => {
  afterEach(() => {
    TestBed.inject(HttpTestingController).verify();
    clearTokens();
  });

  it('leaves the requests of an anonymous visitor alone', () => {
    const { http, backend } = setup();
    http.get(`${API}/drivers`).subscribe();
    const req = backend.expectOne(`${API}/drivers`);
    expect(req.request.headers.has('Authorization')).toBe(false);
    req.flush([]);
  });

  it('sends the stored access token', () => {
    const { http, backend } = setup({ accessToken: 'access-1', expiresInMs: 600_000 });
    http.get(`${API}/me`).subscribe();
    const req = backend.expectOne(`${API}/me`);
    expect(req.request.headers.get('Authorization')).toBe('Bearer access-1');
    req.flush({});
  });

  it('replaces an expired token before sending, with one refresh for parallel requests', () => {
    const { http, backend } = setup({ accessToken: 'access-1', expiresInMs: -1 });
    http.get(`${API}/me`).subscribe();
    http.get(`${API}/drivers`).subscribe();

    const refresh = backend.expectOne(TOKENS_URL);
    expect(refresh.request.body).toEqual({ refreshToken: 'refresh-1' });
    expect(refresh.request.headers.has('Authorization')).toBe(false);
    refresh.flush(fresh('access-2', 'refresh-2'));

    for (const url of [`${API}/me`, `${API}/drivers`]) {
      const req = backend.expectOne(url);
      expect(req.request.headers.get('Authorization')).toBe('Bearer access-2');
      req.flush({});
    }
    expect(readTokens()?.refreshToken).toBe('refresh-2');
  });

  it('refreshes once and repeats a request the server refused', () => {
    const { http, backend } = setup({ accessToken: 'access-1', expiresInMs: 600_000 });
    let body: unknown;
    http.get(`${API}/me`).subscribe((res) => (body = res));

    backend.expectOne(`${API}/me`).flush(null, { status: 401, statusText: 'Unauthorized' });
    backend.expectOne(TOKENS_URL).flush(fresh('access-2', 'refresh-2'));
    const retry = backend.expectOne(`${API}/me`);
    expect(retry.request.headers.get('Authorization')).toBe('Bearer access-2');
    retry.flush({ id: '1' });
    expect(body).toEqual({ id: '1' });
  });

  it('uses the token another tab already fetched instead of refreshing again', () => {
    const { http, backend } = setup({ accessToken: 'access-1', expiresInMs: 600_000 });
    http.get(`${API}/me`).subscribe();
    const first = backend.expectOne(`${API}/me`);
    writeTokens({
      accessToken: 'access-2',
      refreshToken: 'refresh-2',
      expiresAt: Date.now() + 600_000,
    });
    first.flush(null, { status: 401, statusText: 'Unauthorized' });

    const retry = backend.expectOne(`${API}/me`);
    expect(retry.request.headers.get('Authorization')).toBe('Bearer access-2');
    retry.flush({});
  });

  it('ends the login when the refresh token is refused, and fails the request with its 401', () => {
    const { http, backend, tokens } = setup({ accessToken: 'access-1', expiresInMs: 600_000 });
    let status = 0;
    http.get(`${API}/me`).subscribe({ error: (err) => (status = err.status) });

    backend.expectOne(`${API}/me`).flush(null, { status: 401, statusText: 'Unauthorized' });
    backend.expectOne(TOKENS_URL).flush(null, { status: 401, statusText: 'Unauthorized' });

    expect(status).toBe(401);
    expect(readTokens()).toBeNull();
    expect(tokens.active()).toBe(false);
  });

  it('keeps the login when the refresh could not reach the server', () => {
    const { http, backend, tokens } = setup({ accessToken: 'access-1', expiresInMs: -1 });
    let status = 0;
    http.get(`${API}/me`).subscribe({ error: (err) => (status = err.status) });

    backend.expectOne(TOKENS_URL).flush(null, { status: 502, statusText: 'Bad Gateway' });

    expect(status).toBe(502);
    expect(tokens.active()).toBe(true);
  });
});
