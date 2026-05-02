<script>
  /**
   * Editor + live-validate flow for the General DSL constraints
   * (POST /api/constraints/general). Separate from the structured
   * 4-step NewConstraintModal because the DSL path is text-driven
   * and needs a different layout: big editor, debounced validation,
   * inline errors, example library.
   */
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';

  export let open = false;
  export let onClose = () => { open = false; };
  export let onCreated = () => {};
  // When the modal is opened from a specific entity card (Docente,
  // Classe, ...) the parent passes scope + owner_id so the DSL is
  // tagged on the right entity. Default scope=global means a
  // school-wide rule.
  export let scope = 'global';
  export let ownerId = null;
  export let scopeLabel = '';   // optional human label, e.g. "Docente Borghi"

  let expression = '';
  let label = '';
  let level = 'hard';
  let weight = 100;
  let validateResult = null;
  let busy = false;
  let validateTimer = null;

  $: if (open) {
    expression = '';
    label = '';
    level = 'hard';
    weight = 100;
    validateResult = null;
    busy = false;
  }

  // Debounced live-validate: 500ms after the user stops typing,
  // POST /api/constraints/general/validate and surface errors.
  function onExpressionChange() {
    if (validateTimer) clearTimeout(validateTimer);
    validateTimer = setTimeout(doValidate, 500);
  }
  async function doValidate() {
    if (!expression.trim()) {
      validateResult = null;
      return;
    }
    try {
      validateResult = await api.post(
        '/api/constraints/general/validate',
        { expression, scope, owner_id: ownerId, level, weight,
          label },
      );
    } catch (e) {
      validateResult = { ok: false, errors: [e.message || String(e)],
                          warnings: [], n_atoms: 0 };
    }
  }

  async function submit() {
    if (!expression.trim()) {
      flash('Espressione vuota.', 'error');
      return;
    }
    busy = true;
    try {
      const r = await api.post('/api/constraints/general', {
        expression, label: label || null,
        level, weight: Number(weight) || 100,
        scope, owner_id: ownerId,
      });
      flash(`Vincolo DSL creato: #${r.id}`, 'success');
      onCreated();
      onClose();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    } finally {
      busy = false;
    }
  }

  // Cookbook -- example expressions the user can click to fill the
  // editor.
  const EXAMPLES = [
    {
      title: 'Borghi mai in 1A alla 6a ora',
      text: 'forall l in lessons where l.teacher == Borghi and l.class == 1A: l.hour != 6',
    },
    {
      title: 'Lab Fisica: una sola lezione per slot',
      text: 'forall s in slots: count l in lessons where l.classroom == LabFisica and l.day == s.day and l.hour == s.hour: l <= 1',
    },
    {
      title: 'Borghi: max 4 ore al giorno totali',
      text: 'forall d in days: count l in lessons where l.teacher == Borghi and l.day == d.index: l <= 4',
    },
    {
      title: 'Implicazione fra cattedre',
      text: '(exists l in lessons: l.teacher == X and l.class == Y) => (exists l in lessons: l.teacher == Z and l.class == W)',
    },
    {
      title: 'Curriculum-aware: max 2 ore di Mate al di per Scientifico',
      text: 'forall d in days: count l in lessons where l.subject == Matematica and l.day == d.index and l.class.curriculum == Scientifico: l <= 2',
    },
  ];

  function loadExample(text) {
    expression = text;
    onExpressionChange();
  }
</script>

<Modal {open} title={`Nuovo vincolo DSL${scopeLabel ? ' - ' + scopeLabel : ''}`}
       {onClose}>
  <div class="space-y-3">
    <p class="text-xs text-ink-500">
      Esprimi un vincolo HARD/SOFT come combinazione logica di
      predicati sul modello. Sintassi: <code>forall / exists / count
      ... in ... [where ...]: ...</code> con operatori
      <code>== != &lt; &lt;= &gt; &gt;= and or not =&gt;</code>. Sorgenti:
      lessons / assignments / teachers / classes / classrooms /
      subjects / curricula / groups / days / hours / slots.
      Vedere <code>docs/general_dsl.md</code> per la grammatica
      completa.
    </p>

    <!-- Examples -->
    <details>
      <summary class="cursor-pointer text-xs text-accent-500
                       hover:underline">
        ⓘ Esempi (clicca per riempire l'editor)
      </summary>
      <div class="text-xs space-y-1 mt-2 pl-2">
        {#each EXAMPLES as ex}
          <div>
            <button class="text-accent-500 hover:underline text-left"
                    on:click={() => loadExample(ex.text)}>
              {ex.title}
            </button>
            <code class="block text-[10px] text-ink-500 ml-2 break-all">
              {ex.text}
            </code>
          </div>
        {/each}
      </div>
    </details>

    <div class="field">
      <label>Espressione DSL *</label>
      <textarea class="w-full h-28 font-mono text-xs px-2 py-1.5
                       rounded-md border border-ink-200"
                bind:value={expression}
                on:input={onExpressionChange}
                placeholder="forall l in lessons where l.teacher == Borghi: l.hour != 6"></textarea>
    </div>

    <!-- Live validation feedback -->
    {#if validateResult}
      {#if validateResult.ok}
        <div class="text-xs text-emerald-700 bg-emerald-50 border
                    border-emerald-300 rounded p-2">
          ✓ Sintassi valida ({validateResult.n_atoms} atomi).
          {#if validateResult.warnings?.length}
            <ul class="list-disc list-inside mt-1 text-amber-700">
              {#each validateResult.warnings as w}<li>{w}</li>{/each}
            </ul>
          {/if}
        </div>
      {:else}
        <div class="text-xs text-red-700 bg-red-50 border
                    border-red-300 rounded p-2">
          <strong>Errori:</strong>
          <ul class="list-disc list-inside">
            {#each validateResult.errors as e}<li>{e}</li>{/each}
          </ul>
        </div>
      {/if}
    {/if}

    <div class="grid grid-cols-3 gap-3">
      <div class="field">
        <label>Livello</label>
        <select bind:value={level}>
          <option value="hard">🟥 HARD</option>
          <option value="soft">🟨 SOFT (penalty)</option>
          <option value="preferred">🟦 PREFERITO (bonus)</option>
          <option value="enforced">🟩 ENFORCED</option>
        </select>
      </div>
      {#if level === 'soft' || level === 'preferred'}
        <div class="field">
          <label>Peso</label>
          <input type="number" bind:value={weight}/>
        </div>
      {/if}
      <div class="field {level === 'soft' || level === 'preferred' ? '' : 'col-span-2'}">
        <label>Etichetta (opzionale)</label>
        <input bind:value={label} placeholder="es. lab fisica capienza"/>
      </div>
    </div>

    <div class="text-[10px] text-ink-500">
      Lo scope di questo vincolo: <strong>{scope}</strong>
      {#if ownerId} (owner_id={ownerId}){/if}.
      Le violazioni HARD vengono evidenziate in
      <em>Feasibility Check</em> e bloccate dal modello a runtime;
      le SOFT contribuiscono allo score globale di Phase B.
    </div>

    <div class="flex justify-end gap-2 pt-3 border-t border-ink-100">
      <button class="btn" on:click={onClose} disabled={busy}>Annulla</button>
      <button class="btn-primary" on:click={submit}
              disabled={busy || !expression.trim()
                          || (validateResult && !validateResult.ok)}>
        {busy ? '...' : 'Crea vincolo'}
      </button>
    </div>
  </div>
</Modal>
