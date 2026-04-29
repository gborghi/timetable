% --------------------------------------------------------------------
% Bozza MiniZinc dell'orario settimanale (Phase A: assegnazione giorno).
% Vedi proposals/analysis.md sez. 5.2 per la motivazione.
%
% Da provare con:  Chuffed (lazy clause gen) o OR-Tools come backend.
%   minizinc --solver Chuffed -p 8 minizinc_sketch.mzn data.dzn
%
% La traduzione di Phase B (slot orari) e\` analoga e si fa per giorno.
% Qui mostriamo solo Phase A perche\` e\` quella in cui MiniZinc
% rende di piu\` (vincoli globali compatti).
% --------------------------------------------------------------------

include "globals.mzn";

% Parametri di taglia
int: NPROFS;
int: NCLASSES;
int: NSUBJ;
int: NDAYS = 6;
int: NHOURS = 6;
int: MAX_PER_DAY_TRIPLE = 2;
int: MAX_PER_DAY_PROF_CL = 3;
int: DAY_HOURS_MAX = 6;

set of int: PROFS = 1..NPROFS;
set of int: CLASSES = 1..NCLASSES;
set of int: SUBJ = 1..NSUBJ;
set of int: DAYS = 1..NDAYS;

% Triple esistenti: array di tuple (prof, classe, materia, ore)
int: NTRIPLES;
array[1..NTRIPLES, 1..4] of int: triples;
% triples[t,1] = prof index
% triples[t,2] = classe index
% triples[t,3] = materia index
% triples[t,4] = ore settimanali della cattedra

% Free day: per ogni prof, lista di 3 candidati (in ordine di pref)
array[PROFS, 1..3] of DAYS: glibero_pref;

% --------------------------------------------------------------------
% Variabili decisionali
% --------------------------------------------------------------------

% day_count[t, d] = ore della triple t nel giorno d
array[1..NTRIPLES, DAYS] of var 0..MAX_PER_DAY_TRIPLE: day_count;

% Scelta del giorno libero: 1, 2 oppure 3 (indice in glibero_pref)
array[PROFS] of var 1..3: glibero_choice;

% --------------------------------------------------------------------
% Vincoli hard
% --------------------------------------------------------------------

% somma settimanale = ore richieste
constraint forall(t in 1..NTRIPLES) (
    sum(d in DAYS) (day_count[t, d]) = triples[t, 4]
);

% no overlap (prof, classe): max MAX_PER_DAY_PROF_CL ore al giorno
constraint forall(p in PROFS, c in CLASSES, d in DAYS) (
    sum(t in 1..NTRIPLES where triples[t,1]=p /\ triples[t,2]=c)
        (day_count[t, d]) <= MAX_PER_DAY_PROF_CL
);

% per (prof, day): max NHOURS lezioni (no overlap implicito)
constraint forall(p in PROFS, d in DAYS) (
    sum(t in 1..NTRIPLES where triples[t,1]=p) (day_count[t, d])
        <= NHOURS
);

% per (cl, day): max DAY_HOURS_MAX
constraint forall(c in CLASSES, d in DAYS) (
    sum(t in 1..NTRIPLES where triples[t,2]=c) (day_count[t, d])
        <= DAY_HOURS_MAX
);

% giorno libero per prof: nel giorno scelto, 0 lezioni
constraint forall(p in PROFS) (
    let { var DAYS: day_off = glibero_pref[p, glibero_choice[p]]; }
    in
    sum(t in 1..NTRIPLES where triples[t,1]=p)
        (day_count[t, day_off]) = 0
);

% --------------------------------------------------------------------
% Penalita\` (objective)
% --------------------------------------------------------------------

% uniformita\` cattedra: |day_count*6 - ore|
array[1..NTRIPLES, DAYS] of var 0..12: u_class_dev;
constraint forall(t in 1..NTRIPLES, d in DAYS) (
    u_class_dev[t, d] = abs(day_count[t, d] * 6 - triples[t, 4])
);

% uniformita\` prof: per (prof, day) somma_t day_count
array[PROFS, DAYS] of var 0..30: u_prof_dev;
constraint forall(p in PROFS, d in DAYS) (
    let {
      var int: ld = sum(t in 1..NTRIPLES where triples[t,1]=p)
                       (day_count[t,d]),
      int: ore_tot = sum(t in 1..NTRIPLES where triples[t,1]=p)
                        (triples[t,4]);
    } in
    u_prof_dev[p, d] = abs(ld * 6 - ore_tot)
);

% penalita\` giorno libero non-primo
array[PROFS] of var 0..100: glib_pen;
constraint forall(p in PROFS) (
    glib_pen[p] = (if glibero_choice[p] = 1 then 0
                  elseif glibero_choice[p] = 2 then 50
                  else 100 endif)
);

% Objective: minimizziamo combinazione lineare delle penalita\`
solve minimize
    4 * sum(t in 1..NTRIPLES, d in DAYS) (u_class_dev[t, d])
  + 3 * sum(p in PROFS, d in DAYS) (u_prof_dev[p, d])
  + 1 * sum(p in PROFS) (glib_pen[p]);

% --------------------------------------------------------------------
% Output
% --------------------------------------------------------------------
output [
    "day_count = ", show(day_count), "\n",
    "glibero_choice = ", show(glibero_choice), "\n"
];
