import { Component, computed, effect, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from './core/auth.service';
import { I18nService } from './core/i18n.service';
import { Organization } from './core/models';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  readonly auth = inject(AuthService);
  readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  readonly organizations = signal<Organization[]>([]);
  private readonly loadedFor = signal<string | null>(null);
  readonly canAdmin = computed(() =>
    [
      'members.view',
      'groups.manage',
      'api_keys.manage',
      'webhooks.manage',
      'privacy.manage',
      'audit.view',
      'data_subject_requests.manage',
    ].some((permission) => this.auth.has(permission)),
  );

  constructor() {
    effect(() => {
      const me = this.auth.me();
      if (me && this.loadedFor() !== me.user.id) {
        this.loadedFor.set(me.user.id);
        this.auth.listOrganizations().subscribe({
          next: (organizations) => this.organizations.set(organizations),
          error: () => undefined,
        });
      }
    });
  }

  switchOrg(slug: string): void {
    if (!slug || slug === this.auth.organization()?.slug) return;
    this.auth.switchOrganization(slug).subscribe({
      next: () => void this.router.navigate(['/videos']),
      error: () => undefined,
    });
  }

  logout(): void {
    this.auth.logout().subscribe({
      next: () => void this.router.navigate(['/login']),
      error: () => void this.router.navigate(['/login']),
    });
  }
}
