import {
  HttpEvent,
  HttpEventType,
  HttpResponse,
} from '@angular/common/http';
import {
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { NgClass } from '@angular/common';
import { RouterLink } from '@angular/router';
import { forkJoin, firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { ConfirmDialog } from '../../shared/confirm-dialog';
import {
  formatBytes,
  formatDateTime,
  formatDuration,
  videoStatusClasses,
  videoStatusLabel,
} from '../../core/format';
import {
  Profile,
  UploadPartResult,
  UploadResponse,
  Video,
} from '../../core/models';

type Filter = 'all' | 'ready' | 'active' | 'failed';

const MULTIPART_LIMIT = 90 * 1024 * 1024;

@Component({
  selector: 'app-video-list-page',
  imports: [NgClass, RouterLink, ConfirmDialog],
  templateUrl: './video-list-page.html',
})
export class VideoListPage {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);

  readonly videos = signal<Video[]>([]);
  readonly profiles = signal<Profile[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly toast = signal<string | null>(null);
  readonly uploadProgress = signal<number | null>(null);
  readonly uploadName = signal<string | null>(null);
  readonly uploadTotal = signal(0);
  readonly uploadIndex = signal(0);
  readonly uploading = signal(false);
  readonly importing = signal(false);
  readonly scanning = signal(false);
  readonly dragActive = signal(false);
  readonly importPath = signal('');
  readonly selectedProfile = signal('');
  readonly filter = signal<Filter>('all');
  readonly selected = signal<Set<string>>(new Set());
  readonly deleteTargets = signal<Video[]>([]);
  readonly deleting = signal(false);
  readonly canManage = computed(() => this.auth.has('videos.manage'));
  readonly canCancelJobs = computed(() => this.auth.has('jobs.cancel'));
  readonly selectedCount = computed(() => this.selected().size);
  readonly deleteMessage = computed(() => {
    const targets = this.deleteTargets();
    if (!targets.length) return '';
    const names = targets
      .slice(0, 4)
      .map((video) => `• ${video.filename}`)
      .join('\n');
    const extra = targets.length > 4 ? `\n• … e mais ${targets.length - 4}` : '';
    const events = targets.reduce((sum, video) => sum + video.event_count, 0);
    return `${names}${extra}\n\n${targets.length} vídeo(s), ${events} evento(s). A mídia no storage e os artefatos locais serão removidos permanentemente. Vídeos em análise ou sob legal hold não serão excluídos.`;
  });

  readonly filteredVideos = computed(() => {
    const filter = this.filter();
    const all = this.videos();
    if (filter === 'ready') {
      return all.filter((video) => video.status === 'ready');
    }
    if (filter === 'failed') {
      return all.filter((video) => video.status === 'failed');
    }
    if (filter === 'active') {
      return all.filter(
        (video) => video.status === 'queued' || video.status === 'analyzing',
      );
    }
    return all;
  });

  readonly stats = computed(() => {
    const all = this.videos();
    return {
      total: all.length,
      ready: all.filter((video) => video.status === 'ready').length,
      active: all.filter(
        (video) => video.status === 'queued' || video.status === 'analyzing',
      ).length,
      events: all.reduce((sum, video) => sum + video.event_count, 0),
    };
  });

  constructor() {
    this.load(true);
    const timer = setInterval(() => this.refresh(), 3000);
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }

  load(showLoading = false): void {
    if (showLoading) {
      this.loading.set(true);
    }
    this.error.set(null);
    forkJoin({
      videos: this.api.listVideos(),
      profiles: this.api.listProfiles(),
    }).subscribe({
      next: ({ videos, profiles }) => {
        this.videos.set(videos);
        this.profiles.set(profiles);
        if (!this.selectedProfile() && profiles.length > 0) {
          this.selectedProfile.set(profiles[0].id);
        }
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.error.set(this.errorMessage(err, 'Não foi possível carregar os vídeos.'));
        this.loading.set(false);
      },
    });
  }

  refresh(): void {
    this.api.listVideos().subscribe({
      next: (videos) => this.videos.set(videos),
      error: () => undefined,
    });
  }

  onFileInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    if (files.length) {
      void this.uploadFiles(files);
    }
    input.value = '';
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(false);
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length) {
      void this.uploadFiles(files);
    }
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(true);
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.dragActive.set(false);
  }

  async uploadFiles(files: File[]): Promise<void> {
    if (!files.length || this.uploading()) {
      return;
    }
    const totalBytes = files.reduce((sum, file) => sum + Math.max(0, file.size), 0);
    if (totalBytes <= 0) {
      this.error.set('Nenhum arquivo com conteúdo para enviar.');
      return;
    }
    this.error.set(null);
    this.uploading.set(true);
    this.uploadTotal.set(files.length);
    this.uploadIndex.set(0);
    this.uploadProgress.set(0);
    let success = 0;
    let completedBytes = 0;
    const errors: string[] = [];

    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      this.uploadIndex.set(index);
      this.uploadName.set(file.name);
      try {
        if (file.size <= MULTIPART_LIMIT) {
          await this.uploadMultipart(file, completedBytes, totalBytes);
        } else {
          await this.uploadChunked(file, completedBytes, totalBytes);
        }
        success += 1;
        completedBytes += file.size;
        this.uploadProgress.set(
          Math.min(100, Math.round((completedBytes / totalBytes) * 100)),
        );
        this.load();
      } catch (err: unknown) {
        errors.push(`${file.name}: ${this.errorMessage(err, 'falha no upload')}`);
        completedBytes += file.size;
        this.uploadProgress.set(
          Math.min(100, Math.round((completedBytes / totalBytes) * 100)),
        );
      }
    }

    this.uploading.set(false);
    this.uploadProgress.set(null);
    this.uploadName.set(null);
    this.uploadTotal.set(0);
    if (success > 0) {
      this.showToast(
        `${success} arquivo${success === 1 ? '' : 's'} enviado${success === 1 ? '' : 's'}.`,
      );
      this.load();
    }
    if (errors.length) {
      this.error.set(errors.slice(0, 3).join(' | '));
    }
  }

  private uploadMultipart(
    file: File,
    baseBytes: number,
    totalBytes: number,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      let settled = false;
      this.api.uploadVideo(file, this.selectedProfile() || null).subscribe({
        next: (event: HttpEvent<UploadResponse>) => {
          if (event.type === HttpEventType.UploadProgress) {
            const fraction = event.total ? event.loaded / event.total : 0;
            const overall = (baseBytes + fraction * file.size) / totalBytes;
            this.uploadProgress.set(Math.min(99, Math.round(overall * 100)));
          } else if (event.type === HttpEventType.Response && !settled) {
            settled = true;
            resolve();
          }
        },
        error: (err: unknown) => {
          if (!settled) {
            settled = true;
            reject(err);
          }
        },
        complete: () => {
          if (!settled) {
            settled = true;
            resolve();
          }
        },
      });
    });
  }

  private async uploadChunked(
    file: File,
    baseBytes: number,
    totalBytes: number,
  ): Promise<void> {
    const init = await firstValueFrom(
      this.api.initUpload(file.name, file.size, this.selectedProfile() || null),
    );
    let sent = 0;
    const parts: { part_number: number; etag: string | null }[] = [];

    try {
      for (let index = 0; index < init.total_parts; index += 1) {
        const partNumber = index + 1;
        const start = index * init.part_size;
        const end = Math.min(file.size, start + init.part_size);
        const chunk = file.slice(start, end);
        let uploaded: { etag: string | null } | null = null;
        let lastError: unknown = null;

        for (let attempt = 1; attempt <= 5; attempt += 1) {
          try {
            if (init.storage_backend === 's3' && init.part_urls[index]) {
              try {
                uploaded = await this.uploadPartPresigned(
                  init.part_urls[index],
                  chunk,
                  (loaded) => {
                    const overall = (baseBytes + sent + loaded) / totalBytes;
                    this.uploadProgress.set(
                      Math.min(99, Math.round(overall * 100)),
                    );
                  },
                );
              } catch {
                uploaded = await this.uploadPartRelay(
                  init.upload_id,
                  partNumber,
                  chunk,
                  (loaded) => {
                    const overall = (baseBytes + sent + loaded) / totalBytes;
                    this.uploadProgress.set(
                      Math.min(99, Math.round(overall * 100)),
                    );
                  },
                );
              }
            } else {
              uploaded = await this.uploadPartRelay(
                init.upload_id,
                partNumber,
                chunk,
                (loaded) => {
                  const overall = (baseBytes + sent + loaded) / totalBytes;
                  this.uploadProgress.set(
                    Math.min(99, Math.round(overall * 100)),
                  );
                },
              );
            }
            break;
          } catch (err: unknown) {
            lastError = err;
            if (attempt < 5) {
              await this.sleep(500 * 2 ** (attempt - 1));
            }
          }
        }

        if (!uploaded) {
          throw lastError ?? new Error(`falha no envio da parte ${partNumber}`);
        }
        parts.push({ part_number: partNumber, etag: uploaded.etag });
        sent += chunk.size;
        this.uploadProgress.set(
          Math.min(99, Math.round(((baseBytes + sent) / totalBytes) * 100)),
        );
      }

      await firstValueFrom(this.api.completeUpload(init.upload_id, parts));
    } catch (err: unknown) {
      void firstValueFrom(this.api.cancelUpload(init.upload_id)).catch(
        () => undefined,
      );
      throw err;
    }
  }

  private uploadPartRelay(
    uploadId: string,
    partNumber: number,
    part: Blob,
    onProgress: (loaded: number) => void,
  ): Promise<{ etag: string | null }> {
    return new Promise((resolve, reject) => {
      let settled = false;
      this.api.uploadPart(uploadId, partNumber, part).subscribe({
        next: (event) => {
          if (event.type === HttpEventType.UploadProgress) {
            onProgress(Math.min(part.size, event.loaded));
          } else if (event.type === HttpEventType.Response && !settled) {
            settled = true;
            onProgress(part.size);
            resolve({
              etag: (event as HttpResponse<UploadPartResult>).body?.etag ?? null,
            });
          }
        },
        error: (err: unknown) => {
          if (!settled) {
            settled = true;
            reject(err);
          }
        },
      });
    });
  }

  private uploadPartPresigned(
    url: string,
    part: Blob,
    onProgress: (loaded: number) => void,
  ): Promise<{ etag: string | null }> {
    return new Promise((resolve, reject) => {
      let settled = false;
      this.api.uploadPresigned(url, part).subscribe({
        next: (event) => {
          if (event.type === HttpEventType.UploadProgress) {
            onProgress(Math.min(part.size, event.loaded));
          } else if (event.type === HttpEventType.Response && !settled) {
            settled = true;
            onProgress(part.size);
            const etag =
              event.headers.get('ETag') ?? event.headers.get('etag');
            resolve({ etag: etag ? etag.replace(/"/g, '') : null });
          }
        },
        error: (err: unknown) => {
          if (!settled) {
            settled = true;
            reject(err);
          }
        },
      });
    });
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  importPathNow(): void {
    const path = this.importPath().trim();
    if (!path) {
      this.error.set('Informe um caminho de arquivo ou pasta para importar.');
      return;
    }
    this.importing.set(true);
    this.error.set(null);
    this.api.importVideos(path, this.selectedProfile() || null).subscribe({
      next: (items) => {
        this.importing.set(false);
        this.importPath.set('');
        this.showToast(`${items.length} vídeo(s) importado(s).`);
        this.load();
      },
      error: (err: unknown) => {
        this.importing.set(false);
        this.error.set(this.errorMessage(err, 'Falha ao importar o caminho.'));
      },
    });
  }

  scanFolder(): void {
    this.scanning.set(true);
    this.error.set(null);
    const path = this.importPath().trim();
    this.api.scanFolder(path || null, this.selectedProfile() || null).subscribe({
      next: (items) => {
        this.scanning.set(false);
        this.showToast(
          items.length
            ? `${items.length} vídeo(s) encontrado(s) na pasta.`
            : 'Nenhum vídeo novo encontrado.',
        );
        this.load();
      },
      error: (err: unknown) => {
        this.scanning.set(false);
        this.error.set(this.errorMessage(err, 'Falha ao varrer a pasta.'));
      },
    });
  }

  analyze(video: Video): void {
    this.api.analyzeVideo(video.id).subscribe({
      next: () => {
        this.showToast(`Análise enfileirada: ${video.filename}`);
        this.refresh();
      },
      error: (err: unknown) => {
        this.error.set(this.errorMessage(err, 'Falha ao enfileirar a análise.'));
      },
    });
  }

  selectProfile(id: string): void {
    this.selectedProfile.set(id);
  }

  profileName(id: string | null): string {
    if (!id) {
      return 'Perfil padrão';
    }
    return this.profiles().find((profile) => profile.id === id)?.name ?? 'Perfil';
  }

  isActive(video: Video): boolean {
    return video.status === 'queued' || video.status === 'analyzing';
  }

  progress(video: Video): number {
    return Math.round((video.job_progress ?? 0) * 100);
  }

  statusClasses(video: Video): string {
    return videoStatusClasses(video.status);
  }

  statusLabel(video: Video): string {
    return videoStatusLabel(video.status);
  }

  duration(value: number | null): string {
    return formatDuration(value);
  }

  date(value: string | null): string {
    return formatDateTime(value);
  }

  bytes(value: number): string {
    return formatBytes(value);
  }

  thumbnailUrl(video: Video): string {
    return this.api.videoThumbnailUrl(video.id);
  }

  toggleSelection(video: Video, event?: Event): void {
    event?.preventDefault();
    event?.stopPropagation();
    const next = new Set(this.selected());
    if (next.has(video.id)) {
      next.delete(video.id);
    } else {
      next.add(video.id);
    }
    this.selected.set(next);
  }

  isSelected(video: Video): boolean {
    return this.selected().has(video.id);
  }

  selectAllVisible(): void {
    this.selected.set(new Set(this.filteredVideos().map((video) => video.id)));
  }

  clearSelection(): void {
    this.selected.set(new Set());
  }

  requestDelete(video: Video, event?: Event): void {
    event?.preventDefault();
    event?.stopPropagation();
    this.deleteTargets.set([video]);
  }

  requestBulkDelete(): void {
    const targets = this.videos().filter((video) =>
      this.selected().has(video.id),
    );
    if (targets.length) {
      this.deleteTargets.set(targets);
    }
  }

  cancelDelete(): void {
    if (!this.deleting()) {
      this.deleteTargets.set([]);
    }
  }

  confirmDelete(): void {
    const targets = this.deleteTargets();
    if (!targets.length || this.deleting()) return;
    this.deleting.set(true);
    this.error.set(null);
    if (targets.length === 1) {
      this.api.deleteVideo(targets[0].id).subscribe({
        next: () => {
          this.afterDelete([targets[0].id], [], true);
        },
        error: (err: unknown) => {
          this.deleting.set(false);
          this.deleteTargets.set([]);
          this.error.set(this.errorMessage(err, 'Falha ao excluir o vídeo.'));
        },
      });
      return;
    }
    this.api.bulkDeleteVideos(targets.map((video) => video.id)).subscribe({
      next: (result) => this.afterDelete(result.deleted, result.failed, false),
      error: (err: unknown) => {
        this.deleting.set(false);
        this.deleteTargets.set([]);
        this.error.set(this.errorMessage(err, 'Falha ao excluir os vídeos.'));
      },
    });
  }

  private afterDelete(
    deleted: string[],
    failed: { id: string; detail: string }[],
    single: boolean,
  ): void {
    this.deleting.set(false);
    this.deleteTargets.set([]);
    this.selected.set(new Set());
    if (deleted.length) {
      const removed = new Set(deleted);
      this.videos.update((videos) => videos.filter((video) => !removed.has(video.id)));
      this.showToast(
        single
          ? 'Vídeo excluído.'
          : `${deleted.length} vídeo(s) excluído(s).`,
      );
    }
    if (failed.length) {
      this.error.set(
        failed
          .slice(0, 3)
          .map((item) => item.detail)
          .join(' | '),
      );
    }
    this.load();
  }

  cancelAnalysis(video: Video, event?: Event): void {
    event?.preventDefault();
    event?.stopPropagation();
    if (!video.job_id) return;
    this.api.cancelJob(video.job_id).subscribe({
      next: () => {
        this.showToast('Cancelamento solicitado. Aguarde para excluir.');
        setTimeout(() => this.refresh(), 1200);
        setTimeout(() => this.refresh(), 3000);
      },
      error: (err: unknown) => {
        this.error.set(this.errorMessage(err, 'Falha ao cancelar a análise.'));
      },
    });
  }

  showToast(message: string): void {
    this.toast.set(message);
    setTimeout(() => this.toast.set(null), 3500);
  }

  private errorMessage(error: unknown, fallback: string): string {
    const detail = (error as { error?: { detail?: unknown } })?.error?.detail;
    return typeof detail === 'string' ? detail : fallback;
  }
}
