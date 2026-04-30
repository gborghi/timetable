<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { flash } from '$lib/stores.js';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants.js';

  let summary = null;
  let listRef = null;
  let allRooms = [];

  // For each event row we keep: expanded? + lessons array.
  let expanded = new Set();
  let lessonsByEvent = {};
  let busyEvent = null;

  // Conflict modal state
  let conflictDialog = null;
  // shape: { event_id, lesson_id, day, hour, classroom_name, details:{teacher_busy,...}, original }

  onMount(async () => {
    try { summary = await api.get('/api/monitor/summary'); } catch { /* */ }
    try { allRooms = (await api.get('/api/classrooms')).map((r) => r.name).sort(); }
    catch { allRooms = []; }
  });

  async function refreshSummary() {
    try { summary = await api.get('/api/monitor/summary'); } catch { /* */ }
  }

  async function toggleRow(row) {
    const id = row.assignment_id;
    if (expanded.has(id)) {
      expanded.delete(id);
      expanded = expanded;
      return;
    }
    expanded.add(id);
    expanded = expanded;
    busyEvent = id;
    try {
      const d = await api.get('/api/monitor/event/' + id + '/lessons');
      lessonsByEvent[id] = d.lessons;
      lessonsByEvent = lessonsByEvent;
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally {
      busyEvent = null;
    }
  }

  async function reloadLessonsFor(eventId) {
    try {
      const d = await api.get('/api/monitor/event/' + eventId + '/lessons');
      lessonsByEvent[eventId] = d.lessons;
      lessonsByEvent = lessonsByEvent;
    } catch { /* */ }
  }

  async function applyMove(eventId, lesson, newDay, newHour, newRoom,
                          onConflict) {
    const payload = {
      day: Number(newDay),
      hour: Number(newHour),
      classroom_name: newRoom,
      on_conflict: onConflict,
    };
    return await api.put(
      '/api/monitor/event/' + eventId + '/lesson/' + lesson.lesson_id,
      payload);
  }

  async function tryMove(eventId, lesson, newDay, newHour, newRoom) {
    try {
      // First a dry-run to check conflicts
      const dry = await applyMove(eventId, lesson, newDay, newHour, newRoom,
                                  'dry_run');
      if (dry.no_change) return;
      if (dry.ok) {
        flash('Lezione spostata.', 'success');
        await reloadLessonsFor(eventId);
        await refreshSummary();
        if (listRef) await listRef.reload();
        return;
      }
      if (dry.conflict) {
        conflictDialog = {
          event_id: eventId,
          lesson,
          day: newDay,
          hour: newHour,
          classroom_name: newRoom,
          details: dry.details,
        };
      }
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function resolveConflict(strategy) {
    if (!conflictDialog) return;
    const { event_id, lesson, day, hour, classroom_name } = conflictDialog;
    try {
      const r = await applyMove(event_id, lesson, day, hour, classroom_name,
                                strategy);
      if (r.ok) {
        if (strategy === 'optimize') {
          flash('Lezione spostata; riavvia l\'ottimizzatore dal Workflow per ricoprire le ore liberate.', 'success');
        } else {
          flash('Lezione spostata.', 'success');
        }
        conflictDialog = null;
        await reloadLessonsFor(event_id);
        await refreshSummary();
        if (listRef) await listRef.reload();
      } else if (r.cancelled) {
        flash('Modifica annullata.', 'success');
        conflictDialog = null;
      }
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  function rowBg(row) {
    return row.is_complete ? '' : 'background-color: #fef9c3;';
  }

  const columns = [
    { key: 'docente', label: 'Docente' },
    { key: 'classe', label: 'Classe' },
    { key: 'materia', label: 'Materia' },
    { key: 'expected_hours', label: 'Ore attese' },
    { key: 'assigned_hours', label: 'Ore assegnate' },
    { key: 'missing_hours', label: 'Ore mancanti' },
    { key: 'missing_room', label: 'Aule mancanti' },
    { key: 'gruppo', label: 'Gruppo' },
    { key: 'stato', label: 'Stato' }
  ];
  const help = {
    fields: ['docente', 'teacher', 'classe', 'class_name', 'materia',
             'subject', 'expected_hours', 'ore_attese', 'assigned_hours',
             'ore_assegnate', 'missing_hours', 'ore_mancanti',
             'missing_room', 'aule_mancanti', 'missing_group', 'is_complete',
             'completo', 'group', 'gruppo', 'status', 'stato'],
    examples: [
      'completo = 0',
      'missing_hours > 0',
      'aule_mancanti > 0',
      'materia = Matematica',
      'classe startswith 1A',
      'docente contains Rossi'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Monitor</h1>
    {#if summary}
      <span class="text-sm text-ink-500">
        {summary.n_events} eventi totali
        - <span class="pill-amber">{summary.n_incomplete} incompleti</span>
        {#if summary.n_missing_hours}
          - <span class="pill-red">{summary.n_missing_hours} senza ore</span>
        {/if}
        {#if summary.n_missing_room}
          - <span class="pill-amber">{summary.n_missing_room} senza aula</span>
        {/if}
        {#if summary.n_missing_group}
          - <span class="pill">{summary.n_missing_group} senza gruppo</span>
        {/if}
      </span>
    {/if}
  </div>

  <p class="text-xs text-ink-500">
    Click su una riga per espanderla e vedere le singole lezioni
    (giorno/ora/aula). Da li puoi spostare la lezione: se la nuova
    posizione e' in conflitto con un'altra lezione/aula apparira' un
    modal con le opzioni di risoluzione.
  </p>

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/monitor/events"
    {columns}
    {help}
    rowKey={(r) => r.assignment_id}
    let:row let:columns>
    <tr style={rowBg(row)} class="cursor-pointer"
        on:click={() => toggleRow(row)}>
      <td>
        <span class="text-xs text-ink-400 mr-1">
          {expanded.has(row.assignment_id) ? '▼' : '▶'}
        </span>
        <strong>{row.teacher_display}</strong>
        <span class="text-[10px] text-ink-400">({row.teacher_name})</span>
      </td>
      <td>{row.class_name}</td>
      <td>{row.subject}</td>
      <td class="text-center">{row.expected_hours}</td>
      <td class="text-center">{row.assigned_hours}</td>
      <td class="text-center">
        {#if row.missing_hours > 0}
          <span class="pill-red">{row.missing_hours}</span>
        {:else}<span class="text-ink-300">-</span>{/if}
      </td>
      <td class="text-center">
        {#if row.missing_room > 0}
          <span class="pill-amber">{row.missing_room}</span>
        {:else}<span class="text-ink-300">-</span>{/if}
      </td>
      <td class="text-xs">
        {#if row.group_name}{row.group_name}
        {:else if row.missing_group}<span class="pill-amber">manca</span>
        {:else}<span class="text-ink-300">-</span>{/if}
      </td>
      <td class="text-xs">
        {#if row.is_complete}<span class="pill-green">ok</span>
        {:else}{row.status}{/if}
      </td>
    </tr>
    {#if expanded.has(row.assignment_id)}
      <tr style="background-color:#f9fafb;">
        <td colspan={columns.length + 1} class="p-2">
          {#if busyEvent === row.assignment_id && !lessonsByEvent[row.assignment_id]}
            <span class="text-xs text-ink-400 italic">caricamento...</span>
          {:else if lessonsByEvent[row.assignment_id]?.length === 0}
            <span class="text-xs text-ink-400 italic">nessuna lezione assegnata in questa cattedra</span>
          {:else if lessonsByEvent[row.assignment_id]}
            <table class="tbl text-xs w-full">
              <thead>
                <tr>
                  <th>#</th><th>Giorno</th><th>Ora</th><th>Aula</th><th></th>
                </tr>
              </thead>
              <tbody>
                {#each lessonsByEvent[row.assignment_id] as l}
                  <tr>
                    <td class="text-ink-400">#{l.lesson_id}</td>
                    <td>
                      <select class="text-xs px-1 py-0.5 border border-ink-200 rounded"
                        on:click|stopPropagation
                        on:change={(e) => tryMove(
                          row.assignment_id, l, Number(e.target.value),
                          l.hour, l.classroom_name)}
                        value={l.day}>
                        {#each DAYS as d}
                          <option value={d}>{DAY_NAMES_IT[d]}</option>
                        {/each}
                      </select>
                    </td>
                    <td>
                      <select class="text-xs px-1 py-0.5 border border-ink-200 rounded"
                        on:click|stopPropagation
                        on:change={(e) => tryMove(
                          row.assignment_id, l, l.day,
                          Number(e.target.value), l.classroom_name)}
                        value={l.hour}>
                        {#each HOURS as h}
                          <option value={h}>{h}:00</option>
                        {/each}
                      </select>
                    </td>
                    <td>
                      <select class="text-xs px-1 py-0.5 border border-ink-200 rounded"
                        on:click|stopPropagation
                        on:change={(e) => tryMove(
                          row.assignment_id, l, l.day, l.hour,
                          e.target.value || null)}
                        value={l.classroom_name || ''}>
                        <option value="">(nessuna)</option>
                        {#each allRooms as r}<option value={r}>{r}</option>{/each}
                      </select>
                    </td>
                    <td>
                      {#if !l.classroom_name}
                        <span class="pill-amber !text-[10px]">no aula</span>
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        </td>
      </tr>
    {/if}
  </SortableQueryableList>
</div>

<Modal open={!!conflictDialog}
       title="Conflitto sull'orario di destinazione"
       onClose={() => (conflictDialog = null)}>
  {#if conflictDialog}
    <div class="space-y-3 text-sm">
      <p>
        Lo spostamento della lezione in
        <code>{DAY_NAMES_IT[conflictDialog.day]} {conflictDialog.hour}:00</code>
        {#if conflictDialog.classroom_name}
          aula <strong>{conflictDialog.classroom_name}</strong>
        {/if}
        confligge con altre lezioni:
      </p>
      <ul class="list-disc ml-5 text-xs">
        {#each conflictDialog.details.teacher_busy as r}
          <li><span class="pill-red">docente</span> {r.teacher_name} - {r.class_name} / {r.subject} ({DAY_NAMES_IT[r.day]} {r.hour}:00)</li>
        {/each}
        {#each conflictDialog.details.class_busy as r}
          <li><span class="pill-red">classe</span> {r.class_name} - {r.subject} ({r.teacher_name})</li>
        {/each}
        {#each conflictDialog.details.room_busy as r}
          <li><span class="pill-amber">aula</span> {r.classroom_name} usata da {r.class_name} / {r.subject} ({r.teacher_name})</li>
        {/each}
      </ul>
      <p class="text-xs text-ink-500">
        Cosa vuoi fare?
      </p>
      <div class="flex flex-wrap gap-2 justify-end">
        <button class="btn !text-xs" on:click={() => (conflictDialog = null)}>
          Annulla la modifica
        </button>
        <button class="btn-danger !text-xs" on:click={() => resolveConflict('unassign')}>
          Disassegna le lezioni in conflitto
        </button>
        <button class="btn-primary !text-xs" on:click={() => resolveConflict('optimize')}>
          Disassegna e ottimizza dopo (Workflow)
        </button>
      </div>
    </div>
  {/if}
</Modal>
