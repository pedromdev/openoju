import { NgClass } from '@angular/common';
import {
  Component,
  DestroyRef,
  ElementRef,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { ConfirmDialog } from '../../shared/confirm-dialog';
import {
  eventColor,
  formatDateTime,
  formatDuration,
  formatScore,
  formatTimeRange,
  reviewStatusClasses,
  reviewStatusLabel,
  videoStatusClasses,
  videoStatusLabel,
} from '../../core/format';
import { EventItem, Profile, ReviewStatus, Video } from '../../core/models';

@Component({
  selector: 'app-video-detail-page',
  imports: [NgClass, RouterLink, ConfirmDialog],
  templateUrl: './video-detail-page.html',
})
export class VideoDetailPage {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  readonly videoId = this.route.snapshot.paramMap.get('id') ?? '';

  readonly video = signal<Video | null>(null);
  readonly events = signal<EventItem[]>([]);
  readonly profiles = signal<Profile[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly currentTime = signal(0);
  readonly selectedClip = signal<EventItem | null>(null);
  readonly confirmDelete = signal(false);
  readonly deleting = signal(false);
  readonly canManage = computed(() => this.auth.has('videos.manage'));
  readonly canCancelJobs = computed(() => this.auth.has('jobs.cancel'));
  private readonly player = viewChild<ElementRef<HTMLVideoElement>>('player');

  readonly videoSrc = computed(() => {
    const video = this.video();
    return video?.proxy_path ? this.api.videoStreamUrl(video.id) : null;
  });

  readonly duration = computed(() => {
    const video = this.video();
    if (video?.duration_s && video.duration_s > 0) {
      return video.duration_s;
    }
    return Math.max(0, ...this.events().map((event) => event.end_s));
  });

  readonly motionSeconds = computed(() =>
    this.events().reduce(
      (sum, event) => sum + Math.max(0, event.end_s - event.start_s),
      0,
    ),
  );

  readonly currentEvent = computed(() => {
    const time = this.currentTime();
    return (
      this.events().find(
        (event) => time >= event.start_s && time <= event.end_s,
      ) ?? null
    );
  });

  constructor() {
    this.load(true);
    const timer = setInterval(() => this.refresh(), 2000);
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }

  load(showLoading = false): void {
    if (showLoading) {
      this.loading.set(true);
    }
    this.error.set(null);
    forkJoin({
      video: this.api.getVideo(this.videoId),
      events: this.api.getVideoEvents(this.videoId),
      profiles: this.api.listProfiles(),
    }).subscribe({
      next: ({ video, events, profiles }) => {
        this.video.set(video);
        this.events.set(events);
        this.profiles.set(profiles);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.error.set(this.errorMessage(err, 'Não foi possível carregar o vídeo.'));
        this.loading.set(false);
      },
    });
  }

  refresh(): void {
    if (!this.videoId) {
      return;
    }
    this.api.getVideo(this.videoId).subscribe({
      next: (video) => {
        const previous = this.video();
        this.video.set(video);
        if (
          previous?.event_count !== video.event_count ||
          previous?.status !== video.status
        ) {
          this.loadEvents();
        }
      },
      error: () => undefined,
    });
  }

  loadEvents(): void {
    this.api.getVideoEvents(this.videoId).subscribe({
      next: (events) => this.events.set(events),
      error: () => undefined,
    });
  }

  onTimeUpdate(event: Event): void {
    const target = event.target as HTMLVideoElement;
    this.currentTime.set(target.currentTime);
  }

  seekTo(event: EventItem): void {
    const player = this.player()?.nativeElement;
    if (!player) {
      return;
    }
    player.currentTime = Math.max(0, event.start_s);
    void player.play().catch(() => undefined);
  }

  timelineLeft(event: EventItem): number {
    const duration = this.duration();
    return duration > 0 ? Math.max(0, (event.start_s / duration) * 100) : 0;
  }

  timelineWidth(event: EventItem): number {
    const duration = this.duration();
    if (duration <= 0) {
      return 0.5;
    }
    return Math.max(0.5, ((event.end_s - event.start_s) / duration) * 100);
  }

  playheadLeft(): number {
    const duration = this.duration();
    return duration > 0
      ? Math.max(0, Math.min(100, (this.currentTime() / duration) * 100))
      : 0;
  }

  segmentColor(event: EventItem): string {
    return eventColor(event.review_status);
  }

  review(event: EventItem, status: ReviewStatus): void {
    this.api.reviewEvent(event.id, status).subscribe({
      next: (updated) => {
        this.events.update((events) =>
          events.map((item) => (item.id === updated.id ? updated : item)),
        );
      },
      error: (err: unknown) => {
        this.error.set(this.errorMessage(err, 'Falha ao atualizar a revisão.'));
      },
    });
  }

  analyzeAgain(): void {
    this.api.analyzeVideo(this.videoId).subscribe({
      next: () => this.refresh(),
      error: (err: unknown) => {
        this.error.set(this.errorMessage(err, 'Falha ao reenfileirar a análise.'));
      },
    });
  }

  requestDelete(): void {
    this.confirmDelete.set(true);
  }

  cancelDelete(): void {
    if (!this.deleting()) {
      this.confirmDelete.set(false);
    }
  }

  deleteVideo(): void {
    const video = this.video();
    if (!video || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteVideo(video.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(false);
        void this.router.navigate(['/videos']);
      },
      error: (err: unknown) => {
        this.deleting.set(false);
        this.confirmDelete.set(false);
        this.error.set(this.errorMessage(err, 'Falha ao excluir o vídeo.'));
      },
    });
  }

  cancelAnalysis(): void {
    const video = this.video();
    if (!video?.job_id) return;
    this.api.cancelJob(video.job_id).subscribe({
      next: () => {
        this.error.set(null);
        setTimeout(() => this.refresh(), 1200);
        setTimeout(() => this.refresh(), 3000);
      },
      error: (err: unknown) => {
        this.error.set(this.errorMessage(err, 'Falha ao cancelar a análise.'));
      },
    });
  }

  openClip(event: EventItem): void {
    this.selectedClip.set(event);
  }

  closeClip(): void {
    this.selectedClip.set(null);
  }

  clipUrl(event: EventItem): string {
    return this.api.eventClipUrl(event.id);
  }

  thumbnailUrl(event: EventItem): string {
    return this.api.eventThumbnailUrl(event.id);
  }

  eventClasses(event: EventItem): string {
    return reviewStatusClasses(event.review_status);
  }

  eventLabel(event: EventItem): string {
    return reviewStatusLabel(event.review_status);
  }

  statusClasses(video: Video): string {
    return videoStatusClasses(video.status);
  }

  statusLabel(video: Video): string {
    return videoStatusLabel(video.status);
  }

  durationText(value: number | null): string {
    return formatDuration(value);
  }

  rangeText(event: EventItem): string {
    return formatTimeRange(event.start_s, event.end_s);
  }

  scoreText(value: number): string {
    return formatScore(value);
  }

  date(value: string | null): string {
    return formatDateTime(value);
  }

  profileName(id: string | null): string {
    if (!id) {
      return 'Perfil padrão';
    }
    return this.profiles().find((profile) => profile.id === id)?.name ?? 'Perfil';
  }

  jobProgress(video: Video): number {
    return Math.round((video.job_progress ?? 0) * 100);
  }

  isActive(video: Video): boolean {
    return video.status === 'queued' || video.status === 'analyzing';
  }

  private errorMessage(error: unknown, fallback: string): string {
    const detail = (error as { error?: { detail?: unknown } })?.error?.detail;
    return typeof detail === 'string' ? detail : fallback;
  }
}
