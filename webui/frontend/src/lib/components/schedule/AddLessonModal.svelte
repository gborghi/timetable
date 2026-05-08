<script>
  /**
   * Empty-cell "create new lesson" modal for /schedule.
   *
   * Four modes (which field is pre-filled and locked):
   *   mode='class'   -> class fixed; user picks teacher (subject auto-
   *                     resolved from existing Assignments OR from the
   *                     teacher's abilitazioni) + classroom.
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
   *   2) If conflict -> show ScheduleConflictModal with svincola/elimina;
   *      both options resolve the conflict AND create the lesson via a
   *      second POST.
   *   3) If no conflict -> success, close, refresh.
   *
   * The submit button is enabled as long as the modal is not busy. We
   * validate on click and flash an error if a required field is empty,
   * and we show a green ring on filled valid required fields.
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
  export let teachers = [];    // [{name, subjects:[]}] OR [string] (legacy)
  export let classes = [];     // string[]
  export let rooms = [];       // string[]
  export let onClose = () => { open = false; };
  export let onCreated = () => {};

  // Form state
  let className = '';
  let teacherName = '';
  let subject = '';
  let classroomName = '';
  let busy = false;

  // Conflict modal state
  let conflictOpen = false;
  let conflictDetails = null;

  // Normalise teachers into [{name, subjects}].
  $: teacherList = (teachers || []).map((t) =>
    typeof t === 'string' ? { name: t, subjects: [] } : t,
  );
  $: teacherNames = teacherList.map((t) => t.name);

  // Subjects for the currently-selected teacher. If we have no
  // subjects info (legacy callers), the dropdown becomes a free-text
  // input via the "(altra...)" option.
  $: currentTeacher = teacherList.find((t) => t.name === teacherName);
  $: teacherSubjects = currentTeacher?.subjects ?? [];

  $: if (open) {
    // Re-initialise the form whenever we open from a fresh empty cell.
    className   = preset.class_name   ?? '';
    teacherName = preset.teacher_name ?? '';
    classroomName = preset.classroom_name ?? '';
    subject = '';
    conflictOpen = false;
    conflictDetails = null;
  }

  // If the teacher changes and the chosen subject isn't taught by
  // them, clear it so we don't keep a stale value.
  $: if (teacherName && teacherSubjects.length
         && subject && !teacherSubjects.includes(subject)) {
    subject = '';
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

  // Visual ring helpers (green when filled, red when explicitly missing
  // after the user attempted to submit).
  let attempted = false;
  function fieldClass(value, required) {
    if (!required) return value ? 'ring-2 ring-emerald-300' : '';
    if (value) return 'ring-2 ring-emerald-400';
    if (attempted) return 'ring-2 ring-red-400';
    return '';
  }

  function validate() {
    const missing = [];
    if (!className) missing.push('classe');
    if (!teacherName) missing.push('docente');
    return missing;
  }

  async function trySubmit(strategy) {
    attempted = true;
    const missing = validate();
    if (missing.length) {
      flash('Manca: ' + missing.join(', '), 'error');
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
  <div class="space-y-3" data-testid="add-lesson-modal">
    <div class="text-xs text-ink-500">
      Modalita': <code>{mode}</code> -- compila i campi mancanti per
      creare una nuova lezione nello slot scelto. La materia dipende
      dal docente scelto (vengono mostrate solo le sue abilitazioni).
      Anello verde = campo valido; anello rosso = campo richiesto
      mancante (dopo un tentativo di invio).
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div class="field">
        <label>Classe {mode === 'class' ? '(fissa)' : ''} *</label>
        {#if mode === 'class'}
          <input value={className} disabled
                 class="bg-ink-50 {fieldClass(className, true)}"
                 data-testid="add-lesson-class-input"/>
        {:else}
          <select bind:value={className} class={fieldClass(className, true)}
                  data-testid="add-lesson-class-select">
            <option value="">-- scegli --</option>
            {#each classes as c}<option value={c}>{c}</option>{/each}
          </select>
        {/if}
      </div>

      <div class="field">
        <label>Docente {mode === 'teacher' ? '(fisso)' : ''} *</label>
        {#if mode === 'teacher'}
          <input value={teacherName} disabled
                 class="bg-ink-50 {fieldClass(teacherName, true)}"
                 data-testid="add-lesson-teacher-input"/>
        {:else}
          <select bind:value={teacherName}
                  class={fieldClass(teacherName, true)}
                  data-testid="add-lesson-teacher-select">
            <option value="">-- scegli --</option>
            {#each teacherNames as t}<option value={t}>{t}</option>{/each}
          </select>
        {/if}
      </div>

      <div class="field">
        <label>Materia (opzionale)</label>
        {#if teacherSubjects.length === 0 && teacherName}
          <input bind:value={subject}
                 class={fieldClass(subject, false)}
                 placeholder="docente senza abilitazioni elencate"
                 data-testid="add-lesson-subject-input"/>
        {:else}
          <select bind:value={subject}
                  class={fieldClass(subject, false)}
                  disabled={!teacherName}
                  data-testid="add-lesson-subject-select">
            <option value="">{teacherName
              ? 'auto (se la coppia ha una sola cattedra)'
              : '-- scegli prima il docente --'}</option>
            {#each teacherSubjects as s}
              <option value={s}>{s}</option>
            {/each}
          </select>
        {/if}
      </div>

      <div class="field">
        <label>Aula {mode === 'room' ? '(fissa)' : ''}</label>
        {#if mode === 'room'}
          <input value={classroomName} disabled
                 class="bg-ink-50 {fieldClass(classroomName, false)}"
                 data-testid="add-lesson-room-input"/>
        {:else}
          <select bind:value={classroomName}
                  class={fieldClass(classroomName, false)}
                  data-testid="add-lesson-room-select">
            <option value="">(nessuna)</option>
            {#each rooms as r}<option value={r}>{r}</option>{/each}
          </select>
        {/if}
      </div>
    </div>

    <div class="flex justify-end gap-2 pt-3 border-t border-ink-100">
      <button class="btn" on:click={onClose} disabled={busy}
              data-testid="add-lesson-cancel-btn">Annulla</button>
      <button class="btn-primary" on:click={() => trySubmit('dry_run')}
              disabled={busy}
              data-testid="add-lesson-submit-btn">
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
