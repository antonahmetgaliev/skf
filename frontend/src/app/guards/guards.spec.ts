import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { EnvironmentInjector, runInInjectionContext } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import {
  ActivatedRouteSnapshot,
  CanActivateFn,
  provideRouter,
  RouterStateSnapshot,
  UrlTree,
} from '@angular/router';
import { API } from '../api';
import { AuthService } from '../services/auth.service';
import { clearTokens, writeTokens } from '../services/token-store';
import { adminGuard } from './admin.guard';

/** `signedIn` puts a login in storage; without one the user is never requested. */
function setup(signedIn = true) {
  if (signedIn) {
    writeTokens({ accessToken: 'a', refreshToken: 'r', expiresAt: Date.now() + 600_000 });
  }
  TestBed.configureTestingModule({
    providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
  });
  return {
    auth: TestBed.inject(AuthService),
    http: TestBed.inject(HttpTestingController),
  };
}

function run(guard: CanActivateFn) {
  return runInInjectionContext(TestBed.inject(EnvironmentInjector), () =>
    guard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot),
  ) as Promise<boolean | UrlTree>;
}

const user = (role: string) => ({ id: '1', role, managedCommunityIds: [] });

describe.each([['adminGuard', adminGuard, 'admin']])('%s', (_name, guard, allowedRole) => {
  afterEach(() => {
    TestBed.inject(HttpTestingController).verify();
    clearTokens();
  });

  it('waits for the pending /me request before allowing access (hard refresh)', async () => {
    const { auth, http } = setup();
    auth.loadUser();
    const result = run(guard);
    http.expectOne(`${API}/me`).flush(user(allowedRole));
    expect(await result).toBe(true);
  });

  it('redirects visitors without a login to / without asking the server', async () => {
    const { auth } = setup(false);
    expect(String(await run(guard))).toBe('/');
    expect(auth.loaded()).toBe(true);
  });

  it('keeps an admin previewing the site as a lower role', async () => {
    const { auth, http } = setup();
    auth.loadUser();
    http.expectOne(`${API}/me`).flush(user(allowedRole));
    await auth.whenLoaded();
    auth.viewAsRole.set('driver');
    expect(await run(guard)).toBe(true);
  });

  it('redirects to / once /me answers 401', async () => {
    const { auth, http } = setup();
    auth.loadUser();
    const result = run(guard);
    http.expectOne(`${API}/me`).flush(null, { status: 401, statusText: 'Unauthorized' });
    const tree = await result;
    expect(tree).toBeInstanceOf(UrlTree);
    expect(String(tree)).toBe('/');
  });

  it('redirects logged-in users without the role', async () => {
    const { auth, http } = setup();
    auth.loadUser();
    const result = run(guard);
    http.expectOne(`${API}/me`).flush(user('driver'));
    expect(String(await result)).toBe('/');
  });

  it('starts loading the user itself if nobody has yet, without a duplicate request', async () => {
    const { auth, http } = setup();
    const result = run(guard);
    auth.whenLoaded();
    http.expectOne(`${API}/me`).flush(user(allowedRole));
    expect(await result).toBe(true);
    expect(auth.loaded()).toBe(true);
  });

  it('decides immediately from cached state once loaded', async () => {
    const { auth, http } = setup();
    auth.loadUser();
    http.expectOne(`${API}/me`).flush(user(allowedRole));
    await auth.whenLoaded();
    expect(await run(guard)).toBe(true);
    auth.user.set(null);
    expect(String(await run(guard))).toBe('/');
  });
});
