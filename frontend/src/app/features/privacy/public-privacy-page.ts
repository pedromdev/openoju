import { HttpClient } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

interface PublicPrivacy {
  organization_name: string;
  organization_slug: string;
  legal_basis: string;
  retention_media_days: number;
  dpo_name: string | null;
  dpo_email: string | null;
  privacy_policy_version: string | null;
  privacy_policy_url: string | null;
  camera_notice_text: string | null;
}

@Component({
  selector: 'app-public-privacy-page',
  imports: [FormsModule],
  template: `
    <div class="mx-auto max-w-3xl space-y-6 py-8">
      @if (privacy(); as data) {
        <header>
          <p class="text-xs uppercase tracking-wider text-emerald-400">Privacidade e LGPD</p>
          <h1 class="mt-1 text-3xl font-semibold text-white">{{ data.organization_name }}</h1>
          <p class="mt-2 text-sm text-slate-400">
            Monitoramento por câmeras para segurança patrimonial. Retenção de mídia:
            {{ data.retention_media_days }} dias.
          </p>
        </header>

        @if (data.camera_notice_text) {
          <p class="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-300">
            {{ data.camera_notice_text }}
          </p>
        }

        <section class="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 text-sm text-slate-300">
          <h2 class="font-medium text-white">Seus direitos</h2>
          <p class="mt-2">
            Você pode solicitar confirmação de tratamento, acesso, correção, portabilidade,
            eliminação e informações sobre compartilhamento. Responderemos em até 15 dias.
          </p>
          @if (data.dpo_email || data.dpo_name) {
            <p class="mt-2">Encarregado (DPO): {{ data.dpo_name }} {{ data.dpo_email }}</p>
          }
          @if (data.privacy_policy_url) {
            <a class="mt-2 inline-block text-emerald-400 hover:underline" [href]="data.privacy_policy_url" target="_blank" rel="noopener">
              Política de privacidade completa
            </a>
          }
        </section>

        <form class="grid gap-3 rounded-2xl border border-slate-800 bg-slate-900/60 p-5" (ngSubmit)="submit()">
          <h2 class="font-medium text-white">Enviar solicitação</h2>
          @if (protocol()) {
            <p class="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">
              Solicitação registrada. Protocolo: <strong>{{ protocol() }}</strong>
            </p>
          }
          @if (error()) {
            <p class="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{{ error() }}</p>
          }
          <label class="text-sm text-slate-300">Tipo
            <select class="input mt-1" name="type" [(ngModel)]="type">
              <option value="access">Acesso</option>
              <option value="correction">Correção</option>
              <option value="deletion">Exclusão</option>
              <option value="portability">Portabilidade</option>
              <option value="information">Informação</option>
            </select>
          </label>
          <label class="text-sm text-slate-300">Nome
            <input class="input mt-1" name="name" [(ngModel)]="name" required minlength="2" />
          </label>
          <label class="text-sm text-slate-300">E-mail
            <input class="input mt-1" type="email" name="email" [(ngModel)]="email" required />
          </label>
          <label class="text-sm text-slate-300">Descrição
            <textarea class="input mt-1 min-h-24" name="description" [(ngModel)]="description"></textarea>
          </label>
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="text-sm text-slate-300">Data inicial
              <input class="input mt-1" type="date" name="start" [(ngModel)]="start" />
            </label>
            <label class="text-sm text-slate-300">Data final
              <input class="input mt-1" type="date" name="end" [(ngModel)]="end" />
            </label>
          </div>
          <button class="btn" type="submit">Enviar solicitação</button>
        </form>
      } @else if (error()) {
        <p class="text-sm text-rose-300">{{ error() }}</p>
      } @else {
        <p class="text-sm text-slate-400">Carregando…</p>
      }
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
        border-radius: 0.75rem;
        background: rgb(16 185 129);
        padding: 0.5rem 1rem;
        font-weight: 500;
        color: rgb(2 6 23);
      }
    `,
  ],
})
export class PublicPrivacyPage implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  readonly privacy = signal<PublicPrivacy | null>(null);
  readonly protocol = signal<string | null>(null);
  readonly error = signal<string | null>(null);

  slug = '';
  type = 'access';
  name = '';
  email = '';
  description = '';
  start = '';
  end = '';

  ngOnInit(): void {
    this.slug = this.route.snapshot.paramMap.get('slug') ?? '';
    this.http.get<PublicPrivacy>(`/api/v1/privacy/${this.slug}`).subscribe({
      next: (privacy) => this.privacy.set(privacy),
      error: () => this.error.set('Organização não encontrada.'),
    });
  }

  submit(): void {
    this.error.set(null);
    this.http
      .post<{ protocol: string }>(`/api/v1/privacy/${this.slug}/requests`, {
        type: this.type,
        requester_name: this.name,
        requester_email: this.email,
        description: this.description,
        date_range_start: this.start ? `${this.start}T00:00:00Z` : null,
        date_range_end: this.end ? `${this.end}T23:59:59Z` : null,
      })
      .subscribe({
        next: (result) => {
          this.protocol.set(result.protocol);
          this.name = '';
          this.email = '';
          this.description = '';
        },
        error: (err) =>
          this.error.set(err?.error?.detail ?? 'Não foi possível registrar a solicitação.'),
      });
  }
}
