<script lang="ts">
  /**
   * Scelta di aula per l'attività alternativa, per chi non imposta
   * i vincoli a mano. All'apertura è già selezionata l'aula di tipo
   * alternativa. L'aula fissa (nome della stanza) e le aule libere
   * si possono cambiare. La scelta si può togliere.
   *
   * Montato in /classrooms da AlternativaPresetPanel, che salva su
   * data/preset_alternativa.json.
   */
  import {
    ALTERNATIVA_ROOM_CHOICES,
    addFreeRoom,
    defaultAlternativaRoomPreset,
    presetSummary,
    removeFreeRoom,
    removePreset,
    restoreDefault,
    selectMode,
    setRoomName,
    type AlternativaRoomMode,
    type AlternativaRoomPreset,
  } from "./alternativa_room_preset";

  let {
    value = $bindable(defaultAlternativaRoomPreset()),
    onchange = (_next: AlternativaRoomPreset) => {},
  }: {
    value?: AlternativaRoomPreset;
    onchange?: (next: AlternativaRoomPreset) => void;
  } = $props();

  const uid = $props.id();
  let draft = $state("");

  function emit(next: AlternativaRoomPreset) {
    value = next;
    onchange(next);
  }

  function onMode(mode: AlternativaRoomMode) {
    emit(selectMode(value, mode));
  }

  function onRoomName(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    emit(setRoomName(value, target.value));
  }

  function onDraft(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    draft = target.value;
  }

  function onAddFree() {
    const next = addFreeRoom(value, draft);
    if (next === value) return;
    draft = "";
    emit(next);
  }

  function onDraftKeydown(event: KeyboardEvent) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    onAddFree();
  }
</script>

<section
  class="card p-4"
  data-testid="alternativa-room-preset"
  aria-labelledby="{uid}-title"
>
  <div class="flex items-start justify-between gap-3">
    <div>
      <h2 id="{uid}-title" class="!text-[16px] !m-0">
        Aula dell'attività alternativa
      </h2>
      <p class="mt-1 text-[12.5px] text-ink-500">
        La scelta predefinita è già selezionata: un'aula il cui tipo è
        alternativa. Puoi passare all'aula fissa, indicare le aule
        libere, oppure togliere la scelta.
      </p>
    </div>
    {#if value.active}
      <button
        type="button"
        class="btn shrink-0 !text-xs"
        data-testid="alternativa-room-remove"
        onclick={() => emit(removePreset(value))}
      >
        Togli questa scelta
      </button>
    {:else}
      <button
        type="button"
        class="btn-primary shrink-0 !text-xs"
        data-testid="alternativa-room-restore"
        onclick={() => emit(restoreDefault(value))}
      >
        Rimetti la scelta predefinita
      </button>
    {/if}
  </div>

  {#if value.active}
    <fieldset class="mt-3 space-y-2 border-0 p-0">
      <legend class="mb-2 text-[12.5px] font-medium text-ink-700">
        Dove si svolge l'attività alternativa
      </legend>
      {#each ALTERNATIVA_ROOM_CHOICES as choice (choice.mode)}
        <div
          class="rounded-lg border p-2.5"
          class:border-accent-500={value.mode === choice.mode}
          class:border-ink-200={value.mode !== choice.mode}
        >
          <label class="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              class="mt-1 shrink-0"
              name="{uid}-mode"
              value={choice.mode}
              checked={value.mode === choice.mode}
              data-testid="alternativa-room-mode-{choice.mode}"
              onchange={() => onMode(choice.mode)}
            />
            <span class="min-w-0">
              <span class="flex flex-wrap items-center gap-2">
                <span class="text-sm font-medium text-ink-900">{choice.label}</span>
                {#if choice.mode === "alternativa"}
                  <span class="pill-blue !text-[10px]">predefinita</span>
                {/if}
              </span>
              <span class="mt-0.5 block text-xs text-ink-500">{choice.hint}</span>
            </span>
          </label>

          {#if choice.mode === "fissa"}
            <div class="field mt-2 ml-6">
              <label for="{uid}-room">Nome della stanza</label>
              <input
                id="{uid}-room"
                type="text"
                value={value.roomName}
                placeholder="es. Aula 12"
                data-testid="alternativa-room-name"
                oninput={onRoomName}
              />
            </div>
          {/if}

          {#if choice.mode === "libere"}
            <div class="mt-2 ml-6">
              <div class="field">
                <label for="{uid}-free">Nome di un'aula libera</label>
                <div class="flex gap-2">
                  <input
                    id="{uid}-free"
                    type="text"
                    value={draft}
                    placeholder="es. Aula 4"
                    data-testid="alternativa-room-free-input"
                    oninput={onDraft}
                    onkeydown={onDraftKeydown}
                  />
                  <button
                    type="button"
                    class="btn shrink-0"
                    data-testid="alternativa-room-free-add"
                    onclick={onAddFree}
                  >
                    Aggiungi
                  </button>
                </div>
              </div>
              {#if value.freeRooms.length > 0}
                <ul class="mt-2 flex flex-wrap gap-1.5" data-testid="alternativa-room-free-list">
                  {#each value.freeRooms as room (room)}
                    <li class="pill-blue inline-flex items-center gap-1 !text-[11px]">
                      <span>{room}</span>
                      <button
                        type="button"
                        class="focus-ring rounded px-0.5"
                        aria-label="Togli {room} dalle aule libere"
                        data-testid="alternativa-room-free-remove"
                        onclick={() => emit(removeFreeRoom(value, room))}
                      >
                        Togli
                      </button>
                    </li>
                  {/each}
                </ul>
              {:else}
                <p class="mt-1 text-xs text-ink-500">
                  Nessun nome. In quell'ora si usano le aule libere.
                </p>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </fieldset>
  {/if}

  <p class="mt-3 text-xs text-ink-600" data-testid="alternativa-room-summary">
    {presetSummary(value)}
  </p>
</section>
