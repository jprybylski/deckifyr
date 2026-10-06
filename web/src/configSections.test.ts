import { describe, expect, it } from "vitest";
import { GENERAL_ID, applySection, buildSections, sectionSchema, sectionValue } from "./configSections";
import type { JSONSchema } from "./components/schemaUtils";

const schema: JSONSchema = {
  type: "object",
  required: ["deckifyr", "slide"],
  properties: {
    deckifyr: { type: "string" },
    slide: { type: "object", properties: { width: { type: "string" } } },
    colors: { type: "object", additionalProperties: { type: "string" } },
    slides: { type: "array", items: { type: "object" } },
    status: { anyOf: [{ type: "string" }, { type: "null" }] },
  },
};
const value = { deckifyr: "0.1", slide: { width: "1in" }, colors: { a: "#fff", b: "#000" }, slides: [{}], status: null };

describe("buildSections", () => {
  it("groups scalars (including optional ones) under General, first", () => {
    const sections = buildSections(schema, {}, value);
    expect(sections[0]).toMatchObject({ id: GENERAL_ID, label: "General", keys: ["deckifyr", "status"] });
  });

  it("gives each container its own section, with entry counts for dicts and arrays", () => {
    const sections = buildSections(schema, {}, value);
    expect(sections.map((s) => s.label)).toEqual(["General", "slide", "colors", "slides"]);
    expect(sections.find((s) => s.id === "colors")?.count).toBe(2);
    expect(sections.find((s) => s.id === "slides")?.count).toBe(1);
    expect(sections.find((s) => s.id === "slide")?.count).toBeUndefined();
  });

  it("omits General when there are no scalars", () => {
    const only: JSONSchema = { type: "object", properties: { layouts: { type: "object", additionalProperties: {} } } };
    expect(buildSections(only, {}, { layouts: {} }).map((s) => s.id)).toEqual(["layouts"]);
  });
});

describe("section projection", () => {
  const sections = buildSections(schema, {}, value);
  const general = sections[0];
  const colors = sections[2];

  it("narrows the schema, value and required list for General", () => {
    expect(Object.keys(sectionSchema(schema, general).properties as object)).toEqual(["deckifyr", "status"]);
    expect(sectionSchema(schema, general).required).toEqual(["deckifyr"]);
    expect(sectionValue(value, general)).toEqual({ deckifyr: "0.1", status: null });
  });

  it("uses the property itself for a single-property section", () => {
    expect(sectionSchema(schema, colors)).toBe((schema.properties as Record<string, JSONSchema>).colors);
    expect(sectionValue(value, colors)).toEqual({ a: "#fff", b: "#000" });
  });

  it("writes an edit back without disturbing other sections", () => {
    expect(applySection(value, colors, { a: "#123" }).colors).toEqual({ a: "#123" });
    expect(applySection(value, colors, { a: "#123" }).slide).toBe(value.slide);
    const next = applySection(value, general, { deckifyr: "0.2", status: "draft" });
    expect(next).toMatchObject({ deckifyr: "0.2", status: "draft", slide: value.slide });
  });
});
