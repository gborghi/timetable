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

  import { api } from '../api.js';
  import { flash } from '../stores.js';

  export let endpoint;
  export let columns = [];
  export let help = { fields: [], examples: [] };
  export let rowKey = (r) => r.id ?? r.name;
  export let onRowsChange = (_) => {};

  const MAX_SORT_LEVELS = 4;

  let q = '';
  let sortLevels = [];           // [{column, direction: 'asc'|'desc'}]
  let rows = [];
  let busy = false;
  let error = '';
  let showHelp = false;
  let lastUrl = '';

  $: sortString = sortLevels.map((l) => `${l.column},${l.direction}`).join(':');

  export async function reload() {
    busy = true;
    error = '';
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (sortString) params.set('sort', sortString);
    const url = endpoint + (params.toString() ? '?' + params.toString() : '');
    lastUrl = url;
    try {
      rows = await api.get(url);
      onRowsChange(rows);
    } catch (e) {
      error = e.message;
      flash('Query error: ' + error, 'error');
    } finally {
      busy = false;
    }
  }

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
      flash(`Massimo ${MAX_SORT_LEVELS} livelli di sort.`, 'error');
      return;
    }
    reload();
  }

  // single click on the ▲/▼ indicator: toggle direction (asc <-> desc)
  function onIndicatorClick(key) {
    const idx = indexOfColumn(key);
    if (idx < 0) return;
    sortLevels = sortLevels.map((l, i) =>
      i === idx ? { ...l, direction: l.direction === 'asc' ? 'desc' : 'asc' } : l
    );
    reload();
  }

  function resetSort() {
    if (sortLevels.length === 0) return;
    sortLevels = [];
    reload();
  }

  function resetQuery() {
    if (!q) return;
    q = '';
    reload();
  }

  function dirOf(key) {
    const l = sortLevels.find((l) => l.column === key);
    return l ? l.direction : null;
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
             on:keydown={(e) => { if (e.key === 'Enter') reload(); }}/>
    </div>
    <button class="btn" on:click={reload} disabled={busy}>{busy ? '...' : 'Cerca'}</button>
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
    <span class="text-xs text-ink-500 ml-auto">{rows.length} risultati</span>
  </div>

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
        {#each rows as row (rowKey(row))}
          <slot {row} {columns}>
            <tr>
              {#each columns as col}
                <td>{col.render ? col.render(row) : (row[col.key] ?? '')}</td>
              {/each}
            </tr>
          </slot>
        {/each}
      </tbody>
    </table>
  </div>
</div>
