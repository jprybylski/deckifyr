import { describe, expect, it } from "vitest";
import {
  activeBranchIndex,
  branchLabel,
  branchesAreDistinguishable,
  composeLength,
  defaultForSchema,
  expandHex,
  layoutKind,
  parseLength,
  seedBranch,
  stepLength,
  unwrapNullable,
  type Defs,
} from "./schemaUtils";

const defs: Defs = {
  Gradient: { type: "object", required: ["stops"], properties: { stops: { type: "array", items: {} }, angle: { type: "number" } } },
  Derivation: { type: "object", required: ["base"], properties: { base: { type: "string" } } },
};
const color = { type: "string", "x-deckifyr-widget": "color" };

describe("unwrapNullable", () => {
  it("passes a non-union through", () => {
    expect(unwrapNullable({ type: "string" }, defs)).toEqual({ inner: { type: "string" }, nullable: false });
  });

  it("unwraps X | None to X", () => {
    expect(unwrapNullable({ anyOf: [{ type: "string" }, { type: "null" }] }, defs)).toEqual({
      inner: { type: "string" },
      nullable: true,
    });
  });

  it("keeps a multi-branch optional union as a synthetic anyOf", () => {
    const { inner, nullable } = unwrapNullable({ anyOf: [color, { $ref: "#/$defs/Gradient" }, { type: "null" }] }, defs);
    expect(nullable).toBe(true);
    expect(inner).toEqual({ anyOf: [color, { $ref: "#/$defs/Gradient" }] });
  });
});

describe("union disambiguation", () => {
  const branches = [color, { $ref: "#/$defs/Derivation" }];

  it("tells string from object branches by the value's JSON type", () => {
    expect(branchesAreDistinguishable(branches, defs)).toBe(true);
    expect(activeBranchIndex(branches, defs, "#fff")).toBe(0);
    expect(activeBranchIndex(branches, defs, { base: "x" })).toBe(1);
    expect(activeBranchIndex(branches, defs, undefined)).toBe(0);
  });

  it("cannot tell two objects apart", () => {
    expect(branchesAreDistinguishable([{ type: "object" }, { $ref: "#/$defs/Gradient" }], defs)).toBe(false);
  });

  it("cannot model an unknown branch", () => {
    expect(branchesAreDistinguishable([{ type: "string" }, {}], defs)).toBe(false);
  });

  it("labels branches for the segmented switch", () => {
    expect(branchLabel(color, defs)).toBe("Color");
    expect(branchLabel({ type: "string" }, defs)).toBe("Text");
    expect(branchLabel({ $ref: "#/$defs/Gradient" }, defs)).toBe("Gradient");
    expect(branchLabel({ type: "array", items: {} }, defs)).toBe("List");
    expect(branchLabel({ type: "object", additionalProperties: {} }, defs)).toBe("Named");
  });
});

describe("layoutKind", () => {
  it("puts scalars inline and containers in cards", () => {
    expect(layoutKind({ type: "string" }, defs, "")).toBe("inline");
    expect(layoutKind({ type: "string", enum: ["a"] }, defs, "a")).toBe("inline");
    expect(layoutKind({ type: "array", items: {} }, defs, [])).toBe("block");
    expect(layoutKind({ $ref: "#/$defs/Gradient" }, defs, {})).toBe("block");
  });

  it("treats an untyped value as inline text only when it is a string", () => {
    expect(layoutKind({}, defs, "some text")).toBe("inline");
    expect(layoutKind({}, defs, 3)).toBe("block");
    expect(layoutKind({}, defs, null)).toBe("block");
    expect(defaultForSchema({}, defs)).toBe("");
  });

  it("follows a union's active branch", () => {
    const union = { anyOf: [color, { $ref: "#/$defs/Derivation" }] };
    expect(layoutKind(union, defs, "#fff")).toBe("inline");
    expect(layoutKind(union, defs, { base: "x" })).toBe("block");
  });
});

describe("defaultForSchema / seedBranch", () => {
  it("creates required fields only for an object", () => {
    expect(defaultForSchema({ $ref: "#/$defs/Derivation" }, defs)).toEqual({ base: "" });
    expect(defaultForSchema({ $ref: "#/$defs/Gradient" }, defs)).toEqual({ stops: [] });
  });

  it("uses the first non-null branch of a union and the first enum value", () => {
    expect(defaultForSchema({ anyOf: [{ type: "number" }, { type: "null" }] }, defs)).toBe(0);
    expect(defaultForSchema({ enum: ["a", "b"] }, defs)).toBe("a");
  });

  it("seeds an object branch from a previous string", () => {
    expect(seedBranch({ $ref: "#/$defs/Derivation" }, defs, "#2457a6")).toEqual({ base: "#2457a6" });
    expect(seedBranch({ $ref: "#/$defs/Derivation" }, defs, "")).toEqual({ base: "" });
    expect(seedBranch({ $ref: "#/$defs/Derivation" }, defs, 3)).toEqual({ base: "" });
  });
});

describe("hex and length parsing", () => {
  it("expands shorthand hex", () => {
    expect(expandHex("#abc")).toBe("#aabbcc");
    expect(expandHex("#aabbcc")).toBe("#aabbcc");
  });

  it("parses a number with an optional unit", () => {
    expect(parseLength("0.75in")).toEqual({ num: "0.75", unit: "in" });
    expect(parseLength(" -2 cm ")).toEqual({ num: "-2", unit: "cm" });
    expect(parseLength(".5pt")).toEqual({ num: ".5", unit: "pt" });
    expect(parseLength("12")).toEqual({ num: "12", unit: "" });
    expect(parseLength("wide")).toBeNull();
    expect(parseLength("1.5em")).toBeNull();
    expect(parseLength("")).toBeNull();
  });

  it("recombines, treating an empty number as empty", () => {
    expect(composeLength("1.5", "cm")).toBe("1.5cm");
    expect(composeLength("", "cm")).toBe("");
  });

  it("steps in each unit's natural increment, without float noise", () => {
    expect(stepLength("1", "in", 1, false)).toBe("1.05");
    expect(stepLength("0.1", "in", 1, false)).toBe("0.15");
    expect(stepLength("0.2", "cm", 1, false)).toBe("0.3");
    expect(stepLength("12", "pt", -1, false)).toBe("11");
    expect(stepLength("1", "mm", 1, true)).toBe("11");
    expect(stepLength("", "in", 1, false)).toBe("0.05");
  });
});
