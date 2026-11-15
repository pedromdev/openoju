import { Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
  selector: 'app-confirm-dialog',
  template: `
    @if (open) {
      <div
        class="fixed inset-0 z-50 grid place-items-center bg-slate-950/80 p-4 backdrop-blur-sm"
        role="presentation"
        (click)="cancelled.emit()"
      >
        <div
          class="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl shadow-black/60"
          role="dialog"
          aria-modal="true"
          [attr.aria-label]="title"
          (click)="$event.stopPropagation()"
        >
          <h2 class="text-lg font-semibold text-white">{{ title }}</h2>
          <p class="mt-2 whitespace-pre-line text-sm text-slate-300">{{ message }}</p>
          <div class="mt-6 flex justify-end gap-2">
            <button
              type="button"
              class="rounded-xl border border-slate-700 px-4 py-2 text-sm text-slate-300 transition hover:border-slate-500 hover:text-white"
              (click)="cancelled.emit()"
            >
              {{ cancelLabel }}
            </button>
            <button
              type="button"
              class="rounded-xl px-4 py-2 text-sm font-medium transition disabled:opacity-50"
              [class]="danger ? 'bg-rose-500 text-white hover:bg-rose-400' : 'bg-emerald-500 text-slate-950 hover:bg-emerald-400'"
              [disabled]="busy"
              (click)="confirmed.emit()"
            >
              {{ busy ? 'Processando…' : confirmLabel }}
            </button>
          </div>
        </div>
      </div>
    }
  `,
})
export class ConfirmDialog {
  @Input() open = false;
  @Input() title = 'Confirmar';
  @Input() message = '';
  @Input() confirmLabel = 'Confirmar';
  @Input() cancelLabel = 'Cancelar';
  @Input() danger = true;
  @Input() busy = false;
  @Output() confirmed = new EventEmitter<void>();
  @Output() cancelled = new EventEmitter<void>();
}
