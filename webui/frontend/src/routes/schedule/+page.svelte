<script>
  import { onMount } from 'svelte';
  import { api, downloadUrl } from '$lib/api.js';
  import { flash, refreshDataset } from '$lib/stores.js';
  import { DAYS, HOURS, DAY_NAMES_IT } from '$lib/constants.js';
  import MoveModeBanner from '$lib/components/schedule/MoveModeBanner.svelte';
  import RoomDropdown from '$lib/components/schedule/RoomDropdown.svelte';
  import PreviewCellHint from '$lib/components/schedule/PreviewCellHint.svelte';
  import RoomClearedNoticeModal from '$lib/components/schedule/RoomClearedNoticeModal.svelte';
  import SolutionsTable from '$lib/components/schedule/SolutionsTable.svelte';

  let view = 'classes';   // classes | teachers | rooms | slot
  // each entity gets an independent layout toggle:
  //   'matrix' = per-entity 6x6 grid with drag-drop / move preview
  //   'list'   = single big table with one row per entity and 36 slot columns
  let classesViewMode = 'matrix';
  let teachersViewMode = 'matrix';
  let roomsViewMode = 'matrix';
  let classData = null;
  let teacherData = null;
  let roomData = null;
  let slotData = null;
  let selectedClass = '';
  let selectedTeacher = '';
  let selectedRoom = '';
  let slotDay = 1, slotHour = 8;
  let dragging = null;
  let dropTarget = null;
  let lastMoveOutcome = null;
  let solutions = [];
  let allRooms = [];
  // 'move mode' state
  let moveSrc = null;          // {lesson_id, teacher, cls, subject, day, hour}
  let movePreview = null;      // map "d-h" -> {status, reason, delta_soft}
  let movePreviewBusy = false;
  // When the backend reports room_cleared after a move, we surface a
  // modal alert so the user knows the old classroom couldn't follow the
  // lesson and must be replaced manually.
  let roomClearedNotice = null;  // {room, day, hour, ctx, class_name, teacher}

  onMount(async () => {
    await loadAll();
    solutions = await api.get('/api/schedule/solutions');
    allRooms = (await api.get('/api/classrooms')).map((r) => r.name).sort();
  });

  async function loadAll() {
    try {
      classData = await api.get('/api/schedule/by-class');
      if (classData?.classes?.length) selectedClass = classData.classes[0];
      teacherData = await api.get('/api/schedule/by-teacher');
      if (teacherData?.teachers?.length) selectedTeacher = teacherData.teachers[0];
      roomData = await api.get('/api/schedule/by-room');
      if (roomData?.rooms?.length && !selectedRoom) selectedRoom = roomData.rooms[0];
    } catch (e) {
      flash('Nessuna soluzione attiva: ' + e.message, 'error');
    }
  }

  function loadSlot() {
    api.get(`/api/schedule/by-slot?day=${slotDay}&hour=${slotHour}`)
      .then((d) => slotData = d)
      .catch((e) => flash(e.message, 'error'));
  }

  function startDrag(ev, payload) {
    dragging = payload;
    ev.dataTransfer.effectAllowed = 'move';
    ev.target.classList.add('dragging');
  }
  function endDrag(ev) {
    if (ev.target.classList) ev.target.classList.remove('dragging');
  }
  function overTarget(ev, key) {
    ev.preventDefault();
    dropTarget = key;
  }
  function leaveTarget(ev) { dropTarget = null; }

  async function dropOn(ev, dst) {
    ev.preventDefault();
    if (!dragging) return;
    const payload = {
      teacher_name: dragging.teacher,
      class_name: dragging.cls,
      subject: dragging.subject,
      src_day: dragging.day,
      src_hour: dragging.hour,
      dst_day: dst.day,
      dst_hour: dst.hour
    };
    dragging = null;
    dropTarget = null;
    try {
      const r = await api.put('/api/schedule/move-lesson', payload);
      lastMoveOutcome = r;
      if (!r.accepted) {
        flash('Mossa rifiutata: ' + r.reason, 'error');
      } else {
        flash(r.reason || 'Mossa accettata', 'success');
      }
      await loadAll();
      await refreshDataset();
      if (r.accepted && r.room_cleared) {
        roomClearedNotice = {
          room: r.cleared_room,
          day: dst.day,
          hour: dst.hour,
          class_name: payload.class_name,
          teacher: payload.teacher_name,
          subject: payload.subject,
        };
      }
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  // ---- Move mode (click-to-select-then-click-target) ---------------
  async function startMove(cell, day, hour, ctx) {
    // ctx tells if we're in classes view or teachers view (so we can
    // pick the right teacher/class)
    if (!cell || !cell.lesson_id) return;
    const teacher = ctx === 'classes' ? cell.teachers[0] : selectedTeacher;
    const cls = ctx === 'classes' ? selectedClass : cell.class_name;
    const subject = ctx === 'classes' ? cell.subjects[0] : cell.subject;
    moveSrc = { lesson_id: cell.lesson_id, teacher, cls, subject, day, hour };
    movePreview = null;
    movePreviewBusy = true;
    try {
      const r = await api.post('/api/schedule/move-preview',
        { lesson_id: cell.lesson_id });
      const map = {};
      for (const s of (r.results || [])) {
        map[s.day + '-' + s.hour] = s;
      }
      movePreview = map;
    } catch (e) {
      flash('Errore preview: ' + e.message, 'error');
      moveSrc = null;
    } finally {
      movePreviewBusy = false;
    }
  }

  function cancelMove() {
    moveSrc = null;
    movePreview = null;
  }

  async function confirmMove(day, hour) {
    if (!moveSrc) return;
    if (day === moveSrc.day && hour === moveSrc.hour) {
      cancelMove();
      return;
    }
    const cell = movePreview ? movePreview[day + '-' + hour] : null;
    if (cell && cell.status === 'hard_violation') {
      flash('Slot non valido: ' + cell.reason, 'error');
      return;
    }
    try {
      const r = await api.put('/api/schedule/move-lesson', {
        teacher_name: moveSrc.teacher,
        class_name: moveSrc.cls,
        subject: moveSrc.subject,
        src_day: moveSrc.day,
        src_hour: moveSrc.hour,
        dst_day: day,
        dst_hour: hour
      });
      lastMoveOutcome = r;
      if (!r.accepted) flash('Mossa rifiutata: ' + r.reason, 'error');
      else flash(r.reason || 'Mossa applicata', 'success');
      const movedDay = day;
      const movedHour = hour;
      const movedSrc = moveSrc;
      cancelMove();
      await loadAll();
      await refreshDataset();
      if (r.accepted && r.room_cleared) {
        roomClearedNotice = {
          room: r.cleared_room,
          day: movedDay,
          hour: movedHour,
          class_name: movedSrc.cls,
          teacher: movedSrc.teacher,
          subject: movedSrc.subject,
        };
      }
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  function previewClass(d, h) {
    if (!movePreview) return null;
    return movePreview[d + '-' + h] || null;
  }

  async function setRoom(lessonId, roomName) {
    try {
      const url = '/api/schedule/lesson/' + lessonId + '/classroom'
        + (roomName ? '?classroom_name=' + encodeURIComponent(roomName) : '');
      await api.put(url);
      flash('Aula aggiornata', 'success');
      await loadAll();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function activateSolution(id) {
    try {
      await api.post('/api/schedule/solutions/' + id + '/activate');
      flash('Soluzione attivata', 'success');
      await loadAll();
      solutions = await api.get('/api/schedule/solutions');
      await refreshDataset();
    } catch (e) {
      flash('Errore: ' + e.message, 'error');
    }
  }

  async function delSolution(id) {
    if (!confirm('Eliminare questa soluzione?')) return;
    try {
      await api.del('/api/schedule/solutions/' + id);
      solutions = await api.get('/api/schedule/solutions');
      await loadAll();
    } catch (e) { flash(e.message, 'error'); }
  }

  $: selClassGrid = classData && selectedClass ? classData.grid[selectedClass] : null;
  $: selTeacherGrid = teacherData && selectedTeacher ? teacherData.grid[selectedTeacher] : null;
  $: selRoomGrid = roomData && selectedRoom ? roomData.grid[selectedRoom] : null;

  // Per-slot set of occupied classroom names. Used by the cell dropdowns
  // to color free rooms green and disable busy rooms (red).
  $: occupiedAt = (() => {
    const out = {};
    if (!roomData) return out;
    for (const d of DAYS) for (const h of HOURS) {
      const set = new Set();
      for (const rn of roomData.rooms) {
        const lst = roomData.grid?.[rn]?.[d]?.[h] ?? [];
        if (lst.length > 0) set.add(rn);
      }
      out[d + '-' + h] = set;
    }
    return out;
  })();

  function isRoomBusy(d, h, roomName, currentRoom) {
    // The room currently assigned to this very lesson stays selectable,
    // so the user can keep it. Any other occupied room is red+disabled.
    if (roomName === currentRoom) return false;
    return (occupiedAt[d + '-' + h] || new Set()).has(roomName);
  }
</script>

<div class="space-y-4">
  <div class="flex items-baseline gap-3 flex-wrap">
    <h1>Orario</h1>
    {#if classData}
      <span class="text-sm text-ink-500">
        obj=<code>{classData.obj_value}</code>
        - {Object.entries(classData.metrics || {}).map(([k, v]) => `${k}=${v}`).join(' ')}
      </span>
    {/if}
    <div class="ml-auto flex gap-1">
      <button class="btn !text-xs" class:bg-ink-100={view === 'classes'} on:click={() => (view = 'classes')}>per classe</button>
      <button class="btn !text-xs" class:bg-ink-100={view === 'teachers'} on:click={() => (view = 'teachers')}>per docente</button>
      <button class="btn !text-xs" class:bg-ink-100={view === 'rooms'} on:click={() => (view = 'rooms')}>per aula</button>
      <button class="btn !text-xs" class:bg-ink-100={view === 'slot'} on:click={() => { view = 'slot'; loadSlot(); }}>per slot</button>
    </div>
    <a class="btn-primary !text-xs" href={downloadUrl('/api/schedule/export/xlsx-classes')}>xlsx classi</a>
    <a class="btn !text-xs" href={downloadUrl('/api/schedule/export/xlsx-teachers')}>xlsx docenti</a>
    <a class="btn !text-xs" href={downloadUrl('/api/schedule/export/pdf-classes')}>pdf classi</a>
    <a class="btn !text-xs" href={downloadUrl('/api/schedule/export/pdf-teachers')}>pdf docenti</a>
  </div>

  {#if !classData}
    <div class="card p-6 text-center text-ink-500">
      Nessuna soluzione attiva. Vai al
      <a class="text-accent-500 underline" href="/optimize">Workflow</a>
      e lancia almeno la Phase B, oppure importa un pickle dalla
      <a class="text-accent-500 underline" href="/">Dashboard</a>.
    </div>
  {:else}

  {#if view === 'classes'}
    <div class="card p-3 flex items-center gap-3 flex-wrap">
      {#if classesViewMode === 'matrix'}
        <label class="text-sm">Classe</label>
        <select class="ml-2 px-2 py-1.5 rounded-md border border-ink-200" bind:value={selectedClass}>
          {#each classData.classes as c}<option>{c}</option>{/each}
        </select>
      {:else}
        <span class="text-sm text-ink-500">Lista: {classData.classes.length} classi</span>
      {/if}
      <div class="ml-auto flex gap-1">
        <button class="btn !text-xs" class:bg-ink-100={classesViewMode === 'matrix'}
                on:click={() => (classesViewMode = 'matrix')}>matrice</button>
        <button class="btn !text-xs" class:bg-ink-100={classesViewMode === 'list'}
                on:click={() => (classesViewMode = 'list')}>lista</button>
      </div>
    </div>
    {#if classesViewMode === 'matrix' && selClassGrid}
      <MoveModeBanner {moveSrc} {movePreviewBusy} showLegend={true} onCancel={cancelMove}/>
      <div class="card p-4 overflow-auto">
        <div class="timetable-grid">
          <div></div>
          {#each DAYS as d}
            <div class="text-xs text-center font-semibold text-ink-500 pb-1">{DAY_NAMES_IT[d]}</div>
          {/each}
          {#each HOURS as h}
            <div class="text-xs text-ink-500 pr-2 pt-2">{h}:00</div>
            {#each DAYS as d}
              {@const cell = selClassGrid[d][h]}
              {@const key = 'cell-' + d + '-' + h}
              {@const pv = movePreview ? movePreview[d + '-' + h] : null}
              <div class="cell card !shadow-none p-2 text-xs relative"
                class:drop-target={dropTarget === key && dragging}
                class:!bg-emerald-100={moveSrc && pv && pv.status === 'ok' && pv.delta_soft !== 0}
                class:!bg-emerald-50={moveSrc && pv && pv.status === 'ok' && pv.delta_soft === 0}
                class:!bg-amber-100={moveSrc && pv && pv.status === 'soft_worse'}
                class:!bg-red-200={moveSrc && pv && pv.status === 'hard_violation'}
                class:cursor-pointer={moveSrc}
                title={pv && pv.reason ? pv.reason
                  : (pv && pv.delta_soft != null
                     ? (pv.delta_soft > 0 ? '+' + pv.delta_soft : '' + pv.delta_soft)
                       + ' punti SOFT'
                     : '')}
                on:click={moveSrc ? () => confirmMove(d, h) : undefined}
                on:dragover={(e) => overTarget(e, key)}
                on:dragleave={leaveTarget}
                on:drop={(e) => dropOn(e, { day: d, hour: h })}>
                {#if cell}
                  <div class="flex items-center justify-between">
                    <div class="font-semibold cursor-grab"
                      draggable="true"
                      on:dragstart={(e) => startDrag(e, {
                        teacher: cell.teachers[0],
                        cls: selectedClass,
                        subject: cell.subjects[0],
                        day: d, hour: h
                      })}
                      on:dragend={endDrag}>
                      {cell.subjects.join('+')}
                    </div>
                    {#if !moveSrc}
                      <button class="text-[10px] text-accent-500 hover:underline"
                        title="Sposta..."
                        on:click|stopPropagation={() => startMove(cell, d, h, 'classes')}>
                        sposta
                      </button>
                    {/if}
                  </div>
                  <div class="text-ink-500">{cell.teachers.join(' + ')}</div>
                  <div class="mt-1">
                    <RoomDropdown lessonId={cell.lesson_id}
                                  currentRoom={cell.classroom}
                                  {allRooms}
                                  isBusy={(r) => isRoomBusy(d, h, r, cell.classroom)}
                                  onChange={setRoom}/>
                  </div>
                {:else}
                  <PreviewCellHint preview={pv} active={!!moveSrc}/>
                {/if}
              </div>
            {/each}
          {/each}
        </div>
      </div>
    {:else if classesViewMode === 'list'}
      <div class="card p-2 overflow-auto">
        <table class="tbl text-xs">
          <thead>
            <tr>
              <th class="sticky left-0 bg-white z-10">Classe</th>
              {#each DAYS as d}{#each HOURS as h}
                <th class="text-[10px] text-center min-w-12">
                  {DAY_NAMES_IT[d][0]}{h}
                </th>
              {/each}{/each}
            </tr>
          </thead>
          <tbody>
            {#each classData.classes as cn}
              <tr>
                <td class="sticky left-0 bg-white font-semibold">{cn}</td>
                {#each DAYS as d}{#each HOURS as h}
                  {@const cell = classData.grid[cn]?.[d]?.[h] ?? null}
                  <td class="p-1 text-[10px] text-center"
                      class:bg-emerald-50={!cell}
                      class:bg-amber-50={cell && cell.subjects.length > 1}
                      class:bg-white={cell && cell.subjects.length === 1}
                      title={cell ? cell.teachers.join(' + ') + ' / ' + cell.subjects.join('+') + (cell.classroom ? ' / ' + cell.classroom : '') : ''}>
                    {#if cell}
                      <div class="font-semibold">{cell.subjects.join('+')}</div>
                      <div class="text-ink-400 text-[9px] truncate">{cell.teachers.join('+')}</div>
                    {:else}
                      <span class="text-ink-300">-</span>
                    {/if}
                  </td>
                {/each}{/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {:else if view === 'teachers'}
    <div class="card p-3 flex items-center gap-3 flex-wrap">
      {#if teachersViewMode === 'matrix'}
        <label class="text-sm">Docente</label>
        <select class="ml-2 px-2 py-1.5 rounded-md border border-ink-200" bind:value={selectedTeacher}>
          {#each teacherData.teachers as t}<option>{t}</option>{/each}
        </select>
      {:else}
        <span class="text-sm text-ink-500">Lista: {teacherData.teachers.length} docenti</span>
      {/if}
      <div class="ml-auto flex gap-1">
        <button class="btn !text-xs" class:bg-ink-100={teachersViewMode === 'matrix'}
                on:click={() => (teachersViewMode = 'matrix')}>matrice</button>
        <button class="btn !text-xs" class:bg-ink-100={teachersViewMode === 'list'}
                on:click={() => (teachersViewMode = 'list')}>lista</button>
      </div>
    </div>
    {#if teachersViewMode === 'matrix' && selTeacherGrid}
      <MoveModeBanner {moveSrc} onCancel={cancelMove}/>
      <div class="card p-4 overflow-auto">
        <div class="timetable-grid">
          <div></div>
          {#each DAYS as d}<div class="text-xs text-center font-semibold text-ink-500 pb-1">{DAY_NAMES_IT[d]}</div>{/each}
          {#each HOURS as h}
            <div class="text-xs text-ink-500 pr-2 pt-2">{h}:00</div>
            {#each DAYS as d}
              {@const cell = selTeacherGrid[d][h]}
              {@const key = 'cell-t-' + d + '-' + h}
              {@const pv = movePreview ? movePreview[d + '-' + h] : null}
              <div class="cell card !shadow-none p-2 text-xs relative"
                class:drop-target={dropTarget === key && dragging}
                class:!bg-emerald-100={moveSrc && pv && pv.status === 'ok' && pv.delta_soft !== 0}
                class:!bg-emerald-50={moveSrc && pv && pv.status === 'ok' && pv.delta_soft === 0}
                class:!bg-amber-100={moveSrc && pv && pv.status === 'soft_worse'}
                class:!bg-red-200={moveSrc && pv && pv.status === 'hard_violation'}
                class:cursor-pointer={moveSrc}
                title={pv && pv.reason ? pv.reason
                  : (pv && pv.delta_soft != null
                     ? (pv.delta_soft > 0 ? '+' + pv.delta_soft : '' + pv.delta_soft)
                       + ' punti SOFT'
                     : '')}
                on:click={moveSrc ? () => confirmMove(d, h) : undefined}
                on:dragover={(e) => overTarget(e, key)}
                on:dragleave={leaveTarget}
                on:drop={(e) => dropOn(e, { day: d, hour: h })}>
                {#if cell}
                  <div class="flex items-center justify-between">
                    <div class="font-semibold cursor-grab"
                      draggable="true"
                      on:dragstart={(e) => startDrag(e, {
                        teacher: selectedTeacher,
                        cls: cell.class_name,
                        subject: cell.subject,
                        day: d, hour: h
                      })}
                      on:dragend={endDrag}>
                      {cell.class_name}
                    </div>
                    {#if !moveSrc}
                      <button class="text-[10px] text-accent-500 hover:underline"
                        title="Sposta..."
                        on:click|stopPropagation={() => startMove(cell, d, h, 'teachers')}>
                        sposta
                      </button>
                    {/if}
                  </div>
                  <div class="text-ink-500">{cell.subject}</div>
                  <div class="mt-1">
                    <RoomDropdown lessonId={cell.lesson_id}
                                  currentRoom={cell.classroom}
                                  {allRooms}
                                  isBusy={(r) => isRoomBusy(d, h, r, cell.classroom)}
                                  onChange={setRoom}/>
                  </div>
                {:else}
                  <PreviewCellHint preview={pv} active={!!moveSrc}/>
                {/if}
              </div>
            {/each}
          {/each}
        </div>
      </div>
    {:else if teachersViewMode === 'list'}
      <div class="card p-2 overflow-auto">
        <table class="tbl text-xs">
          <thead>
            <tr>
              <th class="sticky left-0 bg-white z-10">Docente</th>
              {#each DAYS as d}{#each HOURS as h}
                <th class="text-[10px] text-center min-w-12">
                  {DAY_NAMES_IT[d][0]}{h}
                </th>
              {/each}{/each}
            </tr>
          </thead>
          <tbody>
            {#each teacherData.teachers as tn}
              <tr>
                <td class="sticky left-0 bg-white font-semibold">{tn}</td>
                {#each DAYS as d}{#each HOURS as h}
                  {@const cell = teacherData.grid[tn]?.[d]?.[h] ?? null}
                  <td class="p-1 text-[10px] text-center"
                      class:bg-emerald-50={!cell}
                      class:bg-white={cell}
                      title={cell ? cell.class_name + ' / ' + cell.subject + (cell.classroom ? ' / ' + cell.classroom : '') : ''}>
                    {#if cell}
                      <div class="font-semibold">{cell.class_name}</div>
                      <div class="text-ink-400 text-[9px] truncate">{cell.subject}</div>
                    {:else}
                      <span class="text-ink-300">-</span>
                    {/if}
                  </td>
                {/each}{/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {:else if view === 'rooms'}
    {#if roomData}
    <div class="card p-3 flex items-center gap-3 flex-wrap">
      {#if roomsViewMode === 'matrix'}
        <label class="text-sm">Aula</label>
        <select class="ml-2 px-2 py-1.5 rounded-md border border-ink-200" bind:value={selectedRoom}>
          {#each roomData.rooms as r}<option>{r}</option>{/each}
        </select>
        {#if selectedRoom && roomData.rooms_meta[selectedRoom]}
          <span class="pill">{roomData.rooms_meta[selectedRoom].kind}</span>
          <span class="text-xs text-ink-500">cap. {roomData.rooms_meta[selectedRoom].capacity}</span>
        {/if}
      {:else}
        <span class="text-sm text-ink-500">Lista: {roomData.rooms.length} aule</span>
      {/if}
      <div class="ml-auto flex gap-1">
        <button class="btn !text-xs" class:bg-ink-100={roomsViewMode === 'matrix'}
                on:click={() => (roomsViewMode = 'matrix')}>matrice</button>
        <button class="btn !text-xs" class:bg-ink-100={roomsViewMode === 'list'}
                on:click={() => (roomsViewMode = 'list')}>lista</button>
      </div>
    </div>
    {#if roomsViewMode === 'matrix' && selRoomGrid}
      <MoveModeBanner {moveSrc} onCancel={cancelMove}/>
      <div class="card p-4 overflow-auto">
        <div class="timetable-grid">
          <div></div>
          {#each DAYS as d}<div class="text-xs text-center font-semibold text-ink-500 pb-1">{DAY_NAMES_IT[d]}</div>{/each}
          {#each HOURS as h}
            <div class="text-xs text-ink-500 pr-2 pt-2">{h}:00</div>
            {#each DAYS as d}
              {@const lst = selRoomGrid?.[d]?.[h] ?? []}
              {@const key = 'cell-r-' + d + '-' + h}
              {@const pv = movePreview ? movePreview[d + '-' + h] : null}
              {@const isMulti = lst.length > 1}
              <div class="cell card !shadow-none p-2 text-xs relative"
                class:drop-target={dropTarget === key && dragging}
                class:!bg-emerald-100={moveSrc && pv && pv.status === 'ok' && pv.delta_soft !== 0}
                class:!bg-emerald-50={moveSrc && pv && pv.status === 'ok' && pv.delta_soft === 0}
                class:!bg-amber-100={moveSrc && pv && pv.status === 'soft_worse'}
                class:!bg-red-200={moveSrc && pv && pv.status === 'hard_violation'}
                class:!bg-red-50={!moveSrc && isMulti}
                class:cursor-pointer={moveSrc}
                title={pv && pv.reason ? pv.reason
                  : (pv && pv.delta_soft != null
                     ? (pv.delta_soft > 0 ? '+' + pv.delta_soft : '' + pv.delta_soft)
                       + ' punti SOFT'
                     : (isMulti ? lst.length + ' lezioni nello stesso slot' : ''))}
                on:click={moveSrc ? () => confirmMove(d, h) : undefined}
                on:dragover={(e) => overTarget(e, key)}
                on:dragleave={leaveTarget}
                on:drop={(e) => dropOn(e, { day: d, hour: h })}>
                {#if lst.length}
                  {#each lst as l}
                    <div class="cursor-grab"
                      draggable="true"
                      on:dragstart={(e) => startDrag(e, {
                        teacher: l.teacher, cls: l.class_name,
                        subject: l.subject, day: d, hour: h
                      })}
                      on:dragend={endDrag}>
                      <div class="font-semibold">{l.class_name}</div>
                      <div class="text-ink-500">{l.subject}</div>
                      <div class="text-ink-400 text-[10px]">{l.teacher}</div>
                      {#if !moveSrc}
                        <button class="text-[10px] text-accent-500 hover:underline"
                          title="Sposta..."
                          on:click|stopPropagation={() => startMove(
                            { lesson_id: l.lesson_id, class_name: l.class_name,
                              subject: l.subject, teachers: [l.teacher],
                              subjects: [l.subject] }, d, h, 'teachers')}>
                          sposta
                        </button>
                      {/if}
                    </div>
                  {/each}
                {:else}
                  <PreviewCellHint preview={pv} active={!!moveSrc}/>
                {/if}
              </div>
            {/each}
          {/each}
        </div>
      </div>
    {:else if roomsViewMode === 'list'}
      <div class="card p-4 overflow-auto">
        <table class="tbl">
          <thead>
            <tr>
              <th>Aula</th><th>Tipo</th>
              {#each DAYS as d}{#each HOURS as h}<th class="text-[10px]">{DAY_NAMES_IT[d][0]}{h}</th>{/each}{/each}
            </tr>
          </thead>
          <tbody>
            {#each roomData.rooms as rn}
              <tr>
                <td><strong>{rn}</strong></td>
                <td><span class="pill">{(roomData.rooms_meta[rn]?.kind) || ''}</span></td>
                {#each DAYS as d}{#each HOURS as h}
                  {@const lst = roomData.grid[rn]?.[d]?.[h] ?? []}
                  <td class="text-[10px]" class:bg-emerald-50={lst.length === 0} class:bg-amber-50={lst.length === 1} class:bg-red-100={lst.length > 1}>
                    {#each lst as l}
                      <div>{l.class_name}<br/>{l.subject[0]}{l.subject[1]||''}</div>
                    {/each}
                  </td>
                {/each}{/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
    {/if}
  {:else if view === 'slot'}
    <div class="card p-3 flex gap-3 items-end">
      <div class="field">
        <label>Giorno</label>
        <select bind:value={slotDay} on:change={loadSlot}>
          {#each DAYS as d}<option value={d}>{DAY_NAMES_IT[d]}</option>{/each}
        </select>
      </div>
      <div class="field">
        <label>Ora</label>
        <select bind:value={slotHour} on:change={loadSlot}>
          {#each HOURS as h}<option value={h}>{h}:00</option>{/each}
        </select>
      </div>
      <button class="btn" on:click={loadSlot}>Aggiorna</button>
    </div>
    {#if slotData}
      <div class="card overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>Classe</th><th>Materia</th><th>Docente</th><th>Aula</th></tr></thead>
          <tbody>
            {#each slotData.lessons as l}
              <tr>
                <td><strong>{l.class_name}</strong></td>
                <td>{l.subject}</td>
                <td>{l.teacher}</td>
                <td>{l.classroom ?? ''}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/if}
  {/if}

  {#if lastMoveOutcome}
    <div class="card p-3 text-sm">
      <strong>Ultima mossa</strong>:
      {#if lastMoveOutcome.accepted}
        <span class="pill-green">accepted</span>
      {:else}
        <span class="pill-red">rejected</span>
      {/if}
      - {lastMoveOutcome.reason}
      {#if lastMoveOutcome.obj_before != null}
        - obj {lastMoveOutcome.obj_before} -&gt; {lastMoveOutcome.obj_after}
        ({lastMoveOutcome.delta > 0 ? '+' : ''}{lastMoveOutcome.delta})
      {/if}
    </div>
  {/if}

<RoomClearedNoticeModal notice={roomClearedNotice}
                       onClose={() => (roomClearedNotice = null)}/>

<SolutionsTable {solutions}
                onActivate={activateSolution}
                onDelete={delSolution}/>
</div>
