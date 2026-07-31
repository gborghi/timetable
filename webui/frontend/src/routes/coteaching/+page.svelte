<script>
  import PageHero from '$lib/components/PageHero.svelte';
  import { confirmDialog } from '$lib/confirm';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { flash } from '$lib/stores';
  import Modal from '$lib/components/Modal.svelte';
  import { cloneRow } from '$lib/utils';
  import {
    coteaching as coteachingSvc,
    classes as classesSvc,
    teachers as teachersSvc,
    subjects as subjectsSvc
  } from '$lib/services';

  let rows = [];
  let editing = null;
  let allClasses = [];
  let allTeachers = [];
  let allSubjects = [];

  onMount(async () => {
    rows = await coteachingSvc.list();
    allClasses = (await classesSvc.list()).map((c) => c.name);
    allTeachers = (await teachersSvc.list()).map((t) => t.name);
    allSubjects = (await subjectsSvc.list()).map((s) => s.name);
  });

  function newRule() {
    editing = {
      _new: true, class_name: '', subject: '',
      required: true, weight: 100, n_teachers: 2, teachers: ['', '']
    };
  }

  function edit(row) { editing = cloneRow(row); }

  async function save() {
    const payload = {
      class_name: editing.class_name,
      subject: editing.subject,
      required: editing.required,
      weight: Number(editing.weight),
      n_teachers: Number(editing.n_teachers || 2),
      teachers: editing.teachers.filter((t) => t)
    };
    try {
      if (editing._new) await coteachingSvc.create(payload);
      else await coteachingSvc.update(editing.id, payload);
      flash('Salvato', 'success');
      editing = null;
      rows = await coteachingSvc.list();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function del(row) {
    if (!await confirmDialog('Eliminare regola compresenza per ' + row.class_name + ' / ' + row.subject + '?')) return;
    try {
      await coteachingSvc.remove(row.id);
      rows = await coteachingSvc.list();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  function setNTeachers(n) {
    editing.n_teachers = n;
    while (editing.teachers.length < n) editing.teachers.push('');
    editing.teachers = editing.teachers.slice(0, n);
  }
</script>

<div class="space-y-4" data-testid="coteaching-page">
  <PageHero title="Compresenze"
            description="Due o piu' docenti nella stessa ora sulla stessa classe. Una regola HARD obbliga il solver a farli coincidere; una SOFT la penalizza soltanto.">
    <svelte:fragment slot="chips">
      <span class="pill" data-testid="coteaching-count">
        <span class="num">{rows.length}</span> regole
      </span>
    </svelte:fragment>
    <svelte:fragment slot="actions">
      <button class="btn-primary" on:click={newRule} data-testid="add-coteaching-btn">+ Nuova regola</button>
    </svelte:fragment>
  </PageHero>

  <div class="card overflow-x-auto">
    <table class="tbl" data-testid="coteaching-table">
      <thead>
        <tr>
          <th>Classe</th><th>Materia</th><th>HARD?</th><th>Peso</th>
          <th># docenti</th><th>Docenti</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each rows as r}
          <tr data-testid="coteaching-row" data-class={r.class_name} data-subject={r.subject}>
            <td><strong>{r.class_name}</strong></td>
            <td>{r.subject}</td>
            <td>{#if r.required}<span class="pill-red" data-testid="coteaching-row-required">HARD</span>{:else}<span class="pill-amber" data-testid="coteaching-row-soft">SOFT</span>{/if}</td>
            <td data-testid="coteaching-row-weight">{r.weight}</td>
            <td data-testid="coteaching-row-nteachers">{r.n_teachers}</td>
            <td class="text-xs" data-testid="coteaching-row-teachers">{r.teachers.join(' + ')}</td>
            <td class="whitespace-nowrap">
              <button class="btn !text-xs !px-2 !py-1" on:click={() => edit(r)} data-testid="coteaching-edit-btn">Modifica</button>
              <button class="btn-danger !text-xs !px-2 !py-1" on:click={() => del(r)} data-testid="coteaching-delete-btn">Elimina</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <p class="text-xs text-ink-500">
    Una compresenza HARD blocca due (o piu) docenti nello stesso slot della stessa lezione.
    Le compresenze SOFT sono "preferenze" pesate. La schedulazione (Phase B) gia gestisce la
    coverage per (classe, materia); la compresenza viene risolta in fase di assegnazione cattedre
    (vedi pagina Cattedre).
  </p>
</div>

<Modal open={!!editing} title={editing?._new ? 'Nuova compresenza' : 'Modifica regola'} onClose={() => (editing = null)}>
  {#if editing}
    <div class="grid grid-cols-2 gap-3" data-testid="coteaching-form">
      <div class="field">
        <label>Classe</label>
        <input list="ll-cls" bind:value={editing.class_name} data-testid="coteaching-class-input"/>
        <datalist id="ll-cls">{#each allClasses as c}<option value={c}></option>{/each}</datalist>
      </div>
      <div class="field">
        <label>Materia</label>
        <input list="ll-subj" bind:value={editing.subject} data-testid="coteaching-subject-input"/>
        <datalist id="ll-subj">{#each allSubjects as s}<option value={s}></option>{/each}</datalist>
      </div>
      <label class="flex items-center gap-2 text-sm"><input type="checkbox" bind:checked={editing.required} data-testid="coteaching-required-checkbox"/> HARD (obbligatoria)</label>
      <div class="field">
        <label>Peso (se SOFT)</label>
        <input type="number" bind:value={editing.weight} data-testid="coteaching-weight-input"/>
      </div>
      <div class="field">
        <label>N. docenti</label>
        <input type="number" min="2" max="4"
          value={editing.n_teachers}
          on:input={(e) => setNTeachers(Number(e.target.value))}
          data-testid="coteaching-nteachers-input"/>
      </div>
    </div>
    <div class="mt-3">
      <h3 class="mb-2">Docenti coinvolti</h3>
      <div class="space-y-2" data-testid="coteaching-teachers-list">
        {#each editing.teachers as t, i}
          <input list="ll-t-{i}" class="w-full px-2 py-1 rounded border border-ink-200" bind:value={editing.teachers[i]} data-testid="coteaching-teacher-input" data-index={i}/>
          <datalist id="ll-t-{i}">{#each allTeachers as tn}<option value={tn}></option>{/each}</datalist>
        {/each}
      </div>
    </div>
    <div class="mt-5 flex justify-end gap-2">
      <button class="btn" on:click={() => (editing = null)} data-testid="coteaching-cancel-btn">Annulla</button>
      <button class="btn-primary" on:click={save} data-testid="coteaching-save-btn">Salva</button>
    </div>
  {/if}
</Modal>
