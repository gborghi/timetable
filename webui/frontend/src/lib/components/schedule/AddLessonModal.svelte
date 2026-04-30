<script>
  /**
   * Empty-cell "create new lesson" modal for /schedule.
   *
   * Four modes (which field is pre-filled and locked):
   *   mode='class'   -> class fixed; user picks teacher (subject auto-
   *                     resolved from existing Assignments) + classroom.
   *   mode='teacher' -> teacher fixed; user picks class + subject (auto)
   *                     + classroom.
   *   mode='room'    -> classroom fixed; user picks class + teacher +
   *                     subject.
   *   mode='slot'    -> nothing fixed; user picks class + teacher +
   *                     subject + classroom.
   *
   * In every mode `day` and `hour` come from the empty cell that was
   * clicked (or from the slot selector for mode='slot').
   *
   * Submit flow:
   *   1) POST /api/schedule/lesson on_conflict=dry_run.
   *   2) If conflict -> show ScheduleConflictModal with svincola/elimina.
   *   3) If user picks svincola/elimina -> POST again with that strategy.
   *   4) If no conflict (or after resolution) -> success, close, refresh.
   */
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import { DAY_NAMES_IT } from '$lib/constants';
  import Modal from '$lib/components/Modal.svelte';
  import ScheduleConflictModal from './ScheduleConflictModal.svelte';

  export let open = false;
  export let mode = 'class';   // class | teacher | room | slot
  export let day = 1;
  export let hour = 8;
  export let preset = {};      // { class_name?, teacher_name?, classroom_name? }
  export let teachers = [];    // string[]
  export let classes = [];     // string[]
  export let rooms = [];       // string[]
  export let onClose = () => { open = false; };
  export let onCreated = () => {};

  // Form state
  let className = '';
  let teacherName = '';
  let subject = '';   // optional; backend resolves if blank
  let classroomName = '';
  let busy = false;

  // Conflict modal state
  let conflictOpen = false;
  let conflictDetails = null;

  $: if (open) {
    // Re-initialise the form whenever we open from a fresh empty cell.
    className   = preset.class_name   ?? (mode === 'slot' ? '' : '');
    teacherName = preset.teacher_name ?? '';
    classroomName = preset.classroom_name ?? '';
    subject = '';
    conflictOpen = false;
    conflictDetails = null;
  }

  $: titleSlot = `${DAY_NAMES_IT[day] || ''} ${hour}:00`;

  function buildPayload(strategy) {
    return {
      class_name: className,
      teacher_name: teacherName,
      subject: subject || null,
      classroom_name: classroomName || null,
      day, hour,
      on_conflict: strategy,
    };
  }

  function canSubmit() {
    if (!className || !teacherName) return false;
    return true;
  }

  async function trySubmit(strategy) {
    if (!canSubmit()) {
      flash('Compila classe e docente', 'error');
      return;
    }
    busy = true;
    try {
      const r = await api.post('/api/schedule/lesson',
                               buildPayload(strategy));
      if (r.conflict && (strategy === 'dry_run' || strategy === 'cancel')) {
        conflictDetails = r.details || {};
        conflictOpen = true;
        return;
      }
      flash('Lezione creata', 'success');
      onCreated();
      onClose();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    } finally {
      busy = false;
    }
  }

  function onResolveConflict(strategy) {
    // strategy is 'unbind' (svincola) or 'delete' (elimina)
    conflictOpen = false;
    trySubmit(strategy);
  }
</script>

<Modal {open} title={`Nuovo evento - ${titleSlot}`} {onClose}>
  <div class="space-y-3">
    <div class="text-xs text-ink-500">
      Modalita': <code>{mode}</code> -- compila i campi mancanti per
      creare una nuova lezione nello slot scelto. La materia viene
      risolta automaticamente se la coppia (classe, docente) ha
      esattamente una cattedra associata; altrimenti specificala.
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div class="field">
        <label>Classe {mode === 'class' ? '(fissa)' : ''}</label>
        {#if mode === 'class'}
          <input value={className} disabled class="bg-ink-50"/>
        {:else}
          <select bind:value={className}>
            <option value="">-- scegli --</option>
            {#each classes as c}<option value={c}>{c}</option>{/each}
          </select>
        {/if}
      </div>

      <div class="field">
        <label>Docente {mode === 'teacher' ? '(fisso)' : ''}</label>
        {#if mode === 'teacher'}
          <input value={teacherName} disabled class="bg-ink-50"/>
        {:else}
          <select bind:value={teacherName}>
            <option value="">-- scegli --</option>
            {#each teachers as t}<option value={t}>{t}</option>{/each}
          </select>
        {/if}
      </div>

      <div class="field">
        <label>Materia (opzionale)</label>
        <input bind:value={subject}
               placeholder="auto se la coppia ha una sola cattedra"/>
      </div>

      <div class="field">
        <label>Aula {mode === 'room' ? '(fissa)' : ''}</label>
        {#if mode === 'room'}
          <input value={classroomName} disabled class="bg-ink-50"/>
        {:else}
          <select bind:value={classroomName}>
            <option value="">(nessuna)</option>
            {#each rooms as r}<option value={r}>{r}</option>{/each}
          </select>
        {/if}
      </div>
    </div>

    <div class="flex justify-end gap-2 pt-3 border-t border-ink-100">
      <button class="btn" on:click={onClose} disabled={busy}>Annulla</button>
      <button class="btn-primary" on:click={() => trySubmit('dry_run')}
              disabled={busy || !canSubmit()}>
        Crea evento
      </button>
    </div>
  </div>
</Modal>

<ScheduleConflictModal bind:open={conflictOpen}
                       title="Conflitto su nuovo evento"
                       subject={`${className} / ${teacherName} - ${titleSlot}`}
                       details={conflictDetails || {}}
                       onCancel={() => { conflictOpen = false; }}
                       onResolve={onResolveConflict}/>
