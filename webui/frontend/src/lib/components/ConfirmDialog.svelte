<script>
  // Single instance mounted in +layout.svelte; renders the pending
  // confirmDialog() request as a styled Modal and resolves its promise.
  import Modal from './Modal.svelte';
  import { confirmRequest } from '$lib/confirm';

  function settle(ok) {
    const req = $confirmRequest;
    $confirmRequest = null;
    if (req) req._resolve(ok);
  }
</script>

{#if $confirmRequest}
  <Modal open={true} title={$confirmRequest.title} onClose={() => settle(false)}>
    <p class="text-sm text-ink-700 whitespace-pre-line">{$confirmRequest.message}</p>
    <div class="mt-4 flex justify-end gap-2">
      <button type="button" class="btn" on:click={() => settle(false)}
              data-testid="confirm-cancel">
        {$confirmRequest.cancelLabel}
      </button>
      <button type="button"
              class={$confirmRequest.danger ? 'btn-danger' : 'btn-primary'}
              on:click={() => settle(true)}
              data-testid="confirm-ok">
        {$confirmRequest.confirmLabel}
      </button>
    </div>
  </Modal>
{/if}
