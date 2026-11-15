import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { I18nService } from '../../core/i18n.service';

@Component({
  selector: 'app-login-page',
  imports: [FormsModule, RouterLink],
  template: `
    <div class="mx-auto flex min-h-[70vh] max-w-md flex-col justify-center">
      <div class="rounded-3xl border border-slate-800 bg-slate-900/70 p-8 shadow-2xl">
        <h1 class="text-2xl font-semibold text-white">{{ i18n.t('auth.login') }}</h1>
        <p class="mt-1 text-sm text-slate-400">OpenOju</p>

        @if (error()) {
          <p class="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
            {{ error() }}
          </p>
        }

        <form class="mt-6 space-y-4" (ngSubmit)="submit()">
          <label class="block text-sm">
            <span class="mb-1 block text-slate-300">{{ i18n.t('auth.email') }}</span>
            <input
              class="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-emerald-500"
              type="email"
              name="email"
              [(ngModel)]="email"
              required
              autocomplete="username"
            />
          </label>
          <label class="block text-sm">
            <span class="mb-1 block text-slate-300">{{ i18n.t('auth.password') }}</span>
            <input
              class="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-emerald-500"
              type="password"
              name="password"
              [(ngModel)]="password"
              required
              autocomplete="current-password"
            />
          </label>
          <button
            class="w-full rounded-xl bg-emerald-500 px-4 py-2.5 font-medium text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50"
            type="submit"
            [disabled]="busy()"
          >
            {{ busy() ? i18n.t('common.loading') : i18n.t('auth.login') }}
          </button>
        </form>

        @if (oidcEnabled()) {
          <a
            class="mt-4 block rounded-xl border border-slate-700 px-4 py-2.5 text-center text-sm text-slate-200 transition hover:border-emerald-500"
            href="/api/v1/auth/oidc/login"
          >
            {{ i18n.t('auth.sso') }}
          </a>
        }

        @if (setupRequired()) {
          <p class="mt-4 text-center text-sm text-slate-400">
            Primeiro acesso?
            <a routerLink="/setup" class="text-emerald-400 hover:underline">
              {{ i18n.t('auth.setup') }}
            </a>
          </p>
        }
      </div>
    </div>
  `,
})
export class LoginPage implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  readonly i18n = inject(I18nService);

  email = '';
  password = '';
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly setupRequired = signal(false);
  readonly oidcEnabled = signal(false);

  async ngOnInit(): Promise<void> {
    await this.auth.ensureLoaded();
    this.setupRequired.set(this.auth.setupStatus()?.setup_required ?? false);
    this.oidcEnabled.set(this.auth.setupStatus()?.oidc_enabled ?? false);
    const oidcError = this.route.snapshot.queryParamMap.get('oidc_error');
    if (oidcError) {
      this.error.set(oidcError);
    }
  }

  submit(): void {
    if (this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    this.auth.login(this.email, this.password).subscribe({
      next: (me) => {
        this.busy.set(false);
        void this.router.navigate([me.organization ? '/videos' : '/organizations']);
      },
      error: (err) => {
        this.busy.set(false);
        const detail = err?.error?.detail;
        this.error.set(typeof detail === 'string' ? detail : this.i18n.t('common.error'));
      },
    });
  }
}
