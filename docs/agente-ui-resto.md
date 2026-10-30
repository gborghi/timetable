# Agente UI — resto delle etichette, 2026-10-30

Branch `ui-resto`, da `origin/main` al momento del worktree
(`24a9926`). Non è stato toccato `main`. Nessun valore inviato al
solver è cambiato: dove la parola inglese era anche il valore
(`teacher`, `class`, `group`, `classes`, `teachers`, i livelli
`hard`/`soft`/…), è cambiato solo il testo visibile.

## Commit

| hash | cosa |
| --- | --- |
| `ad77a60` | Etichette inglesi sostituite con parole già scritte nel frontend. |
| questo file | resoconto |

## Collegati

Conteggio vero delle etichette il cui testo visibile è passato
dall'inglese all'italiano già presente nel frontend: **37**.
Ogni riga è una sostituzione, non un'occorrenza.

1. Import → Importa
2. Export → Esporta
3. Wipe → Cancella
4. INFEASIBILE → non fattibile
5. Hall's theorem pre-check → Pre-check fattibilità (Hall)
6. Mode → Modalità
7. classes (nodi=classi) → Classi (nodi)
8. teachers (nodi=docenti) → Docenti (nodi)
9. Max iter → Max iterazioni
10. Time-limit → Tempo limite
11. Obj → Obiettivo
12. hard → Obbligatorio
13. soft → Penalizzato
14. preferred → Preferenza
15. enforced → Imposto
16. allowed → Consentito
17. forbidden → Vietato
18. Reset → azzera
19. Kind → Tipo
20. Scope → Ambito
21. Reset DB → Cancella tutto
22. Code (machine name, unique) → Codice
23. Nome (display) → Nome
24. built with AI → Sviluppato con l'aiuto dell'intelligenza artificiale
25. Nuovo evento (Monitor) → Nuovo evento
26. Max → Massimo
27. Toggle all → Chiudi tutti i gruppi
28. Untoggle all → Apri tutti i gruppi
29. Reset query → Svuota
30. Reset sort → Torna all'ordine originale
31. refresh → Aggiorna
32. Sort → Ordinamento
33. dry-run → Anteprima
34. teacher → Docenti
35. class → Classi
36. group → Gruppi
37. Entità kind → Tipo entità

La frase inglese accanto a Wipe (logical, matrix, coteach, room
preferences) usa le parole già scritte nel dialogo di conferma della
stessa azione. Non è una trentottesima etichetta: è la glossa di
Cancella.

## Saltati, e perché

- **Dashboard.** La chiave è «Dashboard». «Panoramica» è l'inizio del
  suggerimento, non un'etichetta di menu.
- **kind `imported`.** Nessuna etichetta italiana già scritta.
- **LNS, SA, TS, VNS, ILS, Column Generation, Lagrangian.** Solo sigle
  e espansioni inglesi. Non ho inventato un nome.
- **supply.** Non c'è «offerta».
- **Pretty name, Workers, Seed, Owner, Policy** (i codici
  `any` / `single_plesso_*`). Nessuna parola italiana già usata per
  quella etichetta.
- **`(default)`.** C'è «impostazioni predefinite», non la parola da sola.
- **`common.*`.** Il markup ha già Salva, Annulla, Elimina e le altre.
  Collegarle non cambia il testo.
- **Query DSL** (`stato = done`, `kind in [lns, sa, …]`). Linguaggio
  accettato dal backend, non etichette.

## Verifica

In `webui/frontend`, prima del push. `node_modules` non c'era nel
worktree: `npm ci --no-audit --no-fund` (308 pacchetti), poi:

- `npm test`: 108 passati, 0 falliti.
- `npm run build`: ok (`adapter-static`, sito in `build`).

Nessun tentativo fallito, nessun revert. `npm run check` non è stato
rilanciato in questo giro: la richiesta era test e build.

## Push

Solo `ui-resto`, non `main`.
