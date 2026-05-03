<script>
  /**
   * Feasibility Check + interactive Conflict Explorer.
   *
   * Click "Avvia check" -> POST /api/constraints/feasibility-check.
   * If feasible -> green banner. Else -> red panel with:
   *   - one card per "unsatisfiable core" (group of mutually
   *     incompatible HARD/ENFORCED constraints), each member listed
   *     with its level pill + Rimuovi button + Vedi (scroll to row)
   *   - small Cytoscape graph: nodes = constraint members, edges
   *     between pairs in the same core (cliques per core), colored
   *     by level. Click a node -> popover with details + Rimuovi.
   *   - "Applica suggerimento" button: POST /constraints/delete-batch
   *     with the suggested removal set; user gets a confirm first.
   *   - "Ri-verifica" + "Esporta JSON".
   *
   * The panel is controlled by the parent (open/close), but it owns
   * the result + the per-action calls.
   */
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import { levelPill, levelLabel } from '$lib/constraint_levels';

  export let onChanged = () => {};

  let result = null;       // {feasible, cores, suggested_removal, ...}
  let busy = false;
  let cyContainer;
  let cy = null;
  let popover = null;       // {x, y, member}
  let interventions = [];   // audit history (DB-backed)
  let showHistory = false;

  async function run() {
    busy = true;
    popover = null;
    try {
      result = await api.post('/api/constraints/feasibility-check', {
        time_limit_s: 30,
      });
      if (result.feasible) {
        flash('✅ Modello dei vincoli HARD/ENFORCED feasible.', 'success');
      } else if (result.feasible === false) {
        flash(`❌ Infeasible: ${result.cores.length} core, `
              + `${result.suggested_removal.length} rimozioni proposte.`,
              'error');
      } else {
        flash('Risultato inconclusivo: ' + (result.error || 'timeout'),
              'error');
      }
      // Re-render the graph after a tick when DOM is ready.
      setTimeout(renderGraph, 50);
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    } finally {
      busy = false;
    }
  }

  function memberKey(m) { return `${m.db_kind}:${m.db_id}`; }

  function memberShort(m) {
    return `${m.scope || ''} ${m.owner_name || ''} - ${m.detail || ''}`
      .replace(/\s+/g, ' ').trim();
  }

  // Brand-aligned palette per level
  const LEVEL_COLOR = {
    hard: '#9c1c1c',
    enforced: '#0e6b3a',
    soft: '#c9a23a',
    preferred: '#1e3a5f',
    allowed: '#94c1a4',
    forbidden: '#5b1010',
  };

  async function renderGraph() {
    if (!cyContainer || !result || !result.cores
        || result.cores.length === 0) {
      if (cy) { cy.destroy(); cy = null; }
      return;
    }
    const cytoscape = (await import('cytoscape')).default;
    const fcose = (await import('cytoscape-fcose')).default;
    try { cytoscape.use(fcose); } catch (_) {}

    if (cy) { cy.destroy(); cy = null; }

    const seen = new Set();
    const nodes = [];
    const edges = [];
    for (const c of result.cores) {
      // Add nodes
      const memberIds = [];
      for (const m of c.members) {
        const key = memberKey(m);
        memberIds.push(key);
        if (seen.has(key)) continue;
        seen.add(key);
        nodes.push({
          data: {
            id: key,
            label: memberShort(m),
            level: m.level,
            color: LEVEL_COLOR[m.level] || '#666',
            member: m,
          },
        });
      }
      // Clique edges within the core
      for (let i = 0; i < memberIds.length; i++) {
        for (let j = i + 1; j < memberIds.length; j++) {
          edges.push({
            data: {
              id: `e_${c.id}_${i}_${j}`,
              source: memberIds[i],
              target: memberIds[j],
              core_id: c.id,
            },
          });
        }
      }
    }

    cy = cytoscape({
      container: cyContainer,
      elements: [...nodes, ...edges],
      wheelSensitivity: 0.25,
      minZoom: 0.2,
      maxZoom: 3,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'background-color': 'data(color)',
            'border-color': '#1f1f1f',
            'border-width': 1.5,
            color: '#ffffff',
            'font-size': 10,
            'font-weight': 600,
            'text-valign': 'center',
            'text-halign': 'center',
            'text-outline-color': '#1f1f1f',
            'text-outline-width': 1,
            'text-wrap': 'wrap',
            'text-max-width': 80,
            width: 'mapData(label.length, 5, 50, 50, 120)',
            height: 36,
            shape: 'round-rectangle',
          },
        },
        {
          selector: 'edge',
          style: {
            'line-color': '#9c1c1c',
            width: 1.5,
            'curve-style': 'bezier',
            opacity: 0.6,
          },
        },
      ],
      layout: {
        name: 'fcose',
        animate: false,
        nodeRepulsion: 5000,
        idealEdgeLength: 100,
      },
    });
    cy.on('tap', 'node', (ev) => {
      const node = ev.target;
      const m = node.data('member');
      const pos = node.renderedPosition();
      const rect = cyContainer.getBoundingClientRect();
      popover = {
        x: pos.x + rect.left, y: pos.y + rect.top,
        member: m,
      };
    });
    cy.on('tap', (ev) => {
      if (ev.target === cy) popover = null;
    });
  }

  // ----- Intervention actions (use the audit-trail endpoint) ----------

  async function applyAction(member, action, params, opts) {
    const o = opts || {};
    if (o.confirmText && !confirm(o.confirmText)) return;
    try {
      const resp = await api.post('/api/constraints/apply-suggestion', {
        action,
        targets: [{ kind: member.db_kind, id: member.db_id }],
        params: params || null,
        note: o.note || null,
      });
      flash(o.successMsg
        || `Azione '${action}' applicata (intervento `
            + `#${resp.intervention_ids[0]}). Reversibile da Storico.`,
        'success');
      onChanged();
      popover = null;
      await loadInterventions();
      run();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
  }

  function removeMember(m) {
    return applyAction(m, 'remove', null, {
      confirmText: `Rimuovere il vincolo ${memberShort(m)}?\n`
        + `Reversibile dallo Storico (verra' ricreato con un nuovo id).`,
      successMsg: 'Vincolo rimosso. Reversibile da Storico.',
    });
  }

  function softenMember(m) {
    const w = parseInt(prompt(
      `Trasforma "${memberShort(m)}" in SOFT.\n\n`
      + `Specifica la penalty (peso). Tipici: 50 = preferenza tenue, `
      + `100 = preferenza media, 1000 = quasi-hard.`,
      '100'), 10);
    if (!w || w <= 0) return;
    return applyAction(m, 'soften', { weight: w }, {
      successMsg: `Vincolo trasformato in SOFT con penalty ${w}.`,
    });
  }

  function disableMember(m) {
    return applyAction(m, 'disable', null, {
      confirmText: `Disabilitare temporaneamente "${memberShort(m)}"?\n`
        + 'Il vincolo restera\' nel DB ma non sara\' applicato.',
      successMsg: 'Vincolo disabilitato. Riabilitabile da Storico.',
    });
  }

  function editMember(m) {
    const newExpr = prompt(
      `Modifica espressione DSL del vincolo "${memberShort(m)}":\n\n`
      + `Espressione attuale: ${m.detail || '(non disponibile)'}`,
      m.detail || '');
    if (newExpr == null) return;
    if (!newExpr.trim()) {
      flash('Espressione vuota; modifica annullata.', 'info');
      return;
    }
    return applyAction(m, 'edit', { expression: newExpr.trim() }, {
      successMsg: 'Espressione modificata.',
    });
  }

  // ----- Interventions history + revert -------------------------------

  async function loadInterventions() {
    try {
      interventions = await api.get('/api/constraints/interventions?limit=50');
    } catch (e) {
      // non-fatal; just hide history
      interventions = [];
    }
  }

  async function revertIntervention(iv) {
    if (iv.reverted) {
      flash('Intervento gia\' revertito.', 'info');
      return;
    }
    if (!confirm(`Revertire l'intervento #${iv.id} `
        + `(${iv.action} ${iv.target_kind}#${iv.target_id})?`)) return;
    try {
      await api.post('/api/constraints/revert', {
        intervention_ids: [iv.id],
      });
      flash(`Intervento #${iv.id} revertito.`, 'success');
      onChanged();
      await loadInterventions();
      run();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
  }

  function fmtTs(s) {
    if (!s) return '';
    try {
      const d = new Date(s);
      return d.toLocaleString();
    } catch (_) { return s; }
  }

  onMount(() => { loadInterventions(); });

  async function applySuggestion(action) {
    if (!result || !result.suggested_removal
        || result.suggested_removal.length === 0) {
      flash('Nessun suggerimento disponibile.', 'info');
      return;
    }
    const list = result.suggested_removal;
    const summary = list.slice(0, 5).map((m) =>
      `${levelLabel(m.level)} ${memberShort(m)}`).join('\n');
    const more = list.length > 5 ? `\n...e altri ${list.length - 5}` : '';
    const verb = action === 'soften' ? 'trasformare in SOFT'
              : action === 'disable' ? 'disabilitare temporaneamente'
              : 'rimuovere';
    if (!confirm(`${list.length} vincoli da ${verb} per rendere il `
        + `modello feasible:\n\n${summary}${more}\n\n`
        + `Tutte le azioni sono reversibili dallo Storico interventi.`)) {
      return;
    }
    try {
      const targets = list.map((m) => ({ kind: m.db_kind, id: m.db_id }));
      const params = action === 'soften' ? { weight: 100 } : null;
      const r = await api.post('/api/constraints/apply-suggestion', {
        action, targets, params,
        note: `batch ${action} from feasibility panel`,
      });
      flash(`${r.n_applied} vincoli: '${action}' applicato. `
            + `Reversibile da Storico.`, 'success');
      onChanged();
      await loadInterventions();
      run();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
  }

  function exportJson() {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)],
                           { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `feasibility-report-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
</script>

<div class="space-y-3">
  <div class="flex items-center gap-2 flex-wrap">
    <button class="btn-primary" on:click={run} disabled={busy}>
      {busy ? 'analisi in corso...' : 'Avvia check'}
    </button>
    {#if result}
      <button class="btn !text-xs" on:click={run} disabled={busy}>
        Ri-verifica
      </button>
      <button class="btn !text-xs" on:click={exportJson}>
        Esporta JSON
      </button>
      {#if result.feasible === false && result.suggested_removal.length}
        <button class="btn-amber" on:click={() => applySuggestion('remove')}
                title="Rimuovi tutti i vincoli del set suggerito (reversibile da Storico)">
          Rimuovi suggeriti ({result.suggested_removal.length})
        </button>
        <button class="btn !text-xs" on:click={() => applySuggestion('soften')}
                title="Trasforma in SOFT con penalty 100 (reversibile)">
          Trasforma in SOFT
        </button>
        <button class="btn !text-xs" on:click={() => applySuggestion('disable')}
                title="Disabilita temporaneamente (il vincolo resta nel DB)">
          Disabilita temporaneamente
        </button>
      {/if}
      <button class="btn !text-xs"
              on:click={() => { showHistory = !showHistory;
                                if (showHistory) loadInterventions(); }}
              title="Storico interventi sui vincoli">
        Storico ({interventions.length})
      </button>
      <span class="text-xs text-ink-500 ml-auto">
        {result.n_constraints} vincoli HARD/ENFORCED ·
        {result.n_assignments} cattedre · {result.time_s}s
      </span>
    {/if}
  </div>

  {#if result}
    {#if result.feasible}
      <div class="card p-3 border-2 border-emerald-300 bg-emerald-50/60
                  text-emerald-900">
        ✅ <strong>Modello feasible</strong> — i vincoli HARD/ENFORCED
        sono mutuamente compatibili. Phase B avra' (almeno) un'assegnazione
        che li soddisfa tutti.
      </div>
    {:else if result.feasible === false}
      <div class="card p-3 border-2 border-red-300 bg-red-50/60 space-y-2">
        <h3 class="text-red-900">
          ❌ Infeasible — {result.cores.length} core di vincoli incompatibili
        </h3>
        <p class="text-xs text-red-700">
          Ogni core e' un sottoinsieme MINIMALE di vincoli che insieme
          rendono il modello UNSAT: rimuovendone uno qualsiasi del core,
          il sistema torna soddisfacibile (almeno fino al prossimo core).
          Il "suggerimento automatico" propone una rimozione che risolve
          tutti i core in una passata.
        </p>
      </div>
      <div class="grid lg:grid-cols-2 gap-3">
        <!-- LEFT: cores list -->
        <div class="space-y-2">
          {#each result.cores as core}
            <div class="card p-3 border-red-200">
              <div class="text-sm font-semibold mb-1">
                Core #{core.id}
                <span class="text-xs font-normal text-ink-500 ml-2">
                  {core.kind}
                </span>
              </div>
              <p class="text-xs text-ink-600 mb-2">{core.reason}</p>
              <ul class="space-y-1">
                {#each core.members as m}
                  <li class="flex items-center gap-2 text-xs flex-wrap">
                    <span class="{levelPill(m.level)} !text-[10px]">
                      {levelLabel(m.level)}
                    </span>
                    <span class="pill !text-[10px]">{m.scope}</span>
                    <strong>{m.owner_name}</strong>
                    <code class="text-ink-500">{m.detail}</code>
                    <span class="text-[10px] text-ink-400 ml-auto">
                      {m.db_kind}#{m.db_id}
                    </span>
                    <button class="btn-red !text-[10px] !px-1 !py-0"
                            on:click={() => removeMember(m)}
                            title="Rimuovi (reversibile da Storico)">
                      Rimuovi
                    </button>
                    <button class="btn !text-[10px] !px-1 !py-0"
                            on:click={() => softenMember(m)}
                            title="Trasforma in SOFT con penalty">
                      Soften
                    </button>
                    <button class="btn !text-[10px] !px-1 !py-0"
                            on:click={() => disableMember(m)}
                            title="Disabilita temporaneamente">
                      Disabilita
                    </button>
                    <button class="btn !text-[10px] !px-1 !py-0"
                            on:click={() => editMember(m)}
                            title="Modifica espressione DSL">
                      Modifica
                    </button>
                  </li>
                {/each}
              </ul>
            </div>
          {/each}
          {#if result.suggested_removal.length}
            <div class="card p-3 border-amber-300 bg-amber-50/40">
              <div class="text-sm font-semibold mb-1">
                Rimozione suggerita
                ({result.suggested_removal.length} vincoli)
              </div>
              <ul class="space-y-1">
                {#each result.suggested_removal as m}
                  <li class="text-xs">
                    <span class="{levelPill(m.level)} !text-[10px]">
                      {levelLabel(m.level)}
                    </span>
                    <strong>{m.owner_name}</strong>
                    <code class="text-ink-500">{m.detail}</code>
                    <span class="text-ink-400 italic"> — {m.reason}</span>
                  </li>
                {/each}
              </ul>
            </div>
          {/if}
        </div>

        <!-- RIGHT: Cytoscape graph -->
        <div class="card p-2 relative" style="height: 400px;">
          <div class="text-xs text-ink-500 mb-1">
            Grafo dei conflitti — nodi = vincoli, archi = appartenenza
            allo stesso core. Click su un nodo per i dettagli.
          </div>
          <div bind:this={cyContainer}
               style="width: 100%; height: calc(100% - 24px); border: 1px solid #e5e7eb; border-radius: 6px;"></div>
          {#if popover}
            <div class="absolute bg-white border border-ink-300 rounded
                        shadow-lg p-3 text-xs space-y-1 z-10"
                 style="left: {popover.x - 100}px; top: {popover.y + 30}px;
                        max-width: 280px;">
              <div>
                <span class="{levelPill(popover.member.level)} !text-[10px]">
                  {levelLabel(popover.member.level)}
                </span>
                <span class="pill !text-[10px]">{popover.member.scope}</span>
              </div>
              <div><strong>{popover.member.owner_name}</strong></div>
              <div><code>{popover.member.detail}</code></div>
              <div class="text-ink-400">
                {popover.member.db_kind} #{popover.member.db_id}
              </div>
              <div class="flex gap-1 pt-1 border-t border-ink-100 flex-wrap">
                <button class="btn-red !text-[10px] !px-2 !py-0.5"
                        on:click={() => removeMember(popover.member)}>
                  Rimuovi
                </button>
                <button class="btn !text-[10px] !px-2 !py-0.5"
                        on:click={() => softenMember(popover.member)}>
                  Soften
                </button>
                <button class="btn !text-[10px] !px-2 !py-0.5"
                        on:click={() => disableMember(popover.member)}>
                  Disabilita
                </button>
                <button class="btn !text-[10px] !px-2 !py-0.5"
                        on:click={() => editMember(popover.member)}>
                  Modifica
                </button>
                <button class="btn !text-[10px] !px-2 !py-0.5"
                        on:click={() => (popover = null)}>
                  Chiudi
                </button>
              </div>
            </div>
          {/if}
        </div>
      </div>
    {:else}
      <div class="card p-3 border-2 border-amber-300 bg-amber-50/60">
        ⚠️ <strong>Inconclusivo</strong> — {result.error || 'timeout'}.
        Aumenta `time_limit_s` o riduci il numero di vincoli HARD/ENFORCED
        attivi.
      </div>
    {/if}
  {/if}

  {#if showHistory}
    <div class="card p-3 border-ink-200 mt-2">
      <div class="flex items-center mb-2 gap-2">
        <h3 class="text-sm">Storico interventi sui vincoli</h3>
        <span class="text-xs text-ink-500">
          ({interventions.length} record, ordine cronologico inverso)
        </span>
        <button class="btn !text-xs ml-auto"
                on:click={loadInterventions}>
          Aggiorna
        </button>
        <button class="btn !text-xs"
                on:click={() => (showHistory = false)}>
          Chiudi
        </button>
      </div>
      {#if interventions.length === 0}
        <p class="text-xs text-ink-500 italic">
          Nessun intervento registrato. Quando rimuovi, soften o disabiliti
          un vincolo dal pannello qui sopra, l'azione viene salvata qui e
          puo' essere revertita in qualsiasi momento.
        </p>
      {:else}
        <div class="overflow-x-auto">
          <table class="text-xs w-full">
            <thead>
              <tr class="text-left text-ink-500 border-b border-ink-200">
                <th class="py-1 pr-2">#</th>
                <th class="py-1 pr-2">Quando</th>
                <th class="py-1 pr-2">Azione</th>
                <th class="py-1 pr-2">Target</th>
                <th class="py-1 pr-2">Vincolo</th>
                <th class="py-1 pr-2">Stato</th>
                <th class="py-1 pr-2"></th>
              </tr>
            </thead>
            <tbody>
              {#each interventions as iv}
                <tr class="border-b border-ink-100 align-top">
                  <td class="py-1 pr-2 text-ink-400">{iv.id}</td>
                  <td class="py-1 pr-2 text-ink-600">{fmtTs(iv.timestamp)}</td>
                  <td class="py-1 pr-2">
                    <span class="pill !text-[10px]">{iv.action}</span>
                  </td>
                  <td class="py-1 pr-2">
                    {iv.target_kind}#{iv.target_id}
                  </td>
                  <td class="py-1 pr-2 text-ink-600">
                    {iv.target_owner_label || ''}
                  </td>
                  <td class="py-1 pr-2">
                    {#if iv.reverted}
                      <span class="text-[10px] text-emerald-600">
                        revertito {iv.reverted_by_id
                          ? `(#${iv.reverted_by_id})` : ''}
                      </span>
                    {:else if iv.action === 'restore'}
                      <span class="text-[10px] text-ink-400 italic">
                        restore
                      </span>
                    {:else}
                      <span class="text-[10px] text-ink-500">attivo</span>
                    {/if}
                  </td>
                  <td class="py-1 pr-2">
                    {#if !iv.reverted && iv.action !== 'restore'}
                      <button class="btn !text-[10px] !px-1 !py-0"
                              on:click={() => revertIntervention(iv)}
                              title="Annulla questo intervento">
                        Revert
                      </button>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </div>
  {/if}
</div>
