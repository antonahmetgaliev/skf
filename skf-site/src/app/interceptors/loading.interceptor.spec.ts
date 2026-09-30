import { HttpRequest } from '@angular/common/http';
import { runInInjectionContext, Injector } from '@angular/core';
import { throwError, of, EMPTY } from 'rxjs';
import { loadingInterceptor } from './loading.interceptor';
import { LoadingService } from '../services/loading.service';

function run(url: string, handler: () => any, loading: LoadingService, method = 'GET') {
  const injector = Injector.create({
    providers: [{ provide: LoadingService, useValue: loading }],
  });
  const req =
    method === 'GET' ? new HttpRequest('GET', url) : new HttpRequest(method as 'PATCH', url, {});
  return runInInjectionContext(injector, () => loadingInterceptor(req, handler as any));
}

describe('loadingInterceptor', () => {
  let loading: LoadingService;

  beforeEach(() => {
    loading = new LoadingService();
  });

  it('is loading while the request is in flight', () => {
    let wasLoading = false;
    const result = run(
      '/api/v1/incident-windows',
      () => {
        wasLoading = loading.loading();
        return of({} as any);
      },
      loading,
    );

    result.subscribe();
    expect(wasLoading).toBe(true);
  });

  it('clears loading once the request completes', () => {
    run('/api/v1/incident-windows', () => of({} as any), loading).subscribe();
    expect(loading.loading()).toBe(false);
  });

  it('clears loading when the request errors', () => {
    run('/api/v1/incident-windows', () => throwError(() => new Error('boom')), loading).subscribe({
      error: () => {},
    });
    expect(loading.loading()).toBe(false);
  });

  it('clears loading when the request is cancelled', () => {
    const sub = run('/api/v1/incident-windows', () => EMPTY, loading).subscribe();
    sub.unsubscribe();
    expect(loading.loading()).toBe(false);
  });

  it('ignores translation bundle loads', () => {
    let wasLoading = true;
    run(
      '/api/v1/languages/ua/translations',
      () => {
        wasLoading = loading.loading();
        return of({} as any);
      },
      loading,
    ).subscribe();
    expect(wasLoading).toBe(false);
  });

  it('still tracks admin translation edits', () => {
    let wasLoading = false;
    run(
      '/api/v1/languages/ua/translations',
      () => {
        wasLoading = loading.loading();
        return of({} as any);
      },
      loading,
      'PATCH',
    ).subscribe();
    expect(wasLoading).toBe(true);
  });
});
