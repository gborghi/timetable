// Promise-based confirmation dialog, so destructive actions use the app's
// styled Modal instead of the browser's native confirm() (unstyled, and
// blocking). Usage:
//
//   import { confirmDialog } from '$lib/confirm';
//   if (!(await confirmDialog('Eliminare questo docente?'))) return;
//
// A single <ConfirmDialog/> mounted in the root layout renders whatever
// request is set here.
import { writable } from 'svelte/store';

export interface ConfirmRequest {
  message: string;
  title: string;
  confirmLabel: string;
  cancelLabel: string;
  danger: boolean;
  /** internal: resolves the promise returned by confirmDialog() */
  _resolve: (ok: boolean) => void;
}

export const confirmRequest = writable<ConfirmRequest | null>(null);

export function confirmDialog(
  message: string,
  opts: {
    title?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
  } = {},
): Promise<boolean> {
  return new Promise((resolve) => {
    confirmRequest.set({
      message,
      title: opts.title ?? 'Conferma',
      confirmLabel: opts.confirmLabel ?? 'Conferma',
      cancelLabel: opts.cancelLabel ?? 'Annulla',
      danger: opts.danger ?? true,
      _resolve: resolve,
    });
  });
}
