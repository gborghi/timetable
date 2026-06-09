<script>
  /**
   * Decorative brand SVG from /static/decor (see decor/index.json).
   * Purely decorative by default (alt=""), so it is hidden from screen
   * readers. Pass a non-empty `alt` only if the image conveys meaning.
   *
   *   <DecorIcon name="calendar" size={48} />
   */
  let {
    name,
    size = 48,
    alt = '',
    class: klass = '',
  } = $props();
</script>

<img
  src={`/decor/${name}.svg`}
  {alt}
  width={size}
  height={size}
  class={klass}
  aria-hidden={alt ? undefined : 'true'}
  draggable="false"
  loading="lazy"
/>
