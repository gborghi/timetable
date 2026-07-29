<script>
  // Single instance mounted in +layout.svelte; renders the pending
  // confirmDialog()/promptDialog() request as a styled Modal and resolves it.
  import Modal from './Modal.svelte';
  import { confirmRequest } from '$lib/confirm';

  let inputValue = '';
  // Seed the text field whenever a prompt request arrives.
  $: if ($confirmRequest?.input) inputValue = $confirmRequest.input.defaultValue;

  function settle(v) {
    const req = $confirmRequest;
    $confirmRequest = null;
    if (req) req._resolve(v);
  }
  function onConfirm() {
    settle($confirmRequest.input ? inputValue : true);
  }
  function onCancel() {
    settle($confirmRequest.input ? null : false);
  }
  function onKeydown(e) {
    if (e.key === 'Enter') { e.preventDefault(); onConfirm(); }
  }
</script>

{#if $confirmRequest}
  <Modal open={true} title={$confirmRequest.title} onClose={onCancel}>
    <p class="text-sm text-ink-700 whitespace-pre-line">{$confirmRequest.message}</p>
    {#if $confirmRequest.input}
      <!-- svelte-ignore a11y_autofocus -->
      <input class="mt-3 w-full rounded border border-ink-200 px-2 py-1 text-sm"
             bind:value={inputValue}
             placeholder={$confirmRequest.input.placeholder}
             on:keydown={onKeydown}
             autofocus
             data-testid="confirm-input"/>
    {/if}
    <div class="mt-4 flex justify-end gap-2">
      <button type="button" class="btn" on:click={onCancel}
              data-testid="confirm-cancel">
        {$confirmRequest.cancelLabel}
      </button>
      <button type="button"
              class={$confirmRequest.danger ? 'btn-danger' : 'btn-primary'}
              on:click={onConfirm}
              data-testid="confirm-ok">
        {$confirmRequest.confirmLabel}
      </button>
    </div>
  </Modal>
{/if}
