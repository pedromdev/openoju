import { VideoStatus, ReviewStatus } from './models';

export function pad(value: number): string {
  return value.toString().padStart(2, '0');
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) {
    return '--:--';
  }
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(secs)}`
    : `${pad(minutes)}:${pad(secs)}`;
}

export function formatTimeRange(start: number, end: number): string {
  return `${formatDuration(start)} – ${formatDuration(end)}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString('pt-BR');
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) {
    return '0 B';
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const exponent = Math.min(
    units.length - 1,
    Math.floor(Math.log(bytes) / Math.log(1024)),
  );
  const value = bytes / Math.pow(1024, exponent);
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[exponent]}`;
}

export function formatScore(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) {
    return '—';
  }
  return `${(score * 100).toFixed(1)}%`;
}

export function videoStatusLabel(status: VideoStatus): string {
  switch (status) {
    case 'uploaded':
      return 'Importado';
    case 'queued':
      return 'Na fila';
    case 'analyzing':
      return 'Analisando';
    case 'ready':
      return 'Pronto';
    case 'failed':
      return 'Falhou';
    default:
      return status;
  }
}

export function videoStatusClasses(status: VideoStatus): string {
  switch (status) {
    case 'ready':
      return 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30';
    case 'analyzing':
      return 'bg-sky-500/15 text-sky-300 ring-sky-500/30';
    case 'queued':
      return 'bg-amber-500/15 text-amber-300 ring-amber-500/30';
    case 'failed':
      return 'bg-rose-500/15 text-rose-300 ring-rose-500/30';
    default:
      return 'bg-slate-500/15 text-slate-300 ring-slate-500/30';
  }
}

export function reviewStatusLabel(status: ReviewStatus): string {
  switch (status) {
    case 'confirmed':
      return 'Confirmado';
    case 'dismissed':
      return 'Descartado';
    default:
      return 'Novo';
  }
}

export function reviewStatusClasses(status: ReviewStatus): string {
  switch (status) {
    case 'confirmed':
      return 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30';
    case 'dismissed':
      return 'bg-slate-500/15 text-slate-400 ring-slate-500/30';
    default:
      return 'bg-amber-500/15 text-amber-300 ring-amber-500/30';
  }
}

export function eventColor(status: ReviewStatus): string {
  switch (status) {
    case 'confirmed':
      return 'bg-emerald-400/80 hover:bg-emerald-300';
    case 'dismissed':
      return 'bg-slate-500/60 hover:bg-slate-400';
    default:
      return 'bg-amber-400/80 hover:bg-amber-300';
  }
}
