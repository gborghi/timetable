// Promise-based dialogs so destructive actions / text prompts use the app's
// styled Modal instead of the browser's native confirm()/prompt() (unstyled,
// blocking). Usage:
//
//   import { confirmDialog, promptDialog } from '$lib/confirm';
//   if (!(await confirmDialog('Eliminare questo docente?'))) return;
//   const name = await promptDialog('Nome della vista:');  // string | null
//
// A single <ConfirmDialog/> mounted in the root layout renders whatever
// request is set here.
import { writable } from 'svelte/store';

export interface DialogRequest {
  message: string;
  title: string;
  confirmLabel: string;
  cancelLabel: string;
  danger: boolean;
  /** when set, render a text input; resolve its value (or null on cancel). */
  input: { defaultValue: string; placeholder: string } | null;
  /** internal: resolves the promise returned by confirmDialog/promptDialog. */
  _resolve: (v: boolean | string | null) => void;
}

export const confirmRequest = writable<DialogRequest | null>(null);

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
      input: null,
      _resolve: (v) => resolve(v === true),
    });
  });
}

export function promptDialog(
  message: string,
  opts: {
    title?: string;
    defaultValue?: string;
    placeholder?: string;
    confirmLabel?: string;
    cancelLabel?: string;
  } = {},
): Promise<string | null> {
  return new Promise((resolve) => {
    confirmRequest.set({
      message,
      title: opts.title ?? 'Inserisci',
      confirmLabel: opts.confirmLabel ?? 'OK',
      cancelLabel: opts.cancelLabel ?? 'Annulla',
      danger: false,
      input: { defaultValue: opts.defaultValue ?? '', placeholder: opts.placeholder ?? '' },
      _resolve: (v) => resolve(typeof v === 'string' ? v : null),
    });
  });
}
