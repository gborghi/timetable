<script>
  /**
   * Reusable button: consistent styling, a built-in loading spinner, and
   * uniform disabled / focus / aria handling. Replaces copy-pasted
   * `.btn`/`.btn-primary`/`.btn-danger` markup.
   *
   *   <Button variant="primary" loading={busy} onclick={save}>Salva</Button>
   *   <Button variant="icon" ariaLabel="Elimina" onclick={del}>🗑</Button>
   *
   * Any extra attribute (data-testid, title, form, name, …) is forwarded to
   * the native <button>. While `loading`, the button is disabled and shows a
   * spinner; while `disabled || loading` it is non-interactive.
   */
  import { variantClass } from './button_variants';

  let {
    variant = 'primary',
    type = 'button',
    loading = false,
    disabled = false,
    ariaLabel = undefined,
    class: klass = '',
    children,
    ...rest
  } = $props();
</script>

<button
  {type}
  class={`${variantClass(variant)} ${klass} relative inline-flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed`}
  disabled={disabled || loading}
  aria-label={ariaLabel}
  aria-busy={loading || undefined}
  {...rest}
>
  {#if loading}
    <span class="btn-spinner" aria-hidden="true"></span>
  {/if}
  {@render children?.()}
</button>
