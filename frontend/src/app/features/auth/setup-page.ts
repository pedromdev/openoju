import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { I18nService } from '../../core/i18n.service';

@Component({
  selector: 'app-setup-page',
  imports: [FormsModule],
  template: `
    <div class="mx-auto flex min-h-[70vh] max-w-lg flex-col justify-center">
      <div class="rounded-3xl border border-slate-800 bg-slate-900/70 p-8 shadow-2xl">
        <h1 class="text-2xl font-semibold text-white">{{ i18n.t('auth.setup') }}</h1>
        <p class="mt-1 text-sm text-slate-400">Crie a primeira organização e o owner.</p>

        @if (error()) {
          <p class="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
            {{ error() }}
          </p>
        }

        <form class="mt-6 grid gap-4" (ngSubmit)="submit()">
          <label class="block text-sm">
            <span class="mb-1 block text-slate-300">{{ i18n.t('auth.setupToken') }}</span>
            <input class="input" name="token" [(ngModel)]="token" required />
          </label>
          <label class="block text-sm">
            <span class="mb-1 block text-slate-300">{{ i18n.t('auth.orgName') }}</span>
            <input class="input" name="orgName" [(ngModel)]="orgName" required />
          </label>
          <label class="block text-sm">
            <span class="mb-1 block text-slate-300">{{ i18n.t('auth.orgSlug') }}</span>
            <input class="input" name="slug" [(ngModel)]="slug" />
          </label>
          <label class="block text-sm">
            <span class="mb-1 block text-slate-300">{{ i18n.t('auth.email') }}</span>
            <input class="input" type="email" name="email" [(ngModel)]="email" required />
          </label>
          <label class="block text-sm">
            <span class="mb-1 block text-slate-300">{{ i18n.t('auth.displayName') }}</span>
            <input class="input" name="displayName" [(ngModel)]="displayName" />
          </label>
          <label class="block text-sm">
            <span class="mb-1 block text-slate-300">{{ i18n.t('auth.password') }}</span>
            <input class="input" type="password" name="password" [(ngModel)]="password" required minlength="12" />
          </label>
          <button class="btn" type="submit" [disabled]="busy()">
            {{ busy() ? i18n.t('common.loading') : i18n.t('auth.createAccount') }}
          </button>
        </form>
      </div>
    </div>
  `,
  styles: [
    `
      .input {
        width: 100%;
        border-radius: 0.75rem;
        border: 1px solid rgb(51 65 85);
        background: rgb(2 6 23);
        padding: 0.5rem 0.75rem;
        color: rgb(241 245 249);
        outline: none;
      }
      .input:focus {
        border-color: rgb(16 185 129);
      }
      .btn {
        width: 100%;
        border-radius: 0.75rem;
        background: rgb(16 185 129);
        padding: 0.625rem 1rem;
        font-weight: 500;
        color: rgb(2 6 23);
      }
      .btn:disabled {
        opacity: 0.5;
      }
    `,
  ],
})
export class SetupPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  readonly i18n = inject(I18nService);

  token = '';
  orgName = '';
  slug = '';
  email = '';
  displayName = '';
  password = '';
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  submit(): void {
    if (this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    this.auth
      .setup({
        token: this.token,
        organization_name: this.orgName,
        organization_slug: this.slug || null,
        owner_email: this.email,
        owner_password: this.password,
        owner_display_name: this.displayName,
      })
      .subscribe({
        next: () => {
          this.busy.set(false);
          void this.router.navigate(['/videos']);
        },
        error: (err) => {
          this.busy.set(false);
          const detail = err?.error?.detail;
          this.error.set(typeof detail === 'string' ? detail : this.i18n.t('common.error'));
        },
      });
  }
}
