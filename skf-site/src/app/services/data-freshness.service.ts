import { Injectable, signal } from '@angular/core';

/**
 * Tracks which API URLs returned stale cached data (X-Data-Stale header).
 * Updated automatically by the staleness interceptor.
 */
@Injectable({ providedIn: 'root' })
export class DataFreshnessService {
  private readonly staleUrls = signal<Set<string>>(new Set());

  markStale(url: string): void {
    this.staleUrls.update((s) => new Set([...s, url]));
  }

  clearStale(url: string): void {
    this.staleUrls.update((s) => {
      const next = new Set(s);
      next.delete(url);
      return next;
    });
  }

  /** Check if any URL matching a substring is stale. */
  hasStaleData(urlFragment: string): boolean {
    return [...this.staleUrls()].some((url) => url.includes(urlFragment));
  }

  /** Clear all staleness markers matching a substring. */
  clearByFragment(urlFragment: string): void {
    this.staleUrls.update((s) => {
      const next = new Set<string>();
      for (const url of s) {
        if (!url.includes(urlFragment)) next.add(url);
      }
      return next;
    });
  }
}
