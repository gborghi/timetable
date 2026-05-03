<script>
  /**
   * 4-step "Crea nuovo vincolo" modal.
   *
   *   Step 1: Categoria (scope) + entita' (owner)
   *   Step 2: Livello (HARD / SOFT / PREFERRED / ENFORCED / ALLOWED)
   *           + peso (visibile solo per SOFT/PREFERRED)
   *   Step 3: Tipo del vincolo (kind) — campi specifici (slot, expression,
   *           subject, ecc.) si materializzano in base alla scelta
   *   Step 4: Anteprima (linguaggio naturale + JSON tecnico) + conferma
   *
   * Submit -> POST /api/constraints (dispatcher unico).
   */
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants';

  export let open = false;
  export let onClose = () => { open = false; };
  export let onCreated = () => {};

  // Lookup data populated on first open
  let teachers = [];
  let classes = [];
  let classrooms = [];
  let subjects = [];
  let curricula = [];
  let lookupsLoaded = false;

  // Wizard state
  let step = 1;
  let scope = 'teacher';
  let ownerId = null;
  let ownerId2 = null;
  let level = 'hard';
  let weight = 100;
  let kind = '';

  // kind-specific fields
  let day = 1;
  let hour = 8;
  let reason = '';
  let expression = '';
  let labelText = '';
  let yearFilter = null;
  let subject = '';
  let nTeachers = 2;
  let teacherCsv = '';

  // Submission
  let busy = false;
  let createdResult = null;

  // Reset whenever the modal opens
  $: if (open) {
    step = 1;
    scope = 'teacher';
    ownerId = null;
    ownerId2 = null;
    level = 'hard';
    weight = 100;
    kind = '';
    day = 1; hour = 8; reason = '';
    expression = '';
    labelText = '';
    yearFilter = null;
    subject = '';
    nTeachers = 2;
    teacherCsv = '';
    busy = false;
    createdResult = null;
    if (!lookupsLoaded) loadLookups();
  }

  async function loadLookups() {
    try {
      const [t, c, r, s, cu] = await Promise.all([
        api.get('/api/teachers').catch(() => []),
        api.get('/api/classes').catch(() => []),
        api.get('/api/classrooms').catch(() => []),
        api.get('/api/subjects').catch(() => []),
        api.get('/api/curricula').catch(() => []),
      ]);
      teachers = (t || []).map((x) => ({ id: x.id, name: x.name }))
        .sort((a, b) => a.name.localeCompare(b.name));
      classes = (c || []).map((x) => ({ id: x.id, name: x.name }))
        .sort((a, b) => a.name.localeCompare(b.name));
      classrooms = (r || []).map((x) => ({ id: x.id, name: x.name }))
        .sort((a, b) => a.name.localeCompare(b.name));
      subjects = (s || []).map((x) => x.name || x).sort();
      curricula = (cu || []).map((x) => ({ id: x.id, name: x.name || x.code }))
        .sort((a, b) => a.name.localeCompare(b.name));
      lookupsLoaded = true;
    } catch (e) {
      flash('Errore caricamento dati: ' + (e.message || e), 'error');
    }
  }

  // Available scope options
  const SCOPE_OPTIONS = [
    { value: 'teacher',      label: '👤 Docente' },
    { value: 'class',        label: '🏫 Classe' },
    { value: 'classroom',    label: '🚪 Aula' },
    { value: 'curriculum',   label: '🎓 Indirizzo / Curriculum' },
    { value: 'subject_room', label: '📘 Materia + Aula (preferenza)' },
    { value: 'teacher_room', label: '👤+🚪 Docente + Aula (preferenza)' },
  ];

  // Kinds available for the chosen scope. The (scope, kind) pair drives
  // the dispatcher backend.
  $: availableKinds = (() => {
    if (scope === 'teacher' || scope === 'class' || scope === 'classroom') {
      return [
        { value: 'matrix_slot', label: 'Disponibilita oraria (slot specifico)' },
        { value: 'logical',     label: 'Disponibilita logica (espressione DNF)' },
      ].concat(scope === 'class'
        ? [{ value: 'coteach', label: 'Compresenza su una materia' }] : []);
    }
    if (scope === 'curriculum') {
      return [{ value: 'logical', label: 'Vincolo logico sull\'indirizzo' }];
    }
    if (scope === 'subject_room' || scope === 'teacher_room') {
      return [{ value: 'room_pref', label: 'Preferenza aula' }];
    }
    return [];
  })();

  $: if (availableKinds.length && !availableKinds.find((k) => k.value === kind)) {
    kind = availableKinds[0]?.value || '';
  }

  const LEVELS = [
    { value: 'hard',      label: '🟥 HARD',      desc: 'Non negoziabile' },
    { value: 'soft',      label: '🟨 SOFT',      desc: 'Penalita positiva' },
    { value: 'preferred', label: '🟦 PREFERRED', desc: 'Bonus negativo' },
    { value: 'enforced',  label: '🟩 ENFORCED',  desc: 'Deve essere cosi' },
    { value: 'allowed',   label: '🟢 ALLOWED',   desc: 'Esplicitamente permesso (override)' },
    { value: 'forbidden', label: '⛔ FORBIDDEN', desc: 'Esplicitamente vietato' },
  ];

  // Levels valid for the chosen kind
  $: levelsForKind = (() => {
    if (kind === 'matrix_slot') {
      return LEVELS.filter((l) => ['hard', 'soft', 'preferred', 'enforced'].includes(l.value));
    }
    if (kind === 'logical') {
      return LEVELS.filter((l) => ['hard', 'soft', 'preferred', 'enforced'].includes(l.value));
    }
    if (kind === 'room_pref') {
      return LEVELS.filter((l) => ['allowed', 'soft', 'preferred', 'forbidden', 'enforced'].includes(l.value));
    }
    if (kind === 'coteach') {
      return LEVELS.filter((l) => ['hard', 'soft'].includes(l.value));
    }
    return LEVELS;
  })();

  $: if (levelsForKind.length
         && !levelsForKind.find((l) => l.value === level)) {
    level = levelsForKind[0].value;
  }

  function showWeight() {
    return level === 'soft' || level === 'preferred';
  }

  // Validators per step
  function step1Valid() {
    if (scope === 'subject_room') {
      return ownerId != null && !!subject;
    }
    if (scope === 'teacher_room') {
      return ownerId != null && ownerId2 != null;
    }
    return ownerId != null;
  }
  function step3Valid() {
    if (kind === 'matrix_slot') return DAYS.includes(day) && HOURS.includes(hour);
    if (kind === 'logical') return !!expression && expression.trim().length > 0;
    if (kind === 'room_pref') return true;
    if (kind === 'coteach') return !!subject && nTeachers >= 2;
    return false;
  }

  // Owner display helpers
  $: ownerName = (() => {
    if (scope === 'teacher' || scope === 'teacher_room') {
      return teachers.find((t) => t.id === ownerId)?.name || '';
    }
    if (scope === 'class') {
      return classes.find((c) => c.id === ownerId)?.name || '';
    }
    if (scope === 'classroom' || scope === 'subject_room') {
      return classrooms.find((r) => r.id === ownerId)?.name || '';
    }
    if (scope === 'curriculum') {
      return curricula.find((c) => c.id === ownerId)?.name || '';
    }
    return '';
  })();
  $: ownerName2 = (() => {
    if (scope === 'teacher_room') {
      return classrooms.find((r) => r.id === ownerId2)?.name || '';
    }
    return '';
  })();

  // Natural-language summary for step 4
  $: summary = (() => {
    const lvl = LEVELS.find((l) => l.value === level)?.label || level;
    const sc = SCOPE_OPTIONS.find((s) => s.value === scope)?.label || scope;
    if (kind === 'matrix_slot') {
      return `${sc} ${ownerName}: cella ${DAY_NAMES_IT[day] || day} ${hour}:00 marcata ${lvl}.`;
    }
    if (kind === 'logical') {
      return `${sc} ${ownerName}: vincolo logico ${lvl} -- "${expression}".`
            + (yearFilter ? ` (filtrato per anno ${yearFilter})` : '');
    }
    if (kind === 'room_pref' && scope === 'subject_room') {
      return `Materia "${subject}" in aula ${ownerName}: preferenza ${lvl}.`;
    }
    if (kind === 'room_pref' && scope === 'teacher_room') {
      return `Docente ${ownerName} in aula ${ownerName2}: preferenza ${lvl}.`;
    }
    if (kind === 'coteach') {
      return `Classe ${ownerName} - materia ${subject}: compresenza con ${nTeachers} docenti `
            + (level === 'hard' ? '(HARD)' : '(SOFT)') + '.';
    }
    return '(seleziona scope e kind)';
  })();

  $: payload = {
    scope, kind, level,
    weight: showWeight() ? Number(weight) : null,
    owner_id: ownerId,
    owner_id_2: scope === 'teacher_room' ? ownerId2 : null,
    day: kind === 'matrix_slot' ? day : null,
    hour: kind === 'matrix_slot' ? hour : null,
    reason: kind === 'matrix_slot' ? (reason || null) : null,
    expression: kind === 'logical' ? expression : null,
    label: kind === 'logical' ? (labelText || null) : null,
    year_filter: kind === 'logical' && scope === 'curriculum'
                  ? (yearFilter ? Number(yearFilter) : null) : null,
    subject: ['subject_room', 'coteach'].includes(scope) || kind === 'coteach'
              ? (subject || null) : null,
    n_teachers: kind === 'coteach' ? Number(nTeachers) : null,
    teacher_csv: kind === 'coteach' ? (teacherCsv || null) : null,
  };

  async function submit() {
    busy = true;
    try {
      const r = await api.post('/api/constraints', payload);
      createdResult = r;
      flash(`Vincolo creato: ${r.kind} #${r.id} (${r.detail || ''})`,
            'success');
      onCreated();
    } catch (e) {
      flash('Errore: ' + (e.message || e), 'error');
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} title="Crea nuovo vincolo" {onClose}>
  <div class="space-y-3">
    <!-- Stepper indicator -->
    <div class="flex items-center gap-2 text-xs">
      {#each [1, 2, 3, 4] as i}
        <span class="pill {step === i ? 'pill-blue' : ''} !text-[10px]">
          {i}. {['Categoria', 'Livello', 'Tipo', 'Conferma'][i - 1]}
        </span>
        {#if i < 4}<span class="text-ink-300">›</span>{/if}
      {/each}
    </div>

    {#if step === 1}
      <div class="space-y-3">
        <div class="field">
          <label>Categoria del vincolo</label>
          <select bind:value={scope}>
            {#each SCOPE_OPTIONS as o}
              <option value={o.value}>{o.label}</option>
            {/each}
          </select>
        </div>

        {#if scope === 'teacher' || scope === 'teacher_room'}
          <div class="field">
            <label>Docente *</label>
            <select bind:value={ownerId}>
              <option value={null}>-- scegli --</option>
              {#each teachers as t}<option value={t.id}>{t.name}</option>{/each}
            </select>
          </div>
        {/if}
        {#if scope === 'class'}
          <div class="field">
            <label>Classe *</label>
            <select bind:value={ownerId}>
              <option value={null}>-- scegli --</option>
              {#each classes as c}<option value={c.id}>{c.name}</option>{/each}
            </select>
          </div>
        {/if}
        {#if scope === 'classroom' || scope === 'subject_room'}
          <div class="field">
            <label>Aula *</label>
            <select bind:value={ownerId}>
              <option value={null}>-- scegli --</option>
              {#each classrooms as r}<option value={r.id}>{r.name}</option>{/each}
            </select>
          </div>
        {/if}
        {#if scope === 'curriculum'}
          <div class="field">
            <label>Indirizzo *</label>
            <select bind:value={ownerId}>
              <option value={null}>-- scegli --</option>
              {#each curricula as cu}<option value={cu.id}>{cu.name}</option>{/each}
            </select>
          </div>
        {/if}
        {#if scope === 'subject_room'}
          <div class="field">
            <label>Materia *</label>
            <select bind:value={subject}>
              <option value="">-- scegli --</option>
              {#each subjects as s}<option value={s}>{s}</option>{/each}
            </select>
          </div>
        {/if}
        {#if scope === 'teacher_room'}
          <div class="field">
            <label>Aula *</label>
            <select bind:value={ownerId2}>
              <option value={null}>-- scegli --</option>
              {#each classrooms as r}<option value={r.id}>{r.name}</option>{/each}
            </select>
          </div>
        {/if}
      </div>
    {:else if step === 2}
      <div class="space-y-2">
        <div class="text-xs text-ink-500">Livello del vincolo</div>
        {#each levelsForKind as l}
          <label class="flex items-start gap-2 text-sm">
            <input type="radio" bind:group={level} value={l.value} class="mt-1"/>
            <span>
              <strong>{l.label}</strong>
              <span class="text-xs text-ink-500"> - {l.desc}</span>
            </span>
          </label>
        {/each}
        {#if showWeight()}
          <div class="field mt-3">
            <label>Peso (penalty SOFT)</label>
            <input type="number" bind:value={weight}/>
            <div class="text-xs text-ink-500">
              Penalita' positiva quando SOFT viene violato; per
              PREFERRED il valore viene negato automaticamente.
            </div>
          </div>
        {/if}
      </div>
    {:else if step === 3}
      <div class="space-y-3">
        <div class="field">
          <label>Tipo di vincolo</label>
          <select bind:value={kind}>
            {#each availableKinds as k}
              <option value={k.value}>{k.label}</option>
            {/each}
          </select>
        </div>

        {#if kind === 'matrix_slot'}
          <div class="grid grid-cols-2 gap-3">
            <div class="field">
              <label>Giorno *</label>
              <select bind:value={day}>
                {#each DAYS as d}<option value={d}>{DAY_NAMES_IT[d]}</option>{/each}
              </select>
            </div>
            <div class="field">
              <label>Ora *</label>
              <select bind:value={hour}>
                {#each HOURS as h}<option value={h}>{h}:00</option>{/each}
              </select>
            </div>
          </div>
          <div class="field">
            <label>Motivazione (opzionale)</label>
            <input bind:value={reason} placeholder="es. lezione di laboratorio"/>
          </div>
        {/if}
        {#if kind === 'logical'}
          <div class="field">
            <label>Espressione DNF *</label>
            <input bind:value={expression}
                   class="font-mono"
                   placeholder="(lun8 AND lun9) OR (mar8 AND mar9)"/>
            <div class="text-xs text-ink-500">
              Espressione booleana. Slot validi: <code>lun8..sab13</code>.
              Operatori: <code>AND</code>, <code>OR</code>,
              <code>NOT</code>, parentesi.
            </div>
          </div>
          <div class="field">
            <label>Etichetta (opzionale)</label>
            <input bind:value={labelText} placeholder="es. consecutiva matematica"/>
          </div>
          {#if scope === 'curriculum'}
            <div class="field">
              <label>Anno (opzionale, applica solo a quell'anno)</label>
              <input type="number" bind:value={yearFilter}/>
            </div>
          {/if}
        {/if}
        {#if kind === 'coteach'}
          <div class="field">
            <label>Materia *</label>
            <select bind:value={subject}>
              <option value="">-- scegli --</option>
              {#each subjects as s}<option value={s}>{s}</option>{/each}
            </select>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div class="field">
              <label>Numero docenti *</label>
              <input type="number" bind:value={nTeachers} min="2"/>
            </div>
            <div class="field">
              <label>Docenti CSV (opzionale)</label>
              <input bind:value={teacherCsv}
                     placeholder="Rossi,Bianchi"/>
            </div>
          </div>
        {/if}
      </div>
    {:else if step === 4}
      <div class="space-y-3">
        <div class="card !shadow-none p-3 bg-ink-50">
          <div class="text-xs text-ink-500 mb-1">Riepilogo:</div>
          <div class="text-sm">{summary}</div>
        </div>
        <details class="text-xs">
          <summary class="cursor-pointer text-ink-500">
            Payload tecnico (POST /api/constraints)
          </summary>
          <pre class="bg-white p-2 rounded border border-ink-200 text-[10px] mt-1 overflow-auto max-h-48">{JSON.stringify(payload, null, 2)}</pre>
        </details>
        {#if createdResult}
          <div class="card p-2 bg-emerald-50 border-emerald-300 text-xs">
            ✓ Vincolo creato: <strong>{createdResult.kind} #{createdResult.id}</strong>
            ({createdResult.detail || ''})
          </div>
        {/if}
      </div>
    {/if}

    <!-- Navigation -->
    <div class="flex justify-between gap-2 pt-3 border-t border-ink-100">
      <button class="btn" on:click={onClose} disabled={busy}>Chiudi</button>
      <div class="flex gap-2">
        {#if step > 1}
          <button class="btn" on:click={() => step--}
                  disabled={busy}>Indietro</button>
        {/if}
        {#if step === 1}
          <button class="btn-primary" on:click={() => step = 2}
                  disabled={!step1Valid()}>Avanti</button>
        {:else if step === 2}
          <button class="btn-primary" on:click={() => step = 3}>Avanti</button>
        {:else if step === 3}
          <button class="btn-primary" on:click={() => step = 4}
                  disabled={!step3Valid()}>Avanti</button>
        {:else if step === 4 && !createdResult}
          <button class="btn-primary" on:click={submit} disabled={busy}>
            {busy ? '...' : 'Crea vincolo'}
          </button>
        {:else if createdResult}
          <button class="btn-primary" on:click={() => { createdResult = null; step = 1; }}>
            Crea un altro
          </button>
        {/if}
      </div>
    </div>
  </div>
</Modal>
