<script>
  import { api } from '$lib/api';
  import { flash, refreshDataset } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import AvailabilityMatrix from '$lib/components/AvailabilityMatrix.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import LogicalUnavailabilitiesPanel from '$lib/components/LogicalUnavailabilitiesPanel.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';
  import BulkApplyModal from '$lib/components/BulkApplyModal.svelte';
  import { cloneRow } from '$lib/utils';
  import { classes as classesSvc } from '$lib/services';
  import { subjectsQuery, curriculaQuery } from '$lib/queries';

  let editing = null;
  let listRef = null;
  let selectedIds = [];
  let showBulk = false;
  // Mirror the list's currently-rendered rows so bulk-delete can
  // snapshot them (for UNDO) without poking at SortableQueryableList
  // internals.
  let latestRows = [];

  // Lookup data cached via TanStack Query: instant on revisit.
  const subjectsQ = subjectsQuery.useList();
  const curriculaQ = curriculaQuery.useList();
  $: allSubjects = ($subjectsQ.data ?? []).map((s) => s.name).sort();
  $: allCurricula = $curriculaQ.data ?? [];

  function newClass() {
    editing = {
      _new: true,
      name: '', nickname: '', year: 1, section: '', curriculum: '', curriculum_id: null,
      n_students: 22, notes: '',
      hard_entry_at_8: true, hard_exit_after_12: true,
      hard_no_holes: true, hard_dual_math: true,
      hard_dual_italian: true, hard_motorie_pairs: true,
      hard_max_6_per_day: true, soft_minimize_sixth_weight: 50,
      preferred_free_days: [],
      required_free_days_count: 0,
      max_hours_per_day: 5,
      subjects: [], unavailability: []
    };
  }
  function edit(row) { editing = cloneRow(row); }

  function applyCurriculumGrid() {
    if (!editing.curriculum_id) return;
    const c = allCurricula.find((x) => x.id === editing.curriculum_id);
    if (!c) return;
    const yearHours = (c.hours || []).filter((h) => Number(h.year) === Number(editing.year));
    if (yearHours.length === 0) {
      flash(`L'indirizzo ${c.code} non ha ore definite per l'anno ${editing.year}`,
            'warning');
      return;
    }
    editing.subjects = yearHours.map((h) => ({
      subject: h.subject, hours_per_week: h.hours_per_week
    }));
    if (!editing.curriculum) editing.curriculum = c.code;
  }
  function addSubject() {
    editing.subjects = [...editing.subjects, { subject: '', hours_per_week: 1 }];
  }
  function delSubject(i) { editing.subjects = editing.subjects.filter((_, idx) => idx !== i); }
  function onMatrixChange(newCells) {
    editing = { ...editing, unavailability: newCells };
  }

  let saving = false;
  async function save() {
    const payload = { ...editing };
    delete payload._new; delete payload.id;
    delete payload.ore_totali; delete payload.n_subjects;
    saving = true;
    try {
      if (editing._new) await classesSvc.create(payload);
      else await classesSvc.update(editing.id, payload);
      flash('Salvato', 'success');
      editing = null;
      await listRef.reload();
      await refreshDataset();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally {
      saving = false;
    }
  }

  // Strip server-computed fields from a snapshot so it can round-trip
  // through classesSvc.create() without the backend rejecting it.
  function _scrubClassSnapshot(snap) {
    delete snap.id;
    delete snap.ore_totali;
    delete snap.n_subjects;
    return snap;
  }

  async function del(row) {
    if (!confirm('Eliminare ' + row.name + '?')) return;
    const snapshot = _scrubClassSnapshot(cloneRow(row));
    try {
      await classesSvc.remove(row.id);
      await listRef.reload();
      await refreshDataset();
      flash('Classe eliminata', 'success', {
        ms: 8000,
        action: {
          label: 'Annulla',
          fn: async () => {
            try {
              await classesSvc.create(snapshot);
              await listRef.reload();
              await refreshDataset();
              flash('Eliminazione annullata', 'success');
            } catch (e) {
              flash('Annullamento fallito: ' + e.message, 'error');
            }
          }
        }
      });
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  // Bulk-delete: mirrors the per-row del() pattern. Frontend loop of
  // DELETE /api/classes/{id} so cascade behaviour is identical to N
  // single deletes; one batch confirm and one toast UNDO.
  let bulkDeleting = false;
  async function bulkDel() {
    if (bulkDeleting) return;
    if (selectedIds.length === 0) return;
    const idSet = new Set(selectedIds.map((x) => Number(x)));
    const rows = latestRows.filter((r) => idSet.has(Number(r.id)));
    if (rows.length === 0) {
      flash('Selezione non trovata nella vista corrente. Resetta i filtri e riprova.',
            'error');
      return;
    }
    if (rows.length !== selectedIds.length) {
      if (!confirm(`Eliminare ${rows.length} classi? `
          + `(${selectedIds.length - rows.length} non sono nella `
          + `pagina corrente e verranno ignorati.)`)) return;
    } else {
      if (!confirm(`Eliminare ${rows.length} classi? `
          + `L'azione cancella anche le cattedre collegate.`)) return;
    }
    bulkDeleting = true;
    const snapshots = rows.map((r) => _scrubClassSnapshot(cloneRow(r)));
    let okCount = 0;
    const errors = [];
    try {
      for (const r of rows) {
        try {
          await classesSvc.remove(r.id);
          okCount++;
        } catch (e) {
          errors.push(`${r.name}: ${e.message ?? e}`);
        }
      }
      selectedIds = [];
      await listRef.reload();
      await refreshDataset();
      const tone = errors.length ? 'warning' : 'success';
      flash(`${okCount}/${rows.length} classi eliminate`
            + (errors.length ? ` (${errors.length} errori)` : ''),
            tone, {
        ms: 10000,
        action: {
          label: 'Annulla',
          fn: async () => {
            let restored = 0;
            for (const snap of snapshots) {
              try {
                await classesSvc.create(snap);
                restored++;
              } catch (e) { console.warn('UNDO create failed', e); }
            }
            await listRef.reload();
            await refreshDataset();
            flash(`Ripristinate ${restored}/${snapshots.length} classi`,
                  restored === snapshots.length ? 'success' : 'warning');
          }
        }
      });
    } finally {
      bulkDeleting = false;
    }
  }

  const columns = [
    { key: 'name', label: 'Nome' },
    { key: 'year', label: 'Anno' },
    { key: 'section', label: 'Sez.' },
    { key: 'curriculum', label: 'Indirizzo' },
    { key: 'n_students', label: 'Studenti' },
    { key: 'ore_totali', label: 'Ore/sett.',
      render: (r) => (r.subjects || []).reduce((s, x) => s + Number(x.hours_per_week || 0), 0) },
  ];
  const help = {
    fields: ['name', 'year', 'anno', 'section', 'sezione', 'curriculum',
             'indirizzo', 'n_students', 'ore_totali', 'n_subjects'],
    examples: [
      'anno = 3',
      'indirizzo contains scientifico',
      'ore_totali > 30',
      'name startswith 1',
      'unavailable_on(domenica)'
    ]
  };
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Classi</h1>
    <button class="btn-primary ml-auto" on:click={newClass}>+ Nuova classe</button>
    <ImportButton entity="classes" onDone={() => listRef?.reload()}/>
    <button class="btn !text-xs" on:click={() => (showBulk = true)}
            disabled={selectedIds.length === 0}
            title="Applica un vincolo a tutte le classi selezionate">
      Vincolo collettivo ({selectedIds.length})
    </button>
    <button class="btn-danger !text-xs" on:click={bulkDel}
            disabled={selectedIds.length === 0 || bulkDeleting}
            title="Elimina tutte le classi selezionate (con UNDO)">
      {bulkDeleting ? 'Eliminazione...' : `Elimina selezionati (${selectedIds.length})`}
    </button>
  </div>

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/classes"
    entity="classes"
    {columns}
    {help}
    rowKey={(r) => r.id}
    selectable={true}
    bind:selectedIds
    onRowsChange={(rs) => (latestRows = rs)}
    let:row let:columns>
    <td><strong>{row.name}</strong></td>
    <td class="text-center">{row.year}</td>
    <td>{row.section ?? ''}</td>
    <td>{row.curriculum ?? ''}</td>
    <td class="text-center">{row.n_students}</td>
    <td class="text-center">
      {(row.subjects || []).reduce((s, x) => s + Number(x.hours_per_week || 0), 0)}
    </td>
    <td class="whitespace-nowrap">
      <button class="btn !text-xs !px-2 !py-1" on:click={() => edit(row)}>Modifica</button>
      <button class="btn-danger !text-xs !px-2 !py-1" on:click={() => del(row)}>Elimina</button>
    </td>
  </SortableQueryableList>
</div>

<BulkApplyModal entity="classes" bind:open={showBulk}
                {selectedIds}
                onDone={() => { selectedIds = []; listRef?.reload(); }}/>

<Modal open={!!editing} title={editing?._new ? 'Nuova classe' : 'Modifica classe'} onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3">
      <div class="field"><label>Nome</label><input bind:value={editing.name}/></div>
      <div class="field">
        <label>Nickname (mostrato nell'orario)
          <span class="text-xs text-ink-400">- default: nome</span>
        </label>
        <input bind:value={editing.nickname} placeholder={editing.name ?? ''}/>
      </div>
      <div class="field"><label>Anno</label><input type="number" min="1" max="5" bind:value={editing.year}/></div>
      <div class="field"><label>Sezione</label><input bind:value={editing.section}/></div>
      <div class="field">
        <label>Indirizzo</label>
        <div class="flex gap-2">
          <select bind:value={editing.curriculum_id}
                  on:change={() => {
                    const c = allCurricula.find((x) => x.id === editing.curriculum_id);
                    if (c) editing.curriculum = c.code;
                  }}
                  class="flex-1 px-2 py-1 border border-ink-200 rounded">
            <option value={null}>(nessuno)</option>
            {#each allCurricula as c}
              <option value={c.id}>{c.code} - {c.name}</option>
            {/each}
          </select>
          <button class="btn !text-xs !px-2 !py-1"
                  on:click={applyCurriculumGrid}
                  disabled={!editing.curriculum_id}
                  title="Carica il monte-ore dell'indirizzo per l'anno selezionato">
            Importa griglia
          </button>
        </div>
        <input class="mt-1 text-xs" placeholder="(stringa libera, opzionale)"
               bind:value={editing.curriculum}/>
      </div>
      <div class="field"><label>N. studenti</label><input type="number" bind:value={editing.n_students}/></div>
      <div class="field"><label>Note</label><input bind:value={editing.notes}/></div>
    </div>

    <div class="mt-4">
      <h3 class="mb-2">Vincoli HARD</h3>
      <div class="grid grid-cols-2 gap-2 text-sm">
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_entry_at_8}/> Ingresso alle 8:00</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_exit_after_12}/> Uscita non prima delle 12</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_no_holes}/> No buchi nella giornata</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_dual_math}/> Doppia ora consecutiva di Mat</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_dual_italian}/> Doppia ora di Italiano</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_motorie_pairs}/> Sc. motorie a coppie</label>
        <label class="flex gap-2"><input type="checkbox" bind:checked={editing.hard_max_6_per_day}/> Max 6 ore/giorno</label>
      </div>
    </div>

    <div class="mt-4 field">
      <label>Peso minimizzazione 6^a ora (SOFT)</label>
      <input type="number" bind:value={editing.soft_minimize_sixth_weight}/>
    </div>

    <div class="mt-4">
      <h3 class="mb-2">Materie e ore settimanali</h3>
      <table class="tbl">
        <thead><tr><th>Materia</th><th>Ore/sett.</th><th></th></tr></thead>
        <tbody>
          {#each editing.subjects as s, i}
            <tr>
              <td>
                <input list="subj-{i}" class="w-full px-2 py-1 border border-ink-200 rounded" bind:value={s.subject}/>
                <datalist id="subj-{i}">{#each allSubjects as sn}<option value={sn}/>{/each}</datalist>
              </td>
              <td class="w-24"><input type="number" min="0" max="10" bind:value={s.hours_per_week} class="w-full px-2 py-1 border border-ink-200 rounded"/></td>
              <td><button class="btn-danger !text-xs !px-2 !py-1" on:click={() => delSubject(i)}>x</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <button class="btn !text-xs !px-2 !py-1 mt-2" on:click={addSubject}>+ Materia</button>
    </div>

    <div class="mt-4">
      <AvailabilityMatrix
        title="Disponibilita oraria della classe"
        value={editing.unavailability || []}
        onChange={onMatrixChange}/>
    </div>

    <!-- Giorni liberi (analogo alla scheda docente) -->
    <div class="mt-4 card !shadow-none p-3 bg-ink-50/40 space-y-3">
      <div class="text-sm font-semibold">Giorni liberi della classe (avanzato)</div>
      <p class="text-xs text-ink-500">
        Per le classi italiane il default e' lavorare lun-sab (zero
        giorni liberi). Se si imposta un giorno libero HARD, le 6 ore
        del giorno vengono bloccate nella matrice di disponibilita'.
        Tre preferenze ordinate (la 1a viene rispettata per prima),
        e un numero esatto di giorni liberi a settimana.
      </p>
      {#each [0, 1, 2] as i}
        {@const cur = (editing.preferred_free_days ?? [])[i]
                        ?? { day: 0, is_hard: true, soft_penalty: 100 }}
        <div class="grid grid-cols-12 gap-2 items-end">
          <div class="field col-span-3">
            <label>{['Prima', 'Seconda', 'Terza'][i]} preferenza</label>
            <select value={cur.day || 0} on:change={(e) => {
              const list = [...(editing.preferred_free_days ?? [])];
              while (list.length <= i) list.push({ day: 0, is_hard: true, soft_penalty: 100 });
              list[i] = { ...list[i], day: Number(e.target.value) };
              editing = { ...editing, preferred_free_days: list.filter((x) => x.day) };
            }}>
              <option value={0}>(nessuno)</option>
              <option value={1}>Lunedi</option>
              <option value={2}>Martedi</option>
              <option value={3}>Mercoledi</option>
              <option value={4}>Giovedi</option>
              <option value={5}>Venerdi</option>
              <option value={6}>Sabato</option>
            </select>
          </div>
          {#if cur.day}
            <div class="col-span-3 flex items-center gap-3 self-center">
              <label class="flex items-center gap-1 text-xs">
                <input type="radio" checked={cur.is_hard}
                       on:change={() => {
                         const list = [...(editing.preferred_free_days ?? [])];
                         list[i] = { ...list[i], is_hard: true };
                         editing = { ...editing, preferred_free_days: list };
                       }}/>
                🟥 HARD
              </label>
              <label class="flex items-center gap-1 text-xs">
                <input type="radio" checked={!cur.is_hard}
                       on:change={() => {
                         const list = [...(editing.preferred_free_days ?? [])];
                         list[i] = { ...list[i], is_hard: false };
                         editing = { ...editing, preferred_free_days: list };
                       }}/>
                🟨 SOFT
              </label>
            </div>
            {#if !cur.is_hard}
              <div class="field col-span-2">
                <label>Penalty</label>
                <input type="number" value={cur.soft_penalty ?? 100}
                       on:input={(e) => {
                         const list = [...(editing.preferred_free_days ?? [])];
                         list[i] = { ...list[i], soft_penalty: Number(e.target.value) };
                         editing = { ...editing, preferred_free_days: list };
                       }}/>
              </div>
            {/if}
          {/if}
        </div>
      {/each}
      {#if (editing.preferred_free_days ?? []).map((p) => p.day).filter((d, i, a) => d && a.indexOf(d) !== i).length > 0}
        <div class="text-xs text-red-600">
          ⚠️ I tre giorni preferiti devono essere distinti.
        </div>
      {/if}
      <div class="grid grid-cols-2 gap-3">
        <div class="field">
          <label>Giorni liberi totali nella settimana (HARD)
            <span title="Numero esatto di giornate libere per la classe. Default 0 (lavora tutti i giorni). 1 = un giorno libero (es. lunedi'). Aumentare oltre 1 e' raro per le classi italiane.">ℹ️</span>
          </label>
          <input type="number" min="0" max="6"
                 value={editing.required_free_days_count ?? 0}
                 on:input={(e) => editing = { ...editing,
                   required_free_days_count: Math.max(0, Math.min(6, Number(e.target.value) || 0)) }}/>
        </div>
        <div class="field">
          <label>Massimo ore al giorno (HARD)
            <span title="Cap superiore al numero di ore in un singolo giorno. Default 5. Aumentare a 6/7 se la classe ha giorni liberi e deve compensare con piu' ore al giorno.">ℹ️</span>
          </label>
          <input type="number" min="1" max="7"
                 value={editing.max_hours_per_day ?? 5}
                 on:input={(e) => editing = { ...editing,
                   max_hours_per_day: Math.max(1, Math.min(7, Number(e.target.value) || 5)) }}/>
        </div>
      </div>
      <!-- Live feasibility check: ore_settimanali / giorni_lavorativi <= max_per_day -->
      {#if (editing.subjects?.length ?? 0) > 0}
        {@const totalHours = (editing.subjects ?? [])
              .reduce((s, x) => s + (Number(x.hours_per_week) || 0), 0)}
        {@const workDays = 6 - (editing.required_free_days_count ?? 0)}
        {@const minPerDay = workDays > 0
                              ? Math.ceil(totalHours / workDays)
                              : Infinity}
        {@const maxPerDay = editing.max_hours_per_day ?? 5}
        {#if workDays === 0}
          <div class="text-xs text-red-700 bg-red-50 border border-red-300 p-2 rounded">
            ⚠️ Configurazione infeasible: 6 giorni liberi -&gt; nessun
            giorno lavorativo!
          </div>
        {:else if minPerDay > maxPerDay}
          <div class="text-xs text-red-700 bg-red-50 border border-red-300 p-2 rounded">
            ⚠️ Configurazione infeasible: con
            {editing.required_free_days_count ?? 0} giorni liberi e
            {totalHours} ore settimanali servono almeno {minPerDay}
            ore al giorno, ma il massimo e' {maxPerDay}. Aumenta
            "Massimo ore al giorno" a {minPerDay} oppure riduci i
            giorni liberi.
          </div>
        {:else}
          <div class="text-xs text-emerald-700 bg-emerald-50 border border-emerald-300 p-2 rounded">
            ✓ Configurazione feasible: {totalHours} ore settimanali
            su {workDays} giorni lavorativi -&gt; minimo {minPerDay} /
            massimo {maxPerDay} ore al giorno.
          </div>
        {/if}
      {/if}
    </div>

    <div class="mt-4">
      <LogicalUnavailabilitiesPanel entityType="classes" entityId={editing.id ?? null}/>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}>Annulla</button>
      <button class="btn-primary focus-ring" on:click={save} disabled={saving}>
        {saving ? 'Salvataggio...' : 'Salva'}
      </button>
    </div>
  {/if}
</Modal>
