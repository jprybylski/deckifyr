import { describe, expect, it } from "vitest";
import { highlightJson } from "./jsonHighlight";

describe("highlightJson", () => {
  it("wraps an object key and a string value differently", () => {
    const html = highlightJson('{"name": "value"}');
    expect(html).toContain('<span class="json-key">"name":</span>');
    expect(html).toContain('<span class="json-string">"value"</span>');
  });

  it("wraps booleans, null, and numbers", () => {
    const html = highlightJson('{"a": true, "b": false, "c": null, "d": -1.5e3}');
    expect(html).toContain('<span class="json-boolean">true</span>');
    expect(html).toContain('<span class="json-boolean">false</span>');
    expect(html).toContain('<span class="json-null">null</span>');
    expect(html).toContain('<span class="json-number">-1.5e3</span>');
  });

  it("does not treat text inside a string value as a separate token", () => {
    const html = highlightJson('{"note": "true is not a keyword here, 42 isn\'t a number"}');
    expect(html).toContain(
      '<span class="json-string">"true is not a keyword here, 42 isn\'t a number"</span>'
    );
    expect(html).not.toContain('<span class="json-boolean">');
    expect(html).not.toContain('<span class="json-number">42</span>');
  });

  it("HTML-escapes special characters inside a string value", () => {
    const html = highlightJson('{"html": "<b>&amp;</b>"}');
    expect(html).toContain("&lt;b&gt;&amp;amp;&lt;/b&gt;");
    expect(html).not.toContain("<b>");
  });

  it("leaves structural characters (braces, brackets, commas) unwrapped", () => {
    const html = highlightJson("[1, 2]");
    expect(html.startsWith("[")).toBe(true);
    expect(html).toContain(", ");
    expect(html.endsWith("]")).toBe(true);
  });
});
