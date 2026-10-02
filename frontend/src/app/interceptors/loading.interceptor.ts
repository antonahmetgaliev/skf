import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { finalize } from 'rxjs';
import { LoadingService } from '../services/loading.service';

/**
 * Drives the global progress bar from in-flight HTTP requests.
 *
 * Doing it here rather than in each handler means every request in the app
 * reports itself — a component only needs its own busy state when it wants to
 * disable a specific control, not merely to prove that something is happening.
 *
 * Translation bundles are skipped: they load on boot and on every language
 * switch, and flashing the bar for them says nothing about the user's action.
 */
/** Reads of a translation bundle (what the Transloco loader fetches) — not the
 *  admin translation editor's saves, which are user actions and should report
 *  themselves like any other. */
const TRANSLATION_BUNDLE = /\/api\/v1\/languages\/[^/]+\/translations$/;

export const loadingInterceptor: HttpInterceptorFn = (req, next) => {
  if (req.method === 'GET' && TRANSLATION_BUNDLE.test(req.url)) {
    return next(req);
  }

  const loading = inject(LoadingService);
  loading.show();
  // finalize covers success, error and cancellation alike, so the counter can
  // never be left stranded above zero with the bar stuck on screen.
  return next(req).pipe(finalize(() => loading.hide()));
};
