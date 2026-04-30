<script>
  /**
   * Monitor "+ Nuovo evento" modal.
   *
   * Per Giovanni's clarification, an EVENT is a single time-slot (not
   * a weekly subject), so this modal does NOT ask for "ore a settimana"
   * any more -- it always creates the underlying Assignment with
   * hours=1 and (when day/hour are filled) one Lesson at that slot.
   *
   * If `day`/`hour` are left blank the Assignment is created without a
   * Lesson and surfaces in the red panel of /monitor (incomplete event).
   *
   * The materia dropdown is filtered by the chosen docente's
   * abilitazioni (not free-typed).
   *
   * Submit flow mirrors AddLessonModal: a dry_run probe first; if a
   * conflict is reported, ScheduleConflictModal lets the user pick
   * Annulla / Svincola / Elimina (the latter two also create the event
   * after resolving the conflict).
   */
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants';
  import Modal from '$lib/components/Modal.svelte';
  import ScheduleConflictModal from './ScheduleConflictModal.svelte';

  export let open = false;
  export let teachers = [];   // [{name, subjects:[]}] OR [string] (legacy)
  export let classes = [];
  export let rooms = [];
  export let onClose = () => { open = false; };
  export let onCreated = () => {};

  // Form state
  let className = '';
  let teacherName = '';
  let subject = '';
  let classroomName = '';
  let day = '';   // '' means "not assigned yet"
  let hour = '';
  let busy = false;
  let attempted = false;

  // Conflict modal state
  let conflictOpen = false;
  let conflictDetails = null;

  $: teacherList = (teachers || []).map((t) =>
    typeof t === 'string' ? { name: t, subjects: [] } : t,
  );
  $: teacherNames = teacherList.map((t) => t.name);
  $: currentTeacher = teacherList.find((t) => t.name === teacherName);
  $: teacherSubjects = currentTeacher?.subjects ?? [];

  $: if (open) {
    className = '';
    teacherName = '';
    subject = '';
    classroomName = '';
    day = '';
    hour = '';
    attempted = false;
    conflictOpen = false;
    conflictDetails = null;
  }

  // Clear stale subject when teacher changes.
  $: if (teacherName && teacherSubjects.length
         && subject && !teacherSubjects.includes(subject)) {
    subject = '';
  }

  function buildPayload(strategy) {
    return {
      class_name: className,
      teacher_name: teacherName,
      subject,
      hours: 1,        // an "event" is one time-slot; backend default
      classroom_name: classroomName || null,
      day: day === '' ? null : Number(day),
      hour: hour === '' ? null : Number(hour),
      on_conflict: strategy,
    };
  }

  function validate() {
    const missing = [];
    if (!className) missing.push('classe');
    if (!teacherName) missing.push('docente');
    if (!subject) missing.push('materia');
    if ((day === '') !== (hour === '')) {
      missing.push('giorno+ora (o entrambi o nessuno)');
    }
    return missing;
  }

  function fieldClass(value, required) {
    if (!required) return value ? 'ring-2 ring-emerald-300' : '';
    if (value) return 'ring-2 ring-emerald-400';
    if (attempted) return 'ring-2 ring-red-400';
    return '';
  }

  // Special: day/hour are required iff the OTHER one is filled. Treat
  // them as a paired field for the visual cue.
  function dhClass() {
    const both = day !== '' && hour !== '';
    const neither = day === '' && hour === '';
    if (both) return 'ring-2 ring-emerald-400';
    if (neither) return '';   // valid: not scheduled
    if (attempted) return 'ring-2 ring-red-400';
    return '';
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
      const r = await api.post('/api/monitor/event', buildPayload(strategy));
      if (r.conflict && (strategy === 'dry_run' || strategy === 'cancel')) {
        conflictDetails = r.details || {};
        conflictOpen = true;
        return;
      }
      if (day === '' || hour === '') {
        flash('Evento creato senza assegnazione temporale '
              + '(visibile nel pannello rosso).', 'success');
      } else {
        flash('Evento creato.', 'success');
      }
      onCreated();
      onClose();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    } finally {
      busy = false;
    }
  }

  function onResolveConflict(strategy) {
    conflictOpen = false;
    trySubmit(strategy);
  }
</script>

<Modal {open} title="Nuovo evento (Monitor)" {onClose}>
  <div class="space-y-3">
    <p class="text-xs text-ink-500">
      Un evento e' una singola occorrenza in uno slot giorno/ora. Se
      compili giorno + ora viene creato anche immediatamente, altrimenti
      l'evento resta non schedulato e appare nel pannello rosso. La
      materia mostra solo le abilitazioni del docente scelto. Anello
      verde = campo valido; anello rosso = campo richiesto mancante.
    </p>

    <div class="grid grid-cols-2 gap-3">
      <div class="field">
        <label>Classe *</label>
        <select bind:value={className} class={fieldClass(className, true)}>
          <option value="">-- scegli --</option>
          {#each classes as c}<option value={c}>{c}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label>Docente *</label>
        <select bind:value={teacherName}
                class={fieldClass(teacherName, true)}>
          <option value="">-- scegli --</option>
          {#each teacherNames as t}<option value={t}>{t}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label>Materia *</label>
        {#if teacherSubjects.length === 0 && teacherName}
          <input bind:value={subject}
                 class={fieldClass(subject, true)}
                 placeholder="docente senza abilitazioni elencate"/>
        {:else}
          <select bind:value={subject}
                  class={fieldClass(subject, true)}
                  disabled={!teacherName}>
            <option value="">{teacherName
              ? '-- scegli --'
              : '-- scegli prima il docente --'}</option>
            {#each teacherSubjects as s}
              <option value={s}>{s}</option>
            {/each}
          </select>
        {/if}
      </div>
      <div class="field">
        <label>Aula (opzionale)</label>
        <select bind:value={classroomName}
                class={fieldClass(classroomName, false)}>
          <option value="">(nessuna)</option>
          {#each rooms as r}<option value={r}>{r}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label>Giorno {(day !== '' || hour !== '') ? '*' : '(opzionale)'}</label>
        <select bind:value={day} class={dhClass()}>
          <option value="">-- non schedulato --</option>
          {#each DAYS as d}<option value={d}>{DAY_NAMES_IT[d]}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label>Ora {(day !== '' || hour !== '') ? '*' : '(opzionale)'}</label>
        <select bind:value={hour} class={dhClass()}>
          <option value="">-- non schedulato --</option>
          {#each HOURS as h}<option value={h}>{h}:00</option>{/each}
        </select>
      </div>
    </div>

    <div class="flex justify-end gap-2 pt-3 border-t border-ink-100">
      <button class="btn" on:click={onClose} disabled={busy}>Annulla</button>
      <button class="btn-primary" on:click={() => trySubmit('dry_run')}
              disabled={busy}>
        Crea evento
      </button>
    </div>
  </div>
</Modal>

<ScheduleConflictModal bind:open={conflictOpen}
                       title="Conflitto sull'evento da creare"
                       subject={`${className} / ${teacherName} - ${subject}`}
                       details={conflictDetails || {}}
                       onCancel={() => { conflictOpen = false; }}
                       onResolve={onResolveConflict}/>
