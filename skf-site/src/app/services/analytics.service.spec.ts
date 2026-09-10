import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { AnalyticsService } from './analytics.service';
import { CookieConsentService } from './cookie-consent.service';

@Component({ standalone: true, template: '' })
class BlankComponent {}

const gtagUrl = (): string | undefined =>
  Array.from(document.head.querySelectorAll('script'))
    .map((s) => s.src)
    .find((src) => src.includes('googletagmanager.com'));

/** The gtag calls recorded so far, e.g. ['config', 'G-TEST123', {...}]. */
const gtagCalls = (): unknown[][] =>
  ((window.dataLayer ?? []) as ArrayLike<unknown>[]).map((args) => Array.from(args));

function setup(measurementId: string) {
  window.SKF_ENV = { GA_MEASUREMENT_ID: measurementId };
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        { path: '', component: BlankComponent },
        { path: 'drivers/:id', component: BlankComponent, title: 'Driver Profile' },
      ]),
    ],
  });
  return {
    analytics: TestBed.inject(AnalyticsService),
    consent: TestBed.inject(CookieConsentService),
    router: TestBed.inject(Router),
  };
}

describe('AnalyticsService', () => {
  beforeEach(() => {
    localStorage.clear();
    delete window.dataLayer;
    delete window.gtag;
    document.head.querySelectorAll('script[src*="googletagmanager"]').forEach((s) => s.remove());
  });

  afterEach(() => {
    delete window.SKF_ENV;
  });

  it('does nothing when no measurement ID is configured', () => {
    const { analytics, consent } = setup('');
    analytics.init();
    consent.accept();
    TestBed.tick();
    expect(analytics.available()).toBe(false);
    expect(gtagUrl()).toBeUndefined();
  });

  it('loads nothing before the visitor answers the banner', async () => {
    const { analytics, router } = setup('G-TEST123');
    analytics.init();
    await router.navigateByUrl('/drivers/42');
    TestBed.tick();
    expect(analytics.available()).toBe(true);
    expect(gtagUrl()).toBeUndefined();
  });

  it('loads nothing when the visitor declines', async () => {
    const { analytics, consent, router } = setup('G-TEST123');
    analytics.init();
    consent.decline();
    await router.navigateByUrl('/drivers/42');
    TestBed.tick();
    expect(gtagUrl()).toBeUndefined();
  });

  it('loads gtag.js once the visitor accepts', () => {
    const { analytics, consent } = setup('G-TEST123');
    analytics.init();
    consent.accept();
    TestBed.tick();
    expect(gtagUrl()).toContain('id=G-TEST123');
    expect(gtagCalls()).toContainEqual([
      'config',
      'G-TEST123',
      { send_page_view: false },
    ]);
  });

  it('denies advertising storage', () => {
    const { analytics, consent } = setup('G-TEST123');
    analytics.init();
    consent.accept();
    TestBed.tick();
    const consentCall = gtagCalls().find((c) => c[0] === 'consent');
    expect(consentCall?.[2]).toEqual({
      analytics_storage: 'granted',
      ad_storage: 'denied',
      ad_user_data: 'denied',
      ad_personalization: 'denied',
    });
  });

  it('reports a page_view per navigation, keyed by route pattern', async () => {
    vi.useFakeTimers();
    try {
      const { analytics, consent, router } = setup('G-TEST123');
      analytics.init();
      consent.accept();
      TestBed.tick();
      await router.navigateByUrl('/drivers/42');
      TestBed.tick();
      vi.runAllTimers();

      const pageViews = gtagCalls().filter((c) => c[1] === 'page_view');
      const last = pageViews.at(-1)?.[2] as Record<string, unknown>;
      expect(last['page_path']).toBe('/drivers/42');
      expect(last['page_route']).toBe('/drivers/:id');
      expect(last['page_title']).toBe('Driver Profile');
    } finally {
      vi.useRealTimers();
    }
  });
});
