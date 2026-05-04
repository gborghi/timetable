r"""Graph-theoretic analysis of the teacher x class bipartite.

Three measures expose how amenable the school graph is to spectral
decomposition:

  1. **Modularity (Newman-Girvan)** of the natural partition
     (teacher-vs-class, or pre-computed clusters). High modularity
     => spectral decomposition will produce clean clusters with
     few cross-cluster bridges; low modularity => the graph is
     too entangled and spectral methods buy little.

  2. **Betweenness centrality** of "bridge" teachers (those that
     teach in multiple clusters). Identifies the critical-path
     nodes whose SOFT contribution drives the global score.

  3. **Edge density** of the adjacency matrix. Low density (~0.05)
     => well-separated clusters available; high density (~0.5+)
     => the graph is more like a clique and decomposition is
     ineffective.

All metrics are computed via networkx.
"""
from __future__ import annotations

import os
import sys
from typing import Any

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _build_class_graph(profs: dict):
    """Classes-as-nodes, edge weight = # shared teachers."""
    import networkx as nx
    g = nx.Graph()
    classes_per_teacher: dict[str, set[str]] = {}
    for t, info in profs.items():
        classes_per_teacher[t] = set((info.get("classi") or {}).keys())
    all_classes: set[str] = set()
    for cls in classes_per_teacher.values():
        all_classes |= cls
    for c in sorted(all_classes):
        g.add_node(c)
    cls_list = sorted(all_classes)
    for i, ci in enumerate(cls_list):
        for cj in cls_list[i + 1:]:
            shared = sum(
                1 for t, cs in classes_per_teacher.items()
                if ci in cs and cj in cs
            )
            if shared > 0:
                g.add_edge(ci, cj, weight=shared)
    return g


def _build_teacher_graph(profs: dict):
    """Teachers-as-nodes, edge weight = # shared classes."""
    import networkx as nx
    g = nx.Graph()
    classes_per_teacher: dict[str, set[str]] = {}
    for t, info in profs.items():
        g.add_node(t)
        classes_per_teacher[t] = set((info.get("classi") or {}).keys())
    teachers = sorted(profs.keys())
    for i, ti in enumerate(teachers):
        for tj in teachers[i + 1:]:
            shared = len(
                classes_per_teacher.get(ti, set())
                & classes_per_teacher.get(tj, set())
            )
            if shared > 0:
                g.add_edge(ti, tj, weight=shared)
    return g


def analyze(profs: dict, *, mode: str = "classes",
             top_betweenness: int = 10) -> dict[str, Any]:
    """Returns modularity (greedy partition), edge density, and the
    top-K betweenness centrality scores."""
    import networkx as nx
    if mode not in ("classes", "teachers"):
        raise ValueError(f"unknown mode: {mode}")
    g = _build_class_graph(profs) if mode == "classes" \
        else _build_teacher_graph(profs)
    n_nodes = g.number_of_nodes()
    n_edges = g.number_of_edges()
    if n_nodes < 2:
        return {
            "ok": False,
            "msg": "grafo troppo piccolo (n < 2)",
            "mode": mode,
        }
    # Density: 2|E| / (|V|*(|V|-1))
    density = (2.0 * n_edges) / (n_nodes * (n_nodes - 1))

    # Modularity via greedy modularity communities
    try:
        from networkx.algorithms.community import greedy_modularity_communities
        from networkx.algorithms.community.quality import modularity
        communities = list(greedy_modularity_communities(g))
        mod = float(modularity(g, communities))
    except Exception as e:  # noqa: BLE001
        communities = []
        mod = 0.0

    # Betweenness centrality
    bc = nx.betweenness_centrality(g, weight="weight", normalized=True)
    bc_sorted = sorted(bc.items(), key=lambda kv: kv[1], reverse=True)
    top_bc = [{"node": k, "betweenness": float(v)}
              for k, v in bc_sorted[:top_betweenness]]

    # Interpretation hints
    if density < 0.10:
        density_interp = ("Densita' bassa: cluster ben separati. La "
                          "decomposizione spettrale e' efficace.")
    elif density < 0.30:
        density_interp = ("Densita' media: la spettrale aiuta ma "
                          "alcune classi/docenti spaziano fra cluster.")
    else:
        density_interp = ("Densita' alta: il grafo e' quasi una cricca. "
                          "La spettrale non offre vantaggio sostanziale.")
    if mod >= 0.4:
        mod_interp = "Modularita' alta: partizione naturale chiara."
    elif mod >= 0.2:
        mod_interp = "Modularita' media: cluster discernibili ma non puliti."
    else:
        mod_interp = "Modularita' bassa: nessuna partizione utile."

    return {
        "ok": True,
        "mode": mode,
        "n_nodes": n_nodes,
        "n_edges": n_edges,
        "density": float(density),
        "density_interpretation": density_interp,
        "modularity": float(mod),
        "modularity_interpretation": mod_interp,
        "n_communities": len(communities),
        "community_sizes": sorted(
            (len(c) for c in communities), reverse=True
        ),
        "top_betweenness": top_bc,
    }


def analyze_from_db(db, *, mode: str = "classes") -> dict[str, Any]:
    from backend import engine_io  # type: ignore
    profs = engine_io.profs_dict_from_db(db)
    return analyze(profs, mode=mode)
