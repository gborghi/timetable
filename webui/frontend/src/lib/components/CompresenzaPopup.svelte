<script>
  /**
   * Compresenza (co-teaching / sostegno) detail popup — extracted from
   * WeeklyCalendarView (audit Q1).
   *
   * When a filtered-view schedule slot holds >1 lesson, the main lesson
   * fills the cell and a "+N 👥" button opens this fixed-position popup
   * listing every co-present lesson with subject, teacher, class, room.
   *
   * Props:
   *   popup  — null | { key, lst, title, x, y } (null = closed)
   *   onClose — callback()
   */
  import { compresenzaRow } from '$lib/calendar_helpers.mjs';

  export let popup = null;
</script>

{#if popup}
  <div class="cal-compresenza-pop"
       data-testid="compresenza-popup"
       role="dialog" aria-label="Dettagli compresenza" tabindex="-1"
       style={`left:${popup.x}px; top:${popup.y}px;`}
       on:click|stopPropagation
       on:keydown|stopPropagation>
    <div class="cal-compresenza-pop__title">
      Compresenza · {popup.title}
    </div>
    {#each popup.lst as cl2}
      {@const row = compresenzaRow(cl2)}
      <div class="cal-compresenza-pop__row">
        <span class="cal-compresenza-pop__subj">{row.head || '?'}</span>
        {#if row.who}<span class="cal-compresenza-pop__who">{row.who}</span>{/if}
        {#if row.room}<span class="cal-compresenza-pop__room">@ {row.room}</span>{/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  .cal-compresenza-pop {
    position: fixed;
    z-index: 1000;
    min-width: 180px;
    max-width: 240px;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18);
    padding: 6px 8px;
    font-size: 11px;
    color: #1e293b;
  }
  .cal-compresenza-pop__title {
    font-weight: 700;
    font-size: 11px;
    margin-bottom: 4px;
    color: #0f172a;
  }
  .cal-compresenza-pop__row {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 6px;
    padding: 3px 0;
    border-top: 1px solid #f1f5f9;
  }
  .cal-compresenza-pop__subj { font-weight: 600; }
  .cal-compresenza-pop__who { opacity: 0.85; }
  .cal-compresenza-pop__room { opacity: 0.7; }
</style>
