<script>
  /**
   * Multi-select autocomplete for classroom tags.
   *
   * Props:
   *   value: string[]                 - currently selected tag names (lowercase)
   *   suggestions: string[]           - all known tag names (any case)
   *   onChange: (names: string[])     - emit a new array on every change
   *   placeholder?: string
   *
   * Behaviour:
   *   - typing filters suggestions; Enter / "+" adds the current input as a new tag
   *   - already-selected tags appear as colored pills with an "x" to remove
   *   - tag color is derived deterministically from the tag name (string hash)
   */
  export let value = [];
  export let suggestions = [];
  export let onChange = () => {};
  export let placeholder = 'Aggiungi tag...';
  export let disabled = false;

  let input = '';
  let openSuggest = false;

  // Tailwind palette pairs (bg, text). Pick by stable hash of name so the
  // same tag always gets the same color across the UI.
  const PALETTE = [
    'bg-emerald-100 text-emerald-700 border-emerald-200',
    'bg-sky-100 text-sky-700 border-sky-200',
    'bg-violet-100 text-violet-700 border-violet-200',
    'bg-amber-100 text-amber-700 border-amber-200',
    'bg-rose-100 text-rose-700 border-rose-200',
    'bg-teal-100 text-teal-700 border-teal-200',
    'bg-indigo-100 text-indigo-700 border-indigo-200',
    'bg-lime-100 text-lime-700 border-lime-200',
    'bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200',
    'bg-cyan-100 text-cyan-700 border-cyan-200',
    'bg-orange-100 text-orange-700 border-orange-200',
    'bg-pink-100 text-pink-700 border-pink-200',
  ];

  export function colorFor(name) {
    const s = String(name || '');
    let h = 0;
    for (let i = 0; i < s.length; i++) {
      h = (h * 31 + s.charCodeAt(i)) >>> 0;
    }
    return PALETTE[h % PALETTE.length];
  }

  function norm(s) { return String(s || '').trim().toLowerCase(); }

  $: lowerValue = (value || []).map(norm).filter(Boolean);
  $: filtered = (() => {
    const q = norm(input);
    const taken = new Set(lowerValue);
    return (suggestions || [])
      .map(norm)
      .filter((s) => s && !taken.has(s) && (q === '' || s.includes(q)))
      .slice(0, 12);
  })();

  function add(name) {
    const n = norm(name);
    if (!n) return;
    if (lowerValue.includes(n)) {
      input = '';
      return;
    }
    const next = [...lowerValue, n];
    onChange(next);
    input = '';
    openSuggest = false;
  }

  function remove(name) {
    const n = norm(name);
    onChange(lowerValue.filter((x) => x !== n));
  }

  function onKey(ev) {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      if (input.trim()) add(input);
    } else if (ev.key === 'Backspace' && input === '' && lowerValue.length) {
      remove(lowerValue[lowerValue.length - 1]);
    } else if (ev.key === 'Escape') {
      openSuggest = false;
    }
  }

  function onFocus() { openSuggest = true; }
  function onBlur() {
    // delay so click on suggestion can fire first
    setTimeout(() => { openSuggest = false; }, 150);
  }
</script>

<div class="relative">
  <div class="flex flex-wrap gap-1.5 items-center min-h-[34px]
              px-2 py-1.5 border border-ink-200 rounded-md bg-white
              focus-within:ring-2 focus-within:ring-accent-500/40">
    {#each lowerValue as t (t)}
      <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                   border text-xs font-medium {colorFor(t)}">
        #{t}
        {#if !disabled}
          <button type="button"
                  class="hover:opacity-60 leading-none"
                  aria-label="Rimuovi tag {t}"
                  on:click={() => remove(t)}>x</button>
        {/if}
      </span>
    {/each}
    <input
      class="flex-1 min-w-[8rem] outline-none bg-transparent text-sm"
      type="text"
      {placeholder}
      {disabled}
      bind:value={input}
      on:focus={onFocus}
      on:blur={onBlur}
      on:keydown={onKey}/>
    {#if input.trim()}
      <button type="button"
              class="btn !text-xs !px-2 !py-0.5"
              on:click={() => add(input)}
              {disabled}>+ {input.trim().toLowerCase()}</button>
    {/if}
  </div>

  {#if openSuggest && filtered.length}
    <div class="absolute z-30 mt-1 w-full max-h-56 overflow-auto
                rounded-md border border-ink-200 bg-white shadow-lg">
      {#each filtered as s (s)}
        <button type="button"
                class="w-full text-left px-3 py-1.5 text-sm hover:bg-ink-50 flex items-center gap-2"
                on:mousedown|preventDefault={() => add(s)}>
          <span class="inline-block w-3 h-3 rounded-full border {colorFor(s).split(' ')[0]}"></span>
          {s}
        </button>
      {/each}
    </div>
  {/if}
</div>
