import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

/** Waits for the session user to load so a hard refresh on /admin doesn't bounce admins. */
export const adminGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  await auth.whenLoaded();
  if (auth.isAdmin()) {
    return true;
  }
  return router.parseUrl('/');
};
