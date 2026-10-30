# Dipendenze — branch `dipendenze`

Lavoro solo su questa branch, partendo da `d9ce8a7` (allineata a `origin/main`).
Niente push di `main`, niente force-push, niente deploy.
Copia di sicurezza già presente: `~/backup-timetable/2026-10-30-0822/repo/`.

Push: https://github.com/gborghi/timetable/tree/dipendenze
Confronto: https://github.com/gborghi/timetable/compare/main...dipendenze

Gate frontend, prima di ogni commit: `npm ci --no-audit --no-fund && npm run check && npm test && npm run build`.
Gate backend di base (prima dei major): `PYTHONPATH=webui:engine:schedule` con il venv ricreato in questa worktree su `/opt/homebrew/bin/python3.12`. Esito: 1083 passed, 3 skipped, 61 deselected, 402 s.

## Commit

| hash | bump | test |
| --- | --- | --- |
| `960ad14` | vite 5.4.21 → 8.3.5 e `@sveltejs/vite-plugin-svelte` 4.0.4 → 7.3.1. Peer inseparabili: il plugin 4 accetta solo vite 5. Node minimo 22.12, come chiede vite 8. | check 0 errori, 105 test, build verde |
| `90a42ce` | tailwindcss 3.4.19 → 4.3.3 e `@tailwindcss/vite` 4.3.3. Il plugin PostCSS non è più nel pacchetto principale. | stesso gate, verde al secondo tentativo (vedi sotto) |
| `80d3ed5` | `@sveltejs/kit` 2.70.2 → 2.70.3 | verde |
| `c625ed9` | svelte-check 4.4.6 → 4.7.7 | verde |
| `a4d6f6f` | `@playwright/test` 1.59.1 → 1.64.1 | verde |
| `8e5b4da` | `@types/cytoscape` 3.21.9 → 3.31.0 | verde |
| `ae767d6` | `@types/node` 25.6.0 → 25.9.9 | verde |
| `e17daf3` | autoprefixer 10.5.0 → 10.6.2 | verde |
| `84ad5c5` | Cypress 15.20.0 → 15.21.1 | verde |
| `b222b86` | PostCSS 8.5.26 → 8.5.32 | verde |
| `7c062ed` | cytoscape 3.33.3 → 3.34.4 | verde |
| `cc60627` | Cypress 15.21.1 → 16.2.1 | verde (il gate non esegue gli e2e) |
| `244097e` | `@types/node` 25.9.9 → 26.6.6 | verde |

## Tailwind 4 — primo tentativo rosso, secondo verde

Il build falliva con `Cannot apply unknown utility class btn`. In v4 `@apply` non risolve più le classi di `@layer components`. Secondo tentativo, ancora in `src/app.css`: `btn`, `btn-danger` e `pill` registrate come `@utility`. Poi gli shim ufficiali (bordo di default `gray-200`, `cursor: pointer` sui bottoni). Config toccate perché l'upgrade lo richiede: `vite.config.js`, `postcss.config.js`. Il tema resta in `tailwind.config.js`, caricato con `@config`.

Non ho rinominato le utility v3 nei file `.svelte` (`outline-none`, `class:bg-opacity-5`, `shadow-sm`): sono fuori dai manifest. Il build passa; a video quelle classi vecchie non generano più lo stile v3.

## Revert (nessun commit)

- **TanStack Query 6.3.6.** `svelte-check`: 25 errori in `src/lib/queries/index.ts`. La v6 vuole un accessor, non l'oggetto `{ queryKey, queryFn }`. Sistemarlo significa riscrivere le query, fuori dai file consentiti. Working tree ripristinato. Resta `^5.90.2`, ultima 5.x.
- **faker 40.44.0.** Manifest modificato, non committato. La suite si è fermata su `test_group_hours_stay_within_class_capacity` (giorno 3, 2A con 7 slot). Lo stesso test fallisce anche con faker 39.1.0, in isolamento, sei volte di fila: non è il bump. Il solver di quel test usa `workers=2` e un limite di 3 s. Requirements ripristinato.

## Non fatti, e perché

- **SvelteKit 3 e adapter-static 4.** Kit 3 toglie `svelte.config.js` e sostituisce `$lib` con `#lib` più l'estensione, in tutto il sorgente. Fuori dai file consentiti. Restano kit 2.70.3 e adapter 3.0.10.
- **TypeScript 7.0.2.** Kit 2 e svelte-check accettano solo `^5 || ^6`. Resta 6.0.3, ultima 6.x.
- **Già all'ultima versione, nessun commit:** svelte 5.57.3, tslib 2.8.1, echarts 6.1.0, cytoscape-fcose 2.2.0, `@tanstack/svelte-query` 5.90.2.
- **Backend, tetti già all'ultima compatibile con Python 3.11.** Un `pip install` fresco risolve già l'ultima dentro il range. La suite di base, su quelle versioni, era verde (1083). Non ho alzato i pavimenti: non cambia ciò che installa la CI, e una seconda corsa della suite è rossa per test del solver non deterministici, indipendenti dalle dipendenze.
- **Major backend fuori tetto, non committati:** pytest 9, gunicorn 26, sse-starlette 3, reportlab 5, pandas 3. Senza una suite verde attribuibile al bump non li alzo. pandas 3 e numpy ≥2.5 / networkx 3.7 inoltre escludono o stringono Python 3.11 (numpy 2.4.6 e networkx 3.6.1 sono le ultime che la CI 3.11 può installare; il range attuale le prende da solo).
- **Dockerfile.** Nessuna riga di versione da aggiornare: gunicorn nel file resta `>=21.2,<24.0`, allineato a `requirements-dev.txt`.
