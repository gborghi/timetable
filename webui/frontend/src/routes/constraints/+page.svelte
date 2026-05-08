<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import { levelPill, levelLabel } from '$lib/constraint_levels';
  import NewConstraintModal from '$lib/components/constraints/NewConstraintModal.svelte';
  import NewGeneralConstraintModal from '$lib/components/constraints/NewGeneralConstraintModal.svelte';
  import FeasibilityPanel from '$lib/components/constraints/FeasibilityPanel.svelte';

  let listRef = null;
  let conflicts = null;
  let showConflicts = false;
  let conflictsBusy = false;

  // "Nuovo vincolo" wizard
  let newConstraintOpen = false;
  // "Nuovo vincolo DSL" — general DSL editor
  let newDSLConstraintOpen = false;
  // Feasibility Check panel
  let feasibilityOpen = false;
  // List of DSL constraints (loaded on mount + after each create)
  let dslConstraints = [];
  let dslLoading = false;

  // Constraint search ("Ricerca avanzata") state
  let searchEntityType = '';     // teacher|class|classroom|subject|curriculum|group
  let searchEntityId = null;
  let searchText = '';
  let searchLevels = [];         // multi-select: hard|soft|preferred|enforced
  let searchResults = null;      // null = panel closed; [] = "no match"
  let searchBusy = false;

  // Lookup data for the owner dropdowns in the edit modal.
  let allTeachers = [];     // [{id, name, display}]
  let allClasses = [];      // [{id, name}]
  let allRooms = [];        // [{id, name}]
  let allCurricula = [];    // [{id, code, name}]
  let allSubjects = [];     // [{name}]

  onMount(async () => {
    try {
      const t = await api.get('/api/teachers');
      allTeachers = (t || []).map((x) => ({
        id: x.id, name: x.name,
        display: x.nickname
                 || (x.last_name && x.first_name
                       ? `${x.last_name} ${x.first_name}`
                       : x.name),
      })).sort((a, b) => a.display.localeCompare(b.display, 'it'));
    } catch { allTeachers = []; }
    try {
      const c = await api.get('/api/classes');
      allClasses = (c || []).map((x) => ({ id: x.id, name: x.name }))
        .sort((a, b) => a.name.localeCompare(b.name, 'it'));
    } catch { allClasses = []; }
    try {
      const r = await api.get('/api/classrooms');
      allRooms = (r || []).map((x) => ({ id: x.id, name: x.name }))
        .sort((a, b) => a.name.localeCompare(b.name, 'it'));
    } catch { allRooms = []; }
    try {
      const cu = await api.get('/api/curricula');
      allCurricula = (cu || []).map((x) => ({
        id: x.id, code: x.code, name: x.name,
      })).sort((a, b) => a.code.localeCompare(b.code, 'it'));
    } catch { allCurricula = []; }
    try {
      const s = await api.get('/api/subjects');
      allSubjects = (s || []).map((x) => ({ name: x.name }))
        .sort((a, b) => a.name.localeCompare(b.name, 'it'));
    } catch { allSubjects = []; }
    await reloadDSL();
  });

  async function reloadDSL() {
    dslLoading = true;
    try {
      dslConstraints = await api.get('/api/constraints/general');
    } catch { dslConstraints = []; }
    dslLoading = false;
  }
  async function deleteDSL(id) {
    if (!confirm(`Eliminare il vincolo DSL #${id}?`)) return;
    try {
      await api.del('/api/constraints/general/' + id);
      flash('Vincolo eliminato.', 'success');
      await reloadDSL();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function runSearch() {
    searchBusy = true;
    try {
      const params = new URLSearchParams();
      if (searchEntityType && searchEntityId != null) {
        params.set('entity_type', searchEntityType);
        params.set('entity_id', String(searchEntityId));
      }
      if (searchText) params.set('text', searchText);
      if (searchLevels.length) params.set('levels', searchLevels.join(','));
      const url = '/api/constraints/search'
        + (params.toString() ? '?' + params.toString() : '');
      searchResults = await api.get(url);
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
      searchResults = [];
    } finally {
      searchBusy = false;
    }
  }
  function resetSearch() {
    searchEntityType = '';
    searchEntityId = null;
    searchText = '';
    searchLevels = [];
    searchResults = null;
  }
  // Master list for the entity dropdown -- depends on the chosen type.
  $: searchEntityOptions = (() => {
    if (searchEntityType === 'teacher')   return allTeachers.map((t) => ({ id: t.id, label: t.display }));
    if (searchEntityType === 'class')     return allClasses.map((c) => ({ id: c.id, label: c.name }));
    if (searchEntityType === 'classroom') return allRooms.map((r) => ({ id: r.id, label: r.name }));
    if (searchEntityType === 'subject')   return allSubjects.map((s, i) => ({ id: s.name, label: s.name }));
    if (searchEntityType === 'curriculum')return allCurricula.map((c) => ({ id: c.id, label: c.name }));
    return [];
  })();

  // Maps a constraint `kind` to (label, list) pairs telling the modal
  // which owner dropdowns to render. Keys missing here = no owner edit.
  $: ownerSpec = (kind) => {
    if (kind === 'teacher_cell' || kind === 'logical_teacher') {
      return [{ key: 'owner_id', label: 'Docente',
                options: allTeachers.map((t) => ({ value: t.id, text: t.display })) }];
    }
    if (kind === 'class_cell' || kind === 'logical_class'
        || kind === 'coteach') {
      return [{ key: 'owner_id', label: 'Classe',
                options: allClasses.map((c) => ({ value: c.id, text: c.name })) }];
    }
    if (kind === 'room_cell' || kind === 'logical_classroom') {
      return [{ key: 'owner_id', label: 'Aula',
                options: allRooms.map((r) => ({ value: r.id, text: r.name })) }];
    }
    if (kind === 'logical_curriculum') {
      return [{ key: 'owner_id', label: 'Indirizzo',
                options: allCurricula.map((c) => ({
                  value: c.id, text: `${c.code} - ${c.name}` })) }];
    }
    if (kind === 'subject_room_pref') {
      return [
        { key: 'owner_id', label: 'Aula',
          options: allRooms.map((r) => ({ value: r.id, text: r.name })) },
        { key: 'subject', label: 'Materia',
          options: allSubjects.map((s) => ({ value: s.name, text: s.name })) },
      ];
    }
    if (kind === 'teacher_room_pref') {
      return [
        { key: 'owner_id', label: 'Docente',
          options: allTeachers.map((t) => ({ value: t.id, text: t.display })) },
        { key: 'secondary_owner_id', label: 'Aula',
          options: allRooms.map((r) => ({ value: r.id, text: r.name })) },
      ];
    }
    return [];
  };

  let editing = null;   // {kind, id, owner_id, level, weight, expression, ...}

  async function loadConflicts() {
    conflictsBusy = true;
    try {
      conflicts = await api.get('/api/monitor/conflicts');
      showConflicts = true;
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { conflictsBusy = false; }
  }

  async function del(row) {
    if (!confirm('Eliminare il vincolo "' + row.detail + '" su ' + row.owner_name + '?')) return;
    try {
      await api.del(`/api/monitor/constraints/${row.kind}/${row.id}`);
      await listRef.reload();
      if (showConflicts) await loadConflicts();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  function startEdit(row) {
    editing = {
      kind: row.kind,
      id: row.id,
      scope: row.scope,
      owner_name: row.owner_name,
      owner_id: row.owner_id ?? null,
      secondary_owner_id: row.secondary_owner_id ?? null,
      subject: row.subject ?? '',
      detail: row.detail,
      level: row.level,
      weight: row.weight,
      expression: row.extra && row.kind.startsWith('logical_') ? row.extra : '',
    };
  }

  async function saveEdit() {
    try {
      const payload = {
        level: editing.level,
        weight: Number(editing.weight),
        expression: editing.expression || null,
        owner_id: editing.owner_id ?? null,
        secondary_owner_id: editing.secondary_owner_id ?? null,
        subject: editing.subject || null,
      };
      await api.put(`/api/monitor/constraints/${editing.kind}/${editing.id}`,
                    payload);
      flash('Vincolo aggiornato', 'success');
      editing = null;
      await listRef.reload();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  // levelPill / levelLabel imported from $lib/constraint_levels.js

  const columns = [
    { key: 'kind', label: 'Kind' },
    { key: 'scope', label: 'Ambito' },
    { key: 'applicato_a', label: 'Applicato a' },
    { key: 'level', label: 'Stato' },
    { key: 'weight', label: 'Peso' },
    { key: 'detail', label: 'Dettaglio' }
  ];
  const help = {
    fields: ['kind', 'tipo', 'scope', 'ambito',
             'applicato_a', 'applicato', 'chi', 'nome',
             'docente', 'classe', 'aula', 'materia', 'subject',
             'owner', 'level', 'stato',
             'weight', 'peso', 'detail', 'dettaglio', 'extra'],
    examples: [
      'level = hard',
      'level = enforced',
      'kind = logical_teacher',
      'applicato_a contains Rossi',
      'docente = Bianchi',
      'classe contains 3A',
      'aula = LabFisica',
      'peso > 100',
      'scope = aula'
    ]
  };
</script>

<div class="space-y-4" data-testid="constraints-page">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Vincoli</h1>
    <button class="btn-primary ml-auto"
            on:click={() => (newConstraintOpen = true)}
            data-testid="new-constraint-btn">
      + Nuovo vincolo
    </button>
    <button class="btn-primary"
            on:click={() => (newDSLConstraintOpen = true)}
            title="Vincolo espresso in DSL generico (forall/exists/count su lessons/teachers/...)"
            data-testid="new-dsl-constraint-btn">
      + Nuovo vincolo DSL
    </button>
    <button class="btn-primary"
            on:click={() => (feasibilityOpen = !feasibilityOpen)}
            title="Analisi MUS dei vincoli HARD/ENFORCED"
            data-testid="feasibility-toggle-btn">
      {feasibilityOpen ? 'Nascondi' : ''} Feasibility Check
    </button>
    <button class="btn"
            on:click={() => searchResults === null ? (searchResults = []) : (searchResults = null)}
            data-testid="constraints-search-toggle"
            title="Ricerca avanzata: trova tutti i vincoli che coinvolgono un'entita' specifica">
      🔍 Ricerca
    </button>
    <button class="btn" on:click={loadConflicts} disabled={conflictsBusy}>
      {conflictsBusy ? 'cerco...' : 'Cerca conflitti'}
    </button>
    {#if conflicts !== null}
      <button class="btn !text-xs" on:click={() => (showConflicts = !showConflicts)}>
        {showConflicts ? 'nascondi' : 'mostra'} pannello
        ({conflicts.length})
      </button>
    {/if}
  </div>

  {#if feasibilityOpen}
    <div class="card p-4 border-2 border-accent-500/30 bg-accent-500/5">
      <h2 class="mb-2">Feasibility Check (MUS)</h2>
      <FeasibilityPanel onChanged={async () => {
        if (listRef) await listRef.reload();
      }}/>
    </div>
  {/if}

  {#if searchResults !== null}
    <div class="card p-4 border-2 border-blue-300 bg-blue-50/40">
      <h2 class="mb-2">🔍 Ricerca vincoli che coinvolgono un'entita'</h2>
      <p class="text-xs text-ink-500 mb-3">
        Cerca trasversalmente fra TUTTE le sorgenti di vincoli (matrici,
        logici, preferenze aule, coteach, DSL generici), trovando ogni
        vincolo che <strong>menziona</strong> l'entita' scelta -- a
        prescindere da dove e' stato creato. La menzione e' rilevata
        sia da `owner_id`/FK strutturati sia dal testo dell'espressione
        DSL salvata.
      </p>

      <div class="grid grid-cols-12 gap-2 items-end mb-3">
        <div class="field col-span-3">
          <label>Tipo entita'</label>
          <select bind:value={searchEntityType}
                  data-testid="search-entity-type"
                  on:change={() => (searchEntityId = null)}>
            <option value="">(qualunque)</option>
            <option value="teacher">Docente</option>
            <option value="class">Classe</option>
            <option value="classroom">Aula</option>
            <option value="subject">Materia</option>
            <option value="curriculum">Indirizzo</option>
            <option value="group">Gruppo</option>
          </select>
        </div>
        <div class="field col-span-4">
          <label>Entita'</label>
          <select bind:value={searchEntityId}
                  data-testid="search-entity-id"
                  disabled={!searchEntityType}>
            <option value={null}>(scegli)</option>
            {#each searchEntityOptions as o}
              <option value={o.id}>{o.label}</option>
            {/each}
          </select>
        </div>
        <div class="field col-span-3">
          <label>Filtro testo (opzionale)</label>
          <input bind:value={searchText}
                 data-testid="search-text"
                 placeholder="es. LabFisica, Mate, Borghi"/>
        </div>
        <div class="col-span-2 flex gap-1">
          <button class="btn-primary !text-xs" on:click={runSearch}
                  data-testid="search-run"
                  disabled={searchBusy}>
            {searchBusy ? '...' : 'Cerca'}
          </button>
          <button class="btn !text-xs" on:click={resetSearch}
                  data-testid="search-reset">Reset</button>
        </div>
      </div>

      <div class="flex gap-2 text-xs items-center mb-2">
        <span class="text-ink-500">Livelli:</span>
        {#each ['hard', 'soft', 'preferred', 'enforced', 'allowed', 'forbidden'] as lv}
          <label class="flex items-center gap-1">
            <input type="checkbox" value={lv}
                   bind:group={searchLevels}/>
            {lv}
          </label>
        {/each}
      </div>

      {#if searchResults && searchResults.length}
        <table class="tbl text-xs w-full">
          <thead>
            <tr>
              <th>Kind</th><th>Origine</th><th>Scope</th>
              <th>Owner</th><th>Livello</th>
              <th>Dettaglio / Espressione</th>
              <th>Menzioni</th><th></th>
            </tr>
          </thead>
          <tbody>
            {#each searchResults as r}
              <tr>
                <td><code class="text-[10px]">{r.kind}</code></td>
                <td>
                  <span class="pill !text-[10px]">tab: {r.origin}</span>
                </td>
                <td><span class="pill !text-[10px]">{r.scope}</span></td>
                <td>{r.owner_name}</td>
                <td>
                  <span class="{levelPill(r.level)} !text-[10px]">
                    {levelLabel(r.level)}
                  </span>
                </td>
                <td><code class="text-[10px]">{r.detail}</code></td>
                <td class="text-[10px] text-ink-500">
                  {r.mentions.map((m) => m.entity_type + '#' + m.entity_id).join(', ')}
                </td>
                <td>
                  <button class="btn-red !text-[10px] !px-1.5 !py-0.5"
                          on:click={async () => {
                            if (r.kind === 'general_dsl') {
                              await deleteDSL(r.id);
                            } else {
                              if (!confirm('Eliminare questo vincolo?')) return;
                              try {
                                await api.del(`/api/monitor/constraints/${r.kind}/${r.id}`);
                                flash('Vincolo eliminato.', 'success');
                              } catch (e) { flash('Errore: ' + e.message, 'error'); }
                            }
                            await runSearch();
                            if (listRef) await listRef.reload();
                          }}>✕</button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else if searchBusy}
        <p class="text-xs text-ink-400 italic">cerco...</p>
      {:else}
        <p class="text-xs text-ink-400 italic">
          Nessun risultato. Imposta un'entita' e clicca Cerca.
        </p>
      {/if}
    </div>
  {/if}

  {#if dslConstraints.length > 0}
    <details class="card p-3 bg-ink-50/40" open data-testid="dsl-constraints-table">
      <summary class="cursor-pointer text-sm font-medium">
        Vincoli DSL generici ({dslConstraints.length})
      </summary>
      <table class="tbl text-xs w-full mt-2">
        <thead>
          <tr>
            <th>#</th><th>Etichetta</th><th>Livello</th>
            <th>Peso</th><th>Scope</th><th>Espressione</th><th></th>
          </tr>
        </thead>
        <tbody>
          {#each dslConstraints as c (c.id)}
            <tr data-testid="dsl-row-{c.id}">
              <td class="text-ink-400">#{c.id}</td>
              <td>{c.label || ''}</td>
              <td>
                <span class="pill !text-[10px]
                            {c.level === 'hard' ? 'pill-red'
                             : c.level === 'soft' ? 'pill-amber'
                             : c.level === 'preferred' ? 'pill-blue'
                             : 'pill-green'}">{c.level}</span>
              </td>
              <td class="text-center">{c.weight}</td>
              <td>
                <span class="pill !text-[10px]">{c.scope}</span>
                {#if c.owner_id != null}<span class="text-ink-400 ml-1">#{c.owner_id}</span>{/if}
              </td>
              <td><code class="text-[10px]">{c.expression}</code></td>
              <td class="text-right">
                <button class="btn-red !text-[10px] !px-1.5 !py-0.5"
                        data-testid="dsl-delete-{c.id}"
                        on:click={() => deleteDSL(c.id)}>✕</button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </details>
  {/if}

  {#if showConflicts && conflicts}
    <div class="card p-3 border-red-300 bg-red-50/50 space-y-2">
      <h3 class="!text-base">
        Conflitti rilevati: <span class={conflicts.length === 0 ? 'text-emerald-700' : 'text-red-700'}>{conflicts.length}</span>
      </h3>
      {#if conflicts.length === 0}
        <p class="text-sm text-emerald-700">Nessun conflitto fra i vincoli attuali.</p>
      {:else}
        <ul class="space-y-2">
          {#each conflicts as c}
            <li class="card !shadow-none p-2 border-red-200 bg-white">
              <div class="text-sm"><strong>{c.kind}</strong>: {c.reason}</div>
              {#if c.members?.length}
                <div class="text-xs text-ink-500 mt-1">Vincoli coinvolti:</div>
                <ul class="text-xs ml-4 list-disc">
                  {#each c.members as m}
                    <li>
                      <span class={levelPill(m.level)}>
                        {levelLabel(m.level)}
                      </span>
                      {m.kind} #{m.id} - {m.owner_name} - {m.detail}
                    </li>
                  {/each}
                </ul>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}

  <p class="text-xs text-ink-500">
    Lista di tutti i vincoli editabili (matrici di disponibilita,
    vincoli logici per docenti/classi/aule/indirizzi, preferenze
    materia-aula e docente-aula non default, regole di compresenza).
    I colori riflettono il tipo: <span class="pill-red">HARD</span>,
    <span class="pill-amber">SOFT</span>,
    <span class="pill-blue">PREFERRED</span>,
    <span class="pill-c-enforced">ENFORCED</span>.
  </p>

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/monitor/constraints"
    {columns}
    {help}
    rowKey={(r) => r.kind + '-' + r.id}
    let:row let:columns>
    <tr>
      <td class="text-xs"><code>{row.kind}</code></td>
      <td class="text-xs">
        <span class="pill !text-[10px]">{row.scope}</span>
      </td>
      <td class="text-xs">
        <!-- "Applicato a": l'entita' a cui il vincolo si riferisce.
             Ricercabile via owner / applicato_a / chi / nome /
             docente / classe / aula nel DSL. -->
        {#if row.scope === 'docente'}
          <span class="text-ink-500">👤 docente:</span>
        {:else if row.scope === 'classe'}
          <span class="text-ink-500">🏫 classe:</span>
        {:else if row.scope === 'aula'}
          <span class="text-ink-500">🚪 aula:</span>
        {:else if row.scope === 'indirizzo'}
          <span class="text-ink-500">🎓 indirizzo:</span>
        {:else if row.scope === 'materia/aula' || row.scope === 'docente/aula'}
          <span class="text-ink-500">{row.scope}:</span>
        {/if}
        <strong class="text-accent-700">{row.owner_name}</strong>
        {#if row.subject}
          <span class="text-ink-500"> · materia: {row.subject}</span>
        {/if}
      </td>
      <td>
        <span class="{levelPill(row.level)} !text-[10px]">
          {levelLabel(row.level)}
        </span>
      </td>
      <td class="text-center text-xs">{row.weight}</td>
      <td class="text-xs"><code>{row.detail}</code></td>
      <td class="whitespace-nowrap">
        {#if row.editable}
          <button class="btn !text-xs !px-2 !py-1" on:click={() => startEdit(row)}>Modifica</button>
        {/if}
        <button class="btn-danger !text-xs !px-2 !py-1" on:click={() => del(row)}>Elimina</button>
      </td>
    </tr>
  </SortableQueryableList>
</div>

<Modal open={!!editing} title={editing ? `Modifica ${editing.kind} #${editing.id}` : ''}
       onClose={() => (editing = null)}>
  {#if editing}
    <div class="space-y-3">
      <div class="text-xs text-ink-500 italic">
        Vincolo applicato a <strong>{editing.scope}</strong>:
        <strong class="text-accent-700">{editing.owner_name}</strong>
        - <code>{editing.detail}</code>.
        I dropdown qui sotto permettono di ri-applicare il vincolo
        a un'altra entita' senza ricrearlo.
      </div>

      <!-- Owner dropdowns: docente / classe / aula / indirizzo /
           materia, in base al kind del vincolo. -->
      {#each ownerSpec(editing.kind) as spec}
        <div class="field">
          <label>{spec.label}</label>
          <select bind:value={editing[spec.key]}>
            {#each spec.options as o}
              <option value={o.value}>{o.text}</option>
            {/each}
          </select>
        </div>
      {/each}

      <div class="field">
        <label>Livello</label>
        <select bind:value={editing.level}>
          {#if editing.kind.endsWith('_pref')}
            <option value="allowed">allowed</option>
            <option value="soft">soft</option>
            <option value="preferred">preferred</option>
            <option value="forbidden">forbidden</option>
            <option value="enforced">enforced</option>
          {:else}
            <option value="hard">hard</option>
            <option value="soft">soft</option>
            <option value="preferred">preferred</option>
            <option value="enforced">enforced</option>
          {/if}
        </select>
      </div>

      <div class="field">
        <label>Peso / Penalita</label>
        <input type="number" bind:value={editing.weight}/>
      </div>

      {#if editing.kind.startsWith('logical_')}
        <div class="field">
          <label>Espressione</label>
          <input class="font-mono text-sm" bind:value={editing.expression}/>
        </div>
      {/if}

      <div class="flex justify-end gap-2 mt-3">
        <button class="btn" on:click={() => (editing = null)}>Annulla</button>
        <button class="btn-primary" on:click={saveEdit}>Salva</button>
      </div>
    </div>
  {/if}
</Modal>

<NewConstraintModal bind:open={newConstraintOpen}
                    onClose={() => (newConstraintOpen = false)}
                    onCreated={async () => {
                      if (listRef) await listRef.reload();
                    }}/>

<NewGeneralConstraintModal bind:open={newDSLConstraintOpen}
                           scope="global"
                           onClose={() => (newDSLConstraintOpen = false)}
                           onCreated={reloadDSL}/>
