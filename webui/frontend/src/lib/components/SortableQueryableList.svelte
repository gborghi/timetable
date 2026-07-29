<script>
  // Reusable list with: query bar (DSL backed by /api endpoint),
  // multi-level sort (up to 4 levels), columns config, render slot per row.
  //
  // Sort interaction:
  //   - DOUBLE CLICK on a column header -> add it as a new sort level
  //     (or remove it if it's already in the sort, with the remaining
  //     levels renumbered).
  //   - SINGLE CLICK on the small ▲/▼ indicator next to the column name
  //     -> toggle direction (asc <-> desc) of that level.
  //   - "Reset sort" button -> empties the sort, back to default ordering.
  //
  // We intentionally separate the two interactions on two different click
  // targets (label vs indicator) to avoid the classic single-vs-double
  // click discrimination headache.
  //
  // Props:
  //   endpoint: string                 — REST URL to fetch from
  //   columns:  Array<{
  //               key: string,         — sort key on backend
  //               label: string,
  //               sortable?: boolean,  — default true
  //             }>
  //   help: { fields: string[], examples: string[] }
  //   rowKey: fn(row) -> stable key for #each
  //
  // Slots: default takes (row, columns) and renders a <tr>.

  import { onMount, onDestroy } from 'svelte';

  import { confirmDialog, promptDialog } from '$lib/confirm';
  import { api } from '../api';
  import { flash } from '../stores';
  import { savedViews as savedViewsSvc } from '../services';
  import DecorIcon from './DecorIcon.svelte';

  // Tracks whether this component is still mounted. We use it to
  // ignore async responses that resolve AFTER the component has
  // been destroyed (e.g. when the user rapidly switches tabs):
  // setting state on an unmounted component is wasted work and
  // can hide bugs behind silent state-mutation warnings.
  let _alive = true;

  export let endpoint;
  export let columns = [];
  export let help = { fields: [], examples: [] };
  export let rowKey = (r) => r.id ?? r.name;
  export let onRowsChange = (_) => {};
  // Multi-select support (shift/ctrl click). When true, a leading
  // checkbox column appears and the parent can read `selectedIds` via
  // bind:selectedIds. Selection is preserved across sorts but reset on
  // explicit reload from the parent only if reload-clear is true.
  export let selectable = false;
  export let selectedIds = [];
  // Optional: machine name of the entity, e.g. 'teachers'. When set,
  // the toolbar shows a "Viste salvate" dropdown linked to the
  // /api/saved-views endpoint scoped to this entity.
  export let entity = '';

  let lastClickedIdx = -1;

  const MAX_SORT_LEVELS = 4;

  let q = '';
  let sortLevels = [];           // [{column, direction: 'asc'|'desc'}]
  let rows = [];
  let busy = false;
  let firstLoad = true;     // true until the first reload() resolves
  let error = '';
  let showHelp = false;
  let lastUrl = '';

  // Pagination -- enabled when the user picks a page size other than
  // 'all'. The endpoints accept `?limit=N&offset=M` and return the
  // envelope `{items, total, limit, offset}`. When pageSize is 'all'
  // we send neither and get a flat list.
  const PAGE_SIZE_OPTIONS = [25, 50, 100, 250, 'all'];
  export let pageSize = 50;       // 'all' or number
  let offset = 0;
  let total = null;               // null when not paginating

  $: sortString = sortLevels.map((l) => `${l.column},${l.direction}`).join(':');

  export async function reload() {
    busy = true;
    error = '';
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (sortString) params.set('sort', sortString);
    if (pageSize !== 'all') {
      params.set('limit', String(pageSize));
      params.set('offset', String(offset));
    }
    const url = endpoint + (params.toString() ? '?' + params.toString() : '');
    lastUrl = url;
    try {
      const result = await api.get(url);
      if (!_alive) return;          // user navigated away mid-fetch
      // Detect paginated envelope vs flat list. Paginated:
      //   {items: [...], total: N, limit: L, offset: O}
      if (result && typeof result === 'object'
          && Array.isArray(result.items)
          && typeof result.total === 'number') {
        rows = result.items;
        total = result.total;
      } else {
        rows = result;
        total = null;
      }
      onRowsChange(rows);
    } catch (e) {
      if (!_alive) return;
      error = e.message;
      flash('Query error: ' + error, 'error');
    } finally {
      if (_alive) {
        busy = false;
        firstLoad = false;
      }
    }
  }

  // ----- Pagination helpers -----
  function gotoPage(newOffset) {
    if (newOffset < 0) newOffset = 0;
    offset = newOffset;
    reload();
  }
  function changePageSize(newSize) {
    pageSize = newSize;
    offset = 0;       // reset to first page when size changes
    reload();
  }
  $: pageSizeNum = pageSize === 'all'
                    ? (total || rows.length || 1)
                    : Number(pageSize);
  $: numPages = total != null
                 ? Math.max(1, Math.ceil(total / pageSizeNum))
                 : 1;
  $: currentPage = Math.floor(offset / Math.max(1, pageSizeNum)) + 1;

  function indexOfColumn(key) {
    return sortLevels.findIndex((l) => l.column === key);
  }

  // double click on the column label: add or remove the column from sort
  function onLabelDblClick(key) {
    const idx = indexOfColumn(key);
    if (idx >= 0) {
      // remove this level; remaining levels renumber automatically
      sortLevels = sortLevels.filter((_, i) => i !== idx);
    } else if (sortLevels.length < MAX_SORT_LEVELS) {
      sortLevels = [...sortLevels, { column: key, direction: 'asc' }];
    } else {
      flash(`Massimo ${MAX_SORT_LEVELS} levels di sort.`, 'error');
      return;
    }
    offset = 0;       // sort change -> back to page 1
    reload();
  }

  // single click on the ▲/▼ indicator: toggle direction (asc <-> desc)
  function onIndicatorClick(key) {
    const idx = indexOfColumn(key);
    if (idx < 0) return;
    sortLevels = sortLevels.map((l, i) =>
      i === idx ? { ...l, direction: l.direction === 'asc' ? 'desc' : 'asc' } : l
    );
    offset = 0;
    reload();
  }

  function resetSort() {
    if (sortLevels.length === 0) return;
    sortLevels = [];
    offset = 0;
    reload();
  }

  function resetQuery() {
    if (!q) return;
    q = '';
    offset = 0;
    reload();
  }

  function applyQuery() {
    offset = 0;
    reload();
  }

  function dirOf(key) {
    const l = sortLevels.find((l) => l.column === key);
    return l ? l.direction : null;
  }

  // ---------- selection ----------
  function isSelected(row) {
    return selectedIds.includes(rowKey(row));
  }

  function toggleOne(row) {
    const k = rowKey(row);
    if (selectedIds.includes(k)) {
      selectedIds = selectedIds.filter((x) => x !== k);
    } else {
      selectedIds = [...selectedIds, k];
    }
  }

  function selectRange(fromIdx, toIdx) {
    const lo = Math.min(fromIdx, toIdx);
    const hi = Math.max(fromIdx, toIdx);
    const ks = rows.slice(lo, hi + 1).map(rowKey);
    const set = new Set(selectedIds);
    ks.forEach((k) => set.add(k));
    selectedIds = [...set];
  }

  function onRowClick(ev, row, idx) {
    if (!selectable) return;
    // Don't hijack clicks on actual interactive controls inside the row
    const t = ev.target;
    if (t && (t.tagName === 'BUTTON' || t.tagName === 'INPUT'
              || t.tagName === 'A' || t.closest('button')
              || t.closest('a') || t.closest('input'))) return;
    if (ev.shiftKey && lastClickedIdx >= 0) {
      selectRange(lastClickedIdx, idx);
    } else if (ev.ctrlKey || ev.metaKey) {
      toggleOne(row);
      lastClickedIdx = idx;
    } else {
      // plain click: single-select (replace)
      const k = rowKey(row);
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
    selectedIds = rows.map(rowKey);
  }

  function clearSelection() {
    selectedIds = [];
    lastClickedIdx = -1;
  }

  // ----- Saved views ----------------------------------------------------

  let savedViewsList = [];
  let selectedViewId = '';

  async function reloadSavedViews() {
    if (!entity) return;
    try {
      const result = await savedViewsSvc.list(entity);
      if (!_alive) return;
      savedViewsList = result;
    } catch { /* */ }
  }

  async function applyView(id) {
    selectedViewId = id;
    if (!id) return;
    const v = savedViewsList.find((x) => String(x.id) === String(id));
    if (!v) return;
    q = v.dsl_query || '';
    sortLevels = (v.sort_levels || []).map((l) => ({
      column: l.column,
      direction: l.direction === 'desc' ? 'desc' : 'asc',
    }));
    await reload();
  }

  async function saveCurrentView() {
    if (!entity) return;
    const name = (await promptDialog('Nome della vista:') || '').trim();
    if (!name) return;
    try {
      await savedViewsSvc.create({
        entity,
        name,
        dsl_query: q || null,
        sort_levels: sortLevels.map((l) => ({
          column: l.column, direction: l.direction,
        })),
      });
      flash('Vista salvata', 'success');
      await reloadSavedViews();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function deleteSelectedView() {
    if (!selectedViewId) return;
    const v = savedViewsList.find(
      (x) => String(x.id) === String(selectedViewId),
    );
    if (!v) return;
    if (!(await confirmDialog('Eliminare la vista "' + v.name + '"?'))) return;
    try {
      await savedViewsSvc.remove(v.id);
      selectedViewId = '';
      await reloadSavedViews();
      flash('Vista eliminata', 'success');
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  onMount(() => { reloadSavedViews(); });
  onDestroy(() => { _alive = false; });

  // ----- Export ---------------------------------------------------------

  /** Build a URL that mirrors the current view (q + sort) plus a
   *  format param. When `all` is true, the q+sort filters are
   *  dropped so the user gets the full unfiltered table. */
  function exportUrl(format, all = false) {
    const params = new URLSearchParams();
    if (!all) {
      if (q) params.set('q', q);
      if (sortString) params.set('sort', sortString);
    }
    params.set('format', format);
    return endpoint + '?' + params.toString();
  }

  let exporting = false;

  async function downloadExport(format, all = false) {
    exporting = true;
    try {
      const url = exportUrl(format, all);
      // Trigger download via a hidden anchor — browser handles the file
      // save natively, no FileSaver dep needed.
      const a = document.createElement('a');
      a.href = url;
      a.rel = 'noopener';
      // Let the server's Content-Disposition pick the filename.
      a.click();
    } finally {
      // small delay so the user sees the spinner if the file is huge
      setTimeout(() => { exporting = false; }, 300);
    }
  }

  reload();
</script>

<div class="space-y-3">
  <div class="card p-3 flex flex-wrap gap-2 items-end">
    <div class="flex-1 min-w-64">
      <label class="text-xs text-ink-500">Query</label>
      <input class="w-full px-2 py-1.5 rounded-md border border-ink-200 font-mono text-sm"
             placeholder="es. group=A026 AND max_hours>=18"
             bind:value={q}
             on:keydown={(e) => { if (e.key === 'Enter') applyQuery(); }}/>
    </div>
    <button class="btn" on:click={applyQuery} disabled={busy}>{busy ? '...' : 'Cerca'}</button>
    <button class="btn !text-xs" on:click={() => (showHelp = !showHelp)}>?  guida</button>
    <span class="border-l border-ink-200 h-6 mx-1"></span>
    <button class="btn !text-xs" on:click={resetQuery}
            disabled={!q}
            title="Svuota la barra di ricerca, mostra tutti i risultati">
      Reset query
    </button>
    <button class="btn !text-xs" on:click={resetSort}
            disabled={sortLevels.length === 0}
            title="Torna all'ordine originale">
      Reset sort
    </button>
    {#if entity}
      <span class="border-l border-ink-200 h-6 mx-1"></span>
      <select class="btn !text-xs !pr-2"
              title="Carica una vista salvata (query + sort)"
              bind:value={selectedViewId}
              on:change={(e) => applyView(e.currentTarget.value)}>
        <option value="">Viste salvate...</option>
        {#each savedViewsList as v (v.id)}
          <option value={v.id}>{v.name}</option>
        {/each}
      </select>
      <button class="btn !text-xs" on:click={saveCurrentView}
              title="Salva la query+sort corrente come vista nominata">
        Salva vista
      </button>
      <button class="btn-danger !text-xs"
              on:click={deleteSelectedView}
              disabled={!selectedViewId}
              title="Elimina la vista selezionata">
        x
      </button>
    {/if}
    <span class="border-l border-ink-200 h-6 mx-1"></span>
    <button class="btn !text-xs" on:click={() => downloadExport('xlsx', false)}
            disabled={exporting || rows.length === 0}
            title="Esporta la vista corrente (query + sort) come xlsx">
      {exporting ? '...' : 'xlsx'}
    </button>
    <button class="btn !text-xs" on:click={() => downloadExport('csv', false)}
            disabled={exporting || rows.length === 0}
            title="Esporta la vista corrente (query + sort) come csv">
      csv
    </button>
    <button class="btn !text-xs" on:click={() => downloadExport('xlsx', true)}
            disabled={exporting}
            title="Esporta TUTTE le righe (ignora query e sort)">
      tutto
    </button>
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
      {#if selectedIds.length > 0}
        <span class="pill pill-blue">{selectedIds.length} selezionati</span>
      {/if}
    {/if}
    <span class="text-xs text-ink-500 ml-auto">
      {#if busy}
        <span class="inline-flex items-center gap-1">
          <span class="inline-block w-2 h-2 bg-accent-500 rounded-full animate-pulse"
                aria-hidden="true"></span>
          <span class="sr-only">Caricamento...</span>
          aggiorno...
        </span>
      {:else if total != null}
        {total} risultati
        {#if pageSize !== 'all'}
          - mostrati {Math.min(rows.length, pageSizeNum)}
          (pag {currentPage}/{numPages})
        {/if}
      {:else}
        {rows.length} risultati
      {/if}
    </span>
  </div>

  <!-- Pagination strip: shown only when paginating (pageSize !=
       'all' and the endpoint returned the total). The user can
       switch page size without losing query/sort. -->
  {#if total != null && pageSize !== 'all'}
    <div class="card p-2 text-xs flex flex-wrap items-center gap-2">
      <span class="text-ink-500">Pagina</span>
      <button class="btn !text-xs !px-2 !py-0.5"
              on:click={() => gotoPage(0)}
              disabled={offset === 0 || busy}>{'|<'}</button>
      <button class="btn !text-xs !px-2 !py-0.5"
              on:click={() => gotoPage(offset - pageSizeNum)}
              disabled={offset === 0 || busy}>{'<'} prec</button>
      <span class="px-2">{currentPage} / {numPages}</span>
      <button class="btn !text-xs !px-2 !py-0.5"
              on:click={() => gotoPage(offset + pageSizeNum)}
              disabled={currentPage >= numPages || busy}>succ {'>'}</button>
      <button class="btn !text-xs !px-2 !py-0.5"
              on:click={() => gotoPage((numPages - 1) * pageSizeNum)}
              disabled={currentPage >= numPages || busy}>{'>|'}</button>
      <span class="ml-auto flex items-center gap-1">
        <span class="text-ink-500">Per pagina:</span>
        <select class="px-1 py-0.5 border border-ink-200 rounded"
                value={pageSize}
                on:change={(e) => changePageSize(
                  e.currentTarget.value === 'all' ? 'all'
                    : Number(e.currentTarget.value),
                )}>
          {#each PAGE_SIZE_OPTIONS as opt}
            <option value={opt}>{opt}</option>
          {/each}
        </select>
      </span>
    </div>
  {:else if total == null && pageSize !== 'all' && rows.length > 0}
    <!-- Endpoint doesn't paginate; expose a switcher so the user
         can opt into "all" or smaller views via DSL filtering -->
    <div class="card p-2 text-xs flex items-center gap-2">
      <span class="text-ink-500">
        Endpoint senza paginazione (tutto in una pagina).
      </span>
      <span class="ml-auto flex items-center gap-1">
        <span class="text-ink-500">Per pagina:</span>
        <select class="px-1 py-0.5 border border-ink-200 rounded"
                value={pageSize}
                on:change={(e) => changePageSize(
                  e.currentTarget.value === 'all' ? 'all'
                    : Number(e.currentTarget.value),
                )}>
          {#each PAGE_SIZE_OPTIONS as opt}
            <option value={opt}>{opt}</option>
          {/each}
        </select>
      </span>
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
        doppio click sul nome di una colonna per aggiungere/rimuovere; click su ▲/▼ per invertire
      </span>
    </div>
  {/if}

  {#if showHelp}
    <div class="card p-3 text-xs space-y-2 bg-ink-50">
      <div>
        <strong>Operatori:</strong>
        <code>= != &lt; &lt;= &gt; &gt;= contains startswith endswith in [...]</code>
      </div>
      <div>
        <strong>Logica:</strong> <code>AND</code> / <code>OR</code> /
        parentesi <code>(...)</code>.
      </div>
      <div>
        <strong>Campi disponibili:</strong>
        <code>{help.fields.join(', ')}</code>
      </div>
      {#if help.examples.length}
        <div>
          <strong>Esempi:</strong>
          <ul class="list-disc list-inside">
            {#each help.examples as ex}<li><code>{ex}</code></li>{/each}
          </ul>
        </div>
      {/if}
      <div class="text-ink-500">
        <strong>Sort multi-livello:</strong>
        doppio click sul nome di una colonna per aggiungerla / rimuoverla
        dal sort (max {MAX_SORT_LEVELS} livelli);
        click sulla freccia ▲/▼ per invertire direzione.
        "Reset sort" toglie tutti i livelli.
      </div>
    </div>
  {/if}

  <div class="card overflow-x-auto">
    <table class="tbl">
      <thead>
        <tr>
          {#if selectable}
            <th class="w-6 text-center"
                title="Tieni Ctrl o Shift per selezione multipla. Click semplice = singola.">
              <input type="checkbox"
                     checked={selectedIds.length > 0 && selectedIds.length === rows.length}
                     indeterminate={selectedIds.length > 0 && selectedIds.length < rows.length}
                     on:change={(e) => e.target.checked ? selectAllVisible() : clearSelection()}/>
            </th>
          {/if}
          {#each columns as col}
            {@const dir = sortLevels.find((l) => l.column === col.key)?.direction ?? null}
            {@const idx = sortLevels.findIndex((l) => l.column === col.key)}
            <th>
              {#if col.sortable !== false && col.key}
                <span class="inline-flex items-center gap-1">
                  <button class="hover:text-accent-500 select-none"
                          title="Doppio click per aggiungere/rimuovere dal sort"
                          on:dblclick={() => onLabelDblClick(col.key)}>
                    {col.label}
                  </button>
                  {#if dir}
                    <button class="text-[10px] text-accent-500 select-none"
                            title="Click per invertire direzione (asc/desc)"
                            on:click|stopPropagation={() => onIndicatorClick(col.key)}>
                      {dir === 'asc' ? '▲' : '▼'}
                    </button>
                    {#if sortLevels.length > 1}
                      <span class="text-[9px] bg-accent-500 text-white rounded-full
                                   w-4 h-4 inline-flex items-center justify-center"
                            title="Livello di sort">
                        {idx + 1}
                      </span>
                    {/if}
                  {/if}
                </span>
              {:else}
                {col.label}
              {/if}
            </th>
          {/each}
          <slot name="extra-thead"/>
        </tr>
      </thead>
      <tbody>
        {#if firstLoad && busy}
          {@const colSpan = columns.length + (selectable ? 2 : 1)}
          {#each Array(6) as _, i}
            <tr aria-hidden="true">
              <td colspan={colSpan} class="px-2 py-3">
                <div class="h-4 bg-ink-100 rounded animate-pulse"
                     style="width: {Math.max(40, 100 - (i * 7))}%"></div>
              </td>
            </tr>
          {/each}
        {:else if !firstLoad && rows.length === 0 && !error}
          {@const colSpan = columns.length + (selectable ? 2 : 1)}
          <tr>
            <td colspan={colSpan} class="py-8">
              <div class="flex flex-col items-center gap-2 text-ink-400">
                <DecorIcon name={q ? 'magnifier' : 'lightbulb'} size={52}
                           class="opacity-70" />
                <p class="italic text-center">
                  {q ? 'Nessun risultato per questa ricerca.'
                     : 'Lista vuota. Crea o importa elementi per cominciare.'}
                </p>
              </div>
            </td>
          </tr>
        {/if}
        {#each rows as row, idx (rowKey(row))}
          {#if selectable}
            <tr class:bg-accent-500={false}
                class:!bg-accent-500={false}
                style={isSelected(row) ? 'background-color: rgba(59,130,246,0.10);' : ''}
                data-testid="entity-row"
                data-entity={entity}
                data-row-id={rowKey(row)}
                on:click={(e) => onRowClick(e, row, idx)}>
              <td class="w-6 text-center">
                <input type="checkbox" checked={isSelected(row)}
                       on:click|stopPropagation={() => { toggleOne(row); lastClickedIdx = idx; }}/>
              </td>
              <slot {row} {columns} {idx}>
                {#each columns as col}
                  <td>{col.render ? col.render(row) : (row[col.key] ?? '')}</td>
                {/each}
              </slot>
            </tr>
          {:else}
            <slot {row} {columns} {idx}>
              <tr data-testid="entity-row"
                  data-entity={entity}
                  data-row-id={rowKey(row)}>
                {#each columns as col}
                  <td>{col.render ? col.render(row) : (row[col.key] ?? '')}</td>
                {/each}
              </tr>
            </slot>
          {/if}
        {/each}
      </tbody>
    </table>
  </div>
</div>
