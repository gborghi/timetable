<script>
  import { onDestroy, tick } from 'svelte';

  export let open = false;
  export let title = '';
  export let onClose = () => { open = false; };
  // Optional: aria-describedby target id (caller can pass an id of an
  // element inside the slot).
  export let describedBy = null;

  let dialog;
  let lastFocused = null;

  // Open/close lifecycle: snapshot the previously-focused element, move
  // focus into the dialog, restore on close.
  $: if (typeof document !== 'undefined') {
    if (open) {
      lastFocused = document.activeElement;
      document.body.style.overflow = 'hidden';
      tick().then(() => {
        const focusable = dialog?.querySelector(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable) focusable.focus();
        else dialog?.focus();
      });
    } else {
      document.body.style.overflow = '';
      if (lastFocused && typeof lastFocused.focus === 'function') {
        lastFocused.focus();
      }
    }
  }

  onDestroy(() => {
    if (typeof document !== 'undefined') document.body.style.overflow = '';
  });

  function focusables() {
    if (!dialog) return [];
    return Array.from(dialog.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]),'
      + ' select:not([disabled]), textarea:not([disabled]),'
      + ' [tabindex]:not([tabindex="-1"])'
    )).filter((el) => !el.hasAttribute('aria-hidden'));
  }

  function onKey(ev) {
    if (!open) return;
    if (ev.key === 'Escape') {
      ev.preventDefault();
      onClose();
      return;
    }
    if (ev.key === 'Tab') {
      const list = focusables();
      if (list.length === 0) return;
      const first = list[0];
      const last = list[list.length - 1];
      if (ev.shiftKey && document.activeElement === first) {
        ev.preventDefault(); last.focus();
      } else if (!ev.shiftKey && document.activeElement === last) {
        ev.preventDefault(); first.focus();
      }
    }
  }
</script>

<svelte:window on:keydown={onKey}/>

{#if open}
  <div class="fixed inset-0 z-40 flex items-start justify-center bg-ink-900/40 backdrop-blur-sm overflow-auto py-12 px-4"
       on:click|self={onClose}
       role="presentation">
    <div class="card w-full max-w-3xl outline-none"
         bind:this={dialog}
         role="dialog"
         aria-modal="true"
         aria-labelledby="modal-title"
         aria-describedby={describedBy}
         tabindex="-1">
      <div class="flex items-center justify-between border-b border-ink-100 px-4 py-3">
        <h2 id="modal-title" class="font-semibold">{title}</h2>
        <button class="btn !px-2 !py-1 focus-ring"
                aria-label="Chiudi finestra"
                on:click={onClose}>Chiudi</button>
      </div>
      <div class="p-4">
        <slot />
      </div>
    </div>
  </div>
{/if}
