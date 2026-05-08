<script>
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash, refreshDataset } from '$lib/stores';
  import { ROOM_KINDS } from '$lib/constants';
  import Modal from '$lib/components/Modal.svelte';
  import WeeklyCalendarView from '$lib/components/WeeklyCalendarView.svelte';
  import SortableQueryableList from '$lib/components/SortableQueryableList.svelte';
  import LogicalUnavailabilitiesPanel from '$lib/components/LogicalUnavailabilitiesPanel.svelte';
  import ImportButton from '$lib/components/ImportButton.svelte';
  import BulkApplyModal from '$lib/components/BulkApplyModal.svelte';
  import TagPicker from '$lib/components/TagPicker.svelte';
  // (TagPicker is the renamed ClassroomTagPicker, generic)
  import ManageTagsModal from '$lib/components/ManageTagsModal.svelte';
  import { cloneRow } from '$lib/utils';
  import {
    classrooms as classroomsSvc,
    classroomTags as tagSvc,
    subjects as subjectsSvc,
    classes as classesSvc,
  } from '$lib/services';

  // colour helper shared with the picker
  const PALETTE = [
    'bg-emerald-100 text-emerald-700 border-emerald-200',
    'bg-sky-100 text-sky-700 border-sky-200',
    'bg-violet-100 text-violet-700 border-violet-200',
    'bg-amber-100 text-amber-700 border-amber-200',
    'bg-rose-100 text-rose-700 border-rose-200',
    'bg-teal-100 text-teal-700 border-teal-200',
    'bg-indigo-100 text-indigo-700 border-indigo-200',
    'bg-lime-100 text-lime-700 border-lime-200',
    'bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200',
    'bg-cyan-100 text-cyan-700 border-cyan-200',
    'bg-orange-100 text-orange-700 border-orange-200',
    'bg-pink-100 text-pink-700 border-pink-200',
  ];
  function tagColor(name) {
    const s = String(name || '');
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return PALETTE[h % PALETTE.length];
  }

  let editing = null;
  let allSubjects = [];
  let allClasses = [];
  let allTagNames = [];
  let listRef = null;
  let selectedIds = [];
  let showBulk = false;
  let showTagsModal = false;
  // Mirror the list's currently-rendered rows so bulk-delete can
  // snapshot them (for UNDO) without poking at SortableQueryableList
  // internals.
  let latestRows = [];

  let showGenPanel = false;
  let suggested = null;
  let genCounts = {
    lab_fisica: 1, lab_chimica: 1, lab_informatica: 1, lab_linguistico: 1,
    palestra: 1, biblioteca: 1, aula_speciale: 1
  };
  let busyGen = false;
  let plessi = [];

  onMount(async () => {
    try {
      allSubjects = (await subjectsSvc.list()).map((s) => s.name).sort();
      allClasses = (await classesSvc.list()).map((c) => c.name).sort();
    } catch { /* */ }
    try {
      const r = await fetch('/api/plessi');
      if (r.ok) plessi = await r.json();
    } catch { plessi = []; }
    await reloadTags();
  });

  async function reloadTags() {
    try {
      const ts = await tagSvc.list();
      allTagNames = ts.map((t) => t.name).sort();
    } catch { /* */ }
  }

  async function loadSuggested() {
    try {
      suggested = await classroomsSvc.suggestedCounts();
      genCounts = { ...suggested.counts };
      showGenPanel = true;
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  async function runGenerate() {
    if (latestRows && latestRows.length > 0
        && !confirm('Sostituire le aule esistenti con la nuova configurazione?')) return;
    busyGen = true;
    try {
      const payload = {
        n_lab_fisica: Number(genCounts.lab_fisica),
        n_lab_chimica: Number(genCounts.lab_chimica),
        n_lab_informatica: Number(genCounts.lab_informatica),
        n_lab_linguistico: Number(genCounts.lab_linguistico),
        n_palestra: Number(genCounts.palestra),
        n_biblioteca: Number(genCounts.biblioteca),
        n_aula_speciale: Number(genCounts.aula_speciale)
      };
      const r = await classroomsSvc.autoGenerate(payload);
      flash('Aule generate: ' + r.created + ' (su ' + r.n_classes + ' classi)', 'success');
      showGenPanel = false;
      await listRef.reload();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
    finally { busyGen = false; }
  }

  function newRoom() {
    editing = {
      _new: true, name: '', kind: 'standard',
      capacity: 30, multi_class: false, multi_class_max: 1,
      multi_class_pref: 1, multi_class_pref_weight: 10,
      notes: '', plesso_id: null,
      subject_prefs: [], class_prefs: [], unavailability: [],
      tags: [],
    };
  }
  function edit(row) { editing = cloneRow(row);
    if (!Array.isArray(editing.unavailability)) editing.unavailability = [];
    if (!Array.isArray(editing.tags)) editing.tags = [];
  }
  function onTagsChange(next) {
    editing = { ...editing, tags: next };
  }
  function addSubjectPref() { editing.subject_prefs = [...editing.subject_prefs, { subject: '', weight: 10, required: false }]; }
  function delSubjectPref(i) { editing.subject_prefs = editing.subject_prefs.filter((_, idx) => idx !== i); }
  function addClassPref() { editing.class_prefs = [...editing.class_prefs, { class_name: '', weight: 20, is_home: false }]; }
  function delClassPref(i) { editing.class_prefs = editing.class_prefs.filter((_, idx) => idx !== i); }
  function onMatrixChange(newCells) {
    editing = { ...editing, unavailability: newCells };
  }

  async function save() {
    const payload = { ...editing };
    delete payload._new; delete payload.id;
    try {
      if (editing._new) await classroomsSvc.create(payload);
      else await classroomsSvc.update(editing.id, payload);
      flash('Salvato', 'success');
      editing = null;
      await listRef.reload();
      await refreshDataset();
    } catch (e) { flash('Errore: ' + e.message, 'error'); }
  }

  // Strip server-computed fields from a snapshot so it can round-trip
  // through classroomsSvc.create() without the backend rejecting it.
  // (Classroom doesn't expose computed fields like teachers do, but
  // the helper is here so bulk and single deletes share one place.)
  function _scrubRoomSnapshot(snap) {
    delete snap.id;
    return snap;
  }

  async function del(row) {
    if (!confirm('Eliminare ' + row.name + '?')) return;
    const snapshot = _scrubRoomSnapshot(cloneRow(row));
    try {
      await classroomsSvc.remove(row.id);
      await listRef.reload();
      await refreshDataset();
      flash('Aula eliminata', 'success', {
        ms: 8000,
        action: {
          label: 'Annulla',
          fn: async () => {
            try {
              await classroomsSvc.create(snapshot);
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

  // Bulk-delete: same pattern as the per-row del(). Frontend loop of
  // DELETE /api/classrooms/{id} — cascade is whatever the per-row
  // endpoint already does.
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
      if (!confirm(`Eliminare ${rows.length} aule? `
          + `(${selectedIds.length - rows.length} non sono nella `
          + `pagina corrente e verranno ignorate.)`)) return;
    } else {
      if (!confirm(`Eliminare ${rows.length} aule?`)) return;
    }
    bulkDeleting = true;
    const snapshots = rows.map((r) => _scrubRoomSnapshot(cloneRow(r)));
    let okCount = 0;
    const errors = [];
    try {
      for (const r of rows) {
        try {
          await classroomsSvc.remove(r.id);
          okCount++;
        } catch (e) {
          errors.push(`${r.name}: ${e.message ?? e}`);
        }
      }
      selectedIds = [];
      await listRef.reload();
      await refreshDataset();
      const tone = errors.length ? 'warning' : 'success';
      flash(`${okCount}/${rows.length} aule eliminate`
            + (errors.length ? ` (${errors.length} errori)` : ''),
            tone, {
        ms: 10000,
        action: {
          label: 'Annulla',
          fn: async () => {
            let restored = 0;
            for (const snap of snapshots) {
              try {
                await classroomsSvc.create(snap);
                restored++;
              } catch (e) { console.warn('UNDO create failed', e); }
            }
            await listRef.reload();
            await refreshDataset();
            flash(`Ripristinate ${restored}/${snapshots.length} aule`,
                  restored === snapshots.length ? 'success' : 'warning');
          }
        }
      });
    } finally {
      bulkDeleting = false;
    }
  }

  $: totalIfApplied = (suggested?.n_classes || 0)
    + Number(genCounts.lab_fisica || 0) + Number(genCounts.lab_chimica || 0)
    + Number(genCounts.lab_informatica || 0) + Number(genCounts.lab_linguistico || 0)
    + Number(genCounts.palestra || 0) + Number(genCounts.biblioteca || 0)
    + Number(genCounts.aula_speciale || 0);

  // Inline capacity editing -- 5..100 client-side, backend authoritative.
  const CAPACITY_MIN = 5;
  const CAPACITY_MAX = 100;
  let savingCapacity = new Set();
  async function saveCapacityInline(row, raw) {
    const v = Number(raw);
    if (!Number.isFinite(v) || v < CAPACITY_MIN || v > CAPACITY_MAX) {
      flash(`Capienza deve essere fra ${CAPACITY_MIN} e ${CAPACITY_MAX}`,
            'error');
      await listRef?.reload();
      return;
    }
    if (Number(row.capacity) === v) return;
    savingCapacity = new Set([...savingCapacity, row.id]);
    try {
      await classroomsSvc.update(row.id, { capacity: v });
      row.capacity = v;
      flash('Capienza aggiornata', 'success');
      await refreshDataset();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
      await listRef?.reload();
    } finally {
      savingCapacity = new Set([...savingCapacity].filter(
        (x) => x !== row.id));
    }
  }

  const columns = [
    { key: 'name', label: 'Nome' },
    { key: 'kind', label: 'Tipo' },
    { key: 'capacity', label: 'Capienza' },
    { key: 'multi_class', label: 'Multi-classe',
      render: (r) => r.multi_class ? `max ${r.multi_class_max} (pref ${r.multi_class_pref})` : 'no' },
    { key: 'tags', label: 'Tag', sortable: false,
      render: (r) => (r.tags || []).join(', ') || '-' },
  ];
  const help = {
    fields: ['name', 'kind', 'tipo', 'capacity', 'capienza',
             'multi_class', 'multi_classe', 'tags', 'tag'],
    examples: [
      'tipo = palestra',
      'tipo in [lab_fisica, lab_chimica]',
      'capienza >= 25 AND tipo contains lab',
      'multi_class = 1',
      'has_tag(matematica)',
      'tag(scientifico) AND tipo = standard',
      'unavailable_on(giovedi, 13)'
    ]
  };
</script>

<div class="space-y-4" data-testid="classrooms-page">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Aule</h1>
    <button class="btn ml-auto" on:click={loadSuggested}>Genera aule...</button>
    <button class="btn" on:click={() => (showTagsModal = true)}
            title="Crea, rinomina o elimina i tag delle aule">
      Gestisci tag
    </button>
    <button class="btn-primary" on:click={newRoom}
            data-testid="add-classroom-btn">+ Nuova aula</button>
    <ImportButton entity="classrooms" onDone={() => listRef?.reload()}/>
    <button class="btn !text-xs" on:click={() => (showBulk = true)}
            disabled={selectedIds.length === 0}
            title="Applica un vincolo a tutte le aule selezionate">
      Vincolo collettivo ({selectedIds.length})
    </button>
    <button class="btn-danger !text-xs" on:click={bulkDel}
            disabled={selectedIds.length === 0 || bulkDeleting}
            title="Elimina tutte le aule selezionate (con UNDO)">
      {bulkDeleting ? 'Eliminazione...' : `Elimina selezionati (${selectedIds.length})`}
    </button>
  </div>

  {#if showGenPanel && suggested}
    <div class="card p-5 border-accent-500/40 bg-accent-500/5">
      <div class="flex items-baseline gap-3 mb-3">
        <h2>Parametri generazione aule</h2>
        <span class="text-sm text-ink-500">
          Classi attualmente nel DB: <strong>{suggested.n_classes}</strong>
          - parametri suggeriti compilati di conseguenza
        </span>
        <button class="btn !text-xs !px-2 !py-1 ml-auto" on:click={() => showGenPanel = false}>chiudi</button>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="field"><label>Lab fisica</label><input type="number" min="0" bind:value={genCounts.lab_fisica}/><span class="text-[10px] text-ink-500">{suggested.rules.lab_fisica}</span></div>
        <div class="field"><label>Lab chimica</label><input type="number" min="0" bind:value={genCounts.lab_chimica}/><span class="text-[10px] text-ink-500">{suggested.rules.lab_chimica}</span></div>
        <div class="field"><label>Lab informatica</label><input type="number" min="0" bind:value={genCounts.lab_informatica}/><span class="text-[10px] text-ink-500">{suggested.rules.lab_informatica}</span></div>
        <div class="field"><label>Lab linguistico</label><input type="number" min="0" bind:value={genCounts.lab_linguistico}/><span class="text-[10px] text-ink-500">{suggested.rules.lab_linguistico}</span></div>
        <div class="field"><label>Palestre</label><input type="number" min="0" bind:value={genCounts.palestra}/><span class="text-[10px] text-ink-500">{suggested.rules.palestra}</span></div>
        <div class="field"><label>Biblioteche</label><input type="number" min="0" bind:value={genCounts.biblioteca}/><span class="text-[10px] text-ink-500">{suggested.rules.biblioteca}</span></div>
        <div class="field"><label>Aule speciali</label><input type="number" min="0" bind:value={genCounts.aula_speciale}/><span class="text-[10px] text-ink-500">{suggested.rules.aula_speciale}</span></div>
        <div class="field">
          <label>Aule totali se generate</label>
          <div class="px-2 py-1.5 rounded-md bg-white border border-ink-200 font-semibold">{totalIfApplied}</div>
          <span class="text-[10px] text-ink-500">{suggested.n_classes} standard + extra</span>
        </div>
      </div>
      <div class="mt-3 flex gap-2 items-center">
        <button class="btn-primary" on:click={runGenerate} disabled={busyGen}>
          {busyGen ? 'Generazione in corso...' : 'Genera aule'}
        </button>
        <button class="btn !text-xs" on:click={() => (genCounts = { ...suggested.counts })}>
          Ripristina suggeriti
        </button>
      </div>
    </div>
  {/if}

  <SortableQueryableList
    bind:this={listRef}
    endpoint="/api/classrooms"
    entity="classrooms"
    {columns}
    {help}
    rowKey={(r) => r.id}
    selectable={true}
    bind:selectedIds
    onRowsChange={(rs) => (latestRows = rs)}
    let:row let:columns>
    <td><strong>{row.name}</strong></td>
    <td><span class="pill">{row.kind}</span></td>
    <td class="text-center">
      <input type="number" min={CAPACITY_MIN} max={CAPACITY_MAX}
             value={row.capacity}
             on:change={(e) => saveCapacityInline(row, e.currentTarget.value)}
             on:keydown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
             disabled={savingCapacity.has(row.id)}
             class="w-16 text-center px-1 py-0.5 border border-ink-200 rounded
                    focus:ring-2 focus:ring-emerald-300"
             data-testid="classroom-capacity-inline-input"
             data-classroom-id={row.id}/>
    </td>
    <td class="text-center">
      {#if row.multi_class}max {row.multi_class_max} (pref {row.multi_class_pref}){:else}no{/if}
    </td>
    <td>
      {#if (row.tags || []).length === 0}
        <span class="text-ink-400">-</span>
      {:else}
        <div class="flex flex-wrap gap-0.5">
          {#each row.tags as t (t)}
            <span class="inline-flex items-center px-1 py-px rounded-sm
                         border text-[9px] leading-tight font-medium {tagColor(t)}">#{t}</span>
          {/each}
        </div>
      {/if}
    </td>
    <td class="whitespace-nowrap">
      <button class="btn !text-xs !px-2 !py-1"
              data-testid="classroom-edit-btn"
              data-classroom-id={row.id}
              on:click={() => edit(row)}>Modifica</button>
      <button class="btn-danger !text-xs !px-2 !py-1"
              data-testid="classroom-delete-btn"
              data-classroom-id={row.id}
              on:click={() => del(row)}>Elimina</button>
    </td>
  </SortableQueryableList>
</div>

<BulkApplyModal entity="classrooms" bind:open={showBulk}
                {selectedIds}
                onDone={() => { selectedIds = []; listRef?.reload(); }}/>

<ManageTagsModal bind:open={showTagsModal}
                 service={tagSvc}
                 title="Gestisci tag aule"
                 countField="n_classrooms"
                 countLabelSingular="aula"
                 countLabelPlural="aule"
                 namePlaceholder="es. proiettore"
                 descPlaceholder="Aule con videoproiettore"
                 onClose={() => (showTagsModal = false)}
                 onChanged={async () => { await reloadTags(); listRef?.reload(); }}/>

<Modal open={!!editing} title={editing?._new ? 'Nuova aula' : 'Modifica aula'} onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3" data-testid="classroom-form">
      <div class="field"><label>Nome / codice</label><input bind:value={editing.name} data-testid="classroom-name-input"/></div>
      <div class="field"><label>Tipo</label>
        <select bind:value={editing.kind} data-testid="classroom-kind-select">{#each ROOM_KINDS as k}<option value={k.value}>{k.label}</option>{/each}</select>
      </div>
      <div class="field"><label>Capienza</label><input type="number" min="5" max="100"
             bind:value={editing.capacity} data-testid="classroom-capacity-input"/></div>
      <div class="field"><label>Note</label><input bind:value={editing.notes}/></div>
      <div class="field"><label>Plesso</label>
        <select bind:value={editing.plesso_id} data-testid="classroom-plesso-select">
          <option value={null}>(nessuno)</option>
          {#each (plessi || []) as p}
            <option value={p.id}>{p.code} - {p.name}</option>
          {/each}
        </select>
      </div>
    </div>

    <div class="mt-4 grid grid-cols-3 gap-3 items-end">
      <label class="flex gap-2 text-sm"><input type="checkbox" bind:checked={editing.multi_class}/> Multi-classe</label>
      <div class="field"><label>Max classi simultanee (HARD)</label><input type="number" bind:value={editing.multi_class_max}/></div>
      <div class="field"><label>PREFERRED (SOFT)</label><input type="number" bind:value={editing.multi_class_pref}/></div>
      <div class="field"><label>Peso preferenza concorrenza</label><input type="number" bind:value={editing.multi_class_pref_weight}/></div>
    </div>

    <div class="mt-4 field">
      <div class="flex items-baseline gap-3 mb-1">
        <label class="!mb-0">Tag</label>
        <span class="text-[11px] text-ink-500">
          Etichette libere usabili dal DSL (es. <code>"matematica" in l.classroom.tags</code>).
          I nuovi tag vengono creati automaticamente al salvataggio.
        </span>
        <button type="button" class="btn !text-xs !px-2 !py-0.5 ml-auto"
                on:click={() => (showTagsModal = true)}>Gestisci tag...</button>
      </div>
      <TagPicker
        value={editing.tags || []}
        suggestions={allTagNames}
        onChange={onTagsChange}/>
    </div>

    <div class="mt-4">
      <h3 class="mb-2">Materie ammesse</h3>
      <table class="tbl">
        <thead><tr><th>Materia</th><th>Peso</th><th>HARD?</th><th></th></tr></thead>
        <tbody>
          {#each editing.subject_prefs as s, i}
            <tr>
              <td>
                <input list="sub-{i}" bind:value={s.subject} class="w-full px-2 py-1 border border-ink-200 rounded"/>
                <datalist id="sub-{i}">{#each allSubjects as ss}<option value={ss}/>{/each}</datalist>
              </td>
              <td class="w-24"><input type="number" bind:value={s.weight} class="w-full px-2 py-1 border border-ink-200 rounded"/></td>
              <td class="w-20 text-center"><input type="checkbox" bind:checked={s.required}/></td>
              <td><button class="btn-danger !text-xs !px-2 !py-1" on:click={() => delSubjectPref(i)}>x</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <button class="btn !text-xs !px-2 !py-1 mt-2" on:click={addSubjectPref}>+ Materia</button>
    </div>

    <div class="mt-4">
      <h3 class="mb-2">Classi affezionate</h3>
      <table class="tbl">
        <thead><tr><th>Classe</th><th>Peso</th><th>Home?</th><th></th></tr></thead>
        <tbody>
          {#each editing.class_prefs as c, i}
            <tr>
              <td>
                <input list="cls-{i}" bind:value={c.class_name} class="w-full px-2 py-1 border border-ink-200 rounded"/>
                <datalist id="cls-{i}">{#each allClasses as cn}<option value={cn}/>{/each}</datalist>
              </td>
              <td class="w-24"><input type="number" bind:value={c.weight} class="w-full px-2 py-1 border border-ink-200 rounded"/></td>
              <td class="w-20 text-center"><input type="checkbox" bind:checked={c.is_home}/></td>
              <td><button class="btn-danger !text-xs !px-2 !py-1" on:click={() => delClassPref(i)}>x</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <button class="btn !text-xs !px-2 !py-1 mt-2" on:click={addClassPref}>+ Classe</button>
    </div>

    <div class="mt-4">
      <WeeklyCalendarView
        title="Disponibilita oraria dell'aula"
        value={editing.unavailability}
        onChange={onMatrixChange}/>
    </div>

    <div class="mt-4">
      <LogicalUnavailabilitiesPanel entityType="classrooms" entityId={editing.id ?? null}/>
    </div>

    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)}
              data-testid="classroom-cancel-btn">Annulla</button>
      <button class="btn-primary" on:click={save}
              data-testid="classroom-save-btn">Salva</button>
    </div>
  {/if}
</Modal>
