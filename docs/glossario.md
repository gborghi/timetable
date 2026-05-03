# Glossario di piTantum

Questo glossario raccoglie tutti i termini tecnici che compaiono
nella documentazione di piTantum. \`E pensato come riferimento
"da consultare al volo": apri questa pagina ogni volta che ti
imbatti in una parola che non riconosci.

I termini sono ordinati alfabeticamente; ogni voce \`e seguita
da una breve spiegazione in linguaggio piano e, dove utile, da
un'analogia o un esempio.

---

## A

**ALLOWED.** Stato di una cella di disponibilit\`a (oraria) che
non vincola la scelta del solver: la cella \`e "neutra", n\'e
preferita n\'e proibita. \`E lo stato di default.

**ALNS (Adaptive Large Neighborhood Search).** Una delle
metaeuristiche del solver. Distrugge una porzione della soluzione
corrente (es. un giorno intero, un cluster di classi) e la
ricostruisce cercando un miglioramento. "Adaptive" perch\'e
sceglie quale tipo di distruzione/ricostruzione usare a seconda
di quale ha funzionato meglio nelle iterazioni precedenti.

**Aula speciale.** Categoria di aula nell'anagrafica
(`aula_speciale`): aule polifunzionali, di disegno, arte, musica.
Distinte dalle aule standard, dai laboratori, dalla palestra,
dalla biblioteca.

**Assignment.** Vedi *cattedra*.

## B

**BES (Bisogni Educativi Speciali).** Tag tipico per studenti
che richiedono attenzioni didattiche particolari. Si pu\`o usare
per scrivere vincoli specifici (es. "studenti BES non hanno mai
lezione il sabato").

**Buco.** Una cella vuota nell'orario di un docente fra due
lezioni. Esempio: il professore ha lezione alle 8, alle 10 e
alle 11; le 9 \`e un buco. Il sistema penalizza i buchi nel
SOFT score perch\'e il docente preferisce avere ore consecutive.

## C

**Cattedra (Assignment).** L'assegnazione di un docente a una
classe per una specifica materia, con un certo monte ore
settimanali. Esempio: "la prof Rossi insegna matematica in 1A
per 4 ore a settimana" \`e una cattedra. Le cattedre sono
prodotte dalla Phase A.

**Classe di concorso (group).** Codice ministeriale che
identifica le materie che un docente \`e abilitato a insegnare
(A026 = matematica per il primo biennio, A050 = scienze, ecc.).

**Cluster (decomposizione spettrale).** Quando la scuola \`e
grande, il solver divide l'insieme delle classi in piccoli
gruppi ("cluster") che hanno pochi docenti in comune. Pianifica
ogni cluster quasi indipendentemente, e poi "ricuce" i risultati.
Idea: \`e come dividere un grande cantiere in piccoli cantieri
quasi-autonomi.

**Column Generation.** Strategia di scaling per scuole molto
grandi (>200 classi). Costruisce iterativamente una grande
combinazione di "pattern settimanali per docente" finch\'e non
si trovano pi\`u miglioramenti. Off di default; vale la pena
solo per istanze enormi.

**Compresenza.** Due o pi\`u docenti che insegnano insieme la
stessa lezione (es. inglese + un madrelingua, scienze motorie
con due insegnanti). In piTantum si modella con regole di
"co-teaching": una cattedra pu\`o richiedere N docenti.

**CP-SAT.** Il solver vincolato (constraint programming + SAT)
di Google OR-Tools. \`E il "motore" che effettivamente cerca
una soluzione che rispetti tutti i vincoli. Pensa a un risolutore
di sudoku ma molto pi\`u potente, capace di gestire migliaia di
vincoli simultanei.

**Curriculum (indirizzo).** Indirizzo di studio: Scientifico,
Linguistico, ITIS, Classico, ecc. Ogni indirizzo ha una matrice
oraria standard (quante ore di matematica al primo anno, quante
al secondo, ecc.).

## D

**Decomposizione spettrale.** Algoritmo che divide il grafo
classe-docente in cluster ben separati. Tecnicamente: usa gli
autovettori della matrice laplaciana del grafo. Concretamente:
identifica gruppi di classi che condividono pochi docenti, in
modo che si possano pianificare quasi indipendentemente. Vedi
*Cluster*.

**Distribuzione oraria.** Il modo in cui le ore di una materia
vengono spalmate sui giorni della settimana. piTantum cerca di
distribuire (es. 5 ore di mate su 5 giorni diversi anzich\'e
tutte un giorno solo).

**DSL (Domain Specific Language).** Mini-linguaggio specializzato
che permette di scrivere vincoli in modo compatto. piTantum ha
un DSL "generico" descritto in [`general_dsl.md`](general_dsl.md)
che permette di esprimere qualunque regola sull'orario.

## E

**ENFORCED.** Stato/livello di vincolo: come HARD ma usato
quando vogliamo dire "questa cosa **deve** accadere" (mentre HARD
di solito vuol dire "questa cosa **non** deve accadere"). Esempio
ENFORCED: "deve esistere almeno una lezione di Storia in 3A".

**Evento.** Vedi *Lezione*.

## F

**Fase A / Phase A (Assegnazione).** Prima fase
dell'ottimizzazione. Decide chi insegna cosa a quale classe e
per quante ore. Risultato: l'elenco delle cattedre.

**Fase B / Phase B (Schedulazione).** Seconda fase. Date le
cattedre, decide in quali slot della settimana piazzare ogni
ora-lezione. Pi\`u complessa della Phase A perch\'e deve
incastrare tutti i vincoli temporali.

**Feasible / Infeasible.** Una soluzione \`e *feasible* se
rispetta tutti i vincoli HARD; *infeasible* se non esiste alcuna
soluzione possibile (per esempio perch\'e i vincoli HARD si
contraddicono).

## G

**General DSL.** Vedi *DSL* e [`general_dsl.md`](general_dsl.md).

**Graduatoria score.** Punteggio di graduatoria di un docente.
Usato dal modulo "supplenze" per ordinare le candidature.

**Group / Gruppo articolato.** Insieme di studenti raggruppati
trasversalmente, di solito provenienti da pi\`u classi, che fanno
una o pi\`u materie insieme (esempi: gruppi di seconda lingua
spagnolo/tedesco, IRC vs alternativa, recupero matematica).

## H

**HARD.** Stato/livello di vincolo: regola assoluta che il
solver non viola mai. Se nessuna soluzione possibile rispetta
tutte le regole HARD, il modello \`e *infeasible* e il sistema
te lo dice.

**Hall (teorema di Hall).** Teorema matematico (von Hall, 1935)
che d\`a una condizione necessaria e sufficiente per l'esistenza
di un matching perfetto in un grafo bipartito. piTantum usa una
sua variante per il "pre-check fattibilit\`a strutturale": prima
di lanciare il solver controlla se la capacit\`a dei docenti
copre la domanda di ore. Se Hall fallisce, il modello \`e
gi\`a infeasible e si evita di lanciare un solver lungo.

## I

**ILS (Iterated Local Search).** Una metaeuristica del solver.
Alterna fasi di "ricerca locale" (piccoli miglioramenti) con
"perturbazioni" (rumore introdotto per sfuggire a minimi locali).

**Indirizzo.** Vedi *Curriculum*.

**Infeasible.** Vedi *Feasible*.

## L

**Lagrangian Relaxation.** Tecnica di ottimizzazione che
"rilassa" alcuni vincoli (li rimuove dal modello principale) e
li riintroduce come penalit\`a moltiplicate per coefficienti
chiamati "moltiplicatori di Lagrange". Iterando, i moltiplicatori
si aggiornano per spingere il rilassamento verso il rispetto
dei vincoli originari.

**Lezione (Lesson).** Una singola ora-lezione fisica
nell'orario settimanale: docente + classe + materia + giorno +
ora + aula.

**LNS (Large Neighborhood Search).** Una metaeuristica del
solver. Distrugge una porzione della soluzione corrente
(esempio: tutte le lezioni di un giorno) e la ricostruisce con
CP-SAT cercando un miglioramento. Vedi anche *ALNS*.

## M

**Materia (Subject).** Disciplina insegnata: matematica,
italiano, storia, ecc.

**Metaeuristica.** Algoritmo di "miglioramento iterativo" che,
partendo da una soluzione gi\`a feasible, cerca di abbassare lo
score SOFT senza violare i vincoli HARD. piTantum ha 7
metaeuristiche disponibili (LNS, ALNS, SA, TS, VNS, ILS,
Lagrangian).

**Modularit\`a (Newman-Girvan).** Misura statistica della
"qualit\`a" di una partizione in cluster di un grafo. Alta
modularit\`a = cluster ben separati = la decomposizione
spettrale funziona bene.

**Monte Carlo Sensitivity.** Analisi statistica che genera N
soluzioni random feasible e ne misura il SOFT score per capire
quanto la soluzione attuale sia vicina all'ottimo locale.

## N

**Nickname (docente, studente).** Etichetta breve mostrata
nell'orario al posto del nome completo (es. "Rossi" invece di
"Maria Rossi Bianchi"). Personalizzabile per ciascun docente o
studente.

## O

**Objective (funzione obiettivo).** La quantit\`a numerica che
il solver cerca di **minimizzare**. \`E la somma pesata delle
violazioni SOFT (con segno + per le penalit\`a, segno - per i
bonus PREFERRED).

**OR-Tools.** Libreria di Google per programmazione vincolata e
ottimizzazione combinatoria. piTantum la usa per il solver
CP-SAT.

## P

**Pattern settimanale.** Una specifica disposizione delle ore
di un docente nella settimana: quali slot occupa in quali
giorni. Concetto centrale nella Column Generation, dove
ogni docente ha un "catalogo" di pattern e il master LP sceglie
quale prendere.

**Phase A / Phase B.** Vedi *Fase A* / *Fase B*.

**Pipeline.** La sequenza di fasi che produce una soluzione
finale: import dataset -> Phase A -> Phase B -> metaeuristiche
-> classroom assignment. Configurabile dal tab Workflow.

**PREFERRED.** Stato/livello di vincolo: bonus se rispettato,
nessuna penalit\`a se violato. Opposto del SOFT.

## R

**Run.** Un'esecuzione di una fase di ottimizzazione (Phase A,
Phase B, una metaeuristica, una diagnostica). Tutte le run sono
visibili nel tab Runs, con stato (pending/running/done/failed),
log, telemetria, durata.

## S

**SA (Simulated Annealing).** Una metaeuristica del solver.
Accetta peggioramenti locali con una probabilit\`a che diminuisce
nel tempo (la "temperatura" si raffredda). Permette di scappare
da minimi locali nelle prime iterazioni.

**Saved view.** Combinazione (entit\`a, query DSL, sort
multi-livello) salvata con un nome riusabile dal dropdown
"Viste salvate" sopra ogni tabella di lista.

**SOFT.** Stato/livello di vincolo: regola che il solver cerca
di rispettare ma pu\`o violare pagando una penalit\`a (peso che
decidi tu). Opposto del PREFERRED.

**Slot.** Una coppia (giorno, ora). Un giorno tipico ha 6 slot
(8\textsuperscript{a}, 9\textsuperscript{a}, ..., 13\textsuperscript{a}); la
settimana ne ha 36.

**Solver.** Il "motore" che cerca una soluzione che rispetti i
vincoli. In piTantum \`e CP-SAT (vedi *CP-SAT*).

**Solution.** Una soluzione completa dell'orario: l'insieme di
tutte le lezioni piazzate. Una scuola pu\`o tenere pi\`u
soluzioni in archivio (l'ultima prodotta + soluzioni passate
salvate) e attivarle a turno.

**Spectral decomposition.** Vedi *Decomposizione spettrale*.

**Splitting (gruppo).** Tipo di gruppo articolato che divide
una classe in due o pi\`u sottogruppi che svolgono materie
diverse contemporaneamente (es. mezza classe in laboratorio,
l'altra met\`a in aula).

**Subject.** Vedi *Materia*.

## T

**Tag.** Etichetta libera che il coordinatore attacca a
un'aula, a uno studente o a un docente per esprimere
caratteristiche trasversali (es. "proiettore" su un'aula,
"BES" su uno studente, "matematica" su un'aula standard).
Usabile dal DSL.

**Telemetria (run).** Serie temporale di sample registrati
durante un run del solver: a ogni iterazione il programma
salva timestamp, fase, valore obiettivo corrente, vincoli
violati, mosse accettate/rifiutate. Visibile nel detail page
del run come grafico interattivo.

**TS (Tabu Search).** Una metaeuristica del solver. Mantiene
una lista "tabu" di mosse recentemente fatte per evitare di
tornare subito indietro; questo le permette di scappare da
plateau dello score.

## V

**VNS (Variable Neighborhood Search).** Una metaeuristica del
solver. Cicla attraverso "vicinati" di dimensione crescente
(1-swap, 2-swap, 3-chain, k-opt) e si ferma quando un intero
ciclo passa senza miglioramenti.

**Vincolo.** Una regola che l'orario deve rispettare. piTantum
ha pi\`u tipi di vincoli: di disponibilit\`a (per cella),
logico (DNF), preferenze (materia-aula, docente-aula),
co-teaching, vincoli del DSL generico, ecc.

## W

**Workflow.** Tab dell'app web (`/optimize`) che espone tutte le
fasi del pipeline come card configurabili, plus la "Pipeline
completa" trascinabile-tickabile.
