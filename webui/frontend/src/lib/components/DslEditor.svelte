<script>
  /**
   * General-DSL textarea with overlay token colouring,
   * squiggle on rejected tokens, and keyword/source autocomplete.
   * The real control stays a textarea (Cypress / a11y / IME).
   */
  import { highlightDsl, suggestDsl } from "$lib/dsl_highlight.mjs";

  export let value = "";
  export let placeholder = "";
  export let testid = "dsl-expression";
  export let rows = 7;
  export let errorSpans = [];

  let ta;
  let hl;
  let suggestions = [];
  let suggestFrom = 0;
  let suggestTo = 0;
  let suggestOpen = false;
  let activeIdx = 0;

  $: painted = highlightDsl(value, errorSpans);

  function syncScroll() {
    if (!ta || !hl) return;
    hl.scrollTop = ta.scrollTop;
    hl.scrollLeft = ta.scrollLeft;
  }

  function onScroll() {
    syncScroll();
    suggestOpen = false;
  }

  function refreshSuggest() {
    if (!ta) return;
    const r = suggestDsl(value, ta.selectionStart);
    suggestions = r.items;
    suggestFrom = r.from;
    suggestTo = r.to;
    suggestOpen = r.items.length > 0;
    activeIdx = 0;
  }

  function applySuggestion(word) {
    value = value.slice(0, suggestFrom) + word + value.slice(suggestTo);
    suggestOpen = false;
    const caret = suggestFrom + word.length;
    requestAnimationFrame(() => {
      if (!ta) return;
      ta.focus();
      ta.setSelectionRange(caret, caret);
    });
  }

  function onKeydown(e) {
    if (!suggestOpen || !suggestions.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIdx = (activeIdx + 1) % suggestions.length;
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIdx = (activeIdx - 1 + suggestions.length) % suggestions.length;
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      applySuggestion(suggestions[activeIdx]);
    } else if (e.key === "Escape") {
      suggestOpen = false;
    }
  }

  function onInput() {
    refreshSuggest();
  }
</script>

<div class="dsl-ed">
  <pre class="dsl-ed-hl" aria-hidden="true" bind:this={hl}>{@html painted}{"\n"}</pre>
  <textarea
    class="dsl-ed-ta"
    bind:this={ta}
    bind:value
    {placeholder}
    {rows}
    spellcheck="false"
    autocomplete="off"
    autocapitalize="off"
    data-testid={testid}
    on:input
    on:input={onInput}
    on:keydown={onKeydown}
    on:scroll={onScroll}></textarea>
  {#if suggestOpen && suggestions.length}
    <ul class="dsl-ac" data-testid="dsl-autocomplete" role="listbox">
      {#each suggestions as s, i}
        <li>
          <button type="button"
                  class:is-active={i === activeIdx}
                  on:mousedown|preventDefault={() => applySuggestion(s)}>
            {s}
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .dsl-ed {
    position: relative;
    width: 100%;
  }
  .dsl-ed-hl,
  .dsl-ed-ta {
    box-sizing: border-box;
    width: 100%;
    margin: 0;
    padding: 0.375rem 0.5rem;
    border: 1px solid #e5e0d4;
    border-radius: 0.375rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 12px;
    line-height: 1.45;
    white-space: pre-wrap;
    word-wrap: break-word;
    overflow-wrap: anywhere;
    tab-size: 2;
  }
  .dsl-ed-hl {
    position: absolute;
    inset: 0;
    overflow: hidden;
    pointer-events: none;
    color: #1a1612;
    background: #fff;
    min-height: 100%;
  }
  .dsl-ed-ta {
    position: relative;
    display: block;
    color: transparent;
    caret-color: #1a1612;
    background: transparent;
    resize: vertical;
    min-height: 7rem;
    z-index: 1;
  }
  .dsl-ed-ta::placeholder {
    color: #9b9384;
    -webkit-text-fill-color: #9b9384;
  }
  .dsl-ed-ta:focus {
    outline: 2px solid rgba(30, 58, 95, 0.35);
    outline-offset: 1px;
  }
  :global(.dsl-t--kw) { color: #1e3a5f; font-weight: 600; }
  :global(.dsl-t--source) { color: #9c4a1c; }
  :global(.dsl-t--str) { color: #2f6f4e; }
  :global(.dsl-t--num) { color: #8a6a12; }
  :global(.dsl-t--comment) { color: #9b9384; font-style: italic; }
  :global(.dsl-t--op) { color: #6b6355; }
  :global(.dsl-t--ident) { color: #1a1612; }
  :global(.dsl-t--unknown) { color: #9c4a1c; }
  :global(.dsl-t--err) {
    text-decoration: wavy underline #c0392b;
    text-decoration-skip-ink: none;
  }
  .dsl-ac {
    position: absolute;
    z-index: 4;
    left: 0.5rem;
    bottom: 100%;
    margin: 0 0 0.25rem;
    padding: 0.25rem 0;
    list-style: none;
    background: #fff;
    border: 1px solid #e5e0d4;
    border-radius: 0.375rem;
    box-shadow: 0 4px 12px rgba(26, 22, 18, 0.12);
    max-height: 10rem;
    overflow-y: auto;
    min-width: 10rem;
  }
  .dsl-ac button {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.2rem 0.6rem;
    font: inherit;
    font-size: 12px;
    background: transparent;
    border: 0;
    cursor: pointer;
  }
  .dsl-ac button.is-active,
  .dsl-ac button:hover {
    background: #f3efe6;
  }
</style>
