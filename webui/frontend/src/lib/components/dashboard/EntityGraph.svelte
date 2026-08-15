<!--
  Network graph for the Dashboard "Grafo" panel.

  Two modes (`mode` prop):
    - 'classes':  one node per SchoolClass; edges weighted by # shared
                   teachers.
    - 'teachers': one node per Teacher;     edges weighted by # shared
                   classes.

  Renders with Cytoscape.js + fcose force-directed layout.
  Modern palette (indigo / teal / rose) applied to nodes/edges.
  Pan / zoom / drag-to-reposition come for free with Cytoscape.

  Interactions:
    - Hover a node → 1st-degree neighbours glow, 2nd-degree neighbours
      light up subtly, everything else dims.
    - Hover an edge → edge highlights, endpoints glow.
    - Layout settles with an elastic spring animation.
-->
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { api } from "$lib/api";
  import { mutationCounter } from "$lib/stores";

  export let mode: "classes" | "teachers" = "classes";
  export let height = 560;

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
  let cy: any = null;
  let payload: GraphPayload | null = null;
  let loading = false;
  let errMsg: string | null = null;
  let tooltip = { show: false, x: 0, y: 0, html: "" };

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

  async function render() {
    if (!container || !payload) return;

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

    // ── Spherical gradient SVG (3D ball with highlight at upper-left) ──
    let _sid = 0;
    function sphereSvg(base: string, highlight: string, edge: string): string {
      const id = `g${++_sid}`;
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40">
  <defs>
    <radialGradient id="${id}" cx="32%" cy="28%" r="62%" fx="28%" fy="22%">
      <stop offset="0%" stop-color="${highlight}"/>
      <stop offset="35%" stop-color="${base}"/>
      <stop offset="85%" stop-color="${edge}"/>
      <stop offset="100%" stop-color="${edge}"/>
    </radialGradient>
  </defs>
  <circle cx="20" cy="20" r="18" fill="url(#${id})" stroke="${edge}" stroke-width="0.3"/>
</svg>`;
      return "data:image/svg+xml;base64," + btoa(svg);
    }

    // Class sphere: indigo
    const SPHERE_CLASS   = sphereSvg("#818cf8", "#c7d2fe", "#4338ca");
    // Teacher sphere: teal
    const SPHERE_TEACHER = sphereSvg("#2dd4bf", "#99f6e4", "#0f766e");
    // Hover sphere: rose
    const SPHERE_HOVER   = sphereSvg("#fb7185", "#fecdd3", "#be123c");
    // 1st-degree sphere: amber
    const SPHERE_N1      = sphereSvg("#fbbf24", "#fde68a", "#b45309");
    // 2nd-degree sphere: violet
    const SPHERE_N2      = sphereSvg("#a78bfa", "#ddd6fe", "#6d28d9");
    // Dimmed sphere: gray
    const SPHERE_DIM     = sphereSvg("#94a3b8", "#cbd5e1", "#64748b");

    const C_EDGE    = "#e2e8f0";
    const C_LABEL   = "#0f172a";
    const FONT      = '"Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';

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
          stroke: 0.6 + (3.4 * (e.weight - 1)) / Math.max(1, maxW - 1),
        },
      })),
    ];

    cy = cytoscape({
      container,
      elements,
      wheelSensitivity: 0.25,
      minZoom: 0.2,
      maxZoom: 3,
      style: ([
        // ── Nodes (idle) ──
        {
          selector: "node",
          style: {
            label: "data(label)",
            "background-image": mode === "classes" ? SPHERE_CLASS : SPHERE_TEACHER,
            "background-color": mode === "classes" ? "#818cf8" : "#2dd4bf",
            "background-width": "100%",
            "background-height": "100%",
            "border-width": 0,
            color: C_LABEL,
            "font-size": 8.5,
            "font-family": FONT,
            "font-weight": 500,
            "letter-spacing": "-0.01em",
            "text-valign": "center",
            "text-halign": "center",
            "text-outline-width": 0,
            "text-wrap": "ellipsis",
            "text-max-width": 72,
            width: 22,
            height: 22,
          },
        },
        // ── Edges ──
        {
          selector: "edge",
          style: {
            "line-color": C_EDGE,
            "curve-style": "bezier",
            "target-arrow-shape": "none",
            opacity: 0.55,
            width: "data(stroke)",
          },
        },
        // ── Hover ──
        {
          selector: "node.node-hover",
          style: {
            "background-image": SPHERE_HOVER,
            "background-color": "#fb7185",
            "background-width": "100%",
            "background-height": "100%",
            color: C_LABEL,
            "font-weight": 600,
            "font-size": 10,
            width: 28,
            height: 28,
          },
        },
        // ── 1st-degree ──
        {
          selector: "node.n1",
          style: {
            "background-image": SPHERE_N1,
            "background-color": "#fbbf24",
            "background-width": "100%",
            "background-height": "100%",
            color: C_LABEL,
            "font-weight": 600,
            "font-size": 9,
            width: 25,
            height: 25,
          },
        },
        { selector: "edge.n1", style: { "line-color": "#f59e0b", opacity: 0.7, width: 2.4 } },
        // ── 2nd-degree ──
        {
          selector: "node.n2",
          style: {
            "background-image": SPHERE_N2,
            "background-color": "#a78bfa",
            "background-width": "100%",
            "background-height": "100%",
            color: C_LABEL,
            "font-weight": 500,
            "font-size": 8.5,
            width: 23,
            height: 23,
          },
        },
        { selector: "edge.n2", style: { "line-color": "#a78bfa", opacity: 0.4 } },
        // ── Dimmed ──
        {
          selector: "node.dimmed",
          style: {
            "background-image": SPHERE_DIM,
            "background-color": "#94a3b8",
            "background-width": "100%",
            "background-height": "100%",
            opacity: 0.22,
            "font-size": 7.5,
            width: 17,
            height: 17,
          },
        },
        { selector: "edge.dimmed", style: { opacity: 0.06, "line-color": "#cbd5e1" } },
      ] as any),

      layout: {
        name: "fcose",
        quality: "default",
        randomize: true,
        // Elastic spring-in animation
        animate: "end",
        animationDuration: 1200,
        animationEasing: "ease-out",
        // Repulsion/spread tuned for readable clusters
        nodeRepulsion: 9000,
        idealEdgeLength: 70,
        edgeElasticity: 0.35,
        gravity: 0.2,
        padding: 35,
      } as any,
    });

    // ═══════════════════════════════════════════════════
    //  Neighbourhood highlight helpers
    // ═══════════════════════════════════════════════════
    let pinnedNode: any = null;

    /** Compute and apply n1/n2/dimmed classes for a node. */
    function applyHighlight(node: any) {
      const n1 = node.closedNeighborhood().nodes().difference(node);
      const n1Edges = node.connectedEdges();
      const n2 = n1.closedNeighborhood().nodes().difference(node).difference(n1);
      const n2Edges = n1.connectedEdges().difference(n1Edges);

      const allNodes = cy.nodes();
      const allEdges = cy.edges();
      const highlightNodes = node.union(n1).union(n2);
      const highlightEdges = n1Edges.union(n2Edges);

      cy.batch(() => {
        allNodes.difference(highlightNodes).addClass("dimmed");
        allEdges.difference(highlightEdges).addClass("dimmed");
        n1.addClass("n1");
        n1Edges.addClass("n1");
        n2.addClass("n2");
        n2Edges.addClass("n2");
      });
    }

    /** Remove all highlight/dim classes from every element. */
    function clearAllHighlights() {
      cy.batch(() => {
        cy.nodes().removeClass("dimmed n1 n2");
        cy.edges().removeClass("dimmed n1 n2");
      });
    }

    // ── Position animation helpers ──
    let savedPositions: Record<string, {x:number;y:number}> | null = null;

    function savePositions() {
      savedPositions = {};
      cy.nodes().forEach((n: any) => {
        savedPositions![n.id()] = { ...n.position() };
      });
    }

    function animateToTargets(targets: Record<string, {x:number;y:number}>, duration = 550, onDone?: () => void) {
      const start = performance.now();
      const starts: Record<string, {x:number;y:number}> = {};
      cy.nodes().forEach((n: any) => { starts[n.id()] = { ...n.position() }; });

      function step(now: number) {
        const raw = Math.min(1, (now - start) / duration);
        // Elastic-out easing
        const t = raw === 1 ? 1 : 1 - Math.pow(2, -10 * raw) * Math.cos((raw * 10 - 0.75) * ((2 * Math.PI) / 3));
        cy.batch(() => {
          cy.nodes().forEach((n: any) => {
            const s = starts[n.id()];
            const tg = targets[n.id()];
            if (!tg) return;
            n.position({ x: s.x + (tg.x - s.x) * t, y: s.y + (tg.y - s.y) * t });
          });
        });
        if (raw < 1) {
          requestAnimationFrame(step);
        } else if (onDone) {
          onDone();
        }
      }
      requestAnimationFrame(step);
    }

    function animateRestore(duration = 500) {
      if (!savedPositions) return;
      animateToTargets(savedPositions, duration, () => { cy.fit(undefined, 30); });
      savedPositions = null;
    }

    function animatePinNode(node: any) {
      const pos = node.position();
      const n1 = node.closedNeighborhood().nodes().difference(node);
      const n2 = n1.closedNeighborhood().nodes().difference(node).difference(n1);
      const rest = cy.nodes().difference(node.union(n1).union(n2));

      // Graph center
      const allNodes = cy.nodes();
      let cx = 0, cy_ = 0;
      allNodes.forEach((n: any) => { const p = n.position(); cx += p.x; cy_ += p.y; });
      cx /= allNodes.length; cy_ /= allNodes.length;

      // Direction from center → selected node
      let dx = pos.x - cx;
      let dy = pos.y - cy_;
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      dx /= len; dy /= len;

      // Use model-space distances: compute graph bounding-box size
      const bb = cy.elements().boundingBox();
      const graphW = bb.w || 800;
      const graphH = bb.h || 600;
      const graphScale = Math.max(graphW, graphH);

      // Push: a fraction of the graph extent — small enough to stay visible
      const push = graphScale * 0.1;

      const targets: Record<string, {x:number;y:number}> = {};

      // Selected node: pushed away from center
      targets[node.id()] = { x: pos.x + dx * push, y: pos.y + dy * push };
      const selX = pos.x + dx * push;
      const selY = pos.y + dy * push;

      // Neighbours: follow
      n1.union(n2).forEach((n: any) => {
        const p = n.position();
        const dist = Math.sqrt((p.x - pos.x) ** 2 + (p.y - pos.y) ** 2) || 1;
        const follow = Math.max(0.2, 1 - dist / graphScale);
        targets[n.id()] = { x: p.x + dx * push * follow, y: p.y + dy * push * follow };
      });

      // Non-neighbours: repelled radially from selected node
      rest.forEach((n: any) => {
        const p = n.position();
        let rdx = p.x - selX;
        let rdy = p.y - selY;
        const rlen = Math.sqrt(rdx * rdx + rdy * rdy) || 1;
        rdx /= rlen; rdy /= rlen;
        const repulse = push * 0.55 * (graphScale / Math.max(rlen, 1));
        targets[n.id()] = { x: p.x + rdx * repulse, y: p.y + rdy * repulse };
      });

      // After animation completes, fit the graph to viewport
      const fit = () => {
        cy.fit(undefined, 30);
      };

      animateToTargets(targets, 700, fit);
    }

    // ═══════════════════════════════════════════════════
    //  Click: toggle pin with elastic animation
    // ═══════════════════════════════════════════════════
    cy.on("click", "node", (evt: any) => {
      const node = evt.target;
      if (pinnedNode === node) {
        // Re-click on pinned node → unpin and restore positions
        pinnedNode = null;
        node.removeClass("node-hover");
        clearAllHighlights();
        animateRestore(500);
      } else {
        // Save positions before first pin
        if (!pinnedNode && !savedPositions) savePositions();
        // If switching pins, first restore, then re-animate
        if (pinnedNode && savedPositions) {
          animateRestore(300);
          // Wait for restore then re-pin (simplified: just go)
          setTimeout(() => {
            if (!savedPositions) savePositions();
            clearAllHighlights();
            pinnedNode = node;
            node.addClass("node-hover");
            applyHighlight(node);
            animatePinNode(node);
          }, 320);
          return;
        }
        pinnedNode = node;
        clearAllHighlights();
        node.addClass("node-hover");
        applyHighlight(node);
        animatePinNode(node);
      }
    });

    cy.on("click", (evt: any) => {
      if (evt.target === cy) {
        pinnedNode = null;
        clearAllHighlights();
        cy.nodes().removeClass("node-hover");
        animateRestore(500);
        tooltip = { ...tooltip, show: false };
      }
    });

    // ═══════════════════════════════════════════════════
    //  Click only — no hover, no tooltip
    // ═══════════════════════════════════════════════════

    // ── Tooltip helpers ──
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
  }

  $: if (mounted && mode !== prevMode) {
    prevMode = mode;
    void loadAndRender();
  }
  $: if (mounted && $mutationCounter !== prevCounter) {
    prevCounter = $mutationCounter;
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
    <div class="absolute inset-0 flex items-center justify-center text-slate-400 text-sm">
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
    class="w-full h-full rounded-lg border border-slate-200 bg-white"
  ></div>

  {#if payload}
    <div class="absolute top-2 right-2 text-[10px] bg-white/90 border border-slate-200 rounded-md px-2 py-1 pointer-events-none text-slate-400">
      {payload.n_nodes} nodi &middot; {payload.n_edges} archi
    </div>
  {/if}

  {#if tooltip.show}
    <div
      class="pointer-events-none absolute z-10 text-xs bg-white border border-slate-200 rounded-lg px-3 py-2 shadow-lg"
      style="left: {tooltip.x + 16}px; top: {tooltip.y + 12}px; max-width: 320px"
    >
      {@html tooltip.html}
    </div>
  {/if}
</div>
