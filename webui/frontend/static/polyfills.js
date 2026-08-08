// Polyfill crypto.randomUUID() for HTTP origins.
// SvelteKit uses it internally for hydration IDs.
// This is a classic (non-module) script — it runs synchronously
// before any module scripts or dynamic imports.
(function () {
  try {
    if (typeof crypto === 'undefined') return;
    if (typeof crypto.randomUUID === 'function') return;
    crypto.randomUUID = function () {
      var buf = new Uint8Array(16);
      crypto.getRandomValues(buf);
      buf[6] = (buf[6] & 0x0f) | 0x40;
      buf[8] = (buf[8] & 0x3f) | 0x80;
      var h = function (b) {
        return b.toString(16).padStart(2, '0');
      };
      return [
        h(buf[0]), h(buf[1]), h(buf[2]), h(buf[3]), '-',
        h(buf[4]), h(buf[5]), '-',
        h(buf[6]), h(buf[7]), '-',
        h(buf[8]), h(buf[9]), '-',
        h(buf[10]), h(buf[11]), h(buf[12]), h(buf[13])
      ].join('');
    };
  } catch (_) {
    // Silently fail — the app will show an error banner if something
    // actually breaks later.
  }
})();
