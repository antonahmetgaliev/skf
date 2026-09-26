import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

/** Waits for the session user to load so a hard refresh doesn't bounce judges. */
export const judgeGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  await auth.whenLoaded();
  if (auth.isJudge()) return true;
  return router.parseUrl('/');
};
