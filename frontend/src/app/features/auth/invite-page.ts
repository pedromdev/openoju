import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { I18nService } from '../../core/i18n.service';
import { InvitationInfo } from '../../core/models';

@Component({
  selector: 'app-invite-page',
  imports: [FormsModule],
  template: `
    <div class="mx-auto flex min-h-[70vh] max-w-md flex-col justify-center">
      <div class="rounded-3xl border border-slate-800 bg-slate-900/70 p-8 shadow-2xl">
        <h1 class="text-2xl font-semibold text-white">{{ i18n.t('auth.invite') }}</h1>
        @if (info(); as data) {
          <p class="mt-2 text-sm text-slate-400">
            {{ data.organization_name }} · {{ data.email }}
          </p>
          <p class="mt-1 text-xs text-slate-500">Grupos: {{ data.groups.join(', ') || 'Viewer' }}</p>
        }
        @if (error()) {
          <p class="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
            {{ error() }}
          </p>
        }
        @if (info()) {
          <form class="mt-6 grid gap-4" (ngSubmit)="submit()">
            <label class="block text-sm">
              <span class="mb-1 block text-slate-300">{{ i18n.t('auth.displayName') }}</span>
              <input class="input" name="displayName" [(ngModel)]="displayName" />
            </label>
            @if (info()?.requires_password) {
              <label class="block text-sm">
                <span class="mb-1 block text-slate-300">{{ i18n.t('auth.password') }}</span>
                <input class="input" type="password" name="password" [(ngModel)]="password" required minlength="12" />
              </label>
            }
            <button class="btn" type="submit" [disabled]="busy()">
              {{ busy() ? i18n.t('common.loading') : i18n.t('auth.createAccount') }}
            </button>
          </form>
        }
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
      }
      .btn {
        width: 100%;
        border-radius: 0.75rem;
        background: rgb(16 185 129);
        padding: 0.625rem 1rem;
        font-weight: 500;
        color: rgb(2 6 23);
      }
    `,
  ],
})
export class InvitePage implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  readonly i18n = inject(I18nService);

  token = '';
  displayName = '';
  password = '';
  readonly info = signal<InvitationInfo | null>(null);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  ngOnInit(): void {
    this.token = this.route.snapshot.queryParamMap.get('token') ?? '';
    if (!this.token) {
      this.error.set('Convite inválido.');
      return;
    }
    this.auth.invitationInfo(this.token).subscribe({
      next: (info) => this.info.set(info),
      error: (err) => this.error.set(err?.error?.detail ?? 'Convite inválido ou expirado.'),
    });
  }

  submit(): void {
    this.busy.set(true);
    this.error.set(null);
    this.auth
      .acceptInvitation({
        token: this.token,
        password: this.password || null,
        display_name: this.displayName || null,
      })
      .subscribe({
        next: () => {
          this.busy.set(false);
          void this.router.navigate(['/videos']);
        },
        error: (err) => {
          this.busy.set(false);
          this.error.set(err?.error?.detail ?? this.i18n.t('common.error'));
        },
      });
  }
}
