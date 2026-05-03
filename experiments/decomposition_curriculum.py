"""Decomposizione per curriculum (indirizzo di studio).

Idea
----
Le scuole italiane organizzano le proprie classi per indirizzo di
studio (Liceo Scientifico, Liceo Classico, ITIS Informatica, ecc.).
I docenti tendono a insegnare prevalentemente all'interno di uno
stesso indirizzo, e il grafo bipartito classe-docente riflette
spesso questa struttura. La decomposizione per curriculum sfrutta
direttamente questa informazione (gia' codificata nel campo
`curriculum_id` di ogni classe) per produrre cluster di classi
omogenei per indirizzo. I docenti che insegnano in piu' indirizzi
diventano i "ponti" fra cluster.

Vantaggi rispetto a quella spettrale
------------------------------------
- Non richiede di calcolare autovettori; e' istantanea.
- Produce cluster prevedibili e interpretabili (un cluster = un
  indirizzo).
- L'utente puo' raggruppare manualmente curricula piccoli per
  evitare cluster con poche classi.

Limiti
------
- Ignora completamente la connettivita' effettiva del grafo: se
  un indirizzo "Linguistico" condivide molti docenti con
  "Scientifico" perche' per ragioni storiche i docenti di lingue
  insegnano in entrambi, la decomposizione per curriculum li
  separa lo stesso e produce molti ponti.
- Non funziona se i curricula non sono definiti (es. scuola
  generalista mono-indirizzo).

API
---
Il modulo espone le stesse funzioni della spettrale per facilita'
di integrazione nella pipeline:

    build_clusters_by_curriculum(profs, classroom_to_curriculum,
                                 manual_groupings=None)
        -> labels (np.array), classes (sorted list)

    find_bridges(profs, classes, labels)
        -> bridge_teachers (set)

    partition_metrics(profs, classes, labels, bridges)
        -> dict con metriche descrittive

    auto_group_small_curricula(class_curriculum_map, min_classes=3)
        -> manual_groupings dict suggerito

`solve_with_curriculum_decomposition` e' lasciato come stub: la
soluzione effettiva di ogni cluster delega a `cpsat_v2_timetable`
(stesso pattern di `decomposition_spectral_v2`).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

import numpy as np


def build_clusters_by_curriculum(
    profs: dict,
    classroom_to_curriculum: dict[str, str],
    manual_groupings: dict[str, str] | None = None,
):
    """Suddivide le classi in cluster basati sul curriculum_id.

    Parameters
    ----------
    profs : dict
        Mappa nome_docente -> {"classi": list[str], "ore_per_classe": ...}.
    classroom_to_curriculum : dict
        Mappa nome_classe -> nome_indirizzo (stringa).
    manual_groupings : dict, optional
        Mappa nome_indirizzo -> nome_macro_cluster, per accorpare
        manualmente curricula piccoli. Se None, ogni indirizzo
        forma un cluster a se' stante.

    Returns
    -------
    labels : np.ndarray of int (len = n_classes)
        Etichetta del cluster per ciascuna classe.
    classes : list[str]
        Nomi classe ordinati.
    cluster_names : list[str]
        Nome (curriculum aggregato) del cluster i-esimo.
    """
    classes = sorted({c for p in profs.values() for c in p["classi"]})
    manual = manual_groupings or {}

    def cluster_of(class_name: str) -> str:
        curriculum = classroom_to_curriculum.get(class_name, "_unknown")
        return manual.get(curriculum, curriculum)

    cluster_for_class = [cluster_of(c) for c in classes]
    distinct = sorted(set(cluster_for_class))
    name_to_id = {n: i for i, n in enumerate(distinct)}
    labels = np.array([name_to_id[c] for c in cluster_for_class], dtype=np.int32)
    return labels, classes, distinct


def find_bridges(profs: dict, classes: list[str], labels: np.ndarray) -> set[str]:
    """Restituisce l'insieme dei docenti che insegnano in classi
    appartenenti a piu' di un cluster.
    """
    class_to_cluster = dict(zip(classes, labels))
    bridges = set()
    for teacher, info in profs.items():
        teacher_clusters = {
            class_to_cluster.get(c) for c in info["classi"] if c in class_to_cluster
        }
        teacher_clusters.discard(None)
        if len(teacher_clusters) > 1:
            bridges.add(teacher)
    return bridges


def partition_metrics(
    profs: dict,
    classes: list[str],
    labels: np.ndarray,
    bridges: set[str],
) -> dict:
    """Metriche descrittive del clustering."""
    n_clusters = int(labels.max()) + 1 if len(labels) else 0
    sizes = [int((labels == k).sum()) for k in range(n_clusters)]
    n_teachers = len(profs)
    return {
        "n_classes": len(classes),
        "n_clusters": n_clusters,
        "cluster_sizes": sizes,
        "balance_ratio": (max(sizes) / max(min(sizes), 1)) if sizes else 0.0,
        "n_bridges": len(bridges),
        "bridge_ratio": len(bridges) / max(n_teachers, 1),
    }


def auto_group_small_curricula(
    class_curriculum_map: dict[str, str],
    min_classes: int = 3,
) -> dict[str, str]:
    """Suggerisce un raggruppamento dei curricula con poche classi.

    Tutti i curricula con meno di `min_classes` classi vengono
    accorpati in un cluster '_misto'. Restituisce un dict
    `manual_groupings` da passare a `build_clusters_by_curriculum`.
    """
    counts = defaultdict(int)
    for curriculum in class_curriculum_map.values():
        counts[curriculum] += 1
    return {
        curriculum: "_misto"
        for curriculum, n in counts.items()
        if n < min_classes
    }


def solve_with_curriculum_decomposition(
    profs: dict,
    classroom_to_curriculum: dict[str, str],
    manual_groupings: dict[str, str] | None = None,
    *,
    time_per_cluster: float = 60.0,
    time_bridges: float = 60.0,
):
    """Stub: integra con cpsat_v2_timetable per risolvere ogni cluster.

    L'implementazione effettiva del solve riusa il pattern
    Stage A (bridges first) -> Stage B (cluster internals con
    bridges fissati) -> Stage C (ricucitura) gia' presente in
    `decomposition_spectral_v2.py`. Qui il modulo si occupa solo
    della partitioning logic; il loop di risoluzione e' delegato.
    """
    raise NotImplementedError(
        "Integrazione con cpsat_v2_timetable: vedi roadmap in "
        "docs/optimization_strategies.md, sezione 'Decomposizione "
        "per curriculum'. La logica di partitioning e' gia' qui; "
        "manca solo il wiring del solve loop, identico a "
        "decomposition_spectral_v2.run_decomposed_pipeline()."
    )
