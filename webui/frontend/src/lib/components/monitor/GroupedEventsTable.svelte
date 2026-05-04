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
  // Pagination state. limit=null means "all rows" (legacy default).
  // For big schools we recommend 100 rows/page so the DOM stays small.
  let pageSize = 100;
  let pageIndex = 0;

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
    pageIndex = 0;
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
    if (pageSize && pageSize > 0) {
      params.set('limit', String(pageSize));
      params.set('offset', String(pageIndex * pageSize));
    }
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

  // Total pages (clamped to 1 even if no rows).
  $: nPages = (data && pageSize)
    ? Math.max(1, Math.ceil((data.n_filtered ?? data.n_total ?? 0) / pageSize))
    : 1;
  function gotoPage(i) {
    pageIndex = Math.max(0, Math.min(nPages - 1, i));
    refresh();
  }
  function changePageSize(n) {
    pageSize = Number(n) || 100;
    pageIndex = 0;
    refresh();
  }
  // Re-fetch when filter/sort/groupBy changes -> reset page.
  function _onFilterReset() { pageIndex = 0; refresh(); }

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

  // visualRows: flat array of rows in DISPLAYED order (after grouping
  // and sub-grouping, in the same order the user sees them on screen).
  // Each row is tagged with two indices:
  //   _vIdx  : 0-based position in the visual order, used for shift+click
  //   _inSub : 0-based position within its subgroup, used to disambiguate
  //            placeholder rows (multiple "missing hours" for the same
  //            assignment) inside one bucket
  // Mutating the row objects in place is fine: groupRows returns the
  // same row references that came from data.items, and the visualRows
  // reactive runs whenever groupedBuckets changes, so the tags stay
  // consistent with what's rendered.
  $: visualRows = (() => {
    const arr = [];
    let v = 0;
    for (const b of groupedBuckets) {
      for (const sb of b.sub) {
        let inSub = 0;
        for (const r of sb.rows2) {
          r._vIdx = v;
          r._inSub = inSub;
          arr.push(r);
          v++;
          inSub++;
        }
      }
    }
    return arr;
  })();

  function rowId(r) {
    // Lessons have a stable lesson_id; placeholders need a tiebreaker
    // because one assignment can have N missing-hour placeholder rows.
    // _inSub is set during the visualRows pass; we fall back to 0 if
    // somehow called before that runs.
    return r.lesson_id != null
      ? `lesson:${r.lesson_id}`
      : `placeholder:${r.assignment_id}:${r._inSub ?? 0}`;
  }

  // ----- Selection helpers (mirrors SortableQueryableList) ------------
  // lastClickedIdx is a _vIdx (visual flat index), so shift+click
  // ranges follow what the user sees, not server order.
  let lastClickedIdx = -1;
  function isSelected(r) {
    return selectedIds.includes(rowId(r));
  }
  function toggleOne(r) {
    const k = rowId(r);
    if (selectedIds.includes(k)) {
      selectedIds = selectedIds.filter((x) => x !== k);
    } else {
      selectedIds = [...selectedIds, k];
    }
    lastClickedIdx = r._vIdx ?? lastClickedIdx;
  }
  function selectRange(fromVIdx, toVIdx) {
    if (visualRows.length === 0) return;
    const lo = Math.max(0, Math.min(fromVIdx, toVIdx));
    const hi = Math.min(visualRows.length - 1, Math.max(fromVIdx, toVIdx));
    const ks = [];
    for (let i = lo; i <= hi; i++) ks.push(rowId(visualRows[i]));
    const set = new Set(selectedIds);
    ks.forEach((k) => set.add(k));
    selectedIds = [...set];
  }
  // Row click handler — same semantics as SortableQueryableList:
  //   plain click       => single-select (replace)
  //   shift+click       => extend range from last anchor (visual order)
  //   ctrl/cmd+click    => toggle one
  // Clicks on the checkbox itself are handled separately (with
  // stopPropagation on the input), so this only fires for clicks on
  // the rest of the row.
  function onRowClick(ev, r) {
    if (!selectable) return;
    // Don't hijack clicks on actual interactive controls inside the row
    // (action buttons, eventual links).
    const t = ev.target;
    if (t && (t.tagName === 'BUTTON' || t.tagName === 'INPUT'
              || t.tagName === 'A' || t.closest('button')
              || t.closest('a') || t.closest('input'))) return;
    const idx = r._vIdx ?? -1;
    if (ev.shiftKey && lastClickedIdx >= 0 && idx >= 0) {
      selectRange(lastClickedIdx, idx);
    } else if (ev.ctrlKey || ev.metaKey) {
      toggleOne(r);
    } else {
      const k = rowId(r);
      if (selectedIds.length === 1 && selectedIds[0] === k) {
        selectedIds = [];
      } else {
        selectedIds = [k];
      }
      lastClickedIdx = idx;
    }
    ev.preventDefault();
  }
  function selectAllVisible() {
    // Walk visualRows so that even placeholders get the right rowId
    // (they need _inSub tagged, which only the visual pass guarantees).
    selectedIds = visualRows.map(rowId);
  }
  function clearSelection() {
    selectedIds = [];
    lastClickedIdx = -1;
  }
  function _selectedRows() {
    const idSet = new Set(selectedIds);
    return visualRows.filter((r) => idSet.has(rowId(r)));
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
    <span class="text-xs text-ink-500 ml-2">Righe/pagina:</span>
    <select class="text-xs px-2 py-1 border border-ink-200 rounded"
            value={pageSize}
            on:change={(e) => changePageSize(e.target.value)}>
      <option value={50}>50</option>
      <option value={100}>100</option>
      <option value={200}>200</option>
      <option value={500}>500</option>
      <option value={0}>tutte</option>
    </select>
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
                  title={'Click sulla riga: seleziona singola.\n'
                       + 'Shift+click sulla riga: estendi selezione fino a qui.\n'
                       + 'Ctrl/Cmd+click sulla riga: aggiungi/togli senza azzerare.\n'
                       + 'Click sulla checkbox: toggle solo della riga.'}>
                <input type="checkbox"
                       checked={selectedIds.length > 0
                                && selectedIds.length === (visualRows.length)}
                       indeterminate={selectedIds.length > 0
                                && selectedIds.length < (visualRows.length)}
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
                  {#each sb.rows2 as r (rowId(r))}
                    <tr style={selectable && isSelected(r)
                                ? 'background-color: rgba(59,130,246,0.18);'
                                : (r.is_scheduled
                                    ? (r.is_complete ? '' : 'background-color:#fef9c3;')
                                    : 'background-color:#fef2f2;')}
                        class:border-l-4={r.is_locked || r.locked}
                        class:border-amber-500={r.is_locked || r.locked}
                        class:cursor-pointer={selectable}
                        on:click={(e) => onRowClick(e, r)}>
                      {#if selectable}
                        <td class="w-6 text-center">
                          <input type="checkbox"
                                 checked={isSelected(r)}
                                 on:click|stopPropagation={() => toggleOne(r)}/>
                        </td>
                      {/if}
                      <td class="text-[11px]"
                          title={r.teacher_name !== r.teacher_display
                                  ? r.teacher_name : ''}>
                        {#if r.is_locked || r.locked}
                          <span class="text-amber-600" title="Evento bloccato">🔒</span>
                        {/if}
                        {r.teacher_display || r.teacher_name}
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
                        <!-- Compact icon-only action buttons with tooltips,
                             so the cell fits even in a narrow viewport. -->
                        <button class="btn !text-[11px] !px-1.5 !py-0.5"
                                on:click={() => onModify(r)}
                                title="Modifica (sposta o disassocia da slot)">
                          ✎
                        </button>
                        {#if onDissociate}
                          <button class="btn-amber !text-[11px] !px-1.5 !py-0.5 ml-0.5"
                                  on:click={async () => { await onDissociate(r); refresh(); onChanged(); }}
                                  title="Dissocia: rimuove SOLO questa lezione (cattedra resta)">
                            ⏏
                          </button>
                        {/if}
                        {#if onLockToggle}
                          <button class="btn !text-[11px] !px-1.5 !py-0.5 ml-0.5"
                                  class:!bg-amber-100={r.is_locked || r.locked}
                                  on:click={async () => { await onLockToggle(r); refresh(); onChanged(); }}
                                  title={(r.is_locked || r.locked)
                                    ? 'Sblocca' : 'Blocca'}>
                            {(r.is_locked || r.locked) ? '🔓' : '🔒'}
                          </button>
                        {/if}
                        {#if onPlace}
                          <button class="btn-primary !text-[11px] !px-1.5 !py-0.5 ml-0.5"
                                  on:click={() => onPlace(r)}
                                  title="Piazza: apri modal di piazzamento">
                            ▶
                          </button>
                        {/if}
                        <button class="btn-red !text-[11px] !px-1.5 !py-0.5 ml-0.5"
                                on:click={async () => { await onDelete(r); refresh(); onChanged(); }}
                                title="Elimina">
                          ✕
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

      <!-- Pagination controls. Hidden when pageSize covers everything. -->
      {#if pageSize && data && (data.n_filtered ?? data.n_total) > pageSize}
        <div class="flex items-center gap-2 px-3 py-2 text-xs">
          <span class="text-ink-500">
            Pagina {pageIndex + 1} / {nPages}
            ({(data.n_filtered ?? data.n_total)} righe filtrate)
          </span>
          <div class="ml-auto flex items-center gap-1">
            <button class="btn !text-[11px] !px-2 !py-0.5"
                    disabled={pageIndex === 0}
                    on:click={() => gotoPage(0)}>«</button>
            <button class="btn !text-[11px] !px-2 !py-0.5"
                    disabled={pageIndex === 0}
                    on:click={() => gotoPage(pageIndex - 1)}>‹ Prec</button>
            <input type="number" class="w-14 text-xs px-1 py-0.5 border border-ink-200 rounded"
                   min="1" max={nPages}
                   value={pageIndex + 1}
                   on:change={(e) => gotoPage(Number(e.target.value) - 1)}/>
            <button class="btn !text-[11px] !px-2 !py-0.5"
                    disabled={pageIndex >= nPages - 1}
                    on:click={() => gotoPage(pageIndex + 1)}>Succ ›</button>
            <button class="btn !text-[11px] !px-2 !py-0.5"
                    disabled={pageIndex >= nPages - 1}
                    on:click={() => gotoPage(nPages - 1)}>»</button>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>
