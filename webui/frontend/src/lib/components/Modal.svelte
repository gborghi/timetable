<script>
  export let open = false;
  export let title = '';
  export let onClose = () => { open = false; };
</script>

{#if open}
  <div class="fixed inset-0 z-40 flex items-start justify-center bg-ink-900/40 backdrop-blur-sm overflow-auto py-12 px-4"
       on:click|self={onClose} role="dialog" aria-modal="true">
    <div class="card w-full max-w-3xl">
      <div class="flex items-center justify-between border-b border-ink-100 px-4 py-3">
        <h2 class="font-semibold">{title}</h2>
        <button class="btn !px-2 !py-1" on:click={onClose}>Chiudi</button>
      </div>
      <div class="p-4">
        <slot />
      </div>
    </div>
  </div>
{/if}
