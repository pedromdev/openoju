import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, firstValueFrom, tap } from 'rxjs';
import { Me, Organization, SetupStatus } from './models';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  readonly me = signal<Me | null>(null);
  readonly setupStatus = signal<SetupStatus | null>(null);
  readonly loading = signal(true);
  readonly initialized = signal(false);

  readonly organization = computed(() => this.me()?.organization ?? null);
  readonly permissions = computed(
    () => new Set(this.me()?.permissions ?? []),
  );
  readonly orgBase = computed(() => {
    const organization = this.organization();
    return organization ? `/api/v1/orgs/${organization.slug}` : '';
  });

  has(permission: string): boolean {
    return this.permissions().has(permission);
  }

  csrfToken(): string | null {
    const match = document.cookie
      .split('; ')
      .find((item) => item.startsWith('openoju_csrf='));
    return match ? decodeURIComponent(match.split('=').slice(1).join('=')) : null;
  }

  async ensureLoaded(): Promise<void> {
    if (this.initialized()) {
      return;
    }
    try {
      this.setupStatus.set(
        await firstValueFrom(this.http.get<SetupStatus>('/api/v1/auth/setup/status')),
      );
      if (!this.setupStatus()?.setup_required) {
        try {
          const me = await firstValueFrom(this.http.get<Me>('/api/v1/auth/me'));
          this.me.set(me);
        } catch {
          this.me.set(null);
        }
      }
    } finally {
      this.loading.set(false);
      this.initialized.set(true);
    }
  }

  loadMe(): Observable<Me> {
    return this.http
      .get<Me>('/api/v1/auth/me')
      .pipe(tap((me) => this.me.set(me)));
  }

  login(email: string, password: string): Observable<Me> {
    return this.http
      .post<Me>('/api/v1/auth/login', { email, password })
      .pipe(tap((me) => this.me.set(me)));
  }

  setup(payload: {
    token: string;
    organization_name: string;
    organization_slug?: string | null;
    owner_email: string;
    owner_password: string;
    owner_display_name?: string;
  }): Observable<Me> {
    return this.http
      .post<Me>('/api/v1/auth/setup', payload)
      .pipe(tap((me) => this.me.set(me)));
  }

  acceptInvitation(payload: {
    token: string;
    password?: string | null;
    display_name?: string | null;
  }): Observable<Me> {
    return this.http
      .post<Me>('/api/v1/auth/invitations/accept', payload)
      .pipe(tap((me) => this.me.set(me)));
  }

  invitationInfo(token: string): Observable<import('./models').InvitationInfo> {
    return this.http.get<import('./models').InvitationInfo>(
      `/api/v1/auth/invitations/${token}`,
    );
  }

  switchOrganization(slug: string): Observable<Me> {
    return this.http
      .post<Me>('/api/v1/auth/switch-organization', { slug })
      .pipe(tap((me) => this.me.set(me)));
  }

  listOrganizations(): Observable<Organization[]> {
    return this.http.get<Organization[]>('/api/v1/organizations');
  }

  logout(): Observable<void> {
    return this.http
      .post<void>('/api/v1/auth/logout', {})
      .pipe(tap(() => this.me.set(null)));
  }

  refreshCsrf(): Observable<{ csrf_token: string }> {
    return this.http.get<{ csrf_token: string }>('/api/v1/auth/csrf');
  }
}
