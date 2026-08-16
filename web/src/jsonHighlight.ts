/**
 * Dependency-free JSON syntax highlighter for `ConfigEditor.tsx`'s Raw
 * view (issue #22) -- a small regex tokenizer, not a real parser,
 * matching this repo's low-dependency ethos (CLAUDE.md: `colorsys` over
 * a color-math library, JSON over `js-yaml` in `ConfigEditor.tsx`'s own
 * docstring). It only has to color valid-*looking* JSON as a human
 * types it -- `JSON.parse` (already in `ConfigEditor.tsx`, and now run
 * live rather than only on Save) remains the actual correctness/
 * validation authority, so this tokenizer doesn't need to be one.
 */

// Matches, in priority order: a quoted string (optionally followed by
// `:` + whitespace, to distinguish an object key from a string value),
// `true`/`false`/`null`, or a JSON number. Alternation order matters --
// the string branch is tried first so a `true`/`123`-looking substring
// *inside* a string is consumed as part of that string, never matched
// on its own.
const TOKEN_RE =
  /"(?:\\.|[^"\\])*"(?:\s*:)?|\btrue\b|\bfalse\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;

function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/**
 * Renders `text` (plain, unescaped JSON source) as an HTML string with
 * each recognized token wrapped in a `<span class="json-{key|string|
 * number|boolean|null}">` -- braces, brackets, commas, and whitespace
 * pass through unwrapped. `text` is HTML-escaped internally; callers
 * must pass raw text, not something already escaped.
 */
export function highlightJson(text: string): string {
  const escaped = escapeHtml(text);
  return escaped.replace(TOKEN_RE, (token) => {
    if (token.startsWith('"')) {
      const isKey = /:\s*$/.test(token);
      return `<span class="${isKey ? "json-key" : "json-string"}">${token}</span>`;
    }
    if (token === "true" || token === "false") {
      return `<span class="json-boolean">${token}</span>`;
    }
    if (token === "null") {
      return `<span class="json-null">${token}</span>`;
    }
    return `<span class="json-number">${token}</span>`;
  });
}
