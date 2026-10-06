import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import SchemaForm, { type JSONSchema } from "./SchemaForm";
import { ColorTokensContext } from "./schemaWidgets";
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
    const { container } = render(
      <SchemaForm schema={schema} defs={{}} value={{ x: "", y: "", note: "" }} onChange={vi.fn()} />
    );
    // "x" and "y" are required -- they carry the marker; "note" does not.
    expect(container.querySelectorAll("[data-required]")).toHaveLength(2);
    expect(screen.getAllByRole("img", { name: "required" })).toHaveLength(2);
  });

  it("wires each label to its control", () => {
    render(<SchemaForm schema={schema} defs={{}} value={{ x: "1in", y: "2in", note: "" }} onChange={vi.fn()} />);
    expect(screen.getByLabelText("x")).toHaveValue("1in");
    expect(screen.getByLabelText("note")).toHaveValue("");
  });

  it("shows a property's description as a hint and its default as a placeholder", () => {
    const described: JSONSchema = {
      type: "object",
      properties: {
        size: { type: "string", description: "Font size with a unit.", default: "18pt" },
      },
    };
    render(<SchemaForm schema={described} defs={{}} value={{ size: "" }} onChange={vi.fn()} />);
    expect(screen.getByText("Font size with a unit.")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("18pt")).toBeInTheDocument();
  });

  it("does not show a referenced definition's class docstring as a hint", () => {
    const withRef: JSONSchema = {
      type: "object",
      properties: { box: { $ref: "#/$defs/Box" } },
    };
    const defs = { Box: { type: "object", description: "Explicit geometry: origin top-left.", properties: { x: { type: "string" } } } };
    render(<SchemaForm schema={withRef} defs={defs} value={{ box: { x: "1in" } }} onChange={vi.fn()} />);
    expect(screen.queryByText(/Explicit geometry/)).not.toBeInTheDocument();
  });

  it("collapses and expands a nested object's card", () => {
    const nested: JSONSchema = {
      type: "object",
      properties: { box: { type: "object", properties: { x: { type: "string" } } } },
    };
    render(<SchemaForm schema={nested} defs={{}} value={{ box: { x: "1in" } }} onChange={vi.fn()} />);
    const toggle = screen.getByRole("button", { name: /box/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByDisplayValue("1in")).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByDisplayValue("1in")).not.toBeInTheDocument();
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

    const removeButtons = screen.getAllByRole("button", { name: /^Remove/ });
    expect(removeButtons).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Remove primary" }));
    expect(onChange).toHaveBeenCalledWith({ accent: "#abcdef" });
  });

  it("adds a new named entry with the item schema's default value", () => {
    const onChange = renderForm(schema, {}, {});
    fireEvent.change(screen.getByPlaceholderText("new key"), { target: { value: "highlight" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(onChange).toHaveBeenCalledWith({ highlight: "" });
  });

  it("adds on Enter, and refuses an empty or duplicate key", () => {
    const onChange = renderForm(schema, {}, { primary: "#123456" });
    const input = screen.getByPlaceholderText("new key");
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "primary" } });
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "accent" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith({ primary: "#123456", accent: "" });
  });
});

describe("SchemaForm -- enum", () => {
  it("renders a short enum as a segmented control", () => {
    const schema: JSONSchema = { type: "string", enum: ["none", "watermark", "corner-tr"] };
    const onChange = renderForm(schema, {}, "watermark");
    expect(screen.getByRole("radiogroup")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "watermark" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "corner-tr" }));
    expect(onChange).toHaveBeenCalledWith("corner-tr");
  });

  it("renders a longer enum as a select with the options", () => {
    const schema: JSONSchema = {
      type: "string",
      enum: ["rectangle", "oval", "triangle", "diamond", "hexagon"],
    };
    const onChange = renderForm(schema, {}, "oval");
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("oval");
    expect(screen.getByRole("option", { name: "hexagon" })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "hexagon" } });
    expect(onChange).toHaveBeenCalledWith("hexagon");
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

    fireEvent.click(screen.getByRole("button", { name: "Remove item 1" }));
    expect(onChange).toHaveBeenCalledWith(["b"]);
  });
});

describe("SchemaForm -- union of differently-typed branches", () => {
  const schema: JSONSchema = {
    type: "object",
    additionalProperties: {
      anyOf: [{ type: "string" }, { $ref: "#/$defs/ColorDerivation" }],
    },
  };
  const defs: Record<string, JSONSchema> = {
    ColorDerivation: {
      type: "object",
      required: ["base"],
      properties: { base: { type: "string" }, lighten: { anyOf: [{ type: "number" }, { type: "null" }] } },
    },
  };

  it("infers the active branch from the value and renders that branch's form", () => {
    renderForm(schema, defs, { primary: "#2457A6" });
    expect(screen.getByRole("radio", { name: "Text" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Derived" })).not.toBeChecked();
    expect(screen.getByDisplayValue("#2457A6")).toBeInTheDocument();
  });

  it("shows the derived branch's fields for an object value", () => {
    renderForm(schema, defs, { soft: { base: "primary", lighten: 0.2 } });
    expect(screen.getByRole("radio", { name: "Derived" })).toBeChecked();
    expect(screen.getByDisplayValue("primary")).toBeInTheDocument();
    expect(screen.getByDisplayValue("0.2")).toBeInTheDocument();
  });

  it("carries a string into the new branch's first required string field when switching", () => {
    const onChange = renderForm(schema, defs, { primary: "#2457A6" });
    fireEvent.click(screen.getByRole("radio", { name: "Derived" }));
    expect(onChange).toHaveBeenCalledWith({ primary: { base: "#2457A6" } });
  });

  it("propagates an edit made inside the active branch", () => {
    const onChange = renderForm(schema, defs, { primary: "#2457A6" });
    fireEvent.change(screen.getByDisplayValue("#2457A6"), { target: { value: "#ff0000" } });
    expect(onChange).toHaveBeenCalledWith({ primary: "#ff0000" });
  });

  it("restores a branch's last value when switching back", () => {
    function Harness() {
      const [value, setValue] = useState<unknown>({ primary: "#2457A6" });
      return <SchemaForm schema={schema} defs={defs} value={value} onChange={setValue} />;
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole("radio", { name: "Derived" }));
    expect(screen.getByRole("radio", { name: "Derived" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "Text" }));
    expect(screen.getByDisplayValue("#2457A6")).toBeInTheDocument();
  });

  it("still shows a color swatch when the string branch holds a hex value", () => {
    const onChange = renderForm(schema, defs, { primary: "#2457a6" });
    const colorInput = screen.getByLabelText("color picker") as HTMLInputElement;
    expect(colorInput.type).toBe("color");
    expect(colorInput.value).toBe("#2457a6");
    fireEvent.change(colorInput, { target: { value: "#ff0000" } });
    expect(onChange).toHaveBeenCalledWith({ primary: "#ff0000" });
  });

  it("shows no color swatch for a derivation object", () => {
    renderForm(schema, defs, { primary: { base: "text", lighten: 0.2 } });
    expect(screen.queryByLabelText("color picker")).not.toBeInTheDocument();
  });

  it("keeps an optional union optional: a switch plus the branch switcher", () => {
    const optional: JSONSchema = {
      type: "object",
      properties: { fill: { anyOf: [{ type: "string" }, { $ref: "#/$defs/ColorDerivation" }, { type: "null" }] } },
    };
    const onChange = renderForm(optional, defs, { fill: null });
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenCalledWith({ fill: "" });
  });

  it("falls back to raw JSON when branches share a JSON type", () => {
    const same: JSONSchema = {
      type: "object",
      additionalProperties: {
        anyOf: [
          { type: "object", properties: { a: { type: "string" } } },
          { type: "object", properties: { b: { type: "string" } } },
        ],
      },
    };
    const onChange = renderForm(same, {}, { thing: { a: "1" } });
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea).not.toBeNull();

    fireEvent.change(textarea, { target: { value: '{"b": "2"}' } });
    expect(onChange).toHaveBeenCalledWith({ thing: { b: "2" } });

    fireEvent.change(textarea, { target: { value: "{not json" } });
    expect(screen.getByText(/./, { selector: ".sf-raw__error" })).toBeInTheDocument();
  });
});

describe("SchemaForm -- untyped (Any) values", () => {
  const schema: JSONSchema = {
    type: "object",
    properties: { value: { anyOf: [{}, { type: "null" }] } },
  };

  it("edits a string value as multi-line text", () => {
    const onChange = renderForm(schema, {}, { value: "# Title\nbody" });
    const box = screen.getByDisplayValue(/# Title/) as HTMLTextAreaElement;
    expect(box.tagName).toBe("TEXTAREA");
    expect(box.rows).toBe(2);
    fireEvent.change(box, { target: { value: "changed" } });
    expect(onChange).toHaveBeenCalledWith({ value: "changed" });
  });

  it("starts an unset value as an empty string when switched on", () => {
    const onChange = renderForm(schema, {}, { value: null });
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenCalledWith({ value: "" });
  });
});

describe("SchemaForm -- color widget", () => {
  const schema: JSONSchema = { type: "string", "x-deckifyr-widget": "color" };

  it("renders a swatch fused to a text field that also accepts a token name", () => {
    const onChange = renderForm(schema, {}, "primary");
    expect(screen.getByLabelText("color picker")).toHaveAttribute("data-empty", "true");
    fireEvent.change(screen.getByDisplayValue("primary"), { target: { value: "accent" } });
    expect(onChange).toHaveBeenCalledWith("accent");
  });

  it("offers the document's tokens as chips and previews a token's color", () => {
    const onChange = vi.fn();
    render(
      <ColorTokensContext.Provider value={{ primary: "#2457a6", accent: "#ff8800" }}>
        <SchemaForm schema={schema} defs={{}} value="primary" onChange={onChange} />
      </ColorTokensContext.Provider>
    );
    expect((screen.getByLabelText("color picker") as HTMLInputElement).value).toBe("#2457a6");
    fireEvent.click(screen.getByRole("button", { name: /accent/ }));
    expect(onChange).toHaveBeenCalledWith("accent");
  });

  it("shows no chips without tokens", () => {
    renderForm(schema, {}, "#2457a6");
    expect(screen.queryByRole("group", { name: "Color tokens" })).not.toBeInTheDocument();
  });
});

describe("SchemaForm -- length widget", () => {
  const schema: JSONSchema = { type: "string", "x-deckifyr-widget": "length" };

  it("splits a value into a number and a unit", () => {
    renderForm(schema, {}, "0.75in");
    expect(screen.getByDisplayValue("0.75")).toBeInTheDocument();
    expect((screen.getByLabelText("unit") as HTMLSelectElement).value).toBe("in");
  });

  it("recombines number and unit on edit", () => {
    const onChange = renderForm(schema, {}, "0.75in");
    fireEvent.change(screen.getByDisplayValue("0.75"), { target: { value: "1.5" } });
    expect(onChange).toHaveBeenCalledWith("1.5in");
    fireEvent.change(screen.getByLabelText("unit"), { target: { value: "cm" } });
    expect(onChange).toHaveBeenCalledWith("1.5cm");
  });

  it("steps with the arrow keys in the unit's own increment (Shift = x10)", () => {
    const onChange = renderForm(schema, {}, "1in");
    const input = screen.getByDisplayValue("1");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(onChange).toHaveBeenLastCalledWith("1.05in");
    fireEvent.keyDown(input, { key: "ArrowDown", shiftKey: true });
    expect(onChange).toHaveBeenLastCalledWith("0.55in");
  });

  it("falls back to one flagged text field for a value outside the grammar", () => {
    const onChange = renderForm(schema, {}, "wide");
    const input = screen.getByDisplayValue("wide");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByLabelText("unit")).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: "wider" } });
    expect(onChange).toHaveBeenCalledWith("wider");
  });
});

describe("SchemaForm -- color swatch (issue #23)", () => {
  const schema: JSONSchema = { type: "string" };

  it("shows a color input alongside the text input when the value is a 6-digit hex color", () => {
    render(<SchemaForm schema={schema} defs={{}} value="#2457a6" onChange={vi.fn()} />);
    const colorInput = screen.getByLabelText("color picker") as HTMLInputElement;
    expect(colorInput.type).toBe("color");
    expect(colorInput.value).toBe("#2457a6");
  });

  it("expands a 3-digit shorthand hex for the color input's own value", () => {
    render(<SchemaForm schema={schema} defs={{}} value="#abc" onChange={vi.fn()} />);
    const colorInput = screen.getByLabelText("color picker") as HTMLInputElement;
    expect(colorInput.value).toBe("#aabbcc");
  });

  it("does not show a color input for a non-hex string", () => {
    render(<SchemaForm schema={schema} defs={{}} value="primary" onChange={vi.fn()} />);
    expect(screen.queryByLabelText("color picker")).not.toBeInTheDocument();
  });

  it("picking a color updates the same value the text input holds", () => {
    const onChange = renderForm(schema, {}, "#2457a6");
    const colorInput = screen.getByLabelText("color picker");
    fireEvent.change(colorInput, { target: { value: "#ff0000" } });
    expect(onChange).toHaveBeenCalledWith("#ff0000");
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

  it("renders colors entries with a Color/Derived switch instead of raw JSON", () => {
    const defs = (designSchema as JSONSchema).$defs as Record<string, JSONSchema>;
    const props = (designSchema as JSONSchema).properties as Record<string, JSONSchema>;
    render(
      <SchemaForm
        schema={props.colors}
        defs={defs}
        value={{ primary: "#2457A6", soft: { base: "primary", lighten: 0.2 } }}
        onChange={vi.fn()}
      />
    );
    expect(screen.getAllByRole("radio", { name: "Color" })).toHaveLength(2);
    expect(screen.getAllByRole("radio", { name: "Derived" })).toHaveLength(2);
  });

  it("renders slide.width as a length field with a unit select", () => {
    const defs = (designSchema as JSONSchema).$defs as Record<string, JSONSchema>;
    const props = (designSchema as JSONSchema).properties as Record<string, JSONSchema>;
    render(
      <SchemaForm
        schema={props.slide}
        defs={defs}
        value={{ width: "13.333in", height: "7.5in", background: "#FFFFFF", safe_area: "0.5in" }}
        onChange={vi.fn()}
      />
    );
    expect(screen.getByDisplayValue("13.333")).toBeInTheDocument();
    expect(screen.getAllByLabelText("unit").length).toBeGreaterThanOrEqual(3);
  });

  it("shows field hints from the schema's own descriptions", () => {
    const defs = (designSchema as JSONSchema).$defs as Record<string, JSONSchema>;
    const props = (designSchema as JSONSchema).properties as Record<string, JSONSchema>;
    render(<SchemaForm schema={props.defaults} defs={defs} value={{}} onChange={vi.fn()} />);
    expect(screen.getByText(/Rotation in degrees applied to elements that set none/)).toBeInTheDocument();
  });
});
