import {
  HttpErrorResponse,
  HttpInterceptorFn,
  HttpRequest,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError } from 'rxjs';
import { AuthService } from './auth.service';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

function withSecurity(request: HttpRequest<unknown>): HttpRequest<unknown> {
  const auth = inject(AuthService);
  const headers: Record<string, string> = {};
  if (!SAFE_METHODS.has(request.method) && request.url.startsWith('/api/')) {
    const token = auth.csrfToken();
    if (token) {
      headers['X-CSRF-Token'] = token;
    }
  }
  return request.clone({
    withCredentials: request.url.startsWith('/'),
    setHeaders: headers,
  });
}

export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return next(withSecurity(request)).pipe(
    catchError((error: HttpErrorResponse) => {
      const detail =
        typeof error.error?.detail === 'string' ? error.error.detail : '';
      if (
        error.status === 403 &&
        detail.includes('CSRF') &&
        !request.url.includes('/auth/csrf')
      ) {
        return auth.refreshCsrf().pipe(
          switchMap(() => next(withSecurity(request))),
        );
      }
      if (
        error.status === 401 &&
        !request.url.includes('/auth/') &&
        !request.url.includes('/privacy/')
      ) {
        auth.me.set(null);
        void router.navigate(['/login']);
      }
      return throwError(() => error);
    }),
  );
};
