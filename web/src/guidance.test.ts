import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearRing, GUIDANCE_TARGETS, handleGuidanceMessage, RING_CLASS } from "./guidance";

// jsdom has no layout: give every element a box unless it sits under [hidden].
const rects = vi.spyOn(Element.prototype, "getClientRects");

function framed(parent: { postMessage: ReturnType<typeof vi.fn> }) {
  Object.defineProperty(window, "parent", { value: parent, configurable: true });
}

function send(data: unknown, opts: { origin?: string; source?: unknown } = {}) {
  const event = new MessageEvent("message", {
    data,
    origin: opts.origin ?? window.location.origin,
    source: (opts.source ?? window.parent) as Window,
  });
  handleGuidanceMessage(event);
}

describe("guidance hook", () => {
  let parent: { postMessage: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    parent = { postMessage: vi.fn() };
    framed(parent);
    rects.mockImplementation(function (this: Element) {
      return (this.closest("[hidden]") ? [] : [{}]) as unknown as DOMRectList;
    });
    document.body.innerHTML = `
      <button data-target="deckifyr.session.save">Save</button>
      <div hidden><button data-target="deckifyr.build.run">Build</button></div>`;
  });

  afterEach(() => {
    clearRing();
    document.body.innerHTML = "";
  });

  it("highlights a shown control and replies shown", () => {
    send({ type: "guidance", v: 1, op: "highlight", id: "deckifyr.session.save", seq: 1 });
    const save = document.querySelector('[data-target="deckifyr.session.save"]')!;
    expect(save).toHaveClass(RING_CLASS);
    expect(parent.postMessage).toHaveBeenCalledWith(
      { type: "guidance-reply", v: 1, op: "highlight", id: "deckifyr.session.save", seq: 1, state: "shown" },
      window.location.origin,
    );
  });

  it("does not move focus or click", () => {
    const click = vi.fn();
    const save = document.querySelector<HTMLButtonElement>('[data-target="deckifyr.session.save"]')!;
    save.addEventListener("click", click);
    const before = document.activeElement;
    send({ type: "guidance", v: 1, op: "highlight", id: "deckifyr.session.save", seq: 1 });
    expect(document.activeElement).toBe(before);
    expect(click).not.toHaveBeenCalled();
  });

  it("replies absent for a hidden control and draws nothing", () => {
    send({ type: "guidance", v: 1, op: "highlight", id: "deckifyr.build.run", seq: 2 });
    expect(document.querySelector(`.${RING_CLASS}`)).toBeNull();
    expect(parent.postMessage.mock.calls[0][0].state).toBe("absent");
  });

  it("replies unknown for an id it doesn't have, and for any condition", () => {
    send({ type: "guidance", v: 1, op: "highlight", id: "deckifyr.nope.here", seq: 3 });
    send({ type: "guidance", v: 1, op: "condition", id: "deckifyr.deck.built", seq: 4 });
    expect(parent.postMessage.mock.calls.map((c) => c[0].state)).toEqual(["unknown", "unknown"]);
  });

  it("clears without replying", () => {
    send({ type: "guidance", v: 1, op: "highlight", id: "deckifyr.session.save", seq: 1 });
    send({ type: "guidance", v: 1, op: "clear", seq: 2 });
    expect(document.querySelector(`.${RING_CLASS}`)).toBeNull();
    expect(parent.postMessage).toHaveBeenCalledTimes(1);
  });

  it("scrolls only when the highlighted element changes", () => {
    const save = document.querySelector<HTMLElement>('[data-target="deckifyr.session.save"]')!;
    const scroll = vi.fn();
    save.scrollIntoView = scroll;
    send({ type: "guidance", v: 1, op: "highlight", id: "deckifyr.session.save", seq: 1 });
    send({ type: "guidance", v: 1, op: "highlight", id: "deckifyr.session.save", seq: 2 });
    expect(scroll).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["another origin", { origin: "http://evil.example" }],
    ["another window", { source: {} }],
  ])("ignores a message from %s", (_label, opts) => {
    send({ type: "guidance", v: 1, op: "highlight", id: "deckifyr.session.save", seq: 1 }, opts);
    expect(document.querySelector(`.${RING_CLASS}`)).toBeNull();
    expect(parent.postMessage).not.toHaveBeenCalled();
  });

  it.each([
    ["a string", "highlight deckifyr.session.save"],
    ["a wrong type", { type: "other", v: 1, op: "highlight", id: "deckifyr.session.save", seq: 1 }],
    ["a wrong version", { type: "guidance", v: 2, op: "highlight", id: "deckifyr.session.save", seq: 1 }],
    ["an unknown op", { type: "guidance", v: 1, op: "click", id: "deckifyr.session.save", seq: 1 }],
    ["a selector as id", { type: "guidance", v: 1, op: "highlight", id: "button", seq: 1 }],
    ["no seq", { type: "guidance", v: 1, op: "highlight", id: "deckifyr.session.save" }],
  ])("ignores %s", (_label, data) => {
    send(data);
    expect(document.querySelector(`.${RING_CLASS}`)).toBeNull();
    expect(parent.postMessage).not.toHaveBeenCalled();
  });

  it("lists exactly the ids the markup carries", () => {
    expect([...GUIDANCE_TARGETS].sort()).toEqual(
      ["deckifyr.build.run", "deckifyr.nav.build", "deckifyr.session.save"].sort(),
    );
  });
});
