<!--
  Network graph for the Dashboard "Grafo" panel.

  Two modes (`mode` prop):
    - 'classes':  one node per SchoolClass; edges weighted by # shared
                   teachers.
    - 'teachers': one node per Teacher;     edges weighted by # shared
                   classes.

  Renders with Cytoscape.js + fcose force-directed layout.
  Brand palette (indigo / gold / terra) is applied to nodes/edges.
  Pan / zoom / drag-to-reposition come for free with Cytoscape.

  Tooltip: hover a node or edge to see counts + the list of shared
  entities. The tooltip is a plain absolute-positioned <div> driven by
  Cytoscape's mouseover/mouseout events.
-->
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api } from "$lib/api";
  import { mutationCounter } from "$lib/stores";

  export let mode: "classes" | "teachers" = "classes";
  export let height = 540;

  // Track the previous mode and mutationCounter so we can react to
  // changes without using `{#key}` outside (which can race with
  // Cytoscape's destroy/init cycle).
  let prevMode: typeof mode = mode;
  let prevCounter = -1;
  let mounted = false;

  type GraphNode = {
    id: string;
    label: string;
    kind: "class" | "teacher";
    meta: Record<string, unknown>;
  };
  type GraphEdge = {
    source: string;
    target: string;
    weight: number;
    shared: string[];
  };
  type GraphPayload = {
    mode: string;
    nodes: GraphNode[];
    edges: GraphEdge[];
    n_nodes: number;
    n_edges: number;
  };

  let container: HTMLDivElement;
  let cy: any = null;          // cytoscape Core instance
  let payload: GraphPayload | null = null;
  let loading = false;
  let errMsg: string | null = null;
  let tooltip = { show: false, x: 0, y: 0, html: "" };

  /** Fetch + render. Called on mount and on every `mode` change. */
  async function loadAndRender() {
    loading = true;
    errMsg = null;
    try {
      payload = await api.get<GraphPayload>(
        `/api/dashboard/graph?mode=${mode}`,
      );
      await render();
    } catch (e: any) {
      errMsg = e?.message || String(e);
    } finally {
      loading = false;
    }
  }

  /** Build / replace the Cytoscape graph. */
  async function render() {
    if (!container || !payload) return;
    // Lazy-load cytoscape so the dashboard chunk doesn't pay the cost
    // when the panel is hidden.
    const cytoscape = (await import("cytoscape")).default;
    const fcose = (await import("cytoscape-fcose")).default;
    try {
      (cytoscape as unknown as { use: (ext: unknown) => void }).use(fcose);
    } catch {
      /* already registered on hot-reload */
    }

    if (cy) {
      cy.destroy();
      cy = null;
    }

    const maxW = Math.max(1, ...payload.edges.map((e) => e.weight));
    // Brand palette
    const C_INDIGO = "#1e3a5f";
    const C_GOLD = "#c9a23a";
    const C_TERRA = "#9c4a1c";
    const C_INK = "#1f1f1f";
    const C_INK_300 = "#94a3b8";
    const C_BG = "#f7f1de";

    const elements = [
      ...payload.nodes.map((n) => ({
        data: {
          id: n.id,
          label: n.label,
          kind: n.kind,
          meta: n.meta,
        },
      })),
      ...payload.edges.map((e, i) => ({
        data: {
          id: `e${i}`,
          source: e.source,
          target: e.target,
          weight: e.weight,
          shared: e.shared,
          // Map weight (1..maxW) to stroke width (1.2..6).
          stroke: 1.2 + (4.8 * (e.weight - 1)) / Math.max(1, maxW - 1),
        },
      })),
    ];

    cy = cytoscape({
      container,
      elements,
      wheelSensitivity: 0.25,
      minZoom: 0.2,
      maxZoom: 3,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "background-color":
              mode === "classes" ? C_INDIGO : C_GOLD,
            "border-color": C_INDIGO,
            "border-width": 1.5,
            color: mode === "classes" ? "#ffffff" : C_INK,
            "font-size": 11,
            "font-weight": 600,
            "text-valign": "center",
            "text-halign": "center",
            "text-outline-color":
              mode === "classes" ? C_INDIGO : "#ffffff",
            "text-outline-width": 1,
            width: 32,
            height: 32,
          },
        },
        {
          selector: "edge",
          style: {
            "line-color": C_TERRA,
            "curve-style": "bezier",
            "target-arrow-shape": "none",
            opacity: 0.55,
            width: "data(stroke)",
          },
        },
        {
          selector: "node:active, node.cy-hover",
          style: {
            "background-color": C_TERRA,
            "border-color": C_TERRA,
          },
        },
        {
          selector: "edge.cy-hover",
          style: {
            "line-color": C_INDIGO,
            opacity: 1,
          },
        },
      ],
      layout: {
        name: "fcose",
        quality: "default",
        randomize: true,
        animate: false,
        nodeRepulsion: 6500,
        idealEdgeLength: 80,
        edgeElasticity: 0.45,
        gravity: 0.25,
        padding: 30,
      } as any,
    });

    // ----- Tooltip wiring -----
    function nodeTooltipHtml(d: any): string {
      const meta = d.meta || {};
      const lines: string[] = [`<div class="font-semibold">${escape(d.label)}</div>`];
      if (d.kind === "class") {
        if (meta.curriculum)
          lines.push(`<div class="text-xs">${escape(meta.curriculum)}</div>`);
        if (typeof meta.n_teachers === "number")
          lines.push(
            `<div class="text-xs">${meta.n_teachers} docenti, ` +
              `${(meta.subjects || []).length} materie</div>`,
          );
        const tt = (meta.teachers || []).slice(0, 12);
        if (tt.length)
          lines.push(
            `<div class="text-xs mt-1 max-w-xs">${tt
              .map(escape)
              .join(", ")}${(meta.teachers?.length ?? 0) > 12 ? " ..." : ""}</div>`,
          );
      } else {
        const subjs = meta.subjects || [];
        const cls = meta.classes || [];
        if (subjs.length)
          lines.push(
            `<div class="text-xs">${subjs.map(escape).join(", ")}</div>`,
          );
        lines.push(
          `<div class="text-xs">${meta.n_classes ?? cls.length} classi: ` +
            `${cls.slice(0, 12).map(escape).join(", ")}${
              cls.length > 12 ? " ..." : ""
            }</div>`,
        );
      }
      return lines.join("");
    }
    function edgeTooltipHtml(d: any): string {
      const w = d.weight;
      const list = (d.shared || []).slice(0, 12);
      const more = (d.shared || []).length > 12 ? " ..." : "";
      const noun = mode === "classes" ? "docenti" : "classi";
      return (
        `<div class="font-semibold">${w} ${noun} in comune</div>` +
        `<div class="text-xs mt-1 max-w-xs">${list
          .map(escape)
          .join(", ")}${more}</div>`
      );
    }
    function escape(s: unknown): string {
      return String(s ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    }

    cy.on("mouseover", "node, edge", (evt: any) => {
      const t = evt.target;
      t.addClass("cy-hover");
      const d = t.data();
      tooltip = {
        show: true,
        x: evt.renderedPosition?.x ?? 0,
        y: evt.renderedPosition?.y ?? 0,
        html: t.isNode() ? nodeTooltipHtml(d) : edgeTooltipHtml(d),
      };
    });
    cy.on("mousemove", (evt: any) => {
      if (!tooltip.show) return;
      tooltip = {
        ...tooltip,
        x: evt.renderedPosition?.x ?? tooltip.x,
        y: evt.renderedPosition?.y ?? tooltip.y,
      };
    });
    cy.on("mouseout", "node, edge", (evt: any) => {
      evt.target.removeClass("cy-hover");
      tooltip = { ...tooltip, show: false };
    });
  }

  // React to (a) mode prop changes after first mount, and (b) the
  // global mutationCounter being bumped (e.g. after an import run
  // finishes -- _runner in webui/backend/run_manager.py bumps it).
  $: if (mounted && mode !== prevMode) {
    prevMode = mode;
    void loadAndRender();
  }
  $: if (mounted && $mutationCounter !== prevCounter) {
    prevCounter = $mutationCounter;
    // Skip the initial subscription tick (counter starts at 0).
    if ($mutationCounter > 0) void loadAndRender();
  }

  onMount(() => {
    mounted = true;
    prevMode = mode;
    prevCounter = $mutationCounter;
    void loadAndRender();
  });

  onDestroy(() => {
    if (cy) {
      cy.destroy();
      cy = null;
    }
  });
</script>

<div class="relative w-full" style="height: {height}px;">
  {#if loading && !payload}
    <div class="absolute inset-0 flex items-center justify-center text-ink-500">
      Caricamento grafo...
    </div>
  {/if}
  {#if errMsg}
    <div class="absolute inset-0 flex items-center justify-center text-red-600 text-sm">
      Errore: {errMsg}
    </div>
  {/if}
  <div
    bind:this={container}
    class="w-full h-full rounded-md border border-ink-200 bg-white"
  ></div>

  {#if payload}
    <div class="absolute top-2 right-2 text-xs bg-white/85 border border-ink-200 rounded px-2 py-1 pointer-events-none">
      {payload.n_nodes} nodi &middot; {payload.n_edges} archi
    </div>
  {/if}

  {#if tooltip.show}
    <div
      class="pointer-events-none absolute z-10 text-xs bg-white border border-ink-300 rounded px-2 py-1 shadow-md"
      style="left: {tooltip.x + 14}px; top: {tooltip.y + 14}px; max-width: 320px"
    >
      {@html tooltip.html}
    </div>
  {/if}
</div>
