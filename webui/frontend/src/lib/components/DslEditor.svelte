<script>
  /**
   * General-DSL textarea with overlay token colouring.
   * The real control stays a textarea (Cypress / a11y / IME).
   * Highlight is paint-only — no Monaco, no autocomplete.
   */
  import { highlightDsl } from "$lib/dsl_highlight.mjs";

  export let value = "";
  export let placeholder = "";
  export let testid = "dsl-expression";
  export let rows = 7;

  let ta;
  let hl;

  $: painted = highlightDsl(value);

  function syncScroll() {
    if (!ta || !hl) return;
    hl.scrollTop = ta.scrollTop;
    hl.scrollLeft = ta.scrollLeft;
  }

  function onScroll() {
    syncScroll();
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
    on:scroll={onScroll}></textarea>
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
</style>
