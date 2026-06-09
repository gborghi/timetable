<!--
  Per-cell classroom dropdown used in the class and teacher matrices.
  Free rooms are tinted green, occupied ones red and disabled. The
  current room (if any) stays selectable so the user can keep it.
-->
<script>
  export let lessonId;
  export let currentRoom;       // string or null
  export let allRooms = [];
  export let isBusy;            // (roomName) => boolean
  export let onChange;          // (lessonId, roomName) => void
</script>

<select class="text-xs border border-ink-200 rounded px-1 py-0.5 w-full"
  value={currentRoom || ''}
  on:click|stopPropagation
  on:change={(e) => onChange(lessonId, e.target.value)}>
  <option value="">(nessuna)</option>
  {#each allRooms as r}
    {@const busy = isBusy(r)}
    <option value={r} disabled={busy}
      class:bg-red-200={busy} class:text-red-800={busy}
      class:bg-green-100={!busy} class:text-green-800={!busy}>
      {r}{busy ? ' (occupata)' : ''}
    </option>
  {/each}
</select>
