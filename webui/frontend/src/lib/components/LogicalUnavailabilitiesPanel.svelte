<script>
  // Reusable panel for logical (disjunctive) unavailability constraints.
  //
  // Props:
  //   entityType: 'teachers' | 'classes' | 'classrooms'
  //   entityId:   int | null      (when null the panel is in "draft" mode
  //                                and shows a hint to save the entity first)
  //
  // The panel always reads/writes via REST; it is independent of the
  // parent's own form state. It calls onChange(rules[]) whenever the
  // backend list updates (parent can use it for counters).

  import { api } from '../api.js';
  import { flash } from '../stores.js';

  export let entityType = 'teachers';
  export let entityId = null;
  export let onChange = (_rules) => {};

  let rules = [];
  let draftExpr = '';
  let draftIsHard = true;
  let draftPenalty = 100;
  let validateInfo = null;     // {ok, pretty?, error?}
  let editingId = null;        // id being edited
  let busy = false;
  let showHelp = false;

  $: base = entityId ? `/api/${entityType}/${entityId}/logical-unavailabilities` : '';

  async function reload() {
    if (!entityId) { rules = []; return; }
    try {
      rules = await api.get(base);
      onChange(rules);
    } catch (e) {
      flash('Errore caricando vincoli logici: ' + e.message, 'error');
    }
  }

  // re-load whenever the entity id changes (e.g. parent opens a different one)
  $: if (entityId) reload();

  async function validate() {
    try {
      validateInfo = await api.post('/api/logic/validate', { expression: draftExpr });
    } catch (e) {
      validateInfo = { ok: false, error: e.message };
    }
  }

  async function add() {
    if (!entityId) {
      flash('Salva prima la scheda per poter aggiungere vincoli logici.', 'error');
      return;
    }
    if (!draftExpr.trim()) return;
    busy = true;
    try {
      const payload = {
        expression: draftExpr,
        is_hard: draftIsHard,
        soft_penalty: Number(draftPenalty)
      };
      if (editingId) {
        await api.put(`${base}/${editingId}`, payload);
        flash('Vincolo aggiornato', 'success');
      } else {
        await api.post(base, payload);
        flash('Vincolo aggiunto', 'success');
      }
      draftExpr = '';
      validateInfo = null;
      editingId = null;
      await reload();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    } finally {
      busy = false;
    }
  }

  function startEdit(r) {
    editingId = r.id;
    draftExpr = r.expression;
    draftIsHard = r.is_hard;
    draftPenalty = r.soft_penalty;
    validateInfo = null;
  }

  function cancelEdit() {
    editingId = null;
    draftExpr = '';
    validateInfo = null;
  }

  async function del(r) {
    if (!confirm('Eliminare questo vincolo?\n' + r.pretty)) return;
    try {
      await api.del(`${base}/${r.id}`);
      flash('Vincolo eliminato', 'success');
      await reload();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function updatePenalty(r, ev) {
    const v = Number(ev.target.value);
    if (!Number.isFinite(v) || v < 0) return;
    try {
      await api.put(`${base}/${r.id}`, {
        expression: r.expression,
        is_hard: r.is_hard,
        soft_penalty: v
      });
      await reload();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function toggleHard(r) {
    try {
      await api.put(`${base}/${r.id}`, {
        expression: r.expression,
        is_hard: !r.is_hard,
        soft_penalty: r.soft_penalty
      });
      await reload();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  const examples = {
    teachers: [
      'lun8 AND lun9',
      '(lun8 AND lun9) OR (mar8 AND mar9)',
      'gio11 OR gio12 OR gio13',
      'NOT (mer3 AND mer4)'
    ],
    classes: [
      'mer4 AND mer5 AND mer6',
      '(mer4 AND mer5) OR (gio4 AND gio5)'
    ],
    classrooms: [
      'gio4 AND gio5 AND gio6',
      '(lun13 AND mar13)'
    ]
  };
</script>

<div class="card p-4 space-y-3">
  <div class="flex items-baseline justify-between">
    <h3 class="!text-base">Vincoli di indisponibilita logica</h3>
    <button class="btn !text-xs !px-2 !py-1" on:click={() => (showHelp = !showHelp)}>?  guida sintassi</button>
  </div>
  <p class="text-xs text-ink-500">
    Esprimi vincoli "uno tra X e Y deve essere libero" come espressioni
    con AND / OR / NOT su slot. Il solver decide quale ramo onorare.
  </p>

  {#if showHelp}
    <div class="card !shadow-none p-3 text-xs space-y-2 bg-ink-50">
      <div><strong>Slot:</strong> <code>&lt;giorno&gt;&lt;ora&gt;</code> con
        giorno in <code>lun mar mer gio ven sab</code>
        (anche <code>lunedi monday Lun</code>) e ora in 1..6 (ordinale, 1=8:00)
        oppure 8..13 (assoluta).
      </div>
      <div><strong>Operatori:</strong>
        <code>AND</code>, <code>OR</code>, <code>NOT</code>, parentesi.
        Anche <code>&amp;</code>, <code>|</code>, <code>!</code> sono accettati.
      </div>
      <div>
        <strong>Esempi {entityType}:</strong>
        <ul class="list-disc ml-5">
          {#each (examples[entityType] || []) as ex}
            <li><code class="cursor-pointer underline" on:click={() => { draftExpr = ex; }}>{ex}</code></li>
          {/each}
        </ul>
      </div>
    </div>
  {/if}

  <!-- list -->
  {#if rules.length}
    <table class="tbl">
      <thead>
        <tr>
          <th>Espressione (DNF normalizzata)</th>
          <th>Tipo</th>
          <th>Penalita</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#each rules as r}
          <tr>
            <td class="text-xs">
              <code>{r.pretty}</code>
              <div class="text-ink-400 text-[10px]">orig: <code>{r.expression}</code></div>
            </td>
            <td>
              <button class="text-xs"
                on:click={() => toggleHard(r)}
                title="click per togglare HARD/SOFT">
                {#if r.is_hard}
                  <span class="pill-red">HARD</span>
                {:else}
                  <span class="pill-amber">SOFT</span>
                {/if}
              </button>
            </td>
            <td class="w-28">
              {#if !r.is_hard}
                <input type="number" min="0" class="w-20 px-1.5 py-0.5 border border-ink-200 rounded text-xs"
                  value={r.soft_penalty}
                  on:change={(e) => updatePenalty(r, e)}/>
              {:else}
                <span class="text-xs text-ink-400">-</span>
              {/if}
            </td>
            <td class="whitespace-nowrap">
              <button class="btn !text-xs !px-2 !py-1" on:click={() => startEdit(r)}>Modifica</button>
              <button class="btn-danger !text-xs !px-2 !py-1" on:click={() => del(r)}>Elimina</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else if entityId}
    <p class="text-xs text-ink-400 italic">Nessun vincolo logico per questa entita.</p>
  {:else}
    <p class="text-xs text-amber-700">
      Salva prima la scheda per poter aggiungere vincoli logici (servono un id).
    </p>
  {/if}

  <!-- form -->
  <div class="border-t border-ink-200 pt-3 space-y-2">
    <div class="text-xs font-semibold">
      {editingId ? 'Modifica vincolo #' + editingId : 'Nuovo vincolo'}
    </div>
    <div class="flex gap-2 flex-wrap items-end">
      <div class="field flex-1 min-w-64">
        <label>Espressione</label>
        <input class="font-mono text-sm"
          placeholder="es. (lun8 AND lun9) OR (mar8 AND mar9)"
          bind:value={draftExpr}
          on:input={() => (validateInfo = null)}
          on:keydown={(e) => { if (e.key === 'Enter') validate(); }}/>
      </div>
      <button class="btn !text-xs" on:click={validate}>Verifica sintassi</button>
      <label class="flex items-center gap-1 text-xs">
        <input type="radio" bind:group={draftIsHard} value={true}/> HARD
      </label>
      <label class="flex items-center gap-1 text-xs">
        <input type="radio" bind:group={draftIsHard} value={false}/> SOFT
      </label>
      <div class="field" class:opacity-50={draftIsHard}>
        <label>Penalita SOFT</label>
        <input type="number" class="w-24" disabled={draftIsHard} bind:value={draftPenalty}/>
      </div>
      <button class="btn-primary" on:click={add} disabled={busy || !draftExpr.trim()}>
        {editingId ? 'Salva modifica' : 'Aggiungi'}
      </button>
      {#if editingId}
        <button class="btn !text-xs" on:click={cancelEdit}>Annulla</button>
      {/if}
    </div>
    {#if validateInfo}
      <div class="text-xs"
        class:text-emerald-700={validateInfo.ok}
        class:text-red-700={!validateInfo.ok}>
        {#if validateInfo.ok}
          OK: <code>{validateInfo.pretty}</code>
          ({validateInfo.clauses.length} clausole)
        {:else}
          Errore di sintassi: {validateInfo.error}
        {/if}
      </div>
    {/if}
  </div>
</div>
