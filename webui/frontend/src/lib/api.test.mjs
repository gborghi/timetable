// Unit tests for the API client utilities (audit T1).
// Run with: npm test
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { formatApiError } from "./api.ts";

describe("formatApiError", () => {
  it("handles null/undefined", () => {
    assert.equal(formatApiError(null, 500, "Server Error"), "500 Server Error");
    assert.equal(formatApiError(undefined), "");
  });

  it("returns a string as-is", () => {
    assert.equal(formatApiError("Something went wrong"), "Something went wrong");
  });

  it("formats FastAPI validation errors (array of detail)", () => {
    const payload = {
      detail: [
        { loc: ["body", "name"], msg: "field required", type: "missing" },
        { loc: ["body", "hours"], msg: "must be positive", type: "value_error" },
      ],
    };
    const result = formatApiError(payload);
    assert.ok(result.includes("body.name: field required"));
    assert.ok(result.includes("body.hours: must be positive"));
  });

  it("formats validation error with type-only fallback", () => {
    const payload = {
      detail: [{ loc: ["query", "page"], type: "type_error.integer" }],
    };
    assert.equal(formatApiError(payload), "query.page: type_error.integer");
  });

  it("returns detail string directly", () => {
    assert.equal(
      formatApiError({ detail: "Not found" }),
      "Not found",
    );
  });

  it("returns error string from legacy format", () => {
    assert.equal(
      formatApiError({ error: "Unauthorized" }),
      "Unauthorized",
    );
  });

  it("truncates long JSON fallback", () => {
    const long = { x: "a".repeat(300) };
    const result = formatApiError(long);
    assert.ok(result.length <= 250, `got ${result.length} chars`);
    assert.ok(result.endsWith("..."));
  });

  it("handles JSON.stringify failure gracefully", () => {
    const cyclic = /** @type {Record<string, unknown>} */ ({});
    cyclic.self = cyclic;
    assert.equal(formatApiError(cyclic, 418), "418");
  });
});
