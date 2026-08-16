import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import SchemaForm, { type JSONSchema } from "./SchemaForm";
// A real `uv run deckifyr schema design` dump, checked in as a fixture
// -- not a hand-written approximation, so this test catches an actual
// schema-shape mismatch rather than confirming only what this renderer's
// author assumed the shape looked like. Regenerate if `DesignDocument`'s
// schema changes: `uv run deckifyr schema design > web/src/components/__fixtures__/design.schema.json`.
import designSchema from "./__fixtures__/design.schema.json";

afterEach(() => {
  cleanup();
});

function renderForm(schema: JSONSchema, defs: Record<string, JSONSchema>, value: unknown) {
  const onChange = vi.fn();
  render(<SchemaForm schema={schema} defs={defs} value={value} onChange={onChange} />);
  return onChange;
}

describe("SchemaForm -- object with properties", () => {
  const schema: JSONSchema = {
    type: "object",
    title: "Box",
    required: ["x", "y"],
    properties: {
      x: { type: "string" },
      y: { type: "string" },
      note: { type: "string" },
    },
  };

  it("renders a labeled text input per property and reports edits via onChange", () => {
    const onChange = renderForm(schema, {}, { x: "1in", y: "2in", note: "" });
    const xInput = screen.getByDisplayValue("1in");
    fireEvent.change(xInput, { target: { value: "3in" } });
    expect(onChange).toHaveBeenCalledWith({ x: "3in", y: "2in", note: "" });
  });

  it("marks required fields", () => {
    render(<SchemaForm schema={schema} defs={{}} value={{ x: "", y: "", note: "" }} onChange={vi.fn()} />);
    // "x" and "y" are required -- their labels carry the "*" marker;
    // "note" is not.
    const labels = screen.getAllByText((_, el) => el?.tagName === "LABEL");
    const requiredCount = labels.filter((l) => l.textContent?.includes("*")).length;
    expect(requiredCount).toBe(2);
  });
});

describe("SchemaForm -- nullable (anyOf with null) field", () => {
  const schema: JSONSchema = {
    type: "object",
    properties: {
      style: {
        anyOf: [{ type: "string" }, { type: "null" }],
        default: null,
      },
    },
  };

  it("shows an unset checkbox and no input when the value is null", () => {
    render(<SchemaForm schema={schema} defs={{}} value={{ style: null }} onChange={vi.fn()} />);
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).not.toBeChecked();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("materializes a default value when the checkbox is checked", () => {
    const onChange = renderForm(schema, {}, { style: null });
    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith({ style: "" });
  });

  it("clears back to null when unchecked", () => {
    const onChange = renderForm(schema, {}, { style: "heading" });
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toBeChecked();
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith({ style: null });
  });
});

describe("SchemaForm -- open dict (additionalProperties)", () => {
  const schema: JSONSchema = {
    type: "object",
    additionalProperties: { type: "string" },
  };

  it("lists existing named entries and allows removing one", () => {
    const onChange = renderForm(schema, {}, { primary: "#123456", accent: "#abcdef" });
    expect(screen.getByText("primary")).toBeInTheDocument();
    expect(screen.getByText("accent")).toBeInTheDocument();

    const removeButtons = screen.getAllByRole("button", { name: "Remove" });
    fireEvent.click(removeButtons[0]);
    expect(onChange).toHaveBeenCalledWith({ accent: "#abcdef" });
  });

  it("adds a new named entry with the item schema's default value", () => {
    const onChange = renderForm(schema, {}, {});
    fireEvent.change(screen.getByPlaceholderText("new key"), { target: { value: "highlight" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(onChange).toHaveBeenCalledWith({ highlight: "" });
  });
});

describe("SchemaForm -- enum", () => {
  const schema: JSONSchema = { type: "string", enum: ["none", "watermark", "corner-tr"] };

  it("renders a select with the enum options", () => {
    render(<SchemaForm schema={schema} defs={{}} value="watermark" onChange={vi.fn()} />);
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("watermark");
    expect(screen.getByRole("option", { name: "corner-tr" })).toBeInTheDocument();
  });
});

describe("SchemaForm -- array", () => {
  const schema: JSONSchema = { type: "array", items: { type: "string" } };

  it("renders one row per item and supports add/remove", () => {
    const onChange = renderForm(schema, {}, ["a", "b"]);
    const inputs = screen.getAllByRole("textbox");
    expect(inputs).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Add item" }));
    expect(onChange).toHaveBeenCalledWith(["a", "b", ""]);

    const removeButtons = screen.getAllByRole("button", { name: "Remove" });
    fireEvent.click(removeButtons[0]);
    expect(onChange).toHaveBeenCalledWith(["b"]);
  });
});

describe("SchemaForm -- ambiguous anyOf falls back to raw JSON", () => {
  const schema: JSONSchema = {
    type: "object",
    additionalProperties: {
      anyOf: [{ type: "string" }, { $ref: "#/$defs/ColorDerivation" }],
    },
  };
  const defs: Record<string, JSONSchema> = {
    ColorDerivation: { type: "object", properties: { base: { type: "string" } } },
  };

  it("renders a raw-JSON textarea for a value with more than one non-null anyOf branch", () => {
    renderForm(schema, defs, { primary: "#2457A6" });
    const textarea = screen.getByDisplayValue('"#2457A6"');
    expect(textarea.tagName).toBe("TEXTAREA");
  });

  it("propagates a valid edit and shows a parse error for invalid JSON", () => {
    const onChange = renderForm(schema, defs, { primary: "#2457A6" });
    const textarea = screen.getByDisplayValue('"#2457A6"');

    fireEvent.change(textarea, { target: { value: '{"base": "primary", "lighten": 0.2}' } });
    expect(onChange).toHaveBeenCalledWith({ primary: { base: "primary", lighten: 0.2 } });

    fireEvent.change(textarea, { target: { value: "{not json" } });
    expect(screen.getByText(/./, { selector: ".schema-form__raw-error" })).toBeInTheDocument();
  });
});

describe("SchemaForm -- against the real design.yaml schema", () => {
  it("resolves furniture.branding through $ref without crashing, and materializes it on toggle", () => {
    const defs = (designSchema as JSONSchema).$defs as Record<string, JSONSchema>;
    const furnitureSchema = (designSchema as JSONSchema).properties as Record<string, JSONSchema>;
    const onChange = vi.fn();
    render(
      <SchemaForm
        schema={furnitureSchema.furniture}
        defs={defs}
        value={{ status: null, branding: null, page_number: null }}
        onChange={onChange}
      />
    );

    // Three nullable sub-fields (status/branding/page_number), each an
    // unset checkbox since every value above is null.
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(3);
    checkboxes.forEach((cb) => expect(cb).not.toBeChecked());
  });
});
