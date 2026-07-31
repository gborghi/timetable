<script>
  import PageHero from '$lib/components/PageHero.svelte';
  import { confirmDialog } from '$lib/confirm';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash, refreshDataset } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';
  import { cloneRow } from '$lib/utils';
  import { curricula as curriculaSvc, subjects as subjectsSvc, logic as logicSvc } from '$lib/services';

  let editing = null;
  let listRef = null;
  let activeTab = 'hours';   // 'hours' | 'logical'
  let selectedYear = 1;

  let allSubjects = [];
  let logicalRules = [];
  let logicalDraftExpr = '';
  let logicalDraftYear = null;
  let logicalDraftKind = 'hard';   // 'hard' | 'soft' | 'preferred' | 'enforced'
  let logicalDraftPenalty = 100;
  $: logicalSignedPenalty = (logicalDraftKind === 'preferred')
                              ? -Math.abs(logicalDraftPenalty || 100)
                              : Math.abs(logicalDraftPenalty || 100);
  function onLogicalPenaltyInput(ev) {
    let v = Number(ev.target.value);
    if (!Number.isFinite(v)) return;
    logicalDraftPenalty = Math.abs(v);
    ev.target.value = (logicalDraftKind === 'preferred')
                        ? -logicalDraftPenalty : logicalDraftPenalty;
  }

  function _payloadFromKind(kind, expr, pen, year, label) {
    const base = {
      expression: expr,
      year_filter: year == null || year === '' ? null : Number(year),
      label: label || null,
      kind,
    };
    if (kind === 'hard' || kind === 'enforced')
      return { ...base, is_hard: true, soft_penalty: 100 };
    if (kind === 'soft')
      return { ...base, is_hard: false,
               soft_penalty: Math.abs(Number(pen) || 100) };
    return { ...base, is_hard: false,
             soft_penalty: -Math.abs(Number(pen) || 100) };
  }
  function _kindFromRule(r) {
    if (r.kind) return r.kind;
    if (r.is_hard) return 'hard';
    if (Number(r.soft_penalty) < 0) return 'preferred';
    return 'soft';
  }
  let logicalDraftLabel = '';
  let logicalEditingId = null;
  let logicalValidate = null;

  onMount(async () => {
    try {
      allSubjects = (await subjectsSvc.list()).map((s) => s.name).sort();
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
    editing = cloneRow(row);
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
      if (editing._new) saved = await curriculaSvc.create(payload);
      else saved = await curriculaSvc.update(editing.id, payload);
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
    if (!await confirmDialog('Eliminare ' + row.code + '? (le classi gia collegate verranno disassociate)')) return;
    try {
      await curriculaSvc.remove(row.id);
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
      logicalValidate = await logicSvc.validate(logicalDraftExpr);
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
    if (!await confirmDialog('Eliminare vincolo?\n' + r.pretty)) return;
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

<div class="space-y-4" data-testid="curricula-page">
  <PageHero title="Indirizzi di studio"
            description="Ogni indirizzo porta con se' il quadro orario per anno: e' da qui che le classi ereditano il monte ore di ciascuna materia.">
    <svelte:fragment slot="actions">
      <button class="btn-primary" on:click={newCurriculum}
              data-testid="add-curriculum-btn">+ Nuovo indirizzo</button>
      <ImportButton entity="curricula" onDone={() => listRef?.reload()}/>
    </svelte:fragment>
  </PageHero>

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/curricula"
    entity="curricula"
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
        <button class="btn !text-xs !px-2 !py-1"
                data-testid="curriculum-edit-btn"
                data-curriculum-id={row.id}
                on:click={() => edit(row)}>Modifica</button>
        <button class="btn-danger !text-xs !px-2 !py-1"
                data-testid="curriculum-delete-btn"
                data-curriculum-id={row.id}
                on:click={() => del(row)}>Elimina</button>
      </td>
    </tr>
  </SortableQueryableList>
</div>

<Modal open={!!editing} title={editing?._new ? 'Nuovo indirizzo' : 'Indirizzo: ' + (editing?.code || '')}
       onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3" data-testid="curriculum-form">
      <div class="field">
        <label>Code (machine name, unique)</label>
        <input bind:value={editing.code} data-testid="curriculum-code-input"/>
      </div>
      <div class="field">
        <label>Nome (display)</label>
        <input bind:value={editing.name} data-testid="curriculum-name-input"/>
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
                    {#each allSubjects as sn}<option value={sn}></option>{/each}
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
                      {#if _kindFromRule(r) === 'enforced'}
                        <span class="pill-c-enforced">ENFORCED</span>
                      {:else if _kindFromRule(r) === 'hard'}
                        <span class="pill-red">HARD</span>
                      {:else if _kindFromRule(r) === 'preferred'}
                        <span class="pill-blue">PREFERRED</span>
                      {:else}
                        <span class="pill-amber">SOFT</span>
                      {/if}
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
                <span class="pill-blue !text-[10px]">PREFERRED</span>
              </label>
              <label class="flex items-center gap-1 text-xs">
                <input type="radio" bind:group={logicalDraftKind} value="enforced"/>
                <span class="pill-c-enforced !text-[10px]">ENFORCED</span>
              </label>
              {#if logicalDraftKind === 'soft' || logicalDraftKind === 'preferred'}
                <div class="field">
                  <label>{logicalDraftKind === 'soft' ? 'Penalita (> 0)' : 'Bonus (< 0)'}</label>
                  <input type="number" class="w-24"
                         value={logicalSignedPenalty}
                         on:input={onLogicalPenaltyInput}/>
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
      <button class="btn" on:click={() => (editing = null)}
              data-testid="curriculum-cancel-btn">Chiudi</button>
      <button class="btn-primary" on:click={save}
              data-testid="curriculum-save-btn">Salva</button>
    </div>
  {/if}
</Modal>
