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

# Riusa le metriche dal modulo curriculum (stessa interfaccia)
from .decomposition_curriculum import find_bridges, partition_metrics  # noqa: F401


def _has_pymetis() -> bool:
    try:
        import pymetis  # noqa: F401
        return True
    except ImportError:
        return False


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
        raise ImportError(
            "pymetis non installato. "
            "Installalo con `pip install pymetis` "
            "oppure scegli un altro metodo di decomposizione."
        )
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
    time_per_cluster: float = 60.0,
    time_bridges: float = 60.0,
):
    """Stub: pipeline end-to-end con clustering METIS + Stage A/B/C.

    Stesso pattern di `decomposition_spectral_v2.run_decomposed_pipeline`
    ma con `metis_cluster` al posto di `spectral_cluster`. Se k
    e' None, usa `auto_k_metis`.
    """
    raise NotImplementedError(
        "Wiring con cpsat_v2_timetable Stage A/B/C: vedi roadmap "
        "in docs/optimization_strategies.md, sezione "
        "'Decomposizione METIS'."
    )
