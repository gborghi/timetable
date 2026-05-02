<!--
  Phase A "Assegnazione docenti -> classi" card with criterion selector.

  - Loads the catalogue of presets from
    GET /api/optimize/phase-a/presets on mount.
  - User picks a preset (radio) or "Custom" -> textarea editor.
  - Custom expressions are debounce-validated via
    POST /api/optimize/phase-a/validate-expression.
  - "Mostra criteri attivi" reveals the underlying DSL of the
    selected preset (read-only).
  - Launch button hits onLaunch({criterion, custom_expression,
    time_limit_s, workers, log}).

  Reusable across pages if needed; today only consumed by
  /routes/optimize/+page.svelte.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "$lib/api";
  import { flash } from "$lib/stores";
  import { debounce } from "$lib/utils";

  type HallReport = {
    ok: boolean;
    n_classes: number;
    n_teachers: number;
    violations: Array<{ kind: string; msg?: string }>;
    stats: {
      total_demand_hours: number;
      total_supply_hours: number;
      n_subjects: number;
      n_samples: number;
    };
  };

  let busyHall = false;
  let hallReport: HallReport | null = null;

  async function runHallPrecheck() {
    busyHall = true;
    try {
      hallReport = await api.post(
        "/api/diagnostics/hall-check",
        { n_samples: 256, sync: true },
      );
      flash(
        hallReport!.ok
          ? `Hall OK: nessuna violazione strutturale (${hallReport!.n_classes} classi, ${hallReport!.n_teachers} docenti)`
          : `Hall: ${hallReport!.violations.length} violazioni rilevate`,
        hallReport!.ok ? "success" : "warning",
      );
    } catch (e: any) {
      flash("Errore Hall pre-check: " + e.message, "error");
    } finally {
      busyHall = false;
    }
  }

  type Preset = {
    key: string;
    label: string;
    summary: string;
    expression: string;
  };
  type ValidateResult = {
    ok: boolean;
    direction: string | null;
    errors: string[];
  };

  export let onLaunch: (payload: {
    criterion: string;
    custom_expression: string | null;
    time_limit_s: number;
    workers: number;
    log: boolean;
  }) => void = () => {};

  // Step settings (mirror of what was in step2 in +page.svelte).
  export let time_limit_s = 30;
  export let workers = 8;
  export let log = true;

  let presets: Preset[] = [];
  let selectedKey = "balance_curricula";
  let customExpression =
    "minimize 50 * total_unused_capacity\n" +
    "       + 100 * total_n_classes\n" +
    "       - 5 * total_n_curricula\n" +
    "       + 5000 * n_under_18";
  let showActive = false;
  let validateResult: ValidateResult | null = null;
  let validateBusy = false;

  $: isCustom = selectedKey === "custom";
  $: activePreset = presets.find((p) => p.key === selectedKey) ?? null;
  $: activeExpression = isCustom
    ? customExpression
    : activePreset?.expression ?? "";

  onMount(async () => {
    try {
      presets = await api.get<Preset[]>("/api/optimize/phase-a/presets");
    } catch (e: unknown) {
      // graceful degrade: keep an empty list and let user use "custom"
      console.error("[phase-a] presets load failed", e);
    }
  });

  // Debounced live validation when typing in the custom editor.
  const validateNow = debounce(async (expr: string) => {
    if (!expr.trim()) {
      validateResult = null;
      return;
    }
    validateBusy = true;
    try {
      validateResult = await api.post<ValidateResult>(
        "/api/optimize/phase-a/validate-expression",
        { expression: expr },
      );
    } catch (e: unknown) {
      validateResult = {
        ok: false,
        direction: null,
        errors: [(e as Error)?.message ?? String(e)],
      };
    } finally {
      validateBusy = false;
    }
  }, 350);
  $: if (isCustom) validateNow(customExpression);

  function loadIntoCustom(p: Preset) {
    selectedKey = "custom";
    customExpression = p.expression
      // Pretty-print the DSL: split each top-level term onto its own
      // line so it reads as a column.
      .replace(/\s*\+\s*/g, "\n+ ")
      .replace(/\s*-\s*/g, "\n- ")
      // Re-attach the leading minimize/maximize on its own line.
      .replace(/^(minimize|maximize)\n([+-])/, "$1 $2")
      .replace(/^(minimize|maximize)/, "$1");
  }

  function launch() {
    onLaunch({
      criterion: selectedKey,
      custom_expression: isCustom ? customExpression : null,
      time_limit_s,
      workers,
      log,
    });
  }
</script>

<div class="card p-5 space-y-4">
  <div class="flex items-baseline justify-between flex-wrap gap-2">
    <h2 class="!mb-0">2) Assegnazione docenti -&gt; classi</h2>
    <span class="text-xs text-ink-500">
      Phase A: chi insegna cosa, in quale classe, per quante ore.
    </span>
  </div>

  <!-- Time / workers params -->
  <div class="grid grid-cols-2 gap-3">
    <div class="field">
      <label>Time-limit (s)</label>
      <input type="number" bind:value={time_limit_s} min="1" />
    </div>
    <div class="field">
      <label>Workers</label>
      <input type="number" bind:value={workers} min="1" />
    </div>
  </div>

  <!-- Criterion selector -->
  <div>
    <h3 class="!text-base mb-2">Criterio di ottimizzazione</h3>
    <p class="text-xs text-ink-500 mb-2">
      Determina cosa minimizzare nella scelta della cattedra:
      bilanciamento, concentrazione, cattedre piene, ecc.
    </p>
    <div class="space-y-1.5">
      {#each presets as p (p.key)}
        <label class="flex items-start gap-2 p-2 rounded hover:bg-ink-50 cursor-pointer
                      border transition-colors"
               class:border-accent-500={selectedKey === p.key}
               class:bg-accent-500={selectedKey === p.key}
               class:!text-white={selectedKey === p.key}
               class:border-ink-200={selectedKey !== p.key}>
          <input type="radio" name="phase-a-criterion"
                 value={p.key} bind:group={selectedKey}
                 class="mt-1 shrink-0"/>
          <div class="flex-1 min-w-0">
            <div class="font-medium text-sm">{p.label}</div>
            <div class="text-xs"
                 class:text-white={selectedKey === p.key}
                 class:opacity-80={selectedKey === p.key}
                 class:text-ink-500={selectedKey !== p.key}>
              {p.summary}
            </div>
          </div>
          {#if selectedKey !== p.key}
            <button type="button"
                    class="btn !text-xs !px-1.5 !py-0.5 self-center"
                    title="Carica questa espressione nell'editor custom"
                    on:click|stopPropagation|preventDefault={() => loadIntoCustom(p)}>
              edita
            </button>
          {/if}
        </label>
      {/each}

      <!-- Custom -->
      <label class="flex items-start gap-2 p-2 rounded cursor-pointer border transition-colors"
             class:border-accent-500={selectedKey === 'custom'}
             class:bg-accent-500={selectedKey === 'custom'}
             class:!text-white={selectedKey === 'custom'}
             class:border-ink-200={selectedKey !== 'custom'}>
        <input type="radio" name="phase-a-criterion"
               value="custom" bind:group={selectedKey}
               class="mt-1 shrink-0"/>
        <div class="flex-1 min-w-0">
          <div class="font-medium text-sm">Custom</div>
          <div class="text-xs"
               class:text-white={selectedKey === 'custom'}
               class:opacity-80={selectedKey === 'custom'}
               class:text-ink-500={selectedKey !== 'custom'}>
            Scrivi un'espressione obiettivo nel DSL piTantum (vedere
            <code>docs/objective_dsl.md</code>).
          </div>
        </div>
      </label>
    </div>
  </div>

  <!-- Custom editor -->
  {#if isCustom}
    <div>
      <label class="text-xs font-medium text-ink-700">
        Espressione DSL
      </label>
      <textarea bind:value={customExpression}
                rows="6"
                class="w-full mt-1 font-mono text-xs border border-ink-300 rounded p-2"
                placeholder="minimize ... + ... + ..."
                spellcheck="false"></textarea>
      <div class="mt-1 flex items-baseline gap-2 flex-wrap text-xs">
        {#if validateBusy}
          <span class="text-ink-500">Validazione...</span>
        {:else if validateResult?.ok}
          <span class="text-emerald-700">
            ✓ Espressione valida ({validateResult.direction})
          </span>
        {:else if validateResult && !validateResult.ok}
          <span class="text-red-700">
            ✗ {validateResult.errors[0]}
          </span>
          {#if validateResult.errors.length > 1}
            <span class="text-ink-500">
              (+{validateResult.errors.length - 1} altri errori)
            </span>
          {/if}
        {/if}
      </div>
      <details class="mt-2 text-xs text-ink-600">
        <summary class="cursor-pointer hover:text-ink-900">
          Aiuto sintassi DSL
        </summary>
        <div class="mt-1 pl-3 space-y-1 border-l-2 border-ink-200">
          <p><strong>Direzione</strong>: <code>minimize</code> o <code>maximize</code> all'inizio.</p>
          <p><strong>Variabili scalari</strong>:
            <code>total_unused_capacity</code>,
            <code>total_n_classes</code>,
            <code>total_n_curricula</code>,
            <code>total_weight</code>,
            <code>n_under_18</code>,
            <code>n_under_10</code>.
          </p>
          <p><strong>Aggregati</strong>: <code>sum(x)</code>, <code>count(x)</code> dove
            <code>x</code> e' una variabile per-docente o un predicato.</p>
          <p><strong>Variabili per-docente</strong> (solo dentro sum/count):
            <code>teacher_hours</code>, <code>teacher_unused</code>,
            <code>teacher_n_classes</code>, <code>teacher_n_curricula</code>,
            <code>teacher_weight</code>.
          </p>
          <p><strong>Predicati</strong>:
            <code>under_min_hours(N)</code>, <code>over_min_hours(N)</code>,
            <code>cross_curricula()</code>, <code>single_curriculum()</code>,
            <code>empty_teacher()</code>.
          </p>
          <p><strong>Operatori</strong>: <code>+ - * /</code> con coefficiente
            costante su almeno un lato (no var*var: non lineare).</p>
          <p><em>Esempio</em>:
            <code>minimize 100*total_n_classes + 5000*sum(under_min_hours(18))</code>
          </p>
        </div>
      </details>
    </div>
  {/if}

  <!-- "Show active criteria" toggle -->
  <div>
    <button type="button"
            class="text-xs text-accent-500 hover:underline"
            on:click={() => (showActive = !showActive)}>
      {showActive ? '▾' : '▸'}
      {showActive
        ? 'Nascondi DSL attivo'
        : 'Mostra DSL attivo nel modello'}
    </button>
    {#if showActive}
      <pre class="mt-1 text-xs bg-ink-50 border border-ink-200 rounded p-2 overflow-x-auto whitespace-pre-wrap"
          >{activeExpression || '(seleziona un criterio)'}</pre>
    {/if}
  </div>

  <div class="border-t border-ink-200 pt-3 mt-1">
    <div class="flex items-baseline gap-2 mb-1">
      <h3 class="!text-sm">Pre-check fattibilita' strutturale</h3>
      <span class="pill pill-amber !text-[10px]">Hall (diagnostico)</span>
    </div>
    <p class="text-[11px] text-ink-500 mb-2">
      Verifica via teorema di Hall che la capacita' dei docenti
      qualificati copra la domanda di ore per materia. Esegui prima
      di Phase A per evitare assegnazioni inutilmente lunghe su
      istanze gia' infeasible al livello strutturale.
    </p>
    <button class="btn !text-xs" type="button"
            on:click={runHallPrecheck}
            disabled={busyHall}>
      {busyHall ? "Pre-check in corso..." : "Pre-check fattibilita' strutturale"}
    </button>
    {#if hallReport}
      <div class="mt-2 text-xs">
        <div class={hallReport.ok ? "text-emerald-700" : "text-rose-700"}>
          <strong>{hallReport.ok ? "Feasible (Hall OK)" : "INFEASIBILE"}</strong>
          - {hallReport.n_classes} classi, {hallReport.n_teachers} docenti
          - domanda {hallReport.stats.total_demand_hours}h / supply
          {hallReport.stats.total_supply_hours}h
        </div>
        {#if hallReport.violations.length}
          <ul class="list-disc ml-5 mt-1 text-rose-700">
            {#each hallReport.violations.slice(0, 5) as v}
              <li>{v.msg ?? v.kind}</li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}
  </div>

  <button class="btn-primary"
          on:click={launch}
          disabled={isCustom && validateResult !== null && !validateResult.ok}>
    Avvia assegnazione
  </button>
</div>
