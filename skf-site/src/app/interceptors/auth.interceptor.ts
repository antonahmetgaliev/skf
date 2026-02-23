import { HttpInterceptorFn } from '@angular/common/http';

/**
 * Adds `withCredentials: true` to every `/api` request so the
 * session cookie is sent automatically.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (req.url.startsWith('/api')) {
    req = req.clone({ withCredentials: true });
  }
  return next(req);
};
