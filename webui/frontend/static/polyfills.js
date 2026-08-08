// Polyfill crypto.randomUUID() for HTTP origins (e.g. Tailscale IP).
// Chrome requires a secure context (HTTPS or localhost) for this Web API.
// This classic script runs synchronously before any module imports.
(function () {
  function makeUUID() {
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
  }

  try {
    // Try assignment first
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID !== 'function') {
      try { crypto.randomUUID = makeUUID; } catch (_) { /* read-only? */ }
    }
  } catch (_) { /* crypto itself might throw */ }

  // Belt-and-suspenders: define on Crypto.prototype if possible.
  try {
    if (typeof Crypto !== 'undefined' && Crypto.prototype &&
        typeof Crypto.prototype.randomUUID !== 'function') {
      Object.defineProperty(Crypto.prototype, 'randomUUID', {
        value: makeUUID, writable: true, configurable: true,
      });
    }
  } catch (_) { /* not available */ }

  // Final fallback: ensure window.crypto.randomUUID exists.
  try {
    var c = window.crypto || globalThis.crypto;
    if (c && typeof c.randomUUID !== 'function') {
      Object.defineProperty(c, 'randomUUID', {
        value: makeUUID, writable: true, configurable: true,
      });
    }
  } catch (_) { /* last resort failed */ }
})();
