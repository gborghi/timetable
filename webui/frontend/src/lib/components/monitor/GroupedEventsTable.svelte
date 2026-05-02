<script>
  /**
   * Reusable grouped + sortable + queryable events table for /monitor.
   *
   * Used twice on the page:
   *   1. Main "all events" view  (auxQuery = '')
   *   2. Red panel "non schedulati"  (auxQuery = 'schedulato = 0')
   *
   * Each instance keeps its OWN state (groupBy1/2, sortLevels,
   * rowQuery, collapsed sets, ...) so toggling/sorting/querying in
   * one panel does not affect the other.
   *
   * Props:
   *   endpoint    GET URL that returns { items[], n_total, n_filtered,
   *                                      n_unscheduled }
   *   auxQuery    extra DSL filter ANDed into every request (e.g.
   *               'schedulato = 0' for the red panel)
   *   redTheme    if true, the panel uses a red colour scheme
   *               (border, header bg) and a red title
   *   title       header text
   *   subtitle    optional explanatory paragraph below the title
   *   onChanged   called whenever the data changes due to a per-row
   *               action so the parent can refresh OTHER instances
   *               and the summary
   *
   * Per-row actions delegate to the parent via `onModify(row)` and
   * `onDelete(row)` callbacks (the parent owns the slot-picker /
   * AddLessonModal / confirm dialogs).
   */
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';

  export let endpoint = '/api/monitor/event-rows';
  export let auxQuery = '';
  export let redTheme = false;
  export let title = 'Eventi';
  export let subtitle = '';
  export let onModify = (_row) => {};
  export let onDelete = (_row) => {};
  export let onDissociate = null;     // optional async (row) => void
  export let onLockToggle = null;     // optional async (row) => void
  export let onPlace = null;          // optional async (row) => void
  export let onBulkDelete = null;     // optional async (rows[]) => void
  export let onBulkDissociate = null; // optional async (rows[]) => void
  export let onBulkLock = null;       // optional async (rows[]) => void
  export let onBulkPlace = null;      // optional async (rows[]) => void
  export let onChanged = () => {};
  // Multi-select like SortableQueryableList. When true, a checkbox
  // column is shown; the parent can read `selectedIds` via
  // bind:selectedIds.
  export let selectable = false;
  export let selectedIds = [];

  // ----- State (per instance) -----------------------------------------
  let data = null;            // { items[], n_total, n_filtered, n_unscheduled }
  let busy = false;
  let queryError = '';
  let lastUrl = '';

  let groupBy1 = 'none';
  let groupBy2 = 'none';
  let rowQuery = '';
  let appliedQuery = '';
  let sortLevels = [];        // [{ column, direction }]
  let showHelp = false;

  const MAX_SORT_LEVELS = 3;

  // collapsed sets: empty = everything expanded.
  let collapsedG1 = new Set();
  let collapsedG2 = new Set();

  const COLS = [
    { key: 'docente', label: 'Docente' },
    { key: 'classe',  label: 'Classe' },
    { key: 'materia', label: 'Materia' },
    { key: 'giorno',  label: 'Giorno' },
    { key: 'ora',     label: 'Ora' },
    { key: 'aula',    label: 'Aula' },
    { key: 'gruppo',  label: 'Gruppo' },
    { key: 'stato',   label: 'Stato' },
  ];
  const GROUP_OPTIONS = [
    { value: 'none',           label: '— nessuno —' },
    { value: 'teacher_name',   label: 'Docente' },
    { value: 'class_name',     label: 'Classe' },
    { value: 'subject',        label: 'Materia' },
    { value: 'day_name',       label: 'Giorno' },
    { value: 'hour',           label: 'Ora' },
    { value: 'classroom_name', label: 'Aula' },
    { value: 'group_name',     label: 'Gruppo' },
    { value: 'is_scheduled',   label: 'Schedulato?' },
    { value: 'is_complete',    label: 'Completo?' },
  ];

  // ----- Sort helpers --------------------------------------------------
  function buildSortString() {
    return sortLevels.map((l) => `${l.column},${l.direction}`).join(':');
  }
  function buildFullQuery() {
    if (auxQuery && appliedQuery) return `(${auxQuery}) AND (${appliedQuery})`;
    return auxQuery || appliedQuery || '';
  }
  function onLabelDblClick(colKey) {
    const idx = sortLevels.findIndex((l) => l.column === colKey);
    if (idx >= 0) {
      sortLevels = sortLevels.filter((_, i) => i !== idx);
    } else if (sortLevels.length < MAX_SORT_LEVELS) {
      sortLevels = [...sortLevels, { column: colKey, direction: 'asc' }];
    } else {
      flash(`Massimo ${MAX_SORT_LEVELS} livelli di sort.`, 'error');
      return;
    }
    refresh();
  }
  function onIndicatorClick(colKey) {
    const idx = sortLevels.findIndex((l) => l.column === colKey);
    if (idx < 0) return;
    sortLevels = sortLevels.map((l, i) => i === idx
      ? { ...l, direction: l.direction === 'asc' ? 'desc' : 'asc' }
      : l);
    refresh();
  }
  function resetSort() {
    if (sortLevels.length === 0) return;
    sortLevels = [];
    refresh();
  }
  function resetQuery() {
    if (!rowQuery && !appliedQuery) return;
    rowQuery = '';
    appliedQuery = '';
    refresh();
  }
  function applyQuery() {
    appliedQuery = rowQuery;
    refresh();
  }

  // ----- Toggle helpers -----------------------------------------------
  function toggleAll() {
    collapsedG1 = new Set(groupedBuckets.map((b) => b.key1));
    const all2 = new Set();
    for (const b of groupedBuckets)
      for (const sb of b.sub) all2.add(b.key1 + '|' + sb.key2);
    collapsedG2 = all2;
  }
  function untoggleAll() {
    collapsedG1 = new Set();
    collapsedG2 = new Set();
  }
  function toggleG1(key) {
    if (collapsedG1.has(key)) collapsedG1.delete(key);
    else collapsedG1.add(key);
    collapsedG1 = collapsedG1;
  }
  function toggleG2(key) {
    if (collapsedG2.has(key)) collapsedG2.delete(key);
    else collapsedG2.add(key);
    collapsedG2 = collapsedG2;
  }

  // ----- Data fetch ----------------------------------------------------
  export async function refresh() {
    busy = true;
    queryError = '';
    const params = new URLSearchParams();
    const q = buildFullQuery();
    if (q) params.set('q', q);
    const sortStr = buildSortString();
    if (sortStr) params.set('sort', sortStr);
    params.set('_t', String(Date.now()));   // cache-buster
    const url = endpoint + '?' + params.toString();
    lastUrl = url;
    try {
      data = await api.get(url);
    } catch (e) {
      queryError = e?.message || String(e);
    } finally {
      busy = false;
    }
  }

  // Initial load on mount
  refresh();

  // ----- Grouping ------------------------------------------------------
  function groupValue(row, key) {
    if (key === 'none') return { label: '' };
    let raw = row[key];
    if (key === 'classroom_name' || key === 'group_name'
        || key === 'day_name') {
      if (!raw) raw = '(nessuno)';
    } else if (key === 'is_scheduled') {
      raw = raw ? 'schedulato' : 'non schedulato';
    } else if (key === 'is_complete') {
      raw = raw ? 'completo' : 'incompleto';
    } else if (key === 'hour') {
      raw = raw == null ? '(non schedulato)' : (raw + ':00');
    }
    return { label: String(raw ?? '') };
  }

  function groupRows(rows, k1, k2) {
    const m1 = new Map();
    for (const r of rows) {
      const v1 = groupValue(r, k1).label;
      if (!m1.has(v1)) m1.set(v1, []);
      m1.get(v1).push(r);
    }
    return Array.from(m1.entries())
      .sort((a, b) => a[0].localeCompare(b[0], 'it'))
      .map(([label1, rows1]) => {
        const m2 = new Map();
        for (const r of rows1) {
          const v2 = groupValue(r, k2).label;
          if (!m2.has(v2)) m2.set(v2, []);
          m2.get(v2).push(r);
        }
        const sub = Array.from(m2.entries())
          .sort((a, b) => a[0].localeCompare(b[0], 'it'))
          .map(([label2, rows2]) => ({ key2: label2, rows2 }));
        return { key1: label1, rows1, sub };
      });
  }

  $: groupedBuckets = data ? groupRows(data.items, groupBy1, groupBy2) : [];

  function rowId(r, idx) {
    return r.lesson_id != null
      ? `lesson:${r.lesson_id}`
      : `placeholder:${r.assignment_id}:${idx}`;
  }

  // ----- Selection helpers (mirrors SortableQueryableList) ------------
  let lastClickedKey = null;
  function isSelected(r, idx) {
    return selectedIds.includes(rowId(r, idx));
  }
  function toggleOne(r, idx) {
    const k = rowId(r, idx);
    if (selectedIds.includes(k)) {
      selectedIds = selectedIds.filter((x) => x !== k);
    } else {
      selectedIds = [...selectedIds, k];
    }
    lastClickedKey = k;
  }
  function selectAllVisible() {
    const all = [];
    let i = 0;
    for (const r of (data?.items ?? [])) {
      all.push(rowId(r, i++));
    }
    selectedIds = all;
  }
  function clearSelection() {
    selectedIds = [];
    lastClickedKey = null;
  }
  function _selectedRows() {
    const idSet = new Set(selectedIds);
    const rows = [];
    let i = 0;
    for (const r of (data?.items ?? [])) {
      if (idSet.has(rowId(r, i))) rows.push(r);
      i++;
    }
    return rows;
  }
  async function bulkDelete() {
    if (!onBulkDelete) return;
    const rows = _selectedRows();
    if (rows.length === 0) return;
    await onBulkDelete(rows);
    clearSelection();
    await refresh();
    onChanged();
  }
  async function bulkDissociate() {
    if (!onBulkDissociate) return;
    const rows = _selectedRows();
    if (rows.length === 0) return;
    await onBulkDissociate(rows);
    clearSelection();
    await refresh();
    onChanged();
  }
  async function bulkLock() {
    if (!onBulkLock) return;
    const rows = _selectedRows();
    if (rows.length === 0) return;
    await onBulkLock(rows);
    clearSelection();
    await refresh();
    onChanged();
  }
  async function bulkPlace() {
    if (!onBulkPlace) return;
    const rows = _selectedRows();
    if (rows.length === 0) return;
    await onBulkPlace(rows);
    clearSelection();
    await refresh();
    onChanged();
  }
</script>

<div class="space-y-2 {redTheme ? 'p-3 border-2 border-red-300 bg-red-50 rounded' : ''}">
  {#if title}
    <h3 class="font-semibold {redTheme ? 'text-red-900' : ''}">
      {title}
      {#if data}
        <span class="text-xs font-normal {redTheme ? 'text-red-700' : 'text-ink-500'} ml-2">
          {data.n_filtered ?? data.n_total} / {data.n_total} righe
          ({data.n_unscheduled} non schedulate)
        </span>
      {/if}
    </h3>
  {/if}

  {#if subtitle}
    <p class="text-xs {redTheme ? 'text-red-700' : 'text-ink-500'}">{subtitle}</p>
  {/if}

  <div class="card p-3 flex items-center gap-3 flex-wrap">
    <span class="text-sm font-medium">Raggruppa per:</span>
    <select class="text-sm px-2 py-1 border border-ink-200 rounded"
            bind:value={groupBy1}>
      {#each GROUP_OPTIONS as o}<option value={o.value}>{o.label}</option>{/each}
    </select>
    <span class="text-sm">e poi per:</span>
    <select class="text-sm px-2 py-1 border border-ink-200 rounded"
            bind:value={groupBy2}>
      {#each GROUP_OPTIONS as o}<option value={o.value}>{o.label}</option>{/each}
    </select>
    <button class="btn !text-xs" on:click={toggleAll}
            title="Chiudi tutti i gruppi">Toggle all</button>
    <button class="btn !text-xs" on:click={untoggleAll}
            title="Apri tutti i gruppi">Untoggle all</button>
  </div>

  <div class="card p-3 flex flex-wrap gap-2 items-end">
    <div class="flex-1 min-w-64">
      <label class="text-xs text-ink-500">Query</label>
      <input class="w-full px-2 py-1.5 rounded-md border border-ink-200 font-mono text-sm"
             placeholder="es. docente contains Rossi, completo = 0, classe = 3B_scientifico"
             bind:value={rowQuery}
             on:keydown={(e) => { if (e.key === 'Enter') applyQuery(); }}/>
    </div>
    <button class="btn" on:click={applyQuery} disabled={busy}>
      {busy ? '...' : 'Cerca'}
    </button>
    <button class="btn !text-xs"
            on:click={() => (showHelp = !showHelp)}>?  guida</button>
    <span class="border-l border-ink-200 h-6 mx-1"></span>
    <button class="btn !text-xs" on:click={resetQuery}
            disabled={!rowQuery && !appliedQuery}
            title="Svuota la barra di ricerca">Reset query</button>
    <button class="btn !text-xs" on:click={resetSort}
            disabled={sortLevels.length === 0}
            title="Torna all'ordine originale">Reset sort</button>
    <button class="btn !text-xs" on:click={refresh} disabled={busy}>refresh</button>
    {#if selectable}
      <span class="border-l border-ink-200 h-6 mx-1"></span>
      <button class="btn !text-xs" on:click={selectAllVisible}
              title="Seleziona tutte le righe attualmente visibili">
        Seleziona tutto
      </button>
      <button class="btn !text-xs" on:click={clearSelection}
              disabled={selectedIds.length === 0}>
        Deseleziona
      </button>
      {#if onBulkDissociate}
        <button class="btn-amber !text-xs" on:click={bulkDissociate}
                disabled={selectedIds.length === 0}
                title="Toglie l'assegnazione temporale a tutti i selezionati (cattedra resta)">
          Dissocia selezionati
        </button>
      {/if}
      {#if onBulkLock}
        <button class="btn !text-xs" on:click={bulkLock}
                disabled={selectedIds.length === 0}
                title="Blocca / sblocca i selezionati (toggle)">
          Blocca selezionati
        </button>
      {/if}
      {#if onBulkPlace}
        <button class="btn-primary !text-xs" on:click={bulkPlace}
                disabled={selectedIds.length === 0}
                title="Esegue il placer sui selezionati">
          Piazza selezionati
        </button>
      {/if}
      {#if onBulkDelete}
        <button class="btn-red !text-xs" on:click={bulkDelete}
                disabled={selectedIds.length === 0}
                title="Elimina tutte le righe selezionate">
          Elimina selezionati
        </button>
      {/if}
      {#if selectedIds.length > 0}
        <span class="pill pill-blue">{selectedIds.length} selezionati</span>
      {/if}
    {/if}
  </div>

  {#if lastUrl}
    <div class="text-[10px] text-ink-400 font-mono px-3">
      <span class="text-ink-500">Ultima richiesta:</span>
      <code>{lastUrl.replace(/&_t=\d+/, '')}</code>
    </div>
  {/if}

  {#if queryError}
    <div class="card p-2 text-xs text-red-700 bg-red-50 border-red-300">
      Errore query: {queryError}
    </div>
  {/if}

  {#if sortLevels.length > 0}
    <div class="card p-2 text-xs flex flex-wrap items-center gap-2 bg-accent-500/5 border-accent-500/30">
      <span class="text-ink-500">Sort attivo:</span>
      {#each sortLevels as l, i}
        <span class="pill pill-blue">
          {i + 1}. {l.column} {l.direction === 'asc' ? '▲' : '▼'}
        </span>
      {/each}
      <span class="text-ink-400 italic ml-2">
        doppio click sul nome colonna per aggiungere/rimuovere; click ▲/▼ per invertire.
      </span>
    </div>
  {/if}

  {#if showHelp}
    <div class="card p-3 text-xs space-y-2 bg-ink-50">
      <div><strong>Operatori:</strong>
        <code>= != &lt; &lt;= &gt; &gt;= contains startswith endswith in [...]</code></div>
      <div><strong>Logica:</strong> <code>AND</code> / <code>OR</code> /
        parentesi <code>(...)</code>.</div>
      <div><strong>Campi:</strong>
        <code>docente, classe, materia, giorno, ora, aula, gruppo,
              schedulato, completo, stato</code></div>
      <div><strong>Esempi:</strong>
        <ul class="list-disc list-inside">
          <li><code>completo = 0</code></li>
          <li><code>schedulato = 0</code></li>
          <li><code>classe = 3B_scientifico</code></li>
          <li><code>aula = LabFisica AND giorno = Lunedi</code></li>
          <li><code>docente contains Rossi</code></li>
        </ul></div>
      <div class="text-ink-500"><strong>Sort multi-livello:</strong>
        doppio click su una colonna per aggiungere/rimuovere
        un livello (max {MAX_SORT_LEVELS}).</div>
    </div>
  {/if}

  {#if !data}
    <div class="card p-4 text-sm text-ink-500">
      {busy ? 'Caricamento eventi...' : 'Nessun evento.'}
    </div>
  {:else}
    <div class="card p-2 overflow-x-auto">
      <table class="tbl text-xs w-full">
        <thead>
          <tr>
            {#if selectable}
              <th class="w-6 text-center"
                  title="Tieni Ctrl o Shift per selezione multipla.">
                <input type="checkbox"
                       checked={selectedIds.length > 0
                                && selectedIds.length === (data.items?.length ?? 0)}
                       indeterminate={selectedIds.length > 0
                                && selectedIds.length < (data.items?.length ?? 0)}
                       on:change={(e) => e.target.checked
                                ? selectAllVisible() : clearSelection()}/>
              </th>
            {/if}
            {#each COLS as c}
              {@const idx = sortLevels.findIndex((l) => l.column === c.key)}
              {@const dir = idx >= 0 ? sortLevels[idx].direction : null}
              <th class="select-none">
                <span class="inline-flex items-center gap-1">
                  <button class="hover:text-accent-500 cursor-pointer
                                 underline decoration-dotted decoration-ink-300
                                 hover:decoration-accent-500"
                          title="Doppio click per aggiungere/rimuovere dal sort"
                          on:dblclick={() => onLabelDblClick(c.key)}>
                    {c.label}
                  </button>
                  {#if dir}
                    <button class="text-[10px] text-accent-500"
                            title="Click per invertire direzione"
                            on:click|stopPropagation={() => onIndicatorClick(c.key)}>
                      {dir === 'asc' ? '▲' : '▼'}
                    </button>
                    {#if sortLevels.length > 1}
                      <span class="text-[9px] bg-accent-500 text-white rounded-full
                                   w-4 h-4 inline-flex items-center justify-center">
                        {idx + 1}
                      </span>
                    {/if}
                  {/if}
                </span>
              </th>
            {/each}
            <th class="text-right">Azioni</th>
          </tr>
        </thead>
        <tbody>
          {#each groupedBuckets as bucket (bucket.key1)}
            {@const g1Open = (groupBy1 === 'none') || !collapsedG1.has(bucket.key1)}
            {#if groupBy1 !== 'none'}
              <tr style="background-color:#e0e7ff;">
                <td colspan={selectable ? 10 : 9} class="font-semibold py-1 px-2">
                  <button class="inline-block w-4 text-ink-400 cursor-pointer"
                          on:click={() => toggleG1(bucket.key1)}
                          title="Espandi/comprimi gruppo">
                    {g1Open ? '▼' : '▶'}
                  </button>
                  <button class="cursor-pointer hover:underline"
                          on:click={() => toggleG1(bucket.key1)}>
                    {GROUP_OPTIONS.find((o) => o.value === groupBy1)?.label || ''}:
                    {bucket.key1 || '(vuoto)'}
                  </button>
                  <span class="text-ink-500 font-normal text-[10px] ml-2">
                    {bucket.rows1.length} righe
                  </span>
                  <!-- Group-level action buttons: applicano l'azione a
                       tutte le righe del gruppo (le rows1 contengono
                       sia placeholder che lezioni schedulate; ogni
                       handler decide cosa fare). -->
                  <span class="ml-3 inline-flex gap-1">
                    {#if onBulkDissociate}
                      <button class="btn-amber !text-[10px] !px-2 !py-0.5"
                              on:click|stopPropagation={async () => { await onBulkDissociate(bucket.rows1); refresh(); onChanged(); }}
                              title="Dissocia tutte le lezioni schedulate del gruppo">
                        Dissocia gruppo
                      </button>
                    {/if}
                    {#if onBulkLock}
                      <button class="btn !text-[10px] !px-2 !py-0.5"
                              on:click|stopPropagation={async () => { await onBulkLock(bucket.rows1); refresh(); onChanged(); }}
                              title="Toggle lock per tutte le cattedre del gruppo">
                        🔒 Blocca gruppo
                      </button>
                    {/if}
                    {#if onBulkPlace}
                      <button class="btn-primary !text-[10px] !px-2 !py-0.5"
                              on:click|stopPropagation={async () => { await onBulkPlace(bucket.rows1); refresh(); onChanged(); }}
                              title="Apri il modal di piazzamento per tutto il gruppo">
                        Piazza gruppo
                      </button>
                    {/if}
                    {#if onBulkDelete}
                      <button class="btn-red !text-[10px] !px-2 !py-0.5"
                              on:click|stopPropagation={async () => { await onBulkDelete(bucket.rows1); refresh(); onChanged(); }}
                              title="Elimina tutte le righe del gruppo">
                        Elimina gruppo
                      </button>
                    {/if}
                  </span>
                </td>
              </tr>
            {/if}
            {#if g1Open}
              {#each bucket.sub as sb (bucket.key1 + '|' + sb.key2)}
                {@const g2Key = bucket.key1 + '|' + sb.key2}
                {@const g2Open = (groupBy2 === 'none') || !collapsedG2.has(g2Key)}
                {#if groupBy1 !== 'none' && groupBy2 !== 'none'}
                  <tr style="background-color:#eef2ff;">
                    <td colspan={selectable ? 10 : 9} class="text-[11px] pl-6 py-1">
                      <button class="inline-block w-4 text-ink-400 cursor-pointer"
                              on:click={() => toggleG2(g2Key)}
                              title="Espandi/comprimi sotto-gruppo">
                        {g2Open ? '▼' : '▶'}
                      </button>
                      <button class="cursor-pointer hover:underline"
                              on:click={() => toggleG2(g2Key)}>
                        {GROUP_OPTIONS.find((o) => o.value === groupBy2)?.label || ''}:
                        <strong>{sb.key2 || '(vuoto)'}</strong>
                      </button>
                      <span class="text-ink-400 ml-2">{sb.rows2.length}</span>
                      <!-- Sub-group level buttons (same as level-1) -->
                      <span class="ml-3 inline-flex gap-1">
                        {#if onBulkDissociate}
                          <button class="btn-amber !text-[10px] !px-2 !py-0.5"
                                  on:click|stopPropagation={async () => { await onBulkDissociate(sb.rows2); refresh(); onChanged(); }}>
                            Dissocia
                          </button>
                        {/if}
                        {#if onBulkLock}
                          <button class="btn !text-[10px] !px-2 !py-0.5"
                                  on:click|stopPropagation={async () => { await onBulkLock(sb.rows2); refresh(); onChanged(); }}>
                            🔒 Blocca
                          </button>
                        {/if}
                        {#if onBulkPlace}
                          <button class="btn-primary !text-[10px] !px-2 !py-0.5"
                                  on:click|stopPropagation={async () => { await onBulkPlace(sb.rows2); refresh(); onChanged(); }}>
                            Piazza
                          </button>
                        {/if}
                        {#if onBulkDelete}
                          <button class="btn-red !text-[10px] !px-2 !py-0.5"
                                  on:click|stopPropagation={async () => { await onBulkDelete(sb.rows2); refresh(); onChanged(); }}>
                            Elimina
                          </button>
                        {/if}
                      </span>
                    </td>
                  </tr>
                {/if}
                {#if g2Open}
                  {#each sb.rows2 as r, i (rowId(r, i))}
                    <tr style={selectable && isSelected(r, i)
                                ? 'background-color: rgba(59,130,246,0.18);'
                                : (r.is_scheduled
                                    ? (r.is_complete ? '' : 'background-color:#fef9c3;')
                                    : 'background-color:#fef2f2;')}
                        class:border-l-4={r.is_locked || r.locked}
                        class:border-amber-500={r.is_locked || r.locked}>
                      {#if selectable}
                        <td class="w-6 text-center">
                          <input type="checkbox"
                                 checked={isSelected(r, i)}
                                 on:click|stopPropagation={() => toggleOne(r, i)}/>
                        </td>
                      {/if}
                      <td>
                        {#if r.is_locked || r.locked}
                          <span class="text-amber-600" title="Evento bloccato (non si muove durante l'ottimizzazione)">🔒</span>
                        {/if}
                        <strong>{r.teacher_display}</strong>
                        <span class="text-[10px] text-ink-400">({r.teacher_name})</span>
                      </td>
                      <td>{r.class_name}</td>
                      <td>{r.subject}</td>
                      <td>{r.day_name || (r.is_scheduled ? '' : '-')}</td>
                      <td>{r.hour != null ? r.hour + ':00' : '-'}</td>
                      <td>
                        {#if r.classroom_name}
                          {r.classroom_name}
                        {:else if r.is_scheduled}
                          <span class="pill-amber !text-[10px]">no aula</span>
                        {:else}
                          <span class="text-ink-300">-</span>
                        {/if}
                      </td>
                      <td>
                        {#if r.group_name}{r.group_name}
                        {:else}<span class="text-ink-300">-</span>{/if}
                      </td>
                      <td>
                        {#if r.is_scheduled}
                          <span class="pill-green !text-[10px]">{r.status}</span>
                        {:else}
                          <span class="pill-red !text-[10px]">non schedulato</span>
                        {/if}
                      </td>
                      <td class="text-right whitespace-nowrap">
                        <button class="btn !text-[10px] !px-2 !py-0.5"
                                on:click={() => onModify(r)}
                                title="Modifica (sposta o disassocia da slot)">
                          Modifica
                        </button>
                        {#if onDissociate}
                          <button class="btn-amber !text-[10px] !px-2 !py-0.5 ml-1"
                                  on:click={async () => { await onDissociate(r); refresh(); onChanged(); }}
                                  title="Toglie l'assegnazione temporale (cattedra resta, ore tornano da assegnare)">
                            Dissocia
                          </button>
                        {/if}
                        {#if onLockToggle}
                          <button class="btn !text-[10px] !px-2 !py-0.5 ml-1"
                                  class:!bg-amber-100={r.is_locked || r.locked}
                                  on:click={async () => { await onLockToggle(r); refresh(); onChanged(); }}
                                  title={(r.is_locked || r.locked)
                                    ? 'Sblocca questo evento (sara\' nuovamente movibile)'
                                    : 'Blocca questo evento (non si muovera\' durante Phase B / metaeuristiche)'}>
                            {(r.is_locked || r.locked) ? '🔓 Sblocca' : '🔒 Blocca'}
                          </button>
                        {/if}
                        {#if onPlace}
                          <button class="btn-primary !text-[10px] !px-2 !py-0.5 ml-1"
                                  on:click={() => onPlace(r)}
                                  title="Apri il modal di piazzamento per questo evento">
                            Piazza
                          </button>
                        {/if}
                        <button class="btn-red !text-[10px] !px-2 !py-0.5 ml-1"
                                on:click={async () => { await onDelete(r); refresh(); onChanged(); }}>
                          Elimina
                        </button>
                      </td>
                    </tr>
                  {/each}
                {/if}
              {/each}
            {/if}
          {/each}
          {#if data.items.length === 0}
            <tr><td colspan={selectable ? 10 : 9} class="text-center text-ink-400 italic py-4">
              {auxQuery
                ? 'Nessun evento corrisponde ai filtri.'
                : 'Nessun evento da mostrare con questi filtri.'}
            </td></tr>
          {/if}
        </tbody>
      </table>
    </div>
  {/if}
</div>
