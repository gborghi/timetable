import test from "node:test";
import assert from "node:assert/strict";

import { tokenizeDsl, highlightDsl, escapeHtml } from "./dsl_highlight.mjs";

function kinds(src) {
  return tokenizeDsl(src).filter((t) => t.kind !== "ws").map((t) => t.kind);
}

function texts(src) {
  return tokenizeDsl(src).filter((t) => t.kind !== "ws").map((t) => t.text);
}

test("tokenizeDsl: empty / null", () => {
  assert.deepEqual(tokenizeDsl(""), []);
  assert.deepEqual(tokenizeDsl(null), []);
});

test("tokenizeDsl: keywords and sources", () => {
  const src = "forall l in lessons where l.teacher == Borghi: l.hour != 6";
  assert.deepEqual(kinds(src), [
    "kw", "ident", "kw", "source", "kw",
    "ident", "op", "ident", "op", "ident", "op",
    "ident", "op", "ident", "op", "num",
  ]);
  assert.ok(texts(src).includes("forall"));
  assert.ok(texts(src).includes("lessons"));
});

test("tokenizeDsl: strings numbers comments", () => {
  const src = 'count l in lessons where l.class == "1A": l <= 2  # cap';
  const toks = tokenizeDsl(src).filter((t) => t.kind !== "ws");
  assert.equal(toks.find((t) => t.kind === "str").text, '"1A"');
  assert.equal(toks.find((t) => t.kind === "num").text, "2");
  assert.equal(toks.find((t) => t.kind === "comment").text, "# cap");
  assert.ok(toks.some((t) => t.kind === "kw" && t.text === "count"));
});

test("tokenizeDsl: class names stay one ident", () => {
  assert.deepEqual(texts("1A_Scientifico"), ["1A_Scientifico"]);
  assert.equal(tokenizeDsl("1A_Scientifico")[0].kind, "ident");
});

test("escapeHtml + highlightDsl never emit raw markup", () => {
  const html = highlightDsl('forall l in lessons: l.teacher == "<x>"');
  assert.equal(html.includes("<x>"), false);
  assert.ok(html.includes("&lt;x&gt;"));
  assert.ok(html.includes('class="dsl-t dsl-t--kw"'));
  assert.ok(html.includes('class="dsl-t dsl-t--source"'));
});

test("highlightDsl: empty string is empty html", () => {
  assert.equal(highlightDsl(""), "");
});
