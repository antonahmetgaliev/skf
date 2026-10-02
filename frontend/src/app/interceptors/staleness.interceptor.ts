import { HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { tap } from 'rxjs';
import { DataFreshnessService } from '../services/data-freshness.service';

/**
 * Detects the X-Data-Stale response header set by the backend when
 * serving stale cached data (e.g. after a SimGrid 429 rate limit).
 */
export const stalenessInterceptor: HttpInterceptorFn = (req, next) => {
  const freshness = inject(DataFreshnessService);
  return next(req).pipe(
    tap((event) => {
      if (event instanceof HttpResponse) {
        if (event.headers.get('X-Data-Stale') === 'true') {
          freshness.markStale(req.url);
        } else {
          freshness.clearStale(req.url);
        }
      }
    }),
  );
};
