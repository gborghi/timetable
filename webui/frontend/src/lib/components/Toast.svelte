<script>
  import { toast } from '../stores.js';
</script>

{#if $toast}
  <div class="fixed bottom-6 right-6 z-50 max-w-sm card px-4 py-3"
       class:border-red-300={$toast.tone === 'error'}
       class:border-emerald-300={$toast.tone === 'success'}>
    <div class="flex items-start gap-3">
      <span class="mt-0.5 inline-block w-2 h-2 rounded-full"
        class:bg-red-500={$toast.tone === 'error'}
        class:bg-emerald-500={$toast.tone === 'success'}
        class:bg-accent-500={$toast.tone !== 'error' && $toast.tone !== 'success'}></span>
      <div class="text-sm text-ink-900 whitespace-pre-line">{$toast.msg}</div>
    </div>
  </div>
{/if}
