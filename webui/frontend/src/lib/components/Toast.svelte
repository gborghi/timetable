<script>
  import { toast } from '../stores.js';

  // Pick the right ARIA live channel: errors are 'assertive' (announced
  // immediately), successes/info are 'polite' (queued, less intrusive).
  $: live = ($toast?.tone === 'error') ? 'assertive' : 'polite';
</script>

<!-- The container is permanent so screen readers can subscribe; only the
     inner card flickers in/out as toasts come and go. -->
<div class="fixed bottom-6 right-6 z-50 max-w-sm pointer-events-none"
     aria-live={live}
     aria-atomic="true"
     role="status">
  {#if $toast}
    <div class="card px-4 py-3 pointer-events-auto"
         class:border-red-300={$toast.tone === 'error'}
         class:border-emerald-300={$toast.tone === 'success'}
         class:border-amber-300={$toast.tone === 'warning'}>
      <div class="flex items-start gap-3">
        <span aria-hidden="true"
          class="mt-0.5 inline-block w-2 h-2 rounded-full"
          class:bg-red-500={$toast.tone === 'error'}
          class:bg-emerald-500={$toast.tone === 'success'}
          class:bg-amber-500={$toast.tone === 'warning'}
          class:bg-accent-500={!['error','success','warning'].includes($toast.tone)}>
        </span>
        <div class="text-sm text-ink-900 whitespace-pre-line flex-1">
          {#if $toast.tone === 'error'}<span class="sr-only">Errore: </span>{/if}
          {#if $toast.tone === 'success'}<span class="sr-only">Successo: </span>{/if}
          {#if $toast.tone === 'warning'}<span class="sr-only">Avviso: </span>{/if}
          {$toast.msg}
        </div>
        {#if $toast.action && $toast.action.label}
          <button class="btn !text-xs !px-2 !py-1 focus-ring"
                  on:click={() => $toast.action.fn?.()}>
            {$toast.action.label}
          </button>
        {/if}
      </div>
    </div>
  {/if}
</div>
