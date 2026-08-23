/**
 * Minimal token colouring for the general-DSL textarea.
 * Mirrors engine/general_dsl.py tokenize() enough to paint keywords,
 * strings, numbers, comments and operators. Not a parser.
 */

const KEYWORDS = new Set([
  "and", "or", "not",
  "forall", "exists", "count", "sum",
  "in", "not_in", "where", "let",
  "true", "false",
]);

const SOURCES = new Set([
  "lessons", "assignments", "teachers", "classes", "classrooms",
  "subjects", "curricula", "groups", "days", "hours", "slots",
  "students",
]);

const TOKEN_RE = /(\s+)|(#.*)|("(?:[^"\\]|\\.)*")|('(?:[^'\\]|\\.)*')|(=>|<=>|<=|>=|!=|==|[<>]=?|[+\-*/%()[\],.:])|([A-Za-z0-9_]*[A-Za-z_][A-Za-z0-9_]*)|(\d+(?:\.\d+)?)|([\s\S])/gy;

/**
 * @param {string} src
 * @returns {{kind: string, text: string}[]}
 */
export function tokenizeDsl(src) {
  const text = String(src ?? "");
  const out = [];
  TOKEN_RE.lastIndex = 0;
  while (TOKEN_RE.lastIndex < text.length) {
    const m = TOKEN_RE.exec(text);
    if (!m) break;
    if (m[1] != null) {
      out.push({ kind: "ws", text: m[1] });
    } else if (m[2] != null) {
      out.push({ kind: "comment", text: m[2] });
    } else if (m[3] != null || m[4] != null) {
      out.push({ kind: "str", text: m[3] ?? m[4] });
    } else if (m[5] != null) {
      out.push({ kind: "op", text: m[5] });
    } else if (m[6] != null) {
      const word = m[6];
      const low = word.toLowerCase();
      if (KEYWORDS.has(low)) out.push({ kind: "kw", text: word });
      else if (SOURCES.has(low)) out.push({ kind: "source", text: word });
      else out.push({ kind: "ident", text: word });
    } else if (m[7] != null) {
      out.push({ kind: "num", text: m[7] });
    } else {
      out.push({ kind: "unknown", text: m[8] ?? "" });
    }
  }
  return out;
}

export function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * @param {string} src
 * @param {{start:number,end:number}[]} [spans]
 * @returns {string} HTML of coloured spans (already escaped)
 */
export function highlightDsl(src, spans) {
  const tokens = tokenizeDsl(src);
  if (tokens.length === 0) return "";
  const ranges = Array.isArray(spans)
    ? spans.filter((s) => s && Number.isFinite(s.start) && Number.isFinite(s.end))
    : [];
  let html = "";
  let pos = 0;
  for (const t of tokens) {
    const start = pos;
    const end = pos + t.text.length;
    pos = end;
    const safe = escapeHtml(t.text);
    const err = ranges.some((s) => start < s.end && end > s.start);
    if (t.kind === "ws" && !err) {
      html += safe;
      continue;
    }
    const cls = err
      ? `dsl-t dsl-t--${t.kind} dsl-t--err`
      : `dsl-t dsl-t--${t.kind}`;
    html += t.kind === "ws" && !err
      ? safe
      : `<span class="${cls}">${safe}</span>`;
  }
  return html;
}

const COMPLETIONS = [
  "forall", "exists", "count", "sum", "where", "let",
  "and", "or", "not", "in", "not_in", "true", "false",
  "lessons", "assignments", "teachers", "classes", "classrooms",
  "subjects", "curricula", "groups", "days", "hours", "slots",
  "students",
  "teacher", "class", "subject", "classroom", "day", "hour",
  "group", "name", "index",
];

/**
 * Prefix completions for the token under the caret.
 * @param {string} src
 * @param {number} caret
 * @returns {{items: string[], prefix: string, from: number, to: number}}
 */
export function suggestDsl(src, caret) {
  const text = String(src ?? "");
  const pos = Math.max(0, Math.min(text.length, Number(caret) || 0));
  let from = pos;
  while (from > 0 && /[A-Za-z0-9_]/.test(text[from - 1])) from -= 1;
  const prefix = text.slice(from, pos);
  if (!prefix) return { items: [], prefix, from, to: pos };
  const low = prefix.toLowerCase();
  const items = COMPLETIONS.filter((w) =>
    w.toLowerCase().startsWith(low) && w.toLowerCase() !== low);
  return { items, prefix, from, to: pos };
}
