import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { finalize } from 'rxjs/operators';
import { LoadingService } from '../services/loading.service';

/**
 * Adds `withCredentials: true` to every `/api` request so the
 * session cookie is sent automatically. Also shows the global
 * loading overlay while the request is in-flight.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const loading = inject(LoadingService);
  if (req.url.startsWith('/api')) {
    req = req.clone({ withCredentials: true });
    loading.show();
    return next(req).pipe(finalize(() => loading.hide()));
  }
  return next(req);
};
