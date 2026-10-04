import { HttpErrorResponse, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';
import { API } from '../api';
import { AuthTokensService } from '../services/auth-tokens.service';

const withToken = (req: HttpRequest<unknown>, token: string) =>
  req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });

/**
 * Sends the access token with every API request of a signed-in visitor.
 * An expired token is replaced before the request leaves; one the server
 * refuses anyway (401) is replaced once and the request repeated. Anonymous
 * visitors' requests pass through untouched.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  // The token endpoints carry the refresh token themselves.
  if (!req.url.startsWith('/api') || req.url.startsWith(`${API}/auth/`)) {
    return next(req);
  }
  const tokens = inject(AuthTokensService);
  if (!tokens.active()) {
    return next(req);
  }

  return tokens.accessToken().pipe(
    switchMap((token) => {
      if (!token) return next(req);
      return next(withToken(req, token)).pipe(
        catchError((err: unknown) => {
          if (!(err instanceof HttpErrorResponse) || err.status !== 401) {
            return throwError(() => err);
          }
          return tokens
            .refresh(token)
            .pipe(
              switchMap((fresh) => (fresh ? next(withToken(req, fresh)) : throwError(() => err))),
            );
        }),
      );
    }),
  );
};
