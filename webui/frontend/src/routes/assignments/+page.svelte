<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash, refreshDataset } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';

  let byClass = {};
  let allSubjects = [];
  let editing = null;
  let filter = '';

  // teachers qualified for the subject of the row being edited
  let teachersForSubject = [];

  // load panel
  let loadInfo = null;     // {teachers:[], n_over, n_under, n_total}
  let showLoadPanel = false;
  let loadFilter = 'problemi';   // 'problemi' | 'all'

  onMount(async () => {
    await reload();
    allSubjects = (await api.get('/api/subjects')).map((s) => s.name);
  });

  async function reload() {
    byClass = await api.get('/api/assignments/by-class');
    try { loadInfo = await api.get('/api/assignments/loads'); }
    catch { loadInfo = null; }
  }

  async function startEdit(cls, row) {
    editing = {
      class_name: cls,
      subject: row.subject,
      teacher_name: row.teacher,
      hours: row.hours,
      locked: row.locked || false,
      _existing: row.id,
    };
    teachersForSubject = [];
    try {
      teachersForSubject = await api.get(
        '/api/assignments/teachers-for-subject?subject='
        + encodeURIComponent(row.subject)
      );
    } catch (e) {
      flash('Errore caricando docenti per ' + row.subject + ': ' + e.message,
            'error');
    }
  }

  async function save() {
    try {
      const r = await api.put('/api/assignments/manual', {
        class_name: editing.class_name,
        subject: editing.subject,
        teacher_name: editing.teacher_name,
        locked: editing.locked
      });
      if (r.accepted) {
        flash('Cattedra aggiornata', 'success');
        editing = null;
        await reload();
        await refreshDataset();
      } else {
        flash('Rifiutato: ' + r.reason, 'error');
      }
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function toggleLock(id, lockedNow) {
    try {
      await api.post('/api/assignments/lock/' + id + '?locked=' + (!lockedNow));
      await reload();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  $: classNames = Object.keys(byClass).filter((c) =>
    !filter || c.toLowerCase().includes(filter.toLowerCase())
  ).sort();

  // Hours delta if the edit gets accepted: current row.hours moves from
  // the OLD teacher to the NEW one. We show this info in the dropdown
  // entries so the user sees if a pick would over-fill them.
  $: editingHours = editing?.hours ?? 0;

  function teacherBadge(t) {
    if (!t) return '';
    const used = t.assigned_hours;
    const mx = t.max_hours;
    if (t.is_over) return `${used}/${mx} (gia oltre il max!)`;
    return `${used}/${mx}`;
  }

  function predictedStatus(t) {
    // If this teacher is selected, and the current editing has a
    // previous teacher different from t, the edit shifts editingHours
    // FROM the old teacher TO this one.
    const oldName = editing._existing ? editing.teacher_name : null;
    const isOldOne = oldName === t.name;
    const wouldHave = (isOldOne ? t.assigned_hours
                                : t.assigned_hours + editingHours);
    if (wouldHave > t.max_hours) return 'over';
    if (wouldHave === t.max_hours) return 'full';
    return 'ok';
  }

  function predictedBadge(t) {
    const ps = predictedStatus(t);
    if (ps === 'over')  return ' [SFORA: +' + (t.assigned_hours + editingHours - t.max_hours) + 'h]';
    if (ps === 'full')  return ' [pieno]';
    return '';
  }

  $: problemRows = (loadInfo?.teachers ?? []).filter(
    (r) => r.status !== 'ok'
  );
  $: visibleLoadRows = loadFilter === 'all'
                          ? (loadInfo?.teachers ?? [])
                          : problemRows;
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Cattedre (assegnazione docenti -&gt; classi)</h1>
    <span class="text-sm text-ink-500">{Object.keys(byClass).length} classi</span>
    {#if loadInfo}
      <button class="btn ml-auto"
              on:click={() => (showLoadPanel = !showLoadPanel)}
              title="Mostra docenti con problemi di copertura">
        {#if loadInfo.n_over + loadInfo.n_under > 0}
          <span class="pill-amber !text-[10px] mr-1">
            {loadInfo.n_over + loadInfo.n_under}
          </span>
        {/if}
        {showLoadPanel ? 'Nascondi warnings' : 'Warnings cattedre'}
      </button>
    {/if}
  </div>

  {#if showLoadPanel && loadInfo}
    <div class="card p-3 border-amber-300 bg-amber-50/40 space-y-2">
      <div class="flex items-baseline gap-3 flex-wrap">
        <h3 class="!text-base">
          Cattedre / docenti incompleti
          <span class="text-xs text-ink-500 ml-2">
            {loadInfo.n_over} sopra il max,
            {loadInfo.n_under} sotto il max,
            su {loadInfo.n_total} docenti totali
          </span>
        </h3>
        <div class="ml-auto flex gap-1">
          <button class="btn !text-xs"
                  class:bg-ink-100={loadFilter === 'problemi'}
                  on:click={() => (loadFilter = 'problemi')}>
            solo problemi
          </button>
          <button class="btn !text-xs"
                  class:bg-ink-100={loadFilter === 'all'}
                  on:click={() => (loadFilter = 'all')}>
            tutti
          </button>
        </div>
      </div>
      {#if visibleLoadRows.length === 0}
        <p class="text-xs text-emerald-700 italic">
          Nessun problema di copertura. Tutti i docenti hanno ore = max.
        </p>
      {:else}
        <table class="tbl text-sm">
          <thead>
            <tr>
              <th>Docente</th>
              <th>Cl. concorso</th>
              <th>Assegnate</th>
              <th>Max</th>
              <th>Delta</th>
              <th>Stato</th>
            </tr>
          </thead>
          <tbody>
            {#each visibleLoadRows as r}
              <tr>
                <td><strong>{r.display}</strong>
                  <span class="text-[10px] text-ink-400">({r.name})</span>
                </td>
                <td class="text-xs">{r.group ?? ''}</td>
                <td class="text-center">{r.assigned_hours}</td>
                <td class="text-center">{r.max_hours}</td>
                <td class="text-center">
                  {#if r.delta > 0}
                    <span class="text-red-700 font-semibold">+{r.delta}</span>
                  {:else if r.delta < 0}
                    <span class="text-amber-700 font-semibold">{r.delta}</span>
                  {:else}
                    <span class="text-ink-400">0</span>
                  {/if}
                </td>
                <td>
                  {#if r.status === 'over'}
                    <span class="pill-red">SFORA il max</span>
                  {:else if r.status === 'under'}
                    <span class="pill-amber">ore mancanti</span>
                  {:else if r.status === 'empty'}
                    <span class="pill-amber">nessuna cattedra</span>
                  {:else}
                    <span class="pill-green">ok</span>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  {/if}

  <div class="card p-3">
    <input class="w-full px-2 py-1.5 rounded-md border border-ink-200" placeholder="Filtra classe..." bind:value={filter}/>
  </div>

  <div class="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
    {#each classNames as cn}
      <div class="card p-4">
        <h3 class="mb-2">{cn}</h3>
        <table class="tbl">
          <thead><tr><th>Materia</th><th>Docente</th><th>Ore</th><th></th></tr></thead>
          <tbody>
            {#each byClass[cn] as row}
              <tr>
                <td>{row.subject}</td>
                <td>{row.teacher}</td>
                <td class="text-center">{row.hours}</td>
                <td class="whitespace-nowrap">
                  <button class="btn !text-xs !px-2 !py-1" on:click={() => startEdit(cn, row)}>cambia</button>
                  <button class="btn !text-xs !px-2 !py-1 focus-ring"
                    title={row.locked ? 'Sblocca' : 'Blocca'}
                    aria-label={row.locked
                      ? 'Sblocca cattedra ' + row.subject + ' per ' + cn
                      : 'Blocca cattedra ' + row.subject + ' per ' + cn}
                    aria-pressed={row.locked}
                    on:click={() => toggleLock(row.id, row.locked)}>
                    <span aria-hidden="true">{row.locked ? '🔒' : '🔓'}</span>
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/each}
  </div>
</div>

<Modal open={!!editing} title="Cambia docente" onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3">
      <div class="field">
        <label>Classe</label>
        <input value={editing.class_name} disabled/>
      </div>
      <div class="field">
        <label>Materia</label>
        <input value={editing.subject} disabled/>
      </div>
      <div class="field col-span-2">
        <label>
          Docente abilitato per "{editing.subject}"
          <span class="text-xs text-ink-400">
            ({teachersForSubject.length} candidati; ore della cattedra: {editingHours})
          </span>
        </label>
        <select bind:value={editing.teacher_name}>
          {#each teachersForSubject as t}
            <option value={t.name}>
              {t.display} - {teacherBadge(t)}{predictedBadge(t)}
            </option>
          {/each}
        </select>
        <div class="text-xs text-ink-400 mt-1">
          (in alternativa puoi digitare manualmente in
          <input list="ll-t" bind:value={editing.teacher_name}
                 class="px-2 py-0.5 border border-ink-200 rounded text-xs"/>
          - <datalist id="ll-t">
              {#each teachersForSubject as t}
                <option value={t.name}/>
              {/each}
            </datalist> )
        </div>
      </div>
      <label class="flex items-center gap-2 col-span-2 text-sm">
        <input type="checkbox" bind:checked={editing.locked}/> Bloccare la modifica (l'ottimizzatore non potra cambiare)
      </label>
    </div>
    <div class="mt-4 text-xs text-ink-500">
      Il backend valida HARD: ore-cattedra, abilitazione materia, esistenza docente.
      Se la mossa rompe un vincolo, viene rifiutata con messaggio chiaro.
      Le voci marcate <code>[SFORA: +Xh]</code> indicano docenti per cui
      questa scelta sforerebbe il max-hours; il backend potrebbe rifiutare.
    </div>
    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}>Annulla</button>
      <button class="btn-primary" on:click={save}>Salva</button>
    </div>
  {/if}
</Modal>
