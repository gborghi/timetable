<script>
  /**
   * Plessi (school sites) management.
   *
   * Three sections:
   *   1. Plessi: CRUD on the Plesso table.
   *   2. Regole di spostamento: PlessoCommutingRule between pairs
   *      of plessi keyed by entity_kind (teacher/class/group),
   *      with optional per-entity override.
   *   3. Regole entita': PlessoEntityPolicy (single_per_day,
   *      single_total, any) for individual teachers / classes.
   *
   * The bottom of the page shows a "config OK" banner driven by
   * GET /api/plessi/validate -- the same validation invoked
   * by every solver run. Editing is allowed even with violations
   * pending (so the user can fix them iteratively); the banner
   * just surfaces the live state.
   */
  import { onMount } from 'svelte';
  import * as api from '$lib/api';
  import { flash } from '$lib/stores';

  let plessi = [];
  let rules = [];
  let policies = [];
  let validation = { ok: true, violations: [] };

  let teachers = [];
  let classes = [];
  let groups = [];

  // CRUD edit state for each section.
  let editingPlesso = null;     // { id?, name, code, address, notes }
  let editingRule = null;
  let editingPolicy = null;

  let filterRuleKind = 'all';
  let filterPolicyKind = 'all';

  async function refreshAll() {
    plessi = await api.get('/api/plessi');
    rules = await api.get('/api/plessi/commuting-rules');
    policies = await api.get('/api/plessi/entity-policies');
    validation = await api.get('/api/plessi/validate');
  }

  async function refreshAuxiliary() {
    try {
      teachers = (await api.get('/api/teachers')) || [];
    } catch { teachers = []; }
    try {
      classes = (await api.get('/api/classes')) || [];
    } catch { classes = []; }
    try {
      groups = (await api.get('/api/groups')) || [];
    } catch { groups = []; }
  }

  onMount(async () => {
    await refreshAuxiliary();
    await refreshAll();
  });

  // ---------- Plesso CRUD ----------

  function newPlesso() {
    editingPlesso = { name: '', code: '', address: '', notes: '' };
  }
  function editPlesso(p) { editingPlesso = { ...p }; }
  async function savePlesso() {
    try {
      if (editingPlesso.id) {
        await api.put(`/api/plessi/${editingPlesso.id}`, editingPlesso);
      } else {
        await api.post('/api/plessi', editingPlesso);
      }
      editingPlesso = null;
      await refreshAll();
      flash('Plesso salvato', 'success');
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }
  async function deletePlesso(p) {
    if (!confirm(`Elimina plesso "${p.name}"?`)) return;
    try {
      await api.del(`/api/plessi/${p.id}`);
      await refreshAll();
      flash('Plesso eliminato', 'success');
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  // ---------- Commuting rules CRUD ----------

  function newRule() {
    editingRule = {
      from_plesso_id: plessi[0]?.id || null,
      to_plesso_id: plessi[1]?.id || plessi[0]?.id || null,
      entity_kind: 'teacher',
      entity_id: null,
      min_gap_hours: 0,
      allowed_break_only: false,
      break_start_hour: null,
      break_end_hour: null,
      symmetric: true,
      priority: 0,
      notes: '',
    };
  }
  function editRule(r) { editingRule = { ...r }; }
  async function saveRule() {
    try {
      if (editingRule.id) {
        await api.put(`/api/plessi/commuting-rules/${editingRule.id}`,
                       editingRule);
      } else {
        await api.post('/api/plessi/commuting-rules', editingRule);
      }
      editingRule = null;
      await refreshAll();
      flash('Regola salvata', 'success');
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }
  async function deleteRule(r) {
    if (!confirm(`Elimina regola #${r.id}?`)) return;
    try {
      await api.del(`/api/plessi/commuting-rules/${r.id}`);
      await refreshAll();
      flash('Regola eliminata', 'success');
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  // ---------- Entity policies CRUD ----------

  function newPolicy() {
    editingPolicy = {
      entity_kind: 'teacher',
      entity_id: null,
      policy: 'any',
      plesso_id: null,
      priority: 0,
      notes: '',
    };
  }
  function editPolicy(p) { editingPolicy = { ...p }; }
  async function savePolicy() {
    try {
      if (editingPolicy.id) {
        await api.put(`/api/plessi/entity-policies/${editingPolicy.id}`,
                       editingPolicy);
      } else {
        await api.post('/api/plessi/entity-policies', editingPolicy);
      }
      editingPolicy = null;
      await refreshAll();
      flash('Policy salvata', 'success');
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }
  async function deletePolicy(p) {
    if (!confirm(`Elimina policy #${p.id}?`)) return;
    try {
      await api.del(`/api/plessi/entity-policies/${p.id}`);
      await refreshAll();
      flash('Policy eliminata', 'success');
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  // ---------- Helpers ----------

  function plessoNameOf(id) {
    const p = plessi.find(p => p.id === id);
    return p ? `${p.code} - ${p.name}` : `#${id}`;
  }
  function entityNameOf(kind, id) {
    if (id === null || id === undefined) return '(tutti)';
    const list =
      kind === 'teacher' ? teachers
      : kind === 'class' ? classes
      : kind === 'group' ? groups : [];
    const e = list.find(x => x.id === id);
    return e ? e.name : `#${id}`;
  }

  $: filteredRules = filterRuleKind === 'all'
      ? rules
      : rules.filter(r => r.entity_kind === filterRuleKind);
  $: filteredPolicies = filterPolicyKind === 'all'
      ? policies
      : policies.filter(p => p.entity_kind === filterPolicyKind);
  $: entityListForKind = (k) => (
      k === 'teacher' ? teachers
      : k === 'class' ? classes
      : k === 'group' ? groups : []
  );
</script>

<div class="container mx-auto p-4 space-y-6" data-testid="plessi-page">
  <h1 class="text-2xl font-bold">Plessi</h1>
  <p class="text-sm text-ink-600 max-w-3xl">
    Gestisci le sedi fisiche dell'istituto (Sede Centrale,
    succursali, plessi distaccati), le regole di spostamento tra
    coppie di plessi (commuting) e le policy globali per docenti
    e classi (uno stesso plesso al giorno o uno stesso plesso
    in tutta la settimana).
  </p>

  <!-- Validation banner -->
  {#if !validation.ok}
    <div class="border border-rose-300 bg-rose-50 rounded p-3">
      <strong class="text-rose-800">Configurazione incoerente</strong>
      <ul class="list-disc pl-6 text-sm text-rose-800 mt-2">
        {#each validation.violations as v}
          <li>{v}</li>
        {/each}
      </ul>
    </div>
  {:else}
    <div class="border border-emerald-300 bg-emerald-50 rounded p-2">
      <strong class="text-emerald-800">Configurazione OK</strong>
    </div>
  {/if}

  <!-- ============= Plessi section ============= -->
  <section class="card p-4 space-y-3">
    <div class="flex items-center gap-3">
      <h2 class="text-xl font-semibold">Plessi</h2>
      <button class="btn-primary !text-sm" on:click={newPlesso}
              data-testid="add-plesso-btn">
        + Nuovo plesso
      </button>
    </div>
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-ink-200">
          <th class="text-left py-1">Codice</th>
          <th class="text-left py-1">Nome</th>
          <th class="text-left py-1">Indirizzo</th>
          <th class="text-left py-1">Note</th>
          <th class="text-right py-1">Azioni</th>
        </tr>
      </thead>
      <tbody>
        {#each plessi as p}
          <tr class="border-b border-ink-100">
            <td class="py-1 font-mono">{p.code}</td>
            <td class="py-1">{p.name}</td>
            <td class="py-1 text-ink-500">{p.address || ''}</td>
            <td class="py-1 text-ink-500 truncate max-w-xs">
              {p.notes || ''}
            </td>
            <td class="py-1 text-right">
              <button class="btn !text-xs"
                      data-testid="plesso-edit-btn"
                      data-plesso-id={p.id}
                      on:click={() => editPlesso(p)}>Modifica</button>
              <button class="btn !text-xs !text-rose-700"
                      data-testid="plesso-delete-btn"
                      data-plesso-id={p.id}
                      on:click={() => deletePlesso(p)}>Elimina</button>
            </td>
          </tr>
        {/each}
        {#if plessi.length === 0}
          <tr>
            <td colspan="5" class="py-3 text-center text-ink-500">
              Nessun plesso configurato.
            </td>
          </tr>
        {/if}
      </tbody>
    </table>
    {#if editingPlesso}
      <div class="border border-accent-300 bg-accent-50 rounded p-3 space-y-2"
           data-testid="plesso-form">
        <div class="grid grid-cols-2 gap-2">
          <label class="field">
            <span class="text-xs">Codice (breve)</span>
            <input type="text" bind:value={editingPlesso.code}
                   maxlength="16" class="w-full"
                   data-testid="plesso-code-input"/>
          </label>
          <label class="field">
            <span class="text-xs">Nome</span>
            <input type="text" bind:value={editingPlesso.name}
                   class="w-full"
                   data-testid="plesso-name-input"/>
          </label>
          <label class="field col-span-2">
            <span class="text-xs">Indirizzo</span>
            <input type="text" bind:value={editingPlesso.address}
                   class="w-full"
                   data-testid="plesso-address-input"/>
          </label>
          <label class="field col-span-2">
            <span class="text-xs">Note</span>
            <textarea rows="2" bind:value={editingPlesso.notes}
                      class="w-full"></textarea>
          </label>
        </div>
        <div class="flex gap-2 justify-end">
          <button class="btn" on:click={() => editingPlesso = null}
                  data-testid="plesso-cancel-btn">
            Annulla
          </button>
          <button class="btn-primary" on:click={savePlesso}
                  data-testid="plesso-save-btn">
            Salva
          </button>
        </div>
      </div>
    {/if}
  </section>

  <!-- ============= Commuting rules section ============= -->
  <section class="card p-4 space-y-3">
    <div class="flex items-center gap-3 flex-wrap">
      <h2 class="text-xl font-semibold">Regole di spostamento</h2>
      <select bind:value={filterRuleKind} class="text-sm">
        <option value="all">Tutte</option>
        <option value="teacher">Docenti</option>
        <option value="class">Classi</option>
        <option value="group">Gruppi</option>
      </select>
      <button class="btn-primary !text-sm" on:click={newRule}
              disabled={plessi.length < 1}>
        + Nuova regola
      </button>
    </div>
    <p class="text-xs text-ink-500">
      Una regola tra (Plesso A, Plesso B) per una certa
      kind/entit&agrave; impone un vincolo sul movimento tra le due
      sedi: gap minimo (slot vuoti) o spostamento solo durante la
      ricreazione.
    </p>
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-ink-200">
          <th class="text-left py-1">Da</th>
          <th class="text-left py-1">A</th>
          <th class="text-left py-1">Kind</th>
          <th class="text-left py-1">Entit&agrave;</th>
          <th class="text-right py-1">Gap</th>
          <th class="text-left py-1">Solo ricreazione</th>
          <th class="text-right py-1">Priorit&agrave;</th>
          <th class="text-right py-1">Azioni</th>
        </tr>
      </thead>
      <tbody>
        {#each filteredRules as r}
          <tr class="border-b border-ink-100">
            <td class="py-1 font-mono">{plessoNameOf(r.from_plesso_id)}</td>
            <td class="py-1 font-mono">{plessoNameOf(r.to_plesso_id)}</td>
            <td class="py-1">{r.entity_kind}</td>
            <td class="py-1">{entityNameOf(r.entity_kind, r.entity_id)}</td>
            <td class="py-1 text-right">{r.min_gap_hours}</td>
            <td class="py-1">
              {#if r.allowed_break_only}
                {r.break_start_hour}↔{r.break_end_hour}
              {:else}
                no
              {/if}
            </td>
            <td class="py-1 text-right">{r.priority}</td>
            <td class="py-1 text-right">
              <button class="btn !text-xs"
                      on:click={() => editRule(r)}>Modifica</button>
              <button class="btn !text-xs !text-rose-700"
                      on:click={() => deleteRule(r)}>Elimina</button>
            </td>
          </tr>
        {/each}
        {#if filteredRules.length === 0}
          <tr>
            <td colspan="8" class="py-3 text-center text-ink-500">
              Nessuna regola.
            </td>
          </tr>
        {/if}
      </tbody>
    </table>
    {#if editingRule}
      <div class="border border-accent-300 bg-accent-50 rounded p-3 space-y-2">
        <div class="grid grid-cols-3 gap-2">
          <label class="field">
            <span class="text-xs">Da plesso</span>
            <select bind:value={editingRule.from_plesso_id} class="w-full">
              {#each plessi as p}
                <option value={p.id}>{p.code} - {p.name}</option>
              {/each}
            </select>
          </label>
          <label class="field">
            <span class="text-xs">A plesso</span>
            <select bind:value={editingRule.to_plesso_id} class="w-full">
              {#each plessi as p}
                <option value={p.id}>{p.code} - {p.name}</option>
              {/each}
            </select>
          </label>
          <label class="field">
            <span class="text-xs">Entit&agrave; kind</span>
            <select bind:value={editingRule.entity_kind} class="w-full">
              <option value="teacher">teacher</option>
              <option value="class">class</option>
              <option value="group">group</option>
            </select>
          </label>
          <label class="field col-span-2">
            <span class="text-xs">Entit&agrave; specifica
              (vuoto = vale per tutti)</span>
            <select bind:value={editingRule.entity_id} class="w-full">
              <option value={null}>(tutti)</option>
              {#each entityListForKind(editingRule.entity_kind) as e}
                <option value={e.id}>{e.name}</option>
              {/each}
            </select>
          </label>
          <label class="field">
            <span class="text-xs">Gap minimo (slot vuoti)</span>
            <input type="number" min="0" max="6"
                   bind:value={editingRule.min_gap_hours}
                   class="w-full"/>
          </label>
          <label class="field flex items-center gap-2">
            <input type="checkbox"
                   bind:checked={editingRule.allowed_break_only}/>
            <span class="text-xs">Solo durante la ricreazione</span>
          </label>
          {#if editingRule.allowed_break_only}
            <label class="field">
              <span class="text-xs">Inizio ricreazione (ora)</span>
              <input type="number" min="8" max="13"
                     bind:value={editingRule.break_start_hour}
                     class="w-full"/>
            </label>
            <label class="field">
              <span class="text-xs">Fine ricreazione (ora)</span>
              <input type="number" min="8" max="13"
                     bind:value={editingRule.break_end_hour}
                     class="w-full"/>
            </label>
          {/if}
          <label class="field flex items-center gap-2">
            <input type="checkbox" bind:checked={editingRule.symmetric}/>
            <span class="text-xs">Simmetrica (vale anche A&rarr;B)</span>
          </label>
          <label class="field">
            <span class="text-xs">Priorit&agrave;</span>
            <input type="number"
                   bind:value={editingRule.priority}
                   class="w-full"/>
          </label>
        </div>
        <div class="flex gap-2 justify-end">
          <button class="btn" on:click={() => editingRule = null}>
            Annulla
          </button>
          <button class="btn-primary" on:click={saveRule}>
            Salva
          </button>
        </div>
      </div>
    {/if}
  </section>

  <!-- ============= Entity policies section ============= -->
  <section class="card p-4 space-y-3">
    <div class="flex items-center gap-3 flex-wrap">
      <h2 class="text-xl font-semibold">Regole entit&agrave;</h2>
      <select bind:value={filterPolicyKind} class="text-sm">
        <option value="all">Tutte</option>
        <option value="teacher">Docenti</option>
        <option value="class">Classi</option>
      </select>
      <button class="btn-primary !text-sm" on:click={newPolicy}
              disabled={plessi.length < 1}>
        + Nuova policy
      </button>
    </div>
    <p class="text-xs text-ink-500">
      Una policy globale per un docente (o tutti i docenti) e per
      una classe (o tutte le classi). Tre tipi:
      <code>any</code> (nessun vincolo,
      default), <code>single_plesso_per_day</code> (in un singolo
      giorno tutte le lezioni nello stesso plesso),
      <code>single_plesso_total</code> (in tutta la settimana
      stesso plesso, opzionalmente fissato a un plesso specifico).
    </p>
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-ink-200">
          <th class="text-left py-1">Kind</th>
          <th class="text-left py-1">Entit&agrave;</th>
          <th class="text-left py-1">Policy</th>
          <th class="text-left py-1">Plesso fissato</th>
          <th class="text-right py-1">Priorit&agrave;</th>
          <th class="text-right py-1">Azioni</th>
        </tr>
      </thead>
      <tbody>
        {#each filteredPolicies as p}
          <tr class="border-b border-ink-100">
            <td class="py-1">{p.entity_kind}</td>
            <td class="py-1">{entityNameOf(p.entity_kind, p.entity_id)}</td>
            <td class="py-1 font-mono">{p.policy}</td>
            <td class="py-1">
              {p.plesso_id ? plessoNameOf(p.plesso_id) : '-'}
            </td>
            <td class="py-1 text-right">{p.priority}</td>
            <td class="py-1 text-right">
              <button class="btn !text-xs"
                      on:click={() => editPolicy(p)}>Modifica</button>
              <button class="btn !text-xs !text-rose-700"
                      on:click={() => deletePolicy(p)}>Elimina</button>
            </td>
          </tr>
        {/each}
        {#if filteredPolicies.length === 0}
          <tr>
            <td colspan="6" class="py-3 text-center text-ink-500">
              Nessuna policy.
            </td>
          </tr>
        {/if}
      </tbody>
    </table>
    {#if editingPolicy}
      <div class="border border-accent-300 bg-accent-50 rounded p-3 space-y-2">
        <div class="grid grid-cols-3 gap-2">
          <label class="field">
            <span class="text-xs">Entit&agrave; kind</span>
            <select bind:value={editingPolicy.entity_kind} class="w-full">
              <option value="teacher">teacher</option>
              <option value="class">class</option>
            </select>
          </label>
          <label class="field col-span-2">
            <span class="text-xs">Entit&agrave; specifica
              (vuoto = vale per tutti)</span>
            <select bind:value={editingPolicy.entity_id} class="w-full">
              <option value={null}>(tutti)</option>
              {#each entityListForKind(editingPolicy.entity_kind) as e}
                <option value={e.id}>{e.name}</option>
              {/each}
            </select>
          </label>
          <label class="field">
            <span class="text-xs">Policy</span>
            <select bind:value={editingPolicy.policy} class="w-full">
              <option value="any">any</option>
              <option value="single_plesso_per_day">
                single_plesso_per_day
              </option>
              <option value="single_plesso_total">
                single_plesso_total
              </option>
            </select>
          </label>
          {#if editingPolicy.policy === 'single_plesso_total'}
            <label class="field col-span-2">
              <span class="text-xs">Plesso fissato (opzionale)</span>
              <select bind:value={editingPolicy.plesso_id}
                      class="w-full">
                <option value={null}>(qualsiasi)</option>
                {#each plessi as p}
                  <option value={p.id}>{p.code} - {p.name}</option>
                {/each}
              </select>
            </label>
          {/if}
          <label class="field">
            <span class="text-xs">Priorit&agrave;</span>
            <input type="number"
                   bind:value={editingPolicy.priority}
                   class="w-full"/>
          </label>
        </div>
        <div class="flex gap-2 justify-end">
          <button class="btn" on:click={() => editingPolicy = null}>
            Annulla
          </button>
          <button class="btn-primary" on:click={savePolicy}>
            Salva
          </button>
        </div>
      </div>
    {/if}
  </section>
</div>
