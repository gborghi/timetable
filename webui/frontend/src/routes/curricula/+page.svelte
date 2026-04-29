<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api.js';
  import { flash, refreshDataset } from '$lib/stores.js';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';

  let editing = null;
  let listRef = null;
  let activeTab = 'hours';   // 'hours' | 'logical'
  let selectedYear = 1;

  let allSubjects = [];
  let logicalRules = [];
  let logicalDraftExpr = '';
  let logicalDraftYear = null;
  let logicalDraftKind = 'hard';   // 'hard' | 'soft' | 'preferred'
  let logicalDraftPenalty = 100;

  function _payloadFromKind(kind, expr, pen, year, label) {
    const base = {
      expression: expr,
      year_filter: year == null || year === '' ? null : Number(year),
      label: label || null,
    };
    if (kind === 'hard') return { ...base, is_hard: true, soft_penalty: 100 };
    if (kind === 'soft') return { ...base, is_hard: false,
                                   soft_penalty: Math.abs(Number(pen) || 100) };
    return { ...base, is_hard: false,
             soft_penalty: -Math.abs(Number(pen) || 100) };
  }
  function _kindFromRule(r) {
    if (r.is_hard) return 'hard';
    if (Number(r.soft_penalty) < 0) return 'preferred';
    return 'soft';
  }
  let logicalDraftLabel = '';
  let logicalEditingId = null;
  let logicalValidate = null;

  onMount(async () => {
    try {
      allSubjects = (await api.get('/api/subjects')).map((s) => s.name).sort();
    } catch { /* */ }
  });

  function newCurriculum() {
    editing = {
      _new: true, code: '', name: '', description: '', notes: '',
      score: 1, hours: []
    };
    activeTab = 'hours';
    selectedYear = 1;
  }

  async function edit(row) {
    editing = JSON.parse(JSON.stringify(row));
    activeTab = 'hours';
    selectedYear = 1;
    await reloadLogicalRules();
  }

  // hours: indexed by year for editing convenience
  function hoursForYear(year) {
    return (editing?.hours || []).filter((h) => Number(h.year) === Number(year));
  }
  function addHour() {
    editing.hours = [...(editing.hours || []),
                     { year: selectedYear, subject: '', hours_per_week: 1 }];
  }
  function delHour(globalIdx) {
    editing.hours = editing.hours.filter((_, i) => i !== globalIdx);
  }
  function globalIndexOf(localItem) {
    return editing.hours.indexOf(localItem);
  }

  async function save() {
    const payload = { ...editing };
    delete payload._new;
    delete payload.id;
    delete payload.n_classes;
    try {
      let saved;
      if (editing._new) saved = await api.post('/api/curricula', payload);
      else saved = await api.put('/api/curricula/' + editing.id, payload);
      flash('Indirizzo salvato', 'success');
      editing = saved;
      await listRef.reload();
      await refreshDataset();
      // After save, reload logical rules now that the row has an id
      await reloadLogicalRules();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function del(row) {
    if (!confirm('Eliminare ' + row.code + '? (le classi gia collegate verranno disassociate)')) return;
    try {
      await api.del('/api/curricula/' + row.id);
      await listRef.reload();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  // ----- logical constraints -----
  async function reloadLogicalRules() {
    if (!editing || !editing.id) { logicalRules = []; return; }
    try {
      logicalRules = await api.get(`/api/curricula/${editing.id}/logical-constraints`);
    } catch (e) {
      flash('Errore caricando vincoli logici: ' + e.message, 'error');
    }
  }

  async function logicalValidateNow() {
    try {
      logicalValidate = await api.post('/api/logic/validate', { expression: logicalDraftExpr });
    } catch (e) {
      logicalValidate = { ok: false, error: e.message };
    }
  }

  async function addLogical() {
    if (!editing?.id) {
      flash('Salva prima l\'indirizzo per poter aggiungere vincoli logici', 'error');
      return;
    }
    if (!logicalDraftExpr.trim()) return;
    try {
      const payload = _payloadFromKind(
        logicalDraftKind, logicalDraftExpr, logicalDraftPenalty,
        logicalDraftYear, logicalDraftLabel
      );
      if (logicalEditingId) {
        await api.put(`/api/curricula/${editing.id}/logical-constraints/${logicalEditingId}`, payload);
      } else {
        await api.post(`/api/curricula/${editing.id}/logical-constraints`, payload);
      }
      logicalDraftExpr = '';
      logicalDraftYear = null;
      logicalDraftLabel = '';
      logicalValidate = null;
      logicalEditingId = null;
      await reloadLogicalRules();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  function startEditLogical(r) {
    logicalEditingId = r.id;
    logicalDraftExpr = r.expression;
    logicalDraftYear = r.year_filter;
    logicalDraftKind = _kindFromRule(r);
    logicalDraftPenalty = Math.abs(r.soft_penalty || 100);
    logicalDraftLabel = r.label || '';
  }
  function cancelEditLogical() {
    logicalEditingId = null;
    logicalDraftExpr = '';
    logicalDraftYear = null;
    logicalDraftLabel = '';
    logicalValidate = null;
  }
  async function delLogical(r) {
    if (!confirm('Eliminare vincolo?\n' + r.pretty)) return;
    await api.del(`/api/curricula/${editing.id}/logical-constraints/${r.id}`);
    await reloadLogicalRules();
  }

  const columns = [
    { key: 'code', label: 'Codice' },
    { key: 'name', label: 'Nome' },
    { key: 'score', label: 'Score' },
    { key: 'n_classes', label: 'N. classi' },
    { key: 'n_hours_rows', label: 'Righe ore' },
  ];
  const help = {
    fields: ['code', 'name', 'description', 'score', 'n_classes', 'n_hours_rows'],
    examples: [
      'code = "Scientifico"',
      'name contains liceo',
      'n_classes > 0'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Indirizzi di studio</h1>
    <button class="btn-primary ml-auto" on:click={newCurriculum}>+ Nuovo indirizzo</button>
    <ImportButton entity="curricula" onDone={() => listRef?.reload()}/>
  </div>

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/curricula"
    {columns}
    {help}
    rowKey={(r) => r.id}
    let:row let:columns>
    <tr>
      <td><strong>{row.code}</strong></td>
      <td>{row.name}</td>
      <td class="text-center">{row.score}</td>
      <td class="text-center">{row.n_classes}</td>
      <td class="text-center">{(row.hours || []).length}</td>
      <td class="whitespace-nowrap">
        <button class="btn !text-xs !px-2 !py-1" on:click={() => edit(row)}>Modifica</button>
        <button class="btn-danger !text-xs !px-2 !py-1" on:click={() => del(row)}>Elimina</button>
      </td>
    </tr>
  </SortableQueryableList>
</div>

<Modal open={!!editing} title={editing?._new ? 'Nuovo indirizzo' : 'Indirizzo: ' + (editing?.code || '')}
       onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3">
      <div class="field">
        <label>Code (machine name, unique)</label>
        <input bind:value={editing.code}/>
      </div>
      <div class="field">
        <label>Nome (display)</label>
        <input bind:value={editing.name}/>
      </div>
      <div class="field">
        <label>Score (engine)</label>
        <input type="number" bind:value={editing.score}/>
      </div>
      <div class="field col-span-2">
        <label>Descrizione</label>
        <input bind:value={editing.description}/>
      </div>
    </div>

    <div class="border-b border-ink-200 mt-5 mb-3 flex gap-2">
      <button class="px-3 py-1.5 text-sm rounded-t-md
                     {activeTab === 'hours' ? 'bg-ink-100 font-medium' : ''}"
              on:click={() => (activeTab = 'hours')}>Materie e ore per anno</button>
      <button class="px-3 py-1.5 text-sm rounded-t-md
                     {activeTab === 'logical' ? 'bg-ink-100 font-medium' : ''}"
              on:click={() => (activeTab = 'logical')}>Vincoli logici per anno</button>
    </div>

    {#if activeTab === 'hours'}
      <div class="space-y-3">
        <div class="flex items-center gap-2 flex-wrap">
          <label class="text-sm">Anno:</label>
          {#each [1,2,3,4,5] as y}
            <button class="btn !text-xs !px-2 !py-1
                           {selectedYear === y ? 'bg-accent-500/10' : ''}"
                    on:click={() => (selectedYear = y)}>
              {y} ({hoursForYear(y).length})
            </button>
          {/each}
          <span class="text-xs text-ink-500 ml-auto">
            Totale ore anno {selectedYear}:
            {hoursForYear(selectedYear).reduce((s, h) => s + Number(h.hours_per_week || 0), 0)}
          </span>
        </div>

        <table class="tbl">
          <thead><tr><th>Materia</th><th>Ore/sett.</th><th></th></tr></thead>
          <tbody>
            {#each hoursForYear(selectedYear) as h, i (i)}
              {@const gIdx = globalIndexOf(h)}
              <tr>
                <td>
                  <input list="curr-subj-{i}" class="w-full px-2 py-1 border border-ink-200 rounded"
                         bind:value={h.subject}/>
                  <datalist id="curr-subj-{i}">
                    {#each allSubjects as sn}<option value={sn}/>{/each}
                  </datalist>
                </td>
                <td class="w-24">
                  <input type="number" min="0" max="10" bind:value={h.hours_per_week}
                         class="w-full px-2 py-1 border border-ink-200 rounded"/>
                </td>
                <td>
                  <button class="btn-danger !text-xs !px-2 !py-1"
                          on:click={() => delHour(gIdx)}>x</button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        <button class="btn !text-xs !px-2 !py-1" on:click={addHour}>+ Materia per anno {selectedYear}</button>
      </div>
    {:else}
      <div class="space-y-3">
        {#if !editing.id}
          <p class="text-xs text-amber-700">
            Salva prima l'indirizzo per poter aggiungere vincoli logici (servono un id).
          </p>
        {:else}
          {#if logicalRules.length}
            <table class="tbl text-xs">
              <thead>
                <tr>
                  <th>Anno</th><th>Etichetta</th>
                  <th>Espressione (DNF)</th>
                  <th>Tipo</th><th>Penalita</th><th></th>
                </tr>
              </thead>
              <tbody>
                {#each logicalRules as r}
                  <tr>
                    <td class="text-center">{r.year_filter ?? 'tutti'}</td>
                    <td>{r.label ?? ''}</td>
                    <td><code>{r.pretty}</code>
                      <div class="text-ink-400 text-[10px]">orig: <code>{r.expression}</code></div>
                    </td>
                    <td>
                      {#if r.is_hard}<span class="pill-red">HARD</span>
                      {:else if Number(r.soft_penalty) < 0}<span class="pill-blue">PREFERITO</span>
                      {:else}<span class="pill-amber">SOFT</span>{/if}
                    </td>
                    <td class="w-20 text-center">{r.is_hard ? '-' : r.soft_penalty}</td>
                    <td class="whitespace-nowrap">
                      <button class="btn !text-xs !px-2 !py-1"
                              on:click={() => startEditLogical(r)}>Modifica</button>
                      <button class="btn-danger !text-xs !px-2 !py-1"
                              on:click={() => delLogical(r)}>Elimina</button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {:else}
            <p class="text-xs italic text-ink-400">Nessun vincolo logico per questo indirizzo.</p>
          {/if}

          <div class="border-t border-ink-200 pt-3 space-y-2">
            <div class="text-xs font-semibold">
              {logicalEditingId ? 'Modifica vincolo #' + logicalEditingId : 'Nuovo vincolo'}
            </div>
            <div class="grid grid-cols-2 gap-2">
              <div class="field">
                <label>Anno (vuoto = tutti gli anni)</label>
                <select bind:value={logicalDraftYear} class="px-2 py-1 border border-ink-200 rounded">
                  <option value={null}>tutti</option>
                  <option value={1}>1</option><option value={2}>2</option>
                  <option value={3}>3</option><option value={4}>4</option><option value={5}>5</option>
                </select>
              </div>
              <div class="field">
                <label>Etichetta (opzionale)</label>
                <input bind:value={logicalDraftLabel}/>
              </div>
            </div>
            <div class="field">
              <label>Espressione</label>
              <input class="font-mono text-sm"
                     placeholder="es. (lun8 AND lun9) OR (mar8 AND mar9)"
                     bind:value={logicalDraftExpr}
                     on:input={() => (logicalValidate = null)}/>
            </div>
            <div class="flex gap-2 items-end flex-wrap">
              <button class="btn !text-xs" on:click={logicalValidateNow}>Verifica sintassi</button>
              <label class="flex items-center gap-1 text-xs">
                <input type="radio" bind:group={logicalDraftKind} value="hard"/>
                <span class="pill-red !text-[10px]">HARD</span>
              </label>
              <label class="flex items-center gap-1 text-xs">
                <input type="radio" bind:group={logicalDraftKind} value="soft"/>
                <span class="pill-amber !text-[10px]">SOFT</span>
              </label>
              <label class="flex items-center gap-1 text-xs">
                <input type="radio" bind:group={logicalDraftKind} value="preferred"/>
                <span class="pill-blue !text-[10px]">PREFERITO</span>
              </label>
              {#if logicalDraftKind !== 'hard'}
                <div class="field">
                  <label>{logicalDraftKind === 'soft' ? 'Penalita' : 'Bonus'}</label>
                  <input type="number" min="0" class="w-24" bind:value={logicalDraftPenalty}/>
                </div>
              {/if}
              <button class="btn-primary" on:click={addLogical}
                      disabled={!logicalDraftExpr.trim()}>
                {logicalEditingId ? 'Salva modifica' : 'Aggiungi'}
              </button>
              {#if logicalEditingId}
                <button class="btn !text-xs" on:click={cancelEditLogical}>Annulla</button>
              {/if}
            </div>
            {#if logicalValidate}
              <div class="text-xs"
                   class:text-emerald-700={logicalValidate.ok}
                   class:text-red-700={!logicalValidate.ok}>
                {#if logicalValidate.ok}
                  OK: <code>{logicalValidate.pretty}</code>
                  ({logicalValidate.clauses.length} clausole)
                {:else}
                  Errore: {logicalValidate.error}
                {/if}
              </div>
            {/if}
          </div>
        {/if}
      </div>
    {/if}

    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}>Chiudi</button>
      <button class="btn-primary" on:click={save}>Salva</button>
    </div>
  {/if}
</Modal>
