<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import { levelPill, levelLabel } from '$lib/constraint_levels';

  let listRef = null;
  let conflicts = null;
  let showConflicts = false;
  let conflictsBusy = false;

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
  });

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
    { key: 'owner', label: 'Owner' },
    { key: 'level', label: 'Stato' },
    { key: 'weight', label: 'Peso' },
    { key: 'detail', label: 'Dettaglio' }
  ];
  const help = {
    fields: ['kind', 'tipo', 'scope', 'ambito', 'owner', 'level', 'stato',
             'weight', 'peso', 'detail', 'dettaglio', 'extra'],
    examples: [
      'level = hard',
      'level = enforced',
      'kind = logical_teacher',
      'owner contains Rossi',
      'peso > 100',
      'scope = aula'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Vincoli</h1>
    <button class="btn ml-auto" on:click={loadConflicts} disabled={conflictsBusy}>
      {conflictsBusy ? 'cerco...' : 'Cerca conflitti'}
    </button>
    {#if conflicts !== null}
      <button class="btn !text-xs" on:click={() => (showConflicts = !showConflicts)}>
        {showConflicts ? 'nascondi' : 'mostra'} pannello
        ({conflicts.length})
      </button>
    {/if}
  </div>

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
    <span class="pill-blue">PREFERITO</span>,
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
        <strong class="text-accent-700">{row.owner_name}</strong>
        {#if row.subject}
          <span class="text-ink-500"> - {row.subject}</span>
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
