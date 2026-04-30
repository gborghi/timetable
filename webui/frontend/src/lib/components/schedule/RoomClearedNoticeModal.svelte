<!--
  Modal alert shown after a successful move when the backend reports
  room_cleared (the previous classroom couldn't follow the lesson into
  the new slot, typically because that slot is already occupied or
  HARD-unavailable).
-->
<script>
  import Modal from '$lib/components/Modal.svelte';
  import { DAY_NAMES_IT } from '$lib/constants.js';

  export let notice;     // {room, day, hour, class_name, teacher, subject} | null
  export let onClose;
</script>

<Modal open={!!notice}
       title="Aula rimossa dopo lo spostamento"
       onClose={onClose}>
  {#if notice}
    <div class="space-y-3 text-sm">
      <p>
        La lezione <strong>{notice.subject}</strong>
        ({notice.class_name} con {notice.teacher})
        e' stata spostata in
        <code>{DAY_NAMES_IT[notice.day]} {notice.hour}:00</code>,
        ma l'aula <strong>{notice.room}</strong> non era
        disponibile in quel nuovo slot (occupata da un'altra lezione
        oppure HARD-non-disponibile in quell'orario).
      </p>
      <p>
        L'aula e' stata <strong>rimossa</strong> dalla lezione spostata.
        Apri la cella nella matrice e seleziona una nuova aula dal
        dropdown (le aule libere appaiono in verde, quelle occupate in
        rosso e non sono selezionabili).
      </p>
      <div class="flex justify-end">
        <button class="btn-primary" on:click={onClose}>
          Ho capito
        </button>
      </div>
    </div>
  {/if}
</Modal>
