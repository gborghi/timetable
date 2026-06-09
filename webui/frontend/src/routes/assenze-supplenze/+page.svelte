<script>
  import DecorIcon from '$lib/components/DecorIcon.svelte';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants';
  import Modal from '$lib/components/Modal.svelte';

  // ----- state -----
  let weekStart = mondayOf(new Date());
  let coverage = null;        // WeekCoverageOut
  let allTeachers = [];

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

  // ----- load -----
  async function load() {
    try {
      coverage = await api.get('/api/coverage/week?week_start=' + weekStart);
      allTeachers = await api.get('/api/teachers');
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
    if (!confirm('Cancellare TUTTE le assenze e supplenze del ' + fmtDateShort(date) + '?')) return;
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

  function closeCellModal() {
    if (cellModal && cellModal.detail
        && cellModal.detail.uncovered.some((u) => !u.substitute_teacher_id)) {
      if (!confirm('Ci sono ancora ore scoperte. Chiudere comunque?')) return;
    }
    cellModal = null;
  }
</script>

<div class="space-y-4" data-testid="absences-page">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1 class="flex items-center gap-2"><DecorIcon name="coffee" size={26} class="shrink-0" /> Assenze e supplenze</h1>
    <div class="ml-auto flex items-center gap-2">
      <button class="btn !text-xs" on:click={() => shiftWeek(-1)}
              data-testid="absences-prev-week">&lt; settimana prec.</button>
      <input type="date" bind:value={weekStart} on:change={load}
             class="px-2 py-1 border border-ink-200 rounded text-sm"
             title="Lunedi della settimana"
             data-testid="absences-week-input"/>
      <button class="btn !text-xs" on:click={() => shiftWeek(1)}
              data-testid="absences-next-week">settimana succ. &gt;</button>
      <button class="btn !text-xs" on:click={() => { weekStart = mondayOf(new Date()); load(); }}
              data-testid="absences-today">oggi</button>
    </div>
  </div>

  {#if !coverage}
    <p class="text-sm text-ink-500">Caricamento...</p>
  {:else if !coverage.has_active_solution}
    <p class="text-sm text-amber-700">Nessuna soluzione attiva: importa o calcola un orario per usare questa pagina.</p>
  {:else}
    <p class="text-xs text-ink-500">
      Click sull'<strong>intestazione di un giorno</strong> per registrare le assenze;
      click su una <strong>cella</strong> per vedere chi e disponibile e
      assegnare supplenze (drag-drop). Le celle rosse hanno classi scoperte;
      verdi sono coperte.
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
                  {DAY_NAMES_IT[d.day]} {fmtDateShort(d.date)}
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
          {#each HOURS as h}
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
                      {cell?.n_available_teachers ?? 0} disp.
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
       title={absencesModal ? `Assenze - ${DAY_NAMES_IT[absencesModal.day]} ${fmtDateShort(absencesModal.date)}` : ''}
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
         ? `${DAY_NAMES_IT[cellModal.day]} ${fmtDateShort(cellModal.date)} - ore ${cellModal.hour}:00`
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
          <span class="pill ml-1">{cellModal.detail.available.length}</span>
        </h3>
        <p class="text-[11px] text-ink-500 mb-2">
          Esclusi: docenti assenti oggi, in giorno libero, gia' impegnati
          o gia' usati come supplenti.
        </p>
        {#if cellModal.detail.available.length === 0}
          <p class="text-xs text-ink-400 italic">Nessun docente disponibile.</p>
        {:else}
          <p class="text-[11px] text-ink-400 mb-1">
            <span class="pill !text-[9px]"
              style="background:#e9d5ff;color:#581c87;">POT</span>
            in cima = docenti con ore di potenziamento
            (Legge 107), priorita' supplenze.
          </p>
          <ul class="space-y-1 max-h-96 overflow-auto">
            {#each cellModal.detail.available as t}
              <li class="card !shadow-none p-2 cursor-grab
                         hover:bg-accent-500/10 active:cursor-grabbing"
                  class:!border-purple-300={t.is_potenziamento}
                  class:!bg-purple-50={t.is_potenziamento}
                  draggable="true"
                  on:dragstart={(ev) => onDragStart(ev, t)}
                  on:dragend={onDragEnd}
                  title="Trascina su una classe scoperta">
                <div class="flex items-baseline justify-between">
                  <strong>
                    {#if t.is_potenziamento}
                      <span class="pill !text-[9px]"
                        style="background:#e9d5ff;color:#581c87;"
                        title={`${t.potenziamento_hours}h di potenziamento`}
                      >POT</span>
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
