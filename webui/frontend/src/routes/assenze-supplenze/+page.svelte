<script>
  import PageHero from '$lib/components/PageHero.svelte';
  import { confirmDialog } from '$lib/confirm';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash, workingHoursConfig } from '$lib/stores';
  import { calendarHours, calendarDayName } from '$lib/constants';
  import Modal from '$lib/components/Modal.svelte';

  // ----- state -----
  let weekStart = mondayOf(new Date());
  let coverage = null;        // WeekCoverageOut
  let allTeachers = [];
  let dispConfig = null;      // school-wide disposizione policy
  let dispCap = '';
  let dispEligibility = 'all';
  let showDispPanel = false;

  // modals
  let absencesModal = null;   // { date, day }
  let cellModal = null;       // { date, day, hour, detail }

  // drag state for cell modal
  let dragTeacher = null;     // teacher object being dragged

  // ----- helpers -----
  function mondayOf(d) {
    const dt = new Date(d);
    const day = (dt.getDay() + 6) % 7;  // Mon=0 .. Sun=6
    dt.setDate(dt.getDate() - day);
    return isoDate(dt);
  }
  function isoDate(d) {
    const dt = (d instanceof Date) ? d : new Date(d);
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, '0');
    const da = String(dt.getDate()).padStart(2, '0');
    return `${y}-${m}-${da}`;
  }
  function shiftWeek(weeks) {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + weeks * 7);
    weekStart = isoDate(d);
    load();
  }
  function fmtDateShort(s) {
    const d = new Date(s);
    return `${String(d.getDate()).padStart(2,'0')}/${String(d.getMonth()+1).padStart(2,'0')}`;
  }
  $: calHours = calendarHours($workingHoursConfig);
  $: calName = (d) => calendarDayName(d, $workingHoursConfig);

  // ----- load -----
  async function load() {
    try {
      coverage = await api.get('/api/coverage/week?week_start=' + weekStart);
      allTeachers = await api.get('/api/teachers');
      try {
        dispConfig = await api.get('/api/coverage/disposizione');
        dispCap = dispConfig.max_total_hours == null
          ? '' : String(dispConfig.max_total_hours);
        dispEligibility = dispConfig.eligibility || 'all';
      } catch { /* older backends without the endpoint */ }
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function saveDispConfig() {
    try {
      const cap = dispCap === '' ? null : Number(dispCap);
      dispConfig = await api.put('/api/coverage/disposizione', {
        max_total_hours: (cap === null || Number.isNaN(cap)) ? null : cap,
        eligibility: dispEligibility,
        slot_priorities: (dispConfig && dispConfig.slot_priorities) || [],
      });
      dispCap = dispConfig.max_total_hours == null
        ? '' : String(dispConfig.max_total_hours);
      flash('Politica disposizione salvata'
            + (dispConfig.placed_hours
               ? ` (${dispConfig.placed_hours} ore piazzate)` : ''),
            'success');
      await load();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function replaceDisp() {
    try {
      const r = await api.post('/api/coverage/disposizione/place', {});
      flash(`Disposizione ripiazzata: ${r.placed_hours || 0} ore`,
            'success');
      await load();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  onMount(load);

  function cellOf(daySummary, hour) {
    return (daySummary.cells || []).find((c) => c.hour === hour);
  }

  function cellClass(cell) {
    if (!cell) return '';
    if (cell.status === 'red')   return 'bg-red-100  hover:bg-red-200  border-red-300';
    if (cell.status === 'green') return 'bg-emerald-100 hover:bg-emerald-200 border-emerald-300';
    if (cell.status === 'mixed') return 'bg-amber-50  hover:bg-amber-100 border-amber-300';
    return 'bg-white hover:bg-ink-50';
  }

  // ----- absences modal (column header) -----
  async function openAbsencesModal(daySummary) {
    absencesModal = { date: daySummary.date, day: daySummary.day,
                      absences: daySummary.absences || [],
                      pickedTeacherId: null, reason: '' };
  }

  async function addAbsence() {
    if (!absencesModal.pickedTeacherId) return;
    try {
      await api.post('/api/absences', {
        teacher_id: Number(absencesModal.pickedTeacherId),
        date: absencesModal.date,
        reason: absencesModal.reason || null,
      });
      absencesModal.pickedTeacherId = null;
      absencesModal.reason = '';
      await load();
      const d = (coverage.days || []).find((d) => d.date === absencesModal.date);
      if (d) absencesModal.absences = d.absences;
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function removeAbsence(a) {
    try {
      await api.del('/api/absences/by-id/' + a.id);
      await load();
      const d = (coverage.days || []).find((d) => d.date === absencesModal.date);
      if (d) absencesModal.absences = d.absences;
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function clearDayAbsences(date) {
    if (!await confirmDialog('Cancellare TUTTE le assenze e supplenze del ' + fmtDateShort(date) + '?')) return;
    try {
      await api.del('/api/absences?date=' + date);
      await load();
      if (absencesModal && absencesModal.date === date) {
        absencesModal.absences = [];
      }
      flash('Giornata azzerata', 'success');
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  // teachers not yet absent, filtered
  let absenceFilter = '';
  $: candidatesForAbsence = !absencesModal ? [] :
    allTeachers.filter((t) => !(absencesModal.absences || [])
      .some((a) => a.teacher_id === t.id))
      .filter((t) => {
        if (!absenceFilter) return true;
        const ql = absenceFilter.toLowerCase();
        return (t.name || '').toLowerCase().includes(ql)
            || (t.last_name || '').toLowerCase().includes(ql)
            || (t.first_name || '').toLowerCase().includes(ql)
            || (t.nickname || '').toLowerCase().includes(ql);
      });

  // ----- cell modal -----
  async function openCellModal(date, day, hour) {
    try {
      const detail = await api.get(
        `/api/coverage/cell?date=${date}&day=${day}&hour=${hour}`
      );
      availFilter = 'all';
      availQuery = '';
      cellModal = { date, day, hour, detail };
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function refreshCellModal() {
    if (!cellModal) return;
    cellModal.detail = await api.get(
      `/api/coverage/cell?date=${cellModal.date}&day=${cellModal.day}&hour=${cellModal.hour}`
    );
    await load();
  }

  function onDragStart(ev, t) {
    dragTeacher = t;
    ev.dataTransfer.effectAllowed = 'move';
    try { ev.dataTransfer.setData('text/plain', String(t.id)); } catch { /* */ }
  }
  function onDragEnd() { dragTeacher = null; }
  function onDragOver(ev) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'move'; }

  async function onDrop(ev, uncov) {
    ev.preventDefault();
    // Capture the teacher reference at drop time. `dragend` fires on the
    // source element AFTER `drop` and clears `dragTeacher`; if we reach
    // it past an `await`, the variable is already null.
    const t = dragTeacher;
    if (!t) return;
    try {
      await api.post('/api/substitutions', {
        date: cellModal.date,
        day: cellModal.day,
        hour: cellModal.hour,
        class_name: uncov.class_name,
        subject: uncov.subject,
        original_teacher_name: uncov.original_teacher_name,
        substitute_teacher_id: t.id,
      });
      flash(`Supplenza assegnata: ${t.display} -> ${uncov.class_name}`,
            'success');
      dragTeacher = null;
      await refreshCellModal();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function removeSub(uncov) {
    if (!uncov.substitute_id) return;
    try {
      await api.del('/api/substitutions/' + uncov.substitute_id);
      await refreshCellModal();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  $: allCovered = !cellModal || !cellModal.detail
                    || cellModal.detail.uncovered.length === 0
                    || cellModal.detail.uncovered.every((u) => u.substitute_teacher_id);

  // Selection chips in the substitutions pane. Disposizione placement
  // stays subject-agnostic; these only filter who is shown/draggable.
  let availFilter = 'all';
  let availQuery = '';

  $: uncoveredSubjects = !cellModal || !cellModal.detail
    ? []
    : [...new Set((cellModal.detail.uncovered || [])
        .map((u) => u.subject)
        .filter(Boolean))];

  $: filteredAvailable = !cellModal || !cellModal.detail
    ? []
    : (cellModal.detail.available || []).filter((t) => {
        const q = availQuery.trim().toLowerCase();
        if (q) {
          const hay = [
            t.display, t.name, t.group,
            ...(t.subjects || []),
          ].filter(Boolean).join(' ').toLowerCase();
          if (!hay.includes(q)) return false;
        }
        if (availFilter === 'same_subject') return !!t.matches_lesson_subject;
        if (availFilter === 'same_as_absent') return !!t.matches_absent_subjects;
        if (availFilter === 'disposizione') return !!t.is_disposizione;
        if (availFilter === 'hole') return !!t.is_hole;
        if (availFilter === 'free') return t.kind === 'free';
        if (availFilter === 'potenziamento') return !!t.is_potenziamento;
        if (availFilter === 'under_hours') {
          return (t.scheduled_hours || 0) < (t.max_hours || 0);
        }
        return true;
      });

  function setAvailFilter(next) {
    availFilter = next;
  }

  async function closeCellModal() {
    if (cellModal && cellModal.detail
        && cellModal.detail.uncovered.some((u) => !u.substitute_teacher_id)) {
      if (!await confirmDialog('Ci sono ancora ore scoperte. Chiudere comunque?')) return;
    }
    cellModal = null;
  }
</script>

<div class="space-y-4" data-testid="absences-page">
  <PageHero title="Assenze e supplenze"
            description="La settimana vista dal lato della copertura: si registrano le assenze e si assegnano i supplenti sulle ore rimaste scoperte, lavorando sulla soluzione attiva.">
    <svelte:fragment slot="actions">
      <button class="btn" on:click={() => shiftWeek(-1)}
              data-testid="absences-prev-week">&lt; settimana prec.</button>
      <input type="date" bind:value={weekStart} on:change={load}
             class="px-2 py-1 border border-ink-200 rounded text-sm"
             title="Lunedi della settimana"
             data-testid="absences-week-input"/>
      <button class="btn" on:click={() => shiftWeek(1)}
              data-testid="absences-next-week">settimana succ. &gt;</button>
      <button class="btn" on:click={() => { weekStart = mondayOf(new Date()); load(); }}
              data-testid="absences-today">oggi</button>
      <button class="btn" on:click={() => (showDispPanel = !showDispPanel)}
              data-testid="absences-disp-toggle">
        {showDispPanel ? 'Chiudi disposizione' : 'Ore di disposizione'}
      </button>
    </svelte:fragment>
  </PageHero>

  {#if !coverage}
    <p class="text-sm text-ink-500">Caricamento...</p>
  {:else if !coverage.has_active_solution}
    <p class="text-sm text-amber-700">Nessuna soluzione attiva: importa o calcola un orario per usare questa pagina.</p>
  {:else}
    {#if showDispPanel}
      <div class="card p-3 space-y-2" data-testid="disp-policy-panel">
        <h3 class="!text-base">Ore di disposizione</h3>
        <p class="text-xs text-ink-500">
          Quota per docente nella scheda Docenti. Qui il tetto scolastico,
          chi è eleggibile, e il ripiazzamento sulla soluzione attiva
          (senza classe né aula). Le ore si spostano a mano dal tab Orario.
        </p>
        <div class="flex flex-wrap items-end gap-3">
          <label class="text-sm">
            Tetto scolastico
            <input type="number" min="0" class="block px-2 py-1 border border-ink-200 rounded text-sm w-28"
                   bind:value={dispCap} placeholder="nessun tetto"
                   data-testid="disp-cap-input"/>
          </label>
          <label class="text-sm">
            Assegna a
            <select class="block px-2 py-1 border border-ink-200 rounded text-sm"
                    bind:value={dispEligibility}
                    data-testid="disp-eligibility">
              <option value="all">tutti i docenti con quota</option>
              <option value="under_contract">solo sotto le ore contrattuali</option>
            </select>
          </label>
          <button class="btn-primary" on:click={saveDispConfig}
                  data-testid="disp-save">Salva e piazza</button>
          <button class="btn" on:click={replaceDisp}
                  data-testid="disp-replace">Ripiazza ora</button>
          {#if dispConfig}
            <span class="text-xs text-ink-500">
              {dispConfig.placed_hours ?? 0} ore in orario
            </span>
          {/if}
        </div>
      </div>
    {/if}

    <p class="text-xs text-ink-500">
      Click sull'<strong>intestazione di un giorno</strong> per registrare le assenze;
      click su una <strong>cella</strong> per vedere chi e disponibile e
      assegnare supplenze (drag-drop). Le celle rosse hanno classi scoperte;
      verdi sono coperte. In lista: <strong>DISP</strong> = disposizione ufficiale,
      <strong>BUCO</strong> = ora vuota tra prima e ultima lezione (priorità
      più alta tra i liberi), gli altri sono semplicemente liberi.
    </p>

    <div class="card overflow-x-auto">
      <table class="tbl text-sm w-full">
        <thead>
          <tr class="bg-ink-50">
            <th class="w-16 text-center">Ora</th>
            {#each coverage.days as d}
              <th class="text-center align-bottom">
                <button class="block w-full px-2 py-1 hover:bg-ink-100 rounded font-semibold"
                        on:click={() => openAbsencesModal(d)}
                        title="Click per registrare assenze">
                  {calName(d.day)} {fmtDateShort(d.date)}
                  {#if d.n_absences > 0}
                    <span class="pill pill-amber !text-[9px] ml-1">{d.n_absences} assenti</span>
                  {/if}
                  {#if d.n_uncovered > 0}
                    <span class="pill pill-red !text-[9px] ml-1">-{d.n_uncovered}</span>
                  {/if}
                  {#if d.n_covered > 0 && d.n_uncovered === 0}
                    <span class="pill pill-green !text-[9px] ml-1">{d.n_covered} ok</span>
                  {/if}
                </button>
                {#if d.n_absences > 0 || d.n_uncovered > 0 || d.n_covered > 0}
                  <button class="text-[10px] text-red-600 hover:underline px-2"
                          on:click|stopPropagation={() => clearDayAbsences(d.date)}
                          title="Cancella tutte le assenze e supplenze del giorno">
                    Clear
                  </button>
                {/if}
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each (coverage.days[0]?.cells?.length
                    ? coverage.days[0].cells.map((c) => c.hour)
                    : calHours) as h}
            <tr>
              <td class="text-center font-mono text-xs bg-ink-50">{h}:00</td>
              {#each coverage.days as d}
                {@const cell = cellOf(d, h)}
                <td class="border align-top p-0">
                  <button class="w-full h-full px-2 py-3 text-left {cellClass(cell)}"
                          on:click={() => openCellModal(d.date, d.day, h)}
                          title={cell?.status === 'red'
                                 ? `${cell.n_uncovered} ore scoperte` :
                                 cell?.status === 'green'
                                 ? `${cell.n_covered} ore coperte` :
                                 cell?.n_absent_teachers
                                 ? `${cell.n_absent_teachers} docenti assenti, nessuna lezione persa`
                                 : 'OK'}>
                    {#if cell?.n_uncovered}
                      <div class="text-xs font-semibold text-red-700">
                        {cell.n_uncovered} scoperte
                      </div>
                    {:else if cell?.n_covered}
                      <div class="text-xs font-semibold text-emerald-700">
                        {cell.n_covered} coperte
                      </div>
                    {:else if cell?.n_absent_teachers}
                      <div class="text-xs text-amber-700">
                        {cell.n_absent_teachers} ass.
                      </div>
                    {:else}
                      <div class="text-xs text-ink-300">-</div>
                    {/if}
                    <div class="text-[10px] text-ink-500">
                      {cell?.n_available_teachers ?? 0} liberi
                      {#if cell?.n_disposizione_teachers}
                        <span class="ml-1 text-sky-700 font-semibold"
                              title="In disposizione ufficiale">
                          {cell.n_disposizione_teachers} disp
                        </span>
                      {/if}
                      {#if cell?.n_hole_teachers}
                        <span class="ml-1 text-amber-800 font-semibold"
                              title="Buco tra prima e ultima ora">
                          {cell.n_hole_teachers} buco
                        </span>
                      {/if}
                    </div>
                  </button>
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<!-- ABSENCES MODAL -->
<Modal open={!!absencesModal}
       title={absencesModal ? `Assenze - ${calName(absencesModal.day)} ${fmtDateShort(absencesModal.date)}` : ''}
       onClose={() => (absencesModal = null)}>
  {#if absencesModal}
    <div class="space-y-3">
      <div>
        <h3 class="!text-base mb-1">Docenti assenti
          <span class="text-xs text-ink-500">({absencesModal.absences.length})</span>
        </h3>
        {#if absencesModal.absences.length === 0}
          <p class="text-xs text-ink-400 italic">Nessuna assenza registrata.</p>
        {:else}
          <table class="tbl text-sm">
            <thead><tr><th>Docente</th><th>Motivo</th><th></th></tr></thead>
            <tbody>
              {#each absencesModal.absences as a}
                <tr>
                  <td><strong>{a.teacher_display}</strong></td>
                  <td class="text-xs">{a.reason ?? ''}</td>
                  <td><button class="btn-danger !text-xs !px-2 !py-1"
                              on:click={() => removeAbsence(a)}>Rimuovi</button></td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>

      <div class="border-t border-ink-200 pt-3 space-y-2">
        <h3 class="!text-base">Aggiungi assenza</h3>
        <input class="w-full px-2 py-1 border border-ink-200 rounded text-sm"
               placeholder="filtra docente per cognome/nome/nickname..."
               bind:value={absenceFilter}/>
        <div class="grid grid-cols-2 gap-2">
          <select bind:value={absencesModal.pickedTeacherId}
                  class="px-2 py-1 border border-ink-200 rounded">
            <option value={null}>-- scegli docente --</option>
            {#each candidatesForAbsence as t}
              <option value={t.id}>
                {t.last_name ?? ''} {t.first_name ?? ''}
                {#if t.nickname && t.nickname !== ((t.last_name ?? '') + ' ' + (t.first_name ?? '')).trim()}
                  ({t.nickname})
                {/if}
              </option>
            {/each}
          </select>
          <input bind:value={absencesModal.reason}
                 placeholder="motivo (es. Malattia)"
                 class="px-2 py-1 border border-ink-200 rounded"/>
        </div>
        <div class="flex justify-between gap-2">
          <button class="btn-danger !text-xs"
                  on:click={() => clearDayAbsences(absencesModal.date)}
                  title="Cancella tutte le assenze e supplenze del giorno">
            Clear (azzera giornata)
          </button>
          <div class="flex gap-2">
            <button class="btn" on:click={() => (absencesModal = null)}>Chiudi</button>
            <button class="btn-primary" on:click={addAbsence}
                    disabled={!absencesModal.pickedTeacherId}>
              Aggiungi assenza
            </button>
          </div>
        </div>
      </div>
    </div>
  {/if}
</Modal>

<!-- CELL MODAL -->
<Modal open={!!cellModal}
       title={cellModal
         ? `${calName(cellModal.day)} ${fmtDateShort(cellModal.date)} - ore ${cellModal.hour}:00`
         : ''}
       onClose={closeCellModal}>
  {#if cellModal && cellModal.detail}
    <div class="grid grid-cols-2 gap-4">
      <!-- Uncovered slots -->
      <div>
        <h3 class="!text-base mb-2">
          Classi scoperte
          <span class="pill {allCovered ? 'pill-green' : 'pill-red'} ml-1">
            {cellModal.detail.uncovered.length}
          </span>
        </h3>
        {#if cellModal.detail.uncovered.length === 0}
          <p class="text-xs text-ink-400 italic">
            Nessuna classe scoperta in questa ora. Trascinare un docente
            disponibile non e' necessario qui.
          </p>
        {:else}
          <ul class="space-y-2">
            {#each cellModal.detail.uncovered as u}
              <li class="card !shadow-none p-3 border-2
                         {u.substitute_teacher_id ? 'border-emerald-300 bg-emerald-50'
                                                  : 'border-red-300 bg-red-50'}"
                  on:dragover={onDragOver}
                  on:drop={(ev) => onDrop(ev, u)}>
                <div class="flex items-baseline justify-between">
                  <strong>{u.class_name}</strong>
                  <span class="text-xs text-ink-500">{u.subject ?? ''}</span>
                </div>
                <div class="text-xs text-ink-500 mt-1">
                  Originale: <strong>{u.original_teacher_display}</strong>
                </div>
                {#if u.substitute_teacher_id}
                  <div class="mt-2 flex items-center justify-between">
                    <span class="text-sm">
                      Supplente: <strong>{u.substitute_teacher_display}</strong>
                    </span>
                    <button class="btn-danger !text-xs !px-2 !py-1"
                            on:click={() => removeSub(u)}>Rimuovi</button>
                  </div>
                {:else}
                  <div class="mt-2 text-xs italic text-red-700">
                    Trascina qui un docente dalla lista a destra.
                  </div>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </div>

      <!-- Available teachers -->
      <div>
        <h3 class="!text-base mb-2">
          Docenti disponibili
          <span class="pill ml-1">{filteredAvailable.length}</span>
          {#if filteredAvailable.length !== cellModal.detail.available.length}
            <span class="text-[11px] text-ink-400 font-normal">
              / {cellModal.detail.available.length}
            </span>
          {/if}
        </h3>
        <p class="text-[11px] text-ink-500 mb-2">
          Esclusi: docenti assenti oggi, in giorno libero, gia' impegnati
          o gia' usati come supplenti. La disposizione non dipende dalla
          materia: i filtri qui sotto selezionano solo chi mostrare.
        </p>
        <div class="mb-2 space-y-1" data-testid="avail-filters">
          <input class="w-full px-2 py-1 border border-ink-200 rounded text-sm"
                 placeholder="filtra per nome, classe di concorso, materia..."
                 bind:value={availQuery}
                 data-testid="avail-query"/>
          <div class="flex flex-wrap gap-1">
            <button class="btn !text-[10px] !px-2 !py-0.5"
                    class:!bg-ink-800={availFilter === 'all'}
                    class:!text-white={availFilter === 'all'}
                    on:click={() => setAvailFilter('all')}
                    data-testid="avail-filter-all">Tutti</button>
            <button class="btn !text-[10px] !px-2 !py-0.5"
                    class:!bg-sky-700={availFilter === 'same_subject'}
                    class:!text-white={availFilter === 'same_subject'}
                    on:click={() => setAvailFilter('same_subject')}
                    title={uncoveredSubjects.length
                      ? ('Stessa materia della lezione: ' + uncoveredSubjects.join(', '))
                      : 'Stessa materia della lezione scoperta'}
                    data-testid="avail-filter-same-subject">
              Stessa materia{uncoveredSubjects.length ? ` (${uncoveredSubjects.join(', ')})` : ''}
            </button>
            <button class="btn !text-[10px] !px-2 !py-0.5"
                    class:!bg-sky-700={availFilter === 'same_as_absent'}
                    class:!text-white={availFilter === 'same_as_absent'}
                    on:click={() => setAvailFilter('same_as_absent')}
                    title="Docenti che insegnano almeno una materia del collega assente"
                    data-testid="avail-filter-same-as-absent">
              Materie del collega
            </button>
            <button class="btn !text-[10px] !px-2 !py-0.5"
                    class:!bg-sky-600={availFilter === 'disposizione'}
                    class:!text-white={availFilter === 'disposizione'}
                    on:click={() => setAvailFilter('disposizione')}
                    data-testid="avail-filter-disp">Disposizione</button>
            <button class="btn !text-[10px] !px-2 !py-0.5"
                    class:!bg-amber-700={availFilter === 'hole'}
                    class:!text-white={availFilter === 'hole'}
                    on:click={() => setAvailFilter('hole')}
                    data-testid="avail-filter-hole">Buco</button>
            <button class="btn !text-[10px] !px-2 !py-0.5"
                    class:!bg-ink-500={availFilter === 'free'}
                    class:!text-white={availFilter === 'free'}
                    on:click={() => setAvailFilter('free')}
                    data-testid="avail-filter-free">Liberi</button>
            <button class="btn !text-[10px] !px-2 !py-0.5"
                    class:!bg-purple-700={availFilter === 'potenziamento'}
                    class:!text-white={availFilter === 'potenziamento'}
                    on:click={() => setAvailFilter('potenziamento')}
                    data-testid="avail-filter-pot">Potenziamento</button>
            <button class="btn !text-[10px] !px-2 !py-0.5"
                    class:!bg-ink-700={availFilter === 'under_hours'}
                    class:!text-white={availFilter === 'under_hours'}
                    on:click={() => setAvailFilter('under_hours')}
                    data-testid="avail-filter-under">Sotto contratto</button>
          </div>
        </div>
        {#if cellModal.detail.available.length === 0}
          <p class="text-xs text-ink-400 italic">Nessun docente disponibile.</p>
        {:else if filteredAvailable.length === 0}
          <p class="text-xs text-ink-400 italic">
            Nessun docente con questo filtro.
            <button class="underline" on:click={() => { availFilter = 'all'; availQuery = ''; }}>
              Mostra tutti
            </button>
          </p>
        {:else}
          <p class="text-[11px] text-ink-400 mb-1">
            <span class="pill !text-[9px]"
              style="background:#bae6fd;color:#0c4a6e;">DISP</span>
            disposizione ufficiale ·
            <span class="pill !text-[9px]"
              style="background:#fde68a;color:#78350f;font-weight:700;">BUCO</span>
            buco (meno scomodo) ·
            <span class="pill !text-[9px]"
              style="background:#e5e7eb;color:#374151;">LIBERO</span>
            semplicemente libero ·
            <span class="pill !text-[9px]"
              style="background:#e9d5ff;color:#581c87;">POT</span>
            potenziamento (Legge 107).
          </p>
          <ul class="space-y-1 max-h-96 overflow-auto">
            {#each filteredAvailable as t}
              <li class="card !shadow-none p-2 cursor-grab
                         hover:bg-accent-500/10 active:cursor-grabbing"
                  class:!border-sky-400={t.is_disposizione}
                  class:!bg-sky-50={t.is_disposizione}
                  class:!border-amber-500={t.is_hole && !t.is_disposizione}
                  class:!bg-amber-100={t.is_hole && !t.is_disposizione}
                  class:!border-purple-300={t.is_potenziamento && !t.is_disposizione && !t.is_hole}
                  class:!bg-purple-50={t.is_potenziamento && !t.is_disposizione && !t.is_hole}
                  class:!ring-2={t.is_hole}
                  class:!ring-amber-500={t.is_hole}
                  draggable="true"
                  on:dragstart={(ev) => onDragStart(ev, t)}
                  on:dragend={onDragEnd}
                  title="Trascina su una classe scoperta">
                <div class="flex items-baseline justify-between">
                  <strong>
                    {#if t.is_disposizione}
                      <span class="pill !text-[9px]"
                        style="background:#bae6fd;color:#0c4a6e;"
                        title="In disposizione ufficiale in questa ora"
                      >DISP</span>
                    {:else if t.is_hole}
                      <span class="pill !text-[9px] font-bold"
                        style="background:#fde68a;color:#78350f;"
                        title="Buco tra prima e ultima lezione: coprire e' meno scomodo"
                      >BUCO</span>
                    {:else}
                      <span class="pill !text-[9px]"
                        style="background:#e5e7eb;color:#374151;"
                        title="Semplicemente libero in questa ora"
                      >LIBERO</span>
                    {/if}
                    {#if t.is_potenziamento}
                      <span class="pill !text-[9px]"
                        style="background:#e9d5ff;color:#581c87;"
                        title={`${t.potenziamento_hours}h di potenziamento`}
                      >POT</span>
                    {/if}
                    {#if t.matches_lesson_subject}
                      <span class="pill !text-[9px]"
                        style="background:#dbeafe;color:#1e3a8a;"
                        title="Insegna la materia della lezione scoperta"
                      >MAT</span>
                    {/if}
                    {t.display}
                  </strong>
                  {#if t.group}<span class="text-[10px] text-ink-500">{t.group}</span>{/if}
                </div>
                <div class="text-[11px] text-ink-500">
                  {(t.subjects || []).join(', ') || '-'}
                  <span class="ml-2">{t.scheduled_hours}/{t.max_hours} ore</span>
                  {#if t.is_potenziamento}
                    <span class="ml-2">+{t.potenziamento_hours}h pot</span>
                  {/if}
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    </div>

    <div class="mt-5 flex items-center justify-between">
      <span class="text-xs text-ink-500">
        Stato:
        {#if cellModal.detail.uncovered.length === 0}
          <span class="pill">nessuna assenza in questa cella</span>
        {:else if allCovered}
          <span class="pill-green">tutte le scoperte sono coperte</span>
        {:else}
          <span class="pill-red">classi ancora scoperte</span>
        {/if}
      </span>
      <button class="btn-primary" on:click={closeCellModal}
              disabled={!allCovered && cellModal.detail.uncovered.length > 0}>
        Salva e chiudi
      </button>
    </div>
  {/if}
</Modal>
