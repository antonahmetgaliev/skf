import { DOCUMENT, effect, inject, Injectable, Injector, signal } from '@angular/core';
import { ActivatedRouteSnapshot, NavigationEnd, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { filter } from 'rxjs/operators';
import { env } from '../env';
import { CookieConsentService } from './cookie-consent.service';

type Gtag = (...args: unknown[]) => void;

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: Gtag;
  }
}

/**
 * Google Analytics 4. Nothing is loaded or sent until the visitor accepts the cookie banner:
 * declining means no request to Google is ever made.
 */
@Injectable({ providedIn: 'root' })
export class AnalyticsService {
  private readonly router = inject(Router);
  private readonly document = inject(DOCUMENT);
  private readonly consent = inject(CookieConsentService);
  private readonly injector = inject(Injector);

  private readonly measurementId = env('GA_MEASUREMENT_ID') ?? '';
  private navigations?: Subscription;

  /** True when a measurement ID is configured and analytics may run (so the banner is worth showing). */
  readonly available = signal(false);

  init(): void {
    if (!this.measurementId) {
      return;
    }
    this.available.set(true);
    effect(
      () => {
        if (this.consent.decision() === 'granted') {
          this.start();
        }
      },
      { injector: this.injector }
    );
  }

  /** Sends a custom GA4 event. No-op until analytics has started. */
  event(name: string, params: Record<string, unknown> = {}): void {
    this.document.defaultView?.gtag?.('event', name, params);
  }

  private start(): void {
    if (this.navigations) {
      return;
    }
    this.loadGtag();
    this.navigations = this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => this.trackPageView(e.urlAfterRedirects));
    // Consent may be given part-way through a visit — record the page already on screen.
    this.trackPageView(this.router.url);
  }

  private loadGtag(): void {
    const win = this.document.defaultView;
    if (!win) {
      return;
    }
    win.dataLayer = win.dataLayer || [];
    win.gtag = function gtag() {
      // gtag.js requires the raw `arguments` object, not a copied array.
      win.dataLayer!.push(arguments);
    };
    // Analytics storage only — the site runs no ads and asks for no advertising consent.
    win.gtag('consent', 'default', {
      analytics_storage: 'granted',
      ad_storage: 'denied',
      ad_user_data: 'denied',
      ad_personalization: 'denied',
    });
    win.gtag('js', new Date());
    // Page views are sent manually per navigation, otherwise only the initial load is counted.
    win.gtag('config', this.measurementId, { send_page_view: false });

    const script = this.document.createElement('script');
    script.async = true;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${this.measurementId}`;
    this.document.head.appendChild(script);
  }

  private trackPageView(url: string): void {
    const win = this.document.defaultView;
    if (!win) {
      return;
    }
    const route = this.routePattern();
    // The router sets the document title just after NavigationEnd, so read it on the next tick.
    win.setTimeout(() => {
      win.gtag?.('event', 'page_view', {
        page_path: url,
        page_location: win.location.href,
        page_title: this.document.title,
        page_route: route,
      });
    });
  }

  /**
   * The matched route pattern, e.g. '/drivers/:id' rather than '/drivers/42', so every visit to a
   * page aggregates under one entry instead of one per driver.
   */
  private routePattern(): string {
    const segments: string[] = [];
    let route: ActivatedRouteSnapshot | null = this.router.routerState.snapshot.root;
    while (route) {
      const path = route.routeConfig?.path;
      if (path) {
        segments.push(path);
      }
      route = route.firstChild;
    }
    return `/${segments.join('/')}`;
  }
}
