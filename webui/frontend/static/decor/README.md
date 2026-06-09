# Decorative SVGs (`/decor`)

20 brand-styled vector illustrations (deep indigo `#1e3a5f` + warm gold
`#c9a23a`, fully transparent background) for decorating the WebUI. Generated
via Recraft `vector_illustration`. Served by SvelteKit at `/decor/<name>.svg`.

Use the helper component:

```svelte
<script>
  import DecorIcon from '$lib/components/DecorIcon.svelte';
</script>
<DecorIcon name="calendar" size={48} alt="" />
```

`index.json` lists every icon with an Italian label and suggested placements.
All are decorative — pass `alt=""` (default) so screen readers skip them.
