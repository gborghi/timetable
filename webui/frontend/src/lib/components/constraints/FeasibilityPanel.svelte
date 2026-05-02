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

  async function removeMember(m) {
    if (!confirm(`Rimuovere il vincolo ${memberShort(m)}? `
        + 'Questa azione non e\' reversibile.')) return;
    try {
      await api.del(`/api/monitor/constraints/${m.db_kind}/${m.db_id}`);
      flash('Vincolo rimosso.', 'success');
      onChanged();
      popover = null;
      // Auto re-verify
      run();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    }
  }

  async function applySuggestion() {
    if (!result || !result.suggested_removal
        || result.suggested_removal.length === 0) {
      flash('Nessun suggerimento disponibile.', 'info');
      return;
    }
    const list = result.suggested_removal;
    const summary = list.slice(0, 5).map((m) =>
      `${levelLabel(m.level)} ${memberShort(m)}`).join('\n');
    const more = list.length > 5 ? `\n...e altri ${list.length - 5}` : '';
    if (!confirm(`Rimuovere ${list.length} vincoli per rendere il `
        + `modello feasible?\n\n${summary}${more}`)) {
      return;
    }
    try {
      const items = list.map((m) => ({ kind: m.db_kind, id: m.db_id }));
      const r = await api.post('/api/constraints/delete-batch', { items });
      flash(`${r.deleted} vincoli rimossi.`, 'success');
      onChanged();
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
        <button class="btn-amber" on:click={applySuggestion}>
          Applica suggerimento ({result.suggested_removal.length} rimozioni)
        </button>
      {/if}
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
                  <li class="flex items-center gap-2 text-xs">
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
                            title="Rimuovi questo vincolo">
                      Rimuovi
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
              <div class="flex gap-2 pt-1 border-t border-ink-100">
                <button class="btn-red !text-[10px] !px-2 !py-0.5"
                        on:click={() => removeMember(popover.member)}>
                  Rimuovi
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
</div>
