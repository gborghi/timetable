# piTantum

<p align="center">
  <img src="branding/logo/logo_light.svg" alt="piTantum" width="280">
</p>

Orario settimanale di un **liceo italiano**: classi × docenti × aule, generato con Google OR-Tools **CP-SAT**, poi modificabile nel browser (trascinamento, assenze, supplenze).

È fatto per il liceo — compresenze, sostegno, plessi, sabato, potenziamento (legge 107/2015) — non per spartire sezioni all’università.

**Italiano** (questo file) · [English](README.md)

[![CI](https://github.com/gborghi/timetable/actions/workflows/ci.yml/badge.svg)](https://github.com/gborghi/timetable/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Svelte 5](https://img.shields.io/badge/svelte-5-orange)](https://svelte.dev/)
[![License](https://img.shields.io/badge/license-proprietary-red)](LICENSE)

```bash
git clone https://github.com/gborghi/timetable.git
cd timetable
./webui/start.sh          # macOS / Linux → http://localhost:5173
# Windows: webui\start.bat
```

Servono Python ≥ 3.11 e Node ≥ 22. Al primo avvio lo script crea l’ambiente Python e `node_modules` (qualche minuto). Poi lo stesso comando riaccende tutto.

Apri **http://localhost:5173**. Nella Dashboard importa un profilo già calcolato (`small` è il più veloce): ottieni una scuola e un orario su cui cliccare.

Note per sistema operativo: [guida all’installazione](docs/installation.md). Per fermare: `./webui/stop.sh`.

---

**piTantum** (anche **Tempus Tantum**) parte dall’anagrafe della scuola — docenti, classi, materie, aule, indirizzi, compresenze, ore di sostegno — e produce la griglia settimanale. Puoi bloccare lezioni, trascinarle, coprire le assenze e rilanciare il risolutore.

Il nome gioca sulla lettera greca **π**: i due tratti verticali della pi minuscola sono le due **T** di **T**empus **T**antum.

> *Omnia, Lucili, aliena sunt, tempus tantum nostrum est.*
> — Seneca, *Epistulae morales ad Lucilium*, I, 1
>
> «Tutto, Lucilio, ci viene da altri; soltanto il tempo è nostro.»

Realizzato con assistenza di intelligenza artificiale (Claude, Anthropic) per il motore CP-SAT, il backend FastAPI e il frontend SvelteKit.

## Che cosa fa

- **Genera** l’orario settimanale con un risolutore CP-SAT (OR-Tools), con decomposizione spettrale sulle scuole grandi e, se serve, metaeuristiche (LNS, SA, tabu, ILS, ALNS, VNS, …) sopra la soluzione CP-SAT.
- **Modifica** la griglia nel browser: trascinamento con controllo di fattibilità, finestra di conflitto se lo slot è occupato, elenco delle lezioni ancora senza ora.
- **Copre le assenze**: segni i docenti assenti, assegni i supplenti, vedi le ore scoperte.
- **Importa** Excel/CSV con modelli scaricabili, oppure carica una scuola dimostrativa (`small` … `mega`).
- **Rispetta le regole del liceo** che gli orari generici saltano: compresenza, sostegno, potenziamento, religione e alternativa nella stessa ora, gruppi di lingua tra più classi, sabato, due plessi con i tempi di spostamento.

Una lezione bloccata è un vincolo duro nel risolutore, non una toppa dopo. I blocchi impossibili falliscono subito, prima di una run lunga.

## Dopo il primo avvio

1. Apri http://localhost:5173.
2. Dashboard → importa il profilo `small` (curricula, aule, studenti se vuoi il demo completo).
3. Apri **Orario** e trascina una lezione; apri **Assenze e supplenze** e copri un giorno.

Il backend sta sulla porta 8000, il frontend sulla 5173. I log sono in `webui/logs/`.

## Tre strati, un solo repository

| Percorso | Ruolo |
| --- | --- |
| `engine/` | Risolutore: CP-SAT, decomposizione, metaeuristiche |
| `webui/` | Backend FastAPI + SQLite, interfaccia SvelteKit, `start.sh` / `start.bat` |
| `schedule/` | Prototipi originali in un solo file (solo consultazione) |

## Test

```bash
cd webui
export PYTHONPATH="$PWD:$PWD/../engine:$PWD/../schedule"
backend/.venv/bin/pytest backend/tests -m "not slow" -q
```

I test end-to-end (Cypress) vogliono lo stack acceso; il modo previsto è `docker compose -f docker-compose.test.yml`. Dettagli: [`webui/frontend/E2E_README.md`](webui/frontend/E2E_README.md).

## Documentazione

- [Installazione](docs/installation.md) — Windows, Linux, macOS
- [Manuale (PDF)](docs/manual.pdf) · [PDF in inglese](docs/manual_en.pdf) (il volume inglese è in parte un riassunto)
- Riferimento in Markdown in [`docs/`](docs/): [architettura](docs/architecture.md), [vincoli](docs/constraints.md), [flusso](docs/workflow.md), [interfaccia](docs/ui_guide.md), [API](docs/api.md)
- Guide brevi collegate dall’interfaccia: [`webui/docs/`](webui/docs/)
- Diario delle modifiche: [`CHANGELOG.md`](CHANGELOG.md)

## Origini

piTantum nasce da idee di **Fernando Gargiulo**, **Giovanni Borghi**, **Matteo Mariani** e **Stefano Bertozzi**: quali vincoli contano davvero in una scuola italiana, e la forma del metodo. Il codice di questo repository le mette in opera.

## Licenza

Progetto privato; nessuna licenza pubblica.
