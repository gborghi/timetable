<script>
  /** Unscheduled-lesson pool sidebar — extracted from WeeklyCalendarView (audit Q1). */
  export let lessons = [];
  export let _colourFor = (/** @type {any} */ _u) => ({ bg: '#fff', bd: '#ccc', fg: '#333' });
  export let _onUnschedDragStart = (/** @type {DragEvent} */ _e, /** @type {any} */ _u) => {};
  export let _onDragEnd = (/** @type {DragEvent} */ _e) => {};
</script>

<aside class="cal-pool" data-testid="schedule-pool" aria-label="Lezioni svincolate">
  <div class="cal-pool__header">
    Pool ({lessons.length})
  </div>
  {#if !lessons.length}
    <div class="cal-pool__empty">Nessuna lezione svincolata.</div>
  {:else}
    <ul class="cal-pool__list">
      {#each lessons as u}
        {@const col = _colourFor(u)}
        <li class="cal-pool__item"
            style={`background:${col.bg};border-color:${col.bd};color:${col.fg};`}
            draggable="true"
            data-unsched-id={u.id}
            data-testid={'sched-pool-item-' + u.id}
            on:dragstart={(e) => _onUnschedDragStart(e, u)}
            on:dragend={_onDragEnd}
            title={`${u.class_name || ''} - ${u.subject || ''} (${u.teacher_name || ''})` +
              (u.original_day != null
                ? ` -- prima era giorno ${u.original_day} ora ${u.original_hour}` : '')}>
          <div class="cal-pool__item-title">
            {u.class_name || ''} - {u.subject || ''}
          </div>
          <div class="cal-pool__item-sub">
            {u.teacher_name || ''}
            {#if u.classroom_name}- {u.classroom_name}{/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</aside>

<style>
  .cal-pool {
    border: 1px solid var(--line);
    border-radius: 11px;
    background: var(--band);
    padding: 12px;
    max-height: 70vh;
    overflow-y: auto;
    position: sticky;
    top: 8px;
  }
  .cal-pool__header {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.11em;
    text-transform: uppercase;
    color: var(--ink3);
    padding: 0 2px 8px;
    margin-bottom: 8px;
    border-bottom: 1px solid var(--line);
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .cal-pool__empty {
    font-size: 11px;
    color: var(--ink3);
    padding: 12px 4px;
    text-align: center;
  }
  .cal-pool__list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .cal-pool__item {
    border-style: solid;
    border-width: 1px;
    border-radius: 7px;
    padding: 6px 8px;
    cursor: grab;
    font-size: 11px;
    transition: box-shadow 0.15s;
  }
  .cal-pool__item:hover { box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
  .cal-pool__item:active { cursor: grabbing; }
  .cal-pool__item-title {
    font-weight: 600;
    line-height: 1.25;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cal-pool__item-sub {
    font-size: 9px;
    opacity: 0.8;
    margin-top: 1px;
  }
</style>
