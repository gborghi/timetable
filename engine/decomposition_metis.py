"""Decomposizione METIS (k-way multilevel partitioning).

Idea
----
METIS e' una libreria classica per partitioning di grafi che
implementa l'algoritmo "multilevel k-way": il grafo viene
prima collassato (matching pesato), poi partizionato sul grafo
piccolo, poi raffinato risalendo i livelli. Sui grafi densi
(dove la spettrale fatica perche' lo spettro non separa i
cluster) METIS funziona spesso meglio.

Vantaggi rispetto alla spettrale
--------------------------------
- Funziona su grafi densi senza struttura comunitaria evidente.
- Bilanciamento dei cluster diretto (vincolo 'imbalance' < x%).
- Velocissimo anche su grafi grandi.

Limiti
------
- Richiede `pymetis` o `nxmetis` come dipendenza esterna.
- Su grafi molto sparsi (modularita' alta), i cluster prodotti
  sono sub-ottimali rispetto allo spectral cluster.

API
---
Espone le stesse funzioni della spettrale per integrazione:

    metis_cluster(M, k, imbalance=1.05)
        -> labels (np.array)

    auto_k_metis(M, k_min=2, k_max=8)
        -> k* suggerito (radice del numero di nodi)

    find_bridges, partition_metrics
        -> riusati dal modulo curriculum (stessa interfaccia)
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np

# Riusa le metriche dal modulo curriculum (stessa interfaccia).
# Import "soft" via importlib per non rompere se questo modulo
# viene caricato fuori dal package (es. dal CLI di engine).
try:  # package import (preferito)
    from .decomposition_curriculum import (  # noqa: F401
        find_bridges, partition_metrics,
    )
except ImportError:  # standalone script execution
    from decomposition_curriculum import (  # type: ignore[no-redef]  # noqa: F401
        find_bridges, partition_metrics,
    )


def _has_pymetis() -> bool:
    try:
        import pymetis  # noqa: F401
        return True
    except ImportError:
        return False


def _balanced_kway_fallback(M: np.ndarray, k: int,
                            imbalance: float = 1.05,
                            max_iter: int = 50) -> np.ndarray:
    """Pure-Python balanced k-way partitioner (METIS fallback).

    Used when pymetis is not installed (typical on Windows where
    pymetis requires a C++ toolchain). The algorithm is a simple
    multilevel-inspired greedy:

      1. initial partition: spectral embedding (top-k eigenvectors
         of the normalized Laplacian) -> KMeans with k clusters,
         producing a partition that respects the graph structure
         (same routine as decomposition_spectral_v2).
      2. balancing pass: while any cluster has more than
         imbalance * (n / k) members, move the member with the
         lowest "internal connection score" to the cluster that
         minimises the cut increase, until all clusters are within
         the imbalance bound.
      3. refinement pass (Kernighan-Lin like): iterate over all
         pairs of nodes in different clusters; compute the swap
         gain (delta of cut weight); apply the best positive swap
         and continue until no positive swap remains or max_iter
         is reached.

    Produces a labels array shape-compatible with `metis_cluster`,
    and preserves the imbalance constraint.
    """
    n = len(M)
    if n == 0 or k <= 1:
        return np.zeros(n, dtype=np.int32)
    A = M.astype(float)
    d = A.sum(axis=1)
    d_safe = np.where(d > 0, d, 1.0)
    inv_sqrt = 1.0 / np.sqrt(d_safe)
    L = np.eye(n) - (A * inv_sqrt[:, None]) * inv_sqrt[None, :]
    eigvals, eigvecs = np.linalg.eigh(L)
    emb = eigvecs[:, :k]
    nrm = np.linalg.norm(emb, axis=1, keepdims=True)
    nrm[nrm == 0] = 1
    emb = emb / nrm
    # Initial partition via KMeans
    try:
        from sklearn.cluster import KMeans
        labels = KMeans(n_clusters=k, random_state=42,
                        n_init=10).fit_predict(emb)
    except ImportError:
        # Crude fallback: round-robin
        labels = np.array([i % k for i in range(n)], dtype=np.int32)

    target = n / k
    upper = int(math.ceil(target * imbalance))

    def cluster_size(lbl_arr, c):
        return int(np.sum(lbl_arr == c))

    def cut_to_cluster(node, c, lbl_arr):
        # Sum of edge weights from `node` to current members of c
        return float(A[node, lbl_arr == c].sum())

    # Balancing pass: move nodes out of overweight clusters
    for _ in range(max_iter):
        sizes = np.array([cluster_size(labels, c) for c in range(k)])
        if sizes.max() <= upper:
            break
        # find largest cluster
        big = int(np.argmax(sizes))
        # find member with smallest internal weight (i.e. weakest tie)
        members = np.where(labels == big)[0]
        internal = np.array([cut_to_cluster(m, big, labels) for m in members])
        weakest = int(members[np.argmin(internal)])
        # move it to the smallest cluster that's not overweight,
        # preferring one with maximum tie strength
        candidates = [c for c in range(k)
                      if c != big and sizes[c] < upper]
        if not candidates:
            break
        gains = [cut_to_cluster(weakest, c, labels) for c in candidates]
        best = candidates[int(np.argmax(gains))]
        labels[weakest] = best

    # Refinement pass: KL-like pairwise swaps
    for it in range(max_iter):
        improved = False
        for i in range(n):
            for j in range(i + 1, n):
                if labels[i] == labels[j]:
                    continue
                # gain = delta in (- cut weight) if we swap labels of i and j
                ci, cj = int(labels[i]), int(labels[j])
                # current contribution of (i, j) to cut: A[i,j] (cross-cluster)
                cur = (cut_to_cluster(i, cj, labels) +
                       cut_to_cluster(j, ci, labels) -
                       cut_to_cluster(i, ci, labels) -
                       cut_to_cluster(j, cj, labels) +
                       2 * A[i, j])
                if cur > 1e-9:
                    labels[i], labels[j] = cj, ci
                    improved = True
        if not improved:
            break

    return labels.astype(np.int32)


def metis_cluster(M: np.ndarray, k: int, imbalance: float = 1.05) -> np.ndarray:
    """Partitioning k-way bilanciato del grafo di adiacenza.

    Parameters
    ----------
    M : np.ndarray, shape (n, n)
        Matrice di adiacenza simmetrica con pesi interi non
        negativi (numero di docenti in comune fra le due classi).
    k : int
        Numero di partizioni da produrre.
    imbalance : float, default 1.05
        Tolleranza di sbilanciamento (1.05 = al massimo +5% di
        differenza fra il cluster piu' grande e l'ideale).

    Returns
    -------
    labels : np.ndarray of int (len = n)
        Etichetta del cluster per ciascuna classe.

    Raises
    ------
    ImportError
        Se pymetis non e' installato. In quel caso il sistema
        suggerisce all'utente di scegliere la decomposizione
        spettrale o di installare pymetis.
    """
    if not _has_pymetis():
        # Pure-Python fallback. Same shape, comparable quality on
        # graphs of school-timetabling size (n < 200). For larger
        # instances install pymetis (Linux/macOS via pip; Windows
        # via conda or prebuilt wheel).
        return _balanced_kway_fallback(M, k, imbalance=imbalance)
    import pymetis

    n = len(M)
    # METIS vuole adjacency lists con pesi; costruisco xadj/adjncy/adjwgt.
    xadj = [0]
    adjncy: list[int] = []
    adjwgt: list[int] = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            w = int(M[i, j])
            if w > 0:
                adjncy.append(j)
                adjwgt.append(w)
        xadj.append(len(adjncy))
    _, parts = pymetis.part_graph(
        k,
        xadj=xadj,
        adjncy=adjncy,
        eweights=adjwgt,
        options=pymetis.Options(ufactor=int((imbalance - 1) * 1000)),
    )
    return np.asarray(parts, dtype=np.int32)


def auto_k_metis(M: np.ndarray, k_min: int = 2, k_max: int = 8) -> int:
    """Heuristica per scegliere k: radice quadrata del numero di
    nodi, vincolata in [k_min, k_max].

    L'idea e' che cluster di taglia sqrt(n) sono un buon
    compromesso fra costo del singolo cluster e overhead della
    ricucitura.
    """
    n = len(M)
    raw = max(1, round(math.sqrt(n)))
    return max(k_min, min(k_max, raw))


def solve_with_metis_decomposition(
    profs: dict,
    *,
    k: int | None = None,
    imbalance: float = 1.05,
    time_a: float = 60.0,
    time_bridges: float = 30.0,
    time_per_cluster: float = 30.0,
    time_ricucitura: float = 60.0,
    time_mono: float = 120.0,
    workers: int = 8,
    log: bool = False,
    dc_value: dict | None = None,
    locked_day_count: dict | None = None,
    locked_by_day: dict | None = None,
    coteach_groups: list | None = None,
    support_assignments: list | None = None,
    parallel_groups: list | None = None,
    group_assignments: list | None = None,
    class_day_load_allowed: dict | None = None,
    special_room_ctx=None,
    plessi_ctx=None,
):
    """Pipeline end-to-end: METIS k-way partitioning + Stage A/B/C/mono.

    Builds clusters via pymetis (or raises ImportError with a clear
    install hint), identifies bridge teachers, and delegates the
    day-wise CP-SAT loop to the shared
    `decomposition_loop.run_partitioned_pipeline`.

    Parameters
    ----------
    profs : dict
        Phase A output.
    k : int, optional
        Number of partitions; default = auto_k_metis(M).
    imbalance : float, default 1.05
        Tolerated imbalance ratio in the partitioner.
    time_a, time_bridges, time_per_cluster, time_ricucitura,
    time_mono : float
        CP-SAT budgets, in seconds.
    workers : int
        CP-SAT search workers per stage.
    log : bool
        If True, log progress on stdout.
    dc_value : dict, optional
        Pre-computed Phase A; if None, the master is run inside.
    """
    import decomposition_loop as dl  # type: ignore
    import decomposition_spectral_v2 as dec_s  # type: ignore

    # Build adjacency from profs (same routine as spectral)
    M, classes, _ = dec_s.build_adjacency(profs)
    if k is None:
        k = auto_k_metis(M)
    labels = metis_cluster(M, k, imbalance=imbalance)
    bridges = find_bridges(profs, classes, labels)
    return dl.run_partitioned_pipeline(
        profs, labels, classes, bridges,
        time_a=time_a, time_bridges=time_bridges,
        time_cluster=time_per_cluster,
        time_ricucitura=time_ricucitura, time_mono=time_mono,
        workers=workers, log=log, dc_value=dc_value,
        locked_day_count=locked_day_count,
        locked_by_day=locked_by_day,
        coteach_groups=coteach_groups,
        support_assignments=support_assignments,
        parallel_groups=parallel_groups,
        group_assignments=group_assignments,
        class_day_load_allowed=class_day_load_allowed,
        special_room_ctx=special_room_ctx,
        plessi_ctx=plessi_ctx,
    )
