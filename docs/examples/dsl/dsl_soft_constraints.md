# DSL example: SOFT constraints / vincoli SOFT

## 🇮🇹 Caso d'uso

Il coordinatore vuole esprimere preferenze ``morbide'' che
non bloccano la run quando vengono violate, ma alimentano lo
score globale della soluzione cosi' che il solver le rispetti
quando puo'. Tre esempi tipici:

1. **Potenziamento Legge 107**: la prof Verdi e' in organico
   potenziato e il coordinatore preferirebbe vederla
   distribuire le sue 18 ore in **almeno 4 giorni distinti**
   (per maggior copertura). Questo e' un desiderio, non un
   obbligo.

2. **Spostamenti pomeridiani**: il coordinatore preferisce
   che una classe **non abbia mai 6 ore in un giorno**,
   anche se a volte e' necessario.

3. **Distribuzione mate**: la classe 4A preferisce avere mate
   **non oltre la 5a ora del giorno** (per concentrazione),
   ma se serve si puo' arrivare alla 6a.

### Path UI

Tab **Vincoli** → modale **+ Nuovo vincolo DSL**. Per ogni
regola compila *Tipo* = ``soft`` e (opzionalmente) un peso
numerico in *Peso*. Default 1.0.

### DSL: potenziamento -- almeno 4 giorni distinti

```
count d in days where (
    exists l in lessons where l.teacher == "ProfVerdi"
                          and l.day == d
): d >= 4
```

In quanto SOFT con peso 50, ogni unita' al di sotto di 4
contribuisce **50** allo score globale di violazione. Se la
soluzione effettiva ha solo 3 giorni distinti, il costo
SOFT che si aggiunge e' $50 \times (4 - 3) = 50$.

### DSL: classe -- mai 6 ore al giorno

```
forall c in classes:
    forall d in days:
        count l in lessons where l.class == c.name
                              and l.day == d: l < 6
```

SOFT, peso 100. Una classe che fa 6 ore in un giorno
contribuisce 100 al costo SOFT.

### DSL: 4A -- mate non oltre la 5a ora

```
forall l in lessons where l.class == "4A"
                       and l.subject == "Matematica":
    l.hour <= 12
```

SOFT, peso 20. Ogni ora di mate alla 6a (h=13) costa 20.

### Stato attuale dell'enforcement

**IMPORTANTE**: il DSL accetta SOFT in modo grammaticalmente
identico al HARD, ma il backend di compilazione CP-SAT
**non** traduce ancora il SOFT in penalita' sull'obiettivo
del solver. Quando il compilatore incontra una regola SOFT,
emette il diagnostico:

```
soft constraint X: SOFT cost not yet wired
```

e archivia la regola come ``label informativo'' nel modello.
Il solver CP-SAT NON cambia il proprio obiettivo per spingere
la soluzione a soddisfare la SOFT.

Il costo SOFT viene comunque calcolato dall'**evaluator
post-hoc**: dopo che la pipeline ha prodotto una soluzione,
ogni clausola SOFT viene valutata sulla soluzione e contribuisce
allo score totale visibile in ``run_metrics``.

In pratica:

- la SOFT in DSL e' una **specifica dichiarativa** che la
  pipeline esegue post-hoc;
- l'**enforcement** via CP-SAT (penalty in obiettivo) e' nei
  prossimi step del piano multi-day;
- per oggi, se vuoi che il solver attivamente eviti una
  configurazione, usa ``hard``;
- usa ``soft`` per misurare/confrontare soluzioni rispetto
  alla configurazione preferita anche quando il solver non sa
  che e' preferita.

### Roadmap della SOFT

I prossimi step (Step 5+) integreranno la SOFT in obiettivo
CP-SAT seguendo lo stesso pattern dei vincoli HARD:

- per ogni clausola SOFT, una variabile booleana ``viol`` che
  vale 1 quando la clausola e' violata;
- una penalty ``+w * viol`` aggiunta all'obiettivo
  ``minimize(soft_cost)`` del solver, dove ``w`` e' il peso
  dichiarato dall'utente;
- linearizzazione automatica dei quantificatori SOFT in
  somme di booleani.

Quando questo arriva, la pipeline ``via_dsl=True`` passera'
da ``HARD-only-enforced`` a ``HARD+SOFT enforced``, e l'output
del solver non solo conformera' alle HARD ma minimizzera' anche
le violazioni SOFT.

---

## 🇬🇧 Use case

The coordinator wants to express **soft** preferences that do
not block the run when violated but feed the solution's global
score so the solver respects them whenever possible. Three
typical examples:

1. **Potenziamento (Law 107)**: teacher Verdi is in the
   ``organico potenziato'' (additional staff) and the
   coordinator would prefer her 18 hours to be distributed
   over **at least 4 distinct days** (wider coverage). This is
   a wish, not a hard requirement.

2. **Afternoon moves**: the coordinator prefers **no class to
   ever have 6 hours in one day**, even when it is sometimes
   necessary.

3. **Math distribution**: class 4A would like math to be
   placed **no later than the 5th hour of the day** (for
   concentration), but it can drop to the 6th if needed.

### UI path

Tab **Constraints** → modal **+ New DSL constraint**. For each
rule pick *Kind* = ``soft`` and (optionally) a numeric weight
in *Weight*. Default 1.0.

### DSL: potenziamento -- at least 4 distinct days

```
count d in days where (
    exists l in lessons where l.teacher == "ProfVerdi"
                          and l.day == d
): d >= 4
```

As SOFT with weight 50, every unit below 4 contributes **50**
to the global violation score. If the actual solution has
only 3 distinct days, the SOFT cost added is
$50 \times (4 - 3) = 50$.

### DSL: class -- never 6 hours per day

```
forall c in classes:
    forall d in days:
        count l in lessons where l.class == c.name
                              and l.day == d: l < 6
```

SOFT, weight 100. A class that has 6 hours on a day
contributes 100 to the SOFT cost.

### DSL: 4A -- math not after the 5th hour

```
forall l in lessons where l.class == "4A"
                       and l.subject == "Matematica":
    l.hour <= 12
```

SOFT, weight 20. Each math hour at slot 6 (h=13) costs 20.

### Current enforcement status

**IMPORTANT**: the DSL accepts SOFT with the same grammar as
HARD, but the CP-SAT compiler backend **does not** translate
SOFT into a penalty on the solver objective yet. When the
compiler encounters a SOFT rule it emits the diagnostic:

```
soft constraint X: SOFT cost not yet wired
```

and archives the rule as an "informational label" in the
model. The CP-SAT solver does not change its objective to
push the solution toward satisfying the SOFT.

The SOFT cost is still computed by the **post-hoc evaluator**:
after the pipeline produces a solution, every SOFT clause is
evaluated against the solution and contributes to the total
score visible in ``run_metrics``.

In practice:

- SOFT in DSL is a **declarative specification** that the
  pipeline applies post-hoc;
- the **enforcement** via CP-SAT (penalty in objective) is
  planned for upcoming steps of the multi-day plan;
- for today, if you want the solver to actively avoid a
  configuration use ``hard``;
- use ``soft`` to measure/compare solutions against the
  preferred configuration even when the solver does not know
  it is preferred.

### SOFT roadmap

Upcoming steps (Step 5+) will wire SOFT into the CP-SAT
objective using the same pattern as HARD:

- for every SOFT clause a boolean ``viol`` that is 1 when
  violated;
- a penalty ``+w * viol`` added to the solver's
  ``minimize(soft_cost)`` objective, where ``w`` is the
  user-declared weight;
- automatic linearisation of SOFT quantifiers into boolean
  sums.

When that lands, the ``via_dsl=True`` pipeline will move from
``HARD-only-enforced`` to ``HARD+SOFT enforced``, and the
solver output will both satisfy the HARDs and minimise SOFT
violations.
