<script>
  /**
   * Monitor "+ Nuovo evento" modal.
   *
   * Creates a brand-new Assignment (cattedra) optionally with one
   * initial Lesson. If `day`/`hour` are left blank the Assignment
   * stays incomplete and surfaces in the red panel of /monitor.
   *
   * Submit flow mirrors AddLessonModal: a dry_run probe first; if a
   * conflict is reported, ScheduleConflictModal lets the user pick
   * Annulla / Svincola / Elimina.
   */
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants';
  import Modal from '$lib/components/Modal.svelte';
  import ScheduleConflictModal from './ScheduleConflictModal.svelte';

  export let open = false;
  export let teachers = [];
  export let classes = [];
  export let rooms = [];
  export let onClose = () => { open = false; };
  export let onCreated = () => {};

  // Form state
  let className = '';
  let teacherName = '';
  let subject = '';
  let hours = 1;
  let classroomName = '';
  let day = '';   // '' means "not assigned yet"
  let hour = '';
  let busy = false;

  // Conflict modal state
  let conflictOpen = false;
  let conflictDetails = null;

  $: if (open) {
    className = '';
    teacherName = '';
    subject = '';
    hours = 1;
    classroomName = '';
    day = '';
    hour = '';
    conflictOpen = false;
    conflictDetails = null;
  }

  function buildPayload(strategy) {
    return {
      class_name: className,
      teacher_name: teacherName,
      subject,
      hours: Number(hours) || 1,
      classroom_name: classroomName || null,
      day: day === '' ? null : Number(day),
      hour: hour === '' ? null : Number(hour),
      on_conflict: strategy,
    };
  }

  function canSubmit() {
    if (!className || !teacherName || !subject) return false;
    if (Number(hours) <= 0) return false;
    if ((day === '') !== (hour === '')) return false;  // both or neither
    return true;
  }

  async function trySubmit(strategy) {
    if (!canSubmit()) {
      flash('Compila classe, docente, materia e ore (giorno/ora '
            + 'entrambi o nessuno).', 'error');
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
      Crea una nuova cattedra. Se compili anche giorno + ora, viene
      creata anche una lezione iniziale in quello slot (con check di
      conflitto). Lasciando giorno/ora vuoti l'evento e' "non
      schedulato": appare nel pannello rosso "Eventi senza assegnazione
      temporale" finche' non gli assegni un giorno/ora.
    </p>

    <div class="grid grid-cols-2 gap-3">
      <div class="field">
        <label>Classe *</label>
        <select bind:value={className}>
          <option value="">-- scegli --</option>
          {#each classes as c}<option value={c}>{c}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label>Docente *</label>
        <select bind:value={teacherName}>
          <option value="">-- scegli --</option>
          {#each teachers as t}<option value={t}>{t}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label>Materia *</label>
        <input bind:value={subject} placeholder="es: Matematica"/>
      </div>
      <div class="field">
        <label>Ore (per settimana) *</label>
        <input type="number" min="1" max="36" bind:value={hours}/>
      </div>
      <div class="field">
        <label>Aula (opzionale)</label>
        <select bind:value={classroomName}>
          <option value="">(nessuna)</option>
          {#each rooms as r}<option value={r}>{r}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label>Giorno (opzionale)</label>
        <select bind:value={day}>
          <option value="">-- non schedulato --</option>
          {#each DAYS as d}<option value={d}>{DAY_NAMES_IT[d]}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label>Ora (opzionale)</label>
        <select bind:value={hour}>
          <option value="">-- non schedulato --</option>
          {#each HOURS as h}<option value={h}>{h}:00</option>{/each}
        </select>
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
                       title="Conflitto sull'evento da creare"
                       subject={`${className} / ${teacherName} - ${subject}`}
                       details={conflictDetails || {}}
                       onCancel={() => { conflictOpen = false; }}
                       onResolve={onResolveConflict}/>
