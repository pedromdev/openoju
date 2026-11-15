import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';

export const authGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  await auth.ensureLoaded();
  if (!auth.me()) {
    return router.parseUrl('/login');
  }
  if (!auth.organization()) {
    return router.parseUrl('/organizations');
  }
  return true;
};

export const guestGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  await auth.ensureLoaded();
  if (auth.me()?.organization) {
    return router.parseUrl('/videos');
  }
  return true;
};
