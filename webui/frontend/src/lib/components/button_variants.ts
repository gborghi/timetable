/**
 * Button variant → base class mapping. Pure (no Svelte) so it is unit-tested
 * with node:test. Consumed by Button.svelte. Classes reuse the existing
 * app.css component layer (.btn / .btn-primary / .btn-danger) plus a couple
 * of inline-utility variants for ghost/icon buttons.
 */
export type ButtonVariant =
  | 'primary'
  | 'secondary'
  | 'danger'
  | 'ghost'
  | 'icon';

export const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: 'btn-primary',
  secondary: 'btn',
  danger: 'btn-danger',
  ghost: 'px-3 py-1.5 text-[12.5px] rounded-[7px] text-ink-500 hover:bg-ink-100 hover:text-ink-900 focus-ring',
  icon: 'p-1.5 rounded-[7px] text-ink-500 hover:bg-ink-100 hover:text-ink-900 focus-ring inline-flex items-center justify-center',
};

/** Resolve a variant to its base class, falling back to `primary`. */
export function variantClass(variant: string | undefined): string {
  return BUTTON_VARIANTS[(variant as ButtonVariant)] ?? BUTTON_VARIANTS.primary;
}
