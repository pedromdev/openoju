import { Component, OnInit, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { Organization } from '../../core/models';

@Component({
  selector: 'app-organizations-page',
  template: `
    <div class="mx-auto max-w-2xl py-10">
      <h1 class="text-2xl font-semibold text-white">Escolha a organização</h1>
      <p class="mt-1 text-sm text-slate-400">Sua conta participa de mais de uma organização.</p>
      @if (error()) {
        <p class="mt-4 text-sm text-rose-300">{{ error() }}</p>
      }
      <div class="mt-6 grid gap-3">
        @for (organization of organizations(); track organization.id) {
          <button
            class="flex items-center justify-between rounded-2xl border border-slate-800 bg-slate-900/70 px-5 py-4 text-left transition hover:border-emerald-500"
            type="button"
            (click)="select(organization)"
          >
            <span>
              <span class="block font-medium text-white">{{ organization.name }}</span>
              <span class="block text-xs text-slate-400">{{ organization.slug }}</span>
            </span>
            <span class="text-emerald-400">→</span>
          </button>
        } @empty {
          <p class="text-sm text-slate-400">Nenhuma organização ativa.</p>
        }
      </div>
    </div>
  `,
})
export class OrganizationsPage implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  readonly organizations = signal<Organization[]>([]);
  readonly error = signal<string | null>(null);

  ngOnInit(): void {
    this.auth.listOrganizations().subscribe({
      next: (organizations) => this.organizations.set(organizations),
      error: () => this.error.set('Não foi possível carregar as organizações.'),
    });
  }

  select(organization: Organization): void {
    this.auth.switchOrganization(organization.slug).subscribe({
      next: () => void this.router.navigate(['/videos']),
      error: (err) => this.error.set(err?.error?.detail ?? 'Falha ao trocar de organização.'),
    });
  }
}
