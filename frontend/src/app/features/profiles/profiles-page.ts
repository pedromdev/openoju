import { Component, computed, inject, signal } from '@angular/core';
import { forkJoin } from 'rxjs';
import { ApiService } from '../../core/api.service';
import { formatDateTime } from '../../core/format';
import { Mask, Profile, Video } from '../../core/models';

@Component({
  selector: 'app-profiles-page',
  templateUrl: './profiles-page.html',
})
export class ProfilesPage {
  private readonly api = inject(ApiService);

  readonly profiles = signal<Profile[]>([]);
  readonly videos = signal<Video[]>([]);
  readonly selected = signal<Profile | null>(null);
  readonly masks = signal<Mask[]>([]);
  readonly editingName = signal('');
  readonly newName = signal('');
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly toast = signal<string | null>(null);

  readonly previewUrl = computed(() => {
    const video = this.videos().find((item) => item.thumbnail_path);
    return video ? this.api.videoThumbnailUrl(video.id) : null;
  });

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set(null);
    forkJoin({
      profiles: this.api.listProfiles(),
      videos: this.api.listVideos(),
    }).subscribe({
      next: ({ profiles, videos }) => {
        this.profiles.set(profiles);
        this.videos.set(videos);
        const current = this.selected();
        const next =
          profiles.find((profile) => profile.id === current?.id) ?? profiles[0] ?? null;
        if (next) {
          this.select(next);
        }
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.error.set(this.errorMessage(err, 'Não foi possível carregar os perfis.'));
        this.loading.set(false);
      },
    });
  }

  select(profile: Profile): void {
    this.selected.set(profile);
    this.editingName.set(profile.name);
    this.masks.set((profile.masks ?? []).map((mask) => ({ ...mask })));
  }

  addMask(preset?: 'left' | 'right'): void {
    const mask: Mask =
      preset === 'right'
        ? { x: 0.65, y: 0.0, w: 0.35, h: 0.1 }
        : { x: 0.0, y: 0.0, w: 0.35, h: 0.1 };
    this.masks.update((masks) => [...masks, mask]);
  }

  updateMask(index: number, field: keyof Mask, rawValue: string): void {
    const value = Number(rawValue);
    if (!Number.isFinite(value)) {
      return;
    }
    const normalized = Math.max(0, Math.min(100, value)) / 100;
    const rounded = Math.round(normalized * 10000) / 10000;
    this.masks.update((masks) =>
      masks.map((mask, i) => (i === index ? { ...mask, [field]: rounded } : mask)),
    );
  }

  pct(value: number): number {
    return Math.round(value * 1000) / 10;
  }

  removeMask(index: number): void {
    this.masks.update((masks) => masks.filter((_, i) => i !== index));
  }

  save(): void {
    const profile = this.selected();
    if (!profile) {
      return;
    }
    const name = this.editingName().trim();
    if (!name) {
      this.error.set('O nome do perfil é obrigatório.');
      return;
    }
    this.error.set(null);
    this.api
      .updateProfile(profile.id, {
        name,
        masks: this.masks(),
        roi: profile.roi,
        settings: profile.settings,
      })
      .subscribe({
        next: (updated) => {
          this.profiles.update((profiles) =>
            profiles.map((item) => (item.id === updated.id ? updated : item)),
          );
          this.select(updated);
          this.showToast('Perfil salvo.');
        },
        error: (err: unknown) => {
          this.error.set(this.errorMessage(err, 'Falha ao salvar o perfil.'));
        },
      });
  }

  create(): void {
    const name = this.newName().trim();
    if (!name) {
      this.error.set('Informe um nome para o novo perfil.');
      return;
    }
    this.error.set(null);
    this.api
      .createProfile({ name, masks: [], roi: null, settings: {} })
      .subscribe({
        next: (created) => {
          this.profiles.update((profiles) => [...profiles, created]);
          this.newName.set('');
          this.select(created);
          this.showToast('Perfil criado.');
        },
        error: (err: unknown) => {
          this.error.set(this.errorMessage(err, 'Falha ao criar o perfil.'));
        },
      });
  }

  remove(): void {
    const profile = this.selected();
    if (!profile) {
      return;
    }
    if (!window.confirm(`Excluir o perfil "${profile.name}"?`)) {
      return;
    }
    this.api.deleteProfile(profile.id).subscribe({
      next: () => {
        this.profiles.update((profiles) =>
          profiles.filter((item) => item.id !== profile.id),
        );
        const next = this.profiles()[0] ?? null;
        if (next) {
          this.select(next);
        } else {
          this.selected.set(null);
          this.masks.set([]);
        }
        this.showToast('Perfil excluído.');
      },
      error: (err: unknown) => {
        this.error.set(this.errorMessage(err, 'Falha ao excluir o perfil.'));
      },
    });
  }

  date(value: string): string {
    return formatDateTime(value);
  }

  private showToast(message: string): void {
    this.toast.set(message);
    setTimeout(() => this.toast.set(null), 3000);
  }

  private errorMessage(error: unknown, fallback: string): string {
    const detail = (error as { error?: { detail?: unknown } })?.error?.detail;
    return typeof detail === 'string' ? detail : fallback;
  }
}
