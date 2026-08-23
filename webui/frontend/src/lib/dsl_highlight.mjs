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
 * @returns {string} HTML of coloured spans (already escaped)
 */
export function highlightDsl(src) {
  const tokens = tokenizeDsl(src);
  if (tokens.length === 0) return "";
  let html = "";
  for (const t of tokens) {
    const safe = escapeHtml(t.text);
    if (t.kind === "ws") html += safe;
    else html += `<span class="dsl-t dsl-t--${t.kind}">${safe}</span>`;
  }
  return html;
}
