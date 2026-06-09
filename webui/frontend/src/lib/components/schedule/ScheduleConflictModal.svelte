<script>
  /**
   * Reusable conflict-resolution modal.
   *
   * Bind `open` from the caller. Caller passes `details` (an object
   * with arrays `teacher_busy`, `class_busy`, `room_busy` of conflict
   * descriptions returned by /api/schedule/lesson?on_conflict=dry_run
   * or /api/monitor/event?on_conflict=dry_run) plus a `subject` string
   * describing the slot being placed.
   *
   * Three resolution buttons:
   *   - "Annulla" : closes without action (calls onCancel).
   *   - "Svincola": calls onResolve('unbind') -- room conflicts clear
   *                 the conflicting classroom_name only; teacher/class
   *                 conflicts delete the conflicting Lesson rows.
   *   - "Elimina" : calls onResolve('delete') -- removes every
   *                 conflicting Lesson row.
   *
   * Per Giovanni's spec the "svincola"/"elimina" terminology MUST
   * appear on every conflict modal. This component is the canonical
   * implementation.
   */
  import Modal from '$lib/components/Modal.svelte';

  export let open = false;
  export let title = 'Conflitto rilevato';
  export let subject = '';
  export let details = { teacher_busy: [], class_busy: [], room_busy: [] };
  export let onCancel = () => { open = false; };
  export let onResolve = (_strategy) => {};
  // When false, hide the "Svincola" button. Used by the drop-on-occupied
  // flow (/schedule), where the user is replacing the slot occupants
  // wholesale -- partial unbind doesn't make sense there.
  export let showUnbind = true;
  // Override the label of the destructive primary action.
  export let deleteLabel = 'Elimina evento confliggente';

  $: hasTeacher = (details.teacher_busy || []).length > 0;
  $: hasClass   = (details.class_busy   || []).length > 0;
  $: hasRoom    = (details.room_busy    || []).length > 0;

  const _DAYS_IT = ['', 'lun', 'mar', 'mer', 'gio', 'ven', 'sab'];
  function describe(r) {
    const when = (r.day != null && r.hour != null)
      ? ` [${_DAYS_IT[r.day] || ('g' + r.day)} ${r.hour}:00]` : '';
    return `${r.class_name} - ${r.subject} (${r.teacher_name})`
         + (r.classroom_name ? ` in ${r.classroom_name}` : '') + when;
  }
</script>

<Modal {open} {title} onClose={onCancel}>
  <div data-testid="schedule-conflict-modal">
  {#if subject}
    <p class="text-sm text-ink-500 mb-3">{subject}</p>
  {/if}

  {#if hasTeacher}
    <div class="mb-3" data-testid="schedule-conflict-teacher">
      <h3 class="text-sm font-medium mb-1">Conflitto docente</h3>
      <ul class="text-sm list-disc pl-5 text-ink-700">
        {#each details.teacher_busy as r}
          <li>{describe(r)}</li>
        {/each}
      </ul>
    </div>
  {/if}
  {#if hasClass}
    <div class="mb-3" data-testid="schedule-conflict-class">
      <h3 class="text-sm font-medium mb-1">Conflitto classe</h3>
      <ul class="text-sm list-disc pl-5 text-ink-700">
        {#each details.class_busy as r}
          <li>{describe(r)}</li>
        {/each}
      </ul>
    </div>
  {/if}
  {#if hasRoom}
    <div class="mb-3" data-testid="schedule-conflict-room">
      <h3 class="text-sm font-medium mb-1">Conflitto aula</h3>
      <ul class="text-sm list-disc pl-5 text-ink-700">
        {#each details.room_busy as r}
          <li>{describe(r)}</li>
        {/each}
      </ul>
    </div>
  {/if}

  <div class="text-xs text-ink-500 mt-3 space-y-1">
    <p><b>Svincola</b>: rimuove SOLO l'attributo che confligge -- per
       i conflitti aula libera il classroom_name della lezione
       confliggente; per docente / classe (non si puo' svincolare
       parzialmente perche' la riga IS la tupla) elimina la lezione.</p>
    <p><b>Elimina</b>: rimuove l'INTERA lezione confliggente da ogni
       categoria.</p>
  </div>

  <div class="flex justify-end gap-2 mt-4">
    <button class="btn" on:click={onCancel} data-testid="schedule-conflict-cancel">Annulla</button>
    {#if showUnbind}
      <button class="btn-amber" on:click={() => onResolve('unbind')} data-testid="schedule-conflict-unbind">
        Svincola evento confliggente
      </button>
    {/if}
    <button class="btn-red" on:click={() => onResolve('delete')} data-testid="schedule-conflict-delete">
      {deleteLabel}
    </button>
  </div>
  </div>
</Modal>
