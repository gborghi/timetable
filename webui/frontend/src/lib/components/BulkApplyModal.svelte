<script>
  // Bulk-apply panel: user picks an action and a payload, hits "Verifica
  // conflitti" to dry-run, then "Applica". On conflicts the user picks
  // override or skip. Self-contained: invokes /api/bulk/{entity}/...
  //
  // Props:
  //   entity:       'teachers' | 'classes' | 'classrooms'
  //   open:         boolean, two-way bound
  //   selectedIds:  array of ids to operate on
  //   onDone:       callback after successful apply

  import Modal from './Modal.svelte';
  import { api } from '../api.js';
  import { flash } from '../stores.js';

  export let entity = 'teachers';
  export let open = false;
  export let selectedIds = [];
  export let onDone = () => {};

  let action = 'add_logical';
  let dryRun = null;     // { candidates, conflicts, n_targets }
  let onConflict = 'skip';
  let busy = false;

  // payload state per action
  let exprText = '';
  // 'hard' | 'soft' | 'preferred'
  let logicalKind = 'hard';
  let softPenalty = 100;

  let fieldName = '';
  let fieldValue = '';
  let fieldType = 'string';

  let unavailDay = 1;
  let unavailHour = 1;
  // 'hard' | 'soft' | 'preferred'
  let unavailState = 'hard';
  let unavailReason = '';

  const FIELD_PRESETS = {
    teachers: [
      { field: 'free_day', label: 'free_day (giorno libero)', type: 'string',
        options: ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'] },
      { field: 'max_hours', label: 'max_hours', type: 'number' },
      { field: 'max_consecutive', label: 'max_consecutive', type: 'number' },
      { field: 'pref_no_buchi_weight', label: 'peso anti-buchi (SOFT)', type: 'number' },
    ],
    classes: [
      { field: 'hard_no_holes', label: 'no buchi (HARD)', type: 'bool' },
      { field: 'hard_max_6_per_day', label: 'max 6 ore/giorno (HARD)', type: 'bool' },
      { field: 'hard_dual_math', label: 'doppia ora Matematica', type: 'bool' },
      { field: 'hard_dual_italian', label: 'doppia ora Italiano', type: 'bool' },
      { field: 'soft_minimize_sixth_weight', label: 'peso 6a ora (SOFT)', type: 'number' },
    ],
    classrooms: [
      { field: 'kind', label: 'kind (tipo)', type: 'string',
        options: ['standard','lab_chimica','lab_fisica','lab_informatica','lab_linguistico','palestra','biblioteca','aula_speciale'] },
      { field: 'capacity', label: 'capacity', type: 'number' },
      { field: 'multi_class', label: 'multi_class', type: 'bool' },
    ],
  };

  $: presets = FIELD_PRESETS[entity] || [];
  $: selectedPreset = presets.find((p) => p.field === fieldName);

  function buildPayload() {
    if (action === 'add_logical') {
      const pen = Number(softPenalty);
      let payload;
      if (logicalKind === 'hard')
        payload = { is_hard: true, soft_penalty: 100 };
      else if (logicalKind === 'soft')
        payload = { is_hard: false, soft_penalty: Math.abs(pen) };
      else
        payload = { is_hard: false, soft_penalty: -Math.abs(pen) };
      return { expression: exprText.trim(), ...payload };
    }
    if (action === 'set_field') {
      let v = fieldValue;
      if (fieldType === 'number') v = Number(v);
      else if (fieldType === 'bool') v = (v === true || v === 'true' || v === 1 || v === '1');
      return { field: fieldName, value: v };
    }
    if (action === 'add_unavailability') {
      const pen = Number(softPenalty);
      let signed_pen = pen;
      if (unavailState === 'soft' && signed_pen < 0) signed_pen = Math.abs(signed_pen);
      if (unavailState === 'preferred' && signed_pen > 0) signed_pen = -signed_pen;
      return { day: Number(unavailDay), hour: Number(unavailHour),
               state: unavailState,
               soft_penalty: signed_pen,
               reason: unavailReason || null };
    }
    return {};
  }

  async function verify() {
    if (selectedIds.length === 0) {
      flash('Nessuna riga selezionata', 'error'); return;
    }
    busy = true;
    try {
      const payload = buildPayload();
      dryRun = await api.post(`/api/bulk/${entity}/dry-run`, {
        entity_ids: selectedIds, action, payload, on_conflict: 'dry_run'
      });
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally { busy = false; }
  }

  async function apply() {
    if (selectedIds.length === 0) {
      flash('Nessuna riga selezionata', 'error'); return;
    }
    busy = true;
    try {
      const payload = buildPayload();
      const res = await api.post(`/api/bulk/${entity}/apply`, {
        entity_ids: selectedIds, action, payload, on_conflict: onConflict
      });
      flash(
        `Applicate ${res.n_applied}, ${res.n_overridden} con override, ` +
        `${res.n_skipped} skip`,
        res.errors?.length ? 'warning' : 'success'
      );
      onDone(res);
      open = false;
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally { busy = false; }
  }

  function reset() {
    dryRun = null;
  }

  $: if (open) { dryRun = null; }
</script>

<Modal {open} title="Operazione collettiva su {selectedIds.length} {entity}"
       onClose={() => (open = false)}>
  <div class="space-y-4">
    <div class="flex flex-wrap gap-2 items-center">
      <label class="text-sm">Azione:</label>
      <select bind:value={action} on:change={reset}
              class="px-2 py-1 border border-ink-200 rounded">
        <option value="add_logical">Aggiungi vincolo logico</option>
        <option value="set_field">Imposta un campo</option>
        <option value="add_unavailability">Aggiungi cella di indisponibilita</option>
      </select>
    </div>

    {#if action === 'add_logical'}
      <div class="space-y-2">
        <label class="text-xs">Espressione (vedi guida sintassi)</label>
        <input class="w-full font-mono text-sm px-2 py-1 border border-ink-200 rounded"
               placeholder="es. lun8 AND lun9"
               bind:value={exprText} on:input={reset}/>
        <div class="flex gap-3 text-xs items-center flex-wrap">
          <label class="flex gap-1 items-center">
            <input type="radio" bind:group={logicalKind} value="hard"/>
            <span class="pill-red !text-[10px]">HARD</span>
          </label>
          <label class="flex gap-1 items-center">
            <input type="radio" bind:group={logicalKind} value="soft"/>
            <span class="pill-amber !text-[10px]">SOFT</span>
          </label>
          <label class="flex gap-1 items-center">
            <input type="radio" bind:group={logicalKind} value="preferred"/>
            <span class="pill-blue !text-[10px]">PREFERITO</span>
          </label>
          {#if logicalKind !== 'hard'}
            <label class="flex gap-1 items-center">
              {logicalKind === 'soft' ? 'Penalita' : 'Bonus'}:
              <input type="number" min="0"
                     class="w-16 px-1 py-0.5 border border-ink-200 rounded"
                     bind:value={softPenalty}/>
            </label>
          {/if}
        </div>
      </div>

    {:else if action === 'set_field'}
      <div class="space-y-2">
        <label class="text-xs">Campo</label>
        <select bind:value={fieldName} on:change={() => {
            const p = presets.find((p) => p.field === fieldName);
            if (p) { fieldType = p.type; fieldValue = (p.type === 'bool' ? false : ''); }
            reset();
          }}
          class="px-2 py-1 border border-ink-200 rounded">
          <option value="">-- scegli --</option>
          {#each presets as p}
            <option value={p.field}>{p.label}</option>
          {/each}
        </select>

        {#if selectedPreset}
          <label class="text-xs block">Valore</label>
          {#if selectedPreset.type === 'bool'}
            <label class="flex gap-2 text-sm">
              <input type="checkbox" bind:checked={fieldValue}/>
              {fieldValue ? 'true' : 'false'}
            </label>
          {:else if selectedPreset.options}
            <select bind:value={fieldValue} on:change={reset}
                    class="px-2 py-1 border border-ink-200 rounded">
              {#each selectedPreset.options as opt}
                <option value={opt}>{opt}</option>
              {/each}
            </select>
          {:else if selectedPreset.type === 'number'}
            <input type="number" bind:value={fieldValue} on:input={reset}
                   class="w-32 px-2 py-1 border border-ink-200 rounded"/>
          {:else}
            <input bind:value={fieldValue} on:input={reset}
                   class="w-64 px-2 py-1 border border-ink-200 rounded"/>
          {/if}
        {/if}
      </div>

    {:else if action === 'add_unavailability'}
      <div class="grid grid-cols-2 gap-3">
        <label class="text-xs">Giorno (1=Lun .. 6=Sab)</label>
        <input type="number" min="1" max="6" bind:value={unavailDay}
               class="px-2 py-1 border border-ink-200 rounded" on:input={reset}/>
        <label class="text-xs">Ora (1..6 ordinale, oppure 8..13)</label>
        <input type="number" min="1" max="13" bind:value={unavailHour}
               class="px-2 py-1 border border-ink-200 rounded" on:input={reset}/>
        <label class="text-xs">Stato</label>
        <select bind:value={unavailState} class="px-2 py-1 border border-ink-200 rounded">
          <option value="hard">HARD (rosso)</option>
          <option value="soft">SOFT (giallo, penalita +)</option>
          <option value="preferred">PREFERITO (blu, bonus -)</option>
        </select>
        {#if unavailState === 'soft' || unavailState === 'preferred'}
          <label class="text-xs">{unavailState === 'soft' ? 'Penalita' : 'Bonus'}</label>
          <input type="number" min="0" bind:value={softPenalty}
                 class="px-2 py-1 border border-ink-200 rounded"/>
        {/if}
        <label class="text-xs">Motivo (opzionale)</label>
        <input bind:value={unavailReason}
               class="px-2 py-1 border border-ink-200 rounded"/>
      </div>
    {/if}

    <div class="border-t border-ink-200 pt-3 space-y-3">
      <div class="flex flex-wrap gap-2 items-center">
        <button class="btn" on:click={verify} disabled={busy}>
          1) Verifica conflitti
        </button>
        {#if dryRun}
          <span class="text-xs text-ink-500">
            ({dryRun.candidates.length} ok / {dryRun.conflicts.length} in conflitto)
          </span>
        {/if}
      </div>

      {#if dryRun && dryRun.conflicts.length > 0}
        <div class="card !shadow-none p-2 text-xs bg-amber-50 border-amber-300">
          <strong>Conflitti rilevati ({dryRun.conflicts.length}):</strong>
          <ul class="list-disc ml-5 max-h-32 overflow-auto">
            {#each dryRun.conflicts as c}
              <li><strong>{c.name}</strong>: {c.reason}</li>
            {/each}
          </ul>
        </div>
        <label class="text-xs flex gap-2 items-center">
          <input type="radio" bind:group={onConflict} value="skip"/>
          Salta i {dryRun.conflicts.length} in conflitto, applica solo
          ai {dryRun.candidates.length} liberi
        </label>
        <label class="text-xs flex gap-2 items-center">
          <input type="radio" bind:group={onConflict} value="override"/>
          Override: forza l'applicazione anche sui conflittuali
        </label>
      {/if}

      {#if dryRun}
        <div class="flex gap-2">
          <button class="btn-primary" on:click={apply} disabled={busy}>
            2) Applica
          </button>
          <button class="btn" on:click={() => (open = false)} disabled={busy}>
            Annulla
          </button>
        </div>
      {/if}
    </div>
  </div>
</Modal>
