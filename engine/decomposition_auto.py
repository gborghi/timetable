"""Auto-detect della strategia di decomposizione ottimale.

Calcola due metriche descrittive del grafo bipartito
classe-docente (modularita' e densita') e su quella base
suggerisce la strategia di decomposizione piu' adatta:

- Modularita' alta (> 0.3) -> spettrale (cluster naturali).
- Densita' alta (> 0.6)    -> METIS (grafo denso, no cluster
                              spontanei).
- In tutti i casi          -> combinare con temporale per
                              parallelizzare sui sei giorni.

Il modulo restituisce una raccomandazione strutturata
(metrica + strategia + motivazione testuale) che il backend
espone via API e il frontend mostra come tooltip "Suggerimento"
nella card di Workflow.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np


@dataclass
class DecompositionRecommendation:
    """Contiene la raccomandazione del sistema all'utente."""
    primary_strategy: str   # 'spectral', 'metis', 'curriculum'
    combine_with_temporal: bool
    modularity: float
    density: float
    motivation: str

    def to_dict(self) -> dict:
        return {
            "primary_strategy": self.primary_strategy,
            "combine_with_temporal": self.combine_with_temporal,
            "modularity": round(self.modularity, 4),
            "density": round(self.density, 4),
            "motivation": self.motivation,
        }


def compute_modularity(M: np.ndarray, labels: np.ndarray | None = None) -> float:
    """Modularita' di Newman-Girvan del grafo di adiacenza M.

    Se `labels` e' None, calcola modularita' rispetto al
    clustering banale "ogni nodo nel suo cluster" (zero) e si
    delega l'utente al fatto che con clustering reale il valore
    pu\`o salire molto. Per la heuristica auto-detect basta una
    stima di "quanto modulare e' la struttura": si fa un
    clustering-spettrale veloce a k=4 e si misura la sua Q.
    """
    from sklearn.cluster import KMeans
    n = len(M)
    if n < 4:
        return 0.0
    A = M.astype(float)
    d = A.sum(axis=1)
    m_total = d.sum() / 2.0
    if m_total <= 0:
        return 0.0
    if labels is None:
        d_safe = np.where(d > 0, d, 1.0)
        inv_sqrt = 1.0 / np.sqrt(d_safe)
        L = np.eye(n) - (A * inv_sqrt[:, None]) * inv_sqrt[None, :]
        eigvals, eigvecs = np.linalg.eigh(L)
        emb = eigvecs[:, :4]
        nrm = np.linalg.norm(emb, axis=1, keepdims=True)
        nrm[nrm == 0] = 1
        emb = emb / nrm
        labels = KMeans(n_clusters=min(4, n), random_state=42, n_init=10) \
            .fit_predict(emb)
    Q = 0.0
    for i in range(n):
        for j in range(n):
            if labels[i] == labels[j]:
                Q += A[i, j] - (d[i] * d[j]) / (2.0 * m_total)
    return Q / (2.0 * m_total)


def compute_density(M: np.ndarray) -> float:
    """Densita' del grafo: archi presenti / archi possibili."""
    n = len(M)
    if n < 2:
        return 0.0
    edges = int((M > 0).sum() / 2)
    possible = n * (n - 1) // 2
    return edges / possible


def auto_detect_decomposition_strategy(profs: dict) -> DecompositionRecommendation:
    """Suggerisce la strategia di decomposizione migliore per `profs`.

    Parameters
    ----------
    profs : dict
        Output di Phase A. Mappa nome_docente -> info.

    Returns
    -------
    DecompositionRecommendation
        Strategia consigliata + motivazione testuale.
    """
    # Costruisci la matrice di adiacenza classe-classe pesata
    # (peso = numero di docenti in comune).
    classes = sorted({c for p in profs.values() for c in p["classi"]})
    n = len(classes)
    teachers_per_class: dict = defaultdict(set)
    for t, info in profs.items():
        for c in info["classi"]:
            teachers_per_class[c].add(t)
    M = np.zeros((n, n), dtype=np.int32)
    for i, ci in enumerate(classes):
        ti = teachers_per_class[ci]
        for j in range(i + 1, n):
            shared = len(ti & teachers_per_class[classes[j]])
            M[i, j] = M[j, i] = shared

    Q = compute_modularity(M)
    rho = compute_density(M)

    # Decisione: modularita' vs densita'
    if Q > 0.3:
        primary = "spectral"
        motivation = (
            f"La scuola ha modularita' {Q:.2f} (> 0.30): il grafo "
            f"classe-docente presenta cluster naturali ben separati, "
            f"tipicamente in corrispondenza degli indirizzi di studio. "
            f"La decomposizione spettrale identifica questi cluster e "
            f"li risolve in parallelo, con uno speedup atteso di 5-10x."
        )
    elif rho > 0.6:
        primary = "metis"
        motivation = (
            f"La scuola ha densita' {rho:.2f} (> 0.60): il grafo e' "
            f"denso e privo di cluster naturali, perche' i docenti "
            f"insegnano in molte classi diverse. La spettrale "
            f"produrrebbe cluster artificiali; METIS forza una "
            f"partizione bilanciata che minimizza il taglio."
        )
    else:
        primary = "curriculum"
        motivation = (
            f"La scuola ha modularita' {Q:.2f} e densita' {rho:.2f}: "
            f"non ci sono cluster spettrali forti ne' un'alta "
            f"densita'. Il modo piu' robusto di partizionare e' "
            f"per indirizzo di studio (curriculum), che produce "
            f"cluster prevedibili e interpretabili."
        )

    combine = True
    motivation += (
        " In tutti i casi conviene combinare la decomposizione "
        "scelta con quella temporale (per giorno), che e' "
        "ortogonale alle altre e parallelizza naturalmente su "
        "sei core. Lo schema combinato e': prima spaccare le "
        "classi nei cluster (spettrale/METIS/curriculum), poi "
        "all'interno di ciascun cluster spaccare per giorno."
    )

    return DecompositionRecommendation(
        primary_strategy=primary,
        combine_with_temporal=combine,
        modularity=Q,
        density=rho,
        motivation=motivation,
    )
