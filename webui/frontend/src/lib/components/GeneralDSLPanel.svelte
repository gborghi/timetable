<script>
  // Reusable panel for the general-purpose DSL constraints (the
  // /api/constraints/general endpoint). Mirrors LogicalUnavailabilities-
  // Panel but for the richer DSL: quantifiers (forall / exists / count),
  // arithmetic, predicates like consecutive_days(d1, d2), and any
  // entity scope (teacher / class / classroom / curriculum / global).
  //
  // The post-hoc DSL behind this panel supports cross-lesson rules that
  // logic_parser cannot express -- e.g. "the 3 hours of Fisica in 3A
  // must NOT be on consecutive days" or "all 3 hours in 3C must fall on
  // the same day with consecutive hours".
  //
  // Props:
  //   scope:     'teacher' | 'class' | 'classroom' | 'curriculum' |
  //              'subject' | 'group' | 'global'
  //   ownerId:   int | null  (null only for scope='global')
  //   scopeLabel: optional human label, forwarded to the modal title

  import { api } from '../api';
  import { flash } from '../stores';
  import NewGeneralConstraintModal
    from './constraints/NewGeneralConstraintModal.svelte';

  export let scope = 'teacher';
  export let ownerId = null;
  export let scopeLabel = '';

  let rules = [];
  let loading = false;
  let modalOpen = false;

  // Reload whenever the entity changes.
  $: void load(scope, ownerId);

  async function load(_scope, _ownerId) {
    if (_ownerId == null && _scope !== 'global') {
      rules = [];
      return;
    }
    loading = true;
    try {
      const params = new URLSearchParams();
      params.set('scope', _scope);
      if (_ownerId != null) params.set('owner_id', String(_ownerId));
      rules = await api.get(
        '/api/constraints/general?' + params.toString());
    } catch {
      rules = [];
    } finally {
      loading = false;
    }
  }

  async function deleteRule(id) {
    if (!confirm(`Eliminare il vincolo DSL #${id}?`)) return;
    try {
      await api.del('/api/constraints/general/' + id);
      flash('Vincolo eliminato.', 'success');
      await load(scope, ownerId);
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
  }

  function openModal() {
    if (ownerId == null && scope !== 'global') {
      flash("Salva l'entità prima di aggiungere vincoli DSL.", 'error');
      return;
    }
    modalOpen = true;
  }

  function levelBadge(level) {
    if (level === 'hard') return '🟥 HARD';
    if (level === 'enforced') return '🟩 ENFORCED';
    if (level === 'soft') return '🟨 SOFT';
    if (level === 'preferred') return '🟦 PREFERRED';
    return level || '?';
  }
</script>

<div class="general-dsl-panel border border-ink-200 rounded-md p-3 space-y-2">
  <div class="flex items-center justify-between">
    <div>
      <strong class="text-sm">Vincoli avanzati DSL</strong>
      <span class="ml-1 text-[10px] text-ink-500"
            title={"Per vincoli complessi cross-lesson (es. 'le 3 ore di "
                   + "matematica non in giorni consecutivi'), usa il DSL "
                   + "avanzato. Supporta quantificatori, aritmetica e "
                   + "predicati come consecutive_days(d1, d2)."}>ⓘ</span>
    </div>
    <button class="btn-primary text-xs" on:click={openModal}
            disabled={ownerId == null && scope !== 'global'}>
      + Aggiungi vincolo avanzato
    </button>
  </div>

  {#if loading}
    <div class="text-xs text-ink-500">Caricamento…</div>
  {:else if rules.length === 0}
    <div class="text-xs text-ink-500 italic">
      Nessun vincolo DSL avanzato per questa entità.
      Per vincoli cross-lesson (es. "le 3 ore non in giorni
      consecutivi") usa il DSL avanzato cliccando il pulsante sopra.
    </div>
  {:else}
    <ul class="space-y-1">
      {#each rules as r (r.id)}
        <li class="flex items-start gap-2 text-xs border-l-2 pl-2
                   {r.level === 'hard' || r.level === 'enforced'
                      ? 'border-red-400'
                      : r.level === 'preferred'
                        ? 'border-sky-400' : 'border-amber-400'}">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-[10px] font-mono">{levelBadge(r.level)}</span>
              {#if r.label}
                <span class="font-semibold truncate">{r.label}</span>
              {/if}
            </div>
            <code class="block text-[10px] text-ink-500 break-all
                         font-mono mt-0.5">{r.expression}</code>
          </div>
          <button class="text-red-600 hover:underline text-xs shrink-0"
                  on:click={() => deleteRule(r.id)}>
            Elimina
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<NewGeneralConstraintModal bind:open={modalOpen}
                           {scope}
                           ownerId={ownerId}
                           scopeLabel={scopeLabel}
                           onClose={() => (modalOpen = false)}
                           onCreated={async () => {
                             modalOpen = false;
                             await load(scope, ownerId);
                           }}/>
