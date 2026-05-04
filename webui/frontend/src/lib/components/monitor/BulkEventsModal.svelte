<script>
  // Bulk operations on /monitor event rows. Three actions:
  //   set_classroom    payload {classroom_name}
  //   clear_classroom  no payload
  //   set_lock         payload {locked: bool}
  //
  // Same dry-run -> verify -> conflicts -> skip|override -> apply flow
  // as BulkApplyModal, but the request shape carries (lesson_id,
  // assignment_id) tuples because a "row" in /monitor is either a real
  // Lesson or a placeholder for a missing-hour Assignment.
  //
  // Props:
  //   open          boolean, two-way bound
  //   selectedRows  array of /monitor rows (must include lesson_id and
  //                 assignment_id; lesson_id may be null for placeholders)
  //   rooms         array of classroom name strings (for the picker)
  //   onDone        callback after a successful apply

  import Modal from '../Modal.svelte';
  import { api } from '../../api';
  import { flash } from '../../stores';

  export let open = false;
  export let selectedRows = [];
  export let rooms = [];
  export let onDone = () => {};

  let action = 'set_classroom';
  let dryRun = null;     // { candidates, conflicts, n_targets }
  let onConflict = 'skip';
  let busy = false;

  // payload state per action
  let classroomName = '';
  let lockValue = true;

  $: rowsPayload = selectedRows.map((r) => ({
    lesson_id: r.lesson_id ?? null,
    assignment_id: r.assignment_id ?? null,
  }));
  $: nLessons = selectedRows.filter((r) => r.lesson_id != null).length;
  $: nPlaceholders = selectedRows.length - nLessons;

  function buildPayload() {
    if (action === 'set_classroom') {
      return { classroom_name: classroomName.trim() };
    }
    if (action === 'set_lock') {
      return { locked: !!lockValue };
    }
    return {};
  }

  async function verify() {
    if (selectedRows.length === 0) {
      flash('Nessuna riga selezionata', 'error');
      return;
    }
    if (action === 'set_classroom' && !classroomName.trim()) {
      flash("Scegli un'aula", 'error');
      return;
    }
    busy = true;
    try {
      const payload = buildPayload();
      dryRun = await api.post('/api/bulk/events/dry-run', {
        rows: rowsPayload, action, payload, on_conflict: 'dry_run',
      });
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally { busy = false; }
  }

  async function apply() {
    if (selectedRows.length === 0) {
      flash('Nessuna riga selezionata', 'error');
      return;
    }
    busy = true;
    try {
      const payload = buildPayload();
      const res = await api.post('/api/bulk/events/apply', {
        rows: rowsPayload, action, payload, on_conflict: onConflict,
      });
      const lvl = res.errors?.length ? 'warning' : 'success';
      flash(
        `Applicate ${res.n_applied}, ${res.n_overridden} con override, `
        + `${res.n_skipped} skip`,
        lvl,
      );
      onDone(res);
      open = false;
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally { busy = false; }
  }

  function reset() {
    dryRun = null;
  }

  $: if (open) { dryRun = null; }
</script>

<Modal {open} title="Operazione collettiva su {selectedRows.length} eventi"
       onClose={() => (open = false)}>
  <div class="space-y-4">
    <div class="text-xs text-ink-500">
      {nLessons} lezioni schedulate
      {#if nPlaceholders}
        + {nPlaceholders} placeholder (non schedulati)
      {/if}
    </div>

    <div class="flex flex-wrap gap-2 items-center">
      <label class="text-sm">Azione:</label>
      <select bind:value={action} on:change={reset}
              class="px-2 py-1 border border-ink-200 rounded">
        <option value="set_classroom">Assegna aula</option>
        <option value="clear_classroom">Togli aula (lascia che il solver riassegni)</option>
        <option value="set_lock">Blocca / sblocca</option>
      </select>
    </div>

    {#if action === 'set_classroom'}
      <div class="space-y-2">
        <label class="text-xs block">Aula di destinazione</label>
        {#if rooms.length}
          <select bind:value={classroomName} on:change={reset}
                  class="px-2 py-1 border border-ink-200 rounded">
            <option value="">-- scegli --</option>
            {#each rooms as r}
              <option value={r}>{r}</option>
            {/each}
          </select>
        {:else}
          <input bind:value={classroomName} on:input={reset}
                 class="w-64 px-2 py-1 border border-ink-200 rounded"
                 placeholder="es. LabFisica"/>
        {/if}
        <p class="text-[11px] text-ink-500">
          I placeholder (eventi non schedulati) verranno saltati: senza
          uno slot temporale non c'e' una lezione su cui impostare l'aula.
        </p>
      </div>
    {:else if action === 'clear_classroom'}
      <p class="text-xs text-ink-500">
        Imposta classroom = NULL su tutte le lezioni schedulate
        selezionate. Utile prima di rilanciare la fase di assegnazione
        aule. I placeholder vengono saltati (non hanno una lezione).
      </p>
    {:else if action === 'set_lock'}
      <div class="space-y-2">
        <div class="flex gap-3 text-sm items-center">
          <label class="flex gap-1 items-center">
            <input type="radio" bind:group={lockValue} value={true} on:change={reset}/>
            Blocca (locked = true)
          </label>
          <label class="flex gap-1 items-center">
            <input type="radio" bind:group={lockValue} value={false} on:change={reset}/>
            Sblocca (locked = false)
          </label>
        </div>
        <p class="text-[11px] text-ink-500">
          Opera sull'Assignment, quindi vale anche per i placeholder.
          Cattedre selezionate piu' volte (lezioni multiple) vengono
          deduplicate dal backend.
        </p>
      </div>
    {/if}

    <div class="border-t border-ink-200 pt-3 space-y-3">
      <div class="flex flex-wrap gap-2 items-center">
        <button class="btn" on:click={verify} disabled={busy}>
          1) Verifica conflitti
        </button>
        {#if dryRun}
          <span class="text-xs text-ink-500">
            ({dryRun.candidates.length} ok / {dryRun.conflicts.length} in conflitto)
          </span>
        {/if}
      </div>

      {#if dryRun && dryRun.conflicts.length > 0}
        <div class="card !shadow-none p-2 text-xs bg-amber-50 border-amber-300">
          <strong>Conflitti rilevati ({dryRun.conflicts.length}):</strong>
          <ul class="list-disc ml-5 max-h-32 overflow-auto">
            {#each dryRun.conflicts as c}
              <li><strong>{c.name}</strong>: {c.reason}</li>
            {/each}
          </ul>
        </div>
        <label class="text-xs flex gap-2 items-center">
          <input type="radio" bind:group={onConflict} value="skip"/>
          Salta i {dryRun.conflicts.length} in conflitto, applica solo
          ai {dryRun.candidates.length} liberi
        </label>
        <label class="text-xs flex gap-2 items-center">
          <input type="radio" bind:group={onConflict} value="override"/>
          Override: forza l'applicazione anche sui conflittuali
          (i placeholder restano comunque saltati)
        </label>
      {/if}

      {#if dryRun}
        <div class="flex gap-2">
          <button class="btn-primary" on:click={apply} disabled={busy}>
            2) Applica
          </button>
          <button class="btn" on:click={() => (open = false)} disabled={busy}>
            Annulla
          </button>
        </div>
      {/if}
    </div>
  </div>
</Modal>
