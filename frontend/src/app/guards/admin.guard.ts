import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

/**
 * Waits for the user to load so a hard refresh on /admin doesn't bounce admins.
 * Checks the real role: previewing the site as a lower role must not lock an admin out.
 */
export const adminGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  await auth.whenLoaded();
  if (auth.isRealAdmin()) {
    return true;
  }
  return router.parseUrl('/');
};
