/**
 * Guidance hook for an embedding host (issue #105).
 *
 * A host that frames the editor on its own origin (for example a local
 * launcher that serves it under a path prefix) can ask the editor to
 * highlight one of a few controls marked with a stable `data-target` id,
 * so a walkthrough can point at them. The editor draws the ring itself;
 * the host never reads or writes this page.
 *
 * Contract ("embedded guidance v1"):
 *
 * - Request (parent -> editor): `{type: "guidance", v: 1, op, id, seq}`,
 *   `op` one of `highlight`, `clear`, `condition`; `id` absent for `clear`.
 * - Reply (editor -> parent): `{type: "guidance-reply", v: 1, op, id, seq,
 *   state}`: `"shown"`/`"absent"` for `highlight`, `"unknown"` for an id
 *   this editor doesn't have (and for every `condition`: there are none in
 *   this version). `clear` gets no reply.
 * - Only a message from `window.parent` on this page's own origin is read;
 *   anything else -- another origin, another window, any other shape -- is
 *   ignored without a reply. Replies go to the sender on this origin only.
 * - A highlight is visual only: it never moves focus, switches tab, clicks
 *   or changes state. Repeating a request for the element already shown is
 *   a no-op (a host may poll), so the page only scrolls when the
 *   highlighted element changes.
 *
 * `GUIDANCE_TARGETS` must match the ids `GET /api/health` lists
 * (`deckifyr.web.app.GUIDANCE_TARGETS`); a Python test checks both against
 * the markup.
 */

export const GUIDANCE_VERSION = 1;
export const GUIDANCE_TARGETS: readonly string[] = [
  "deckifyr.session.save",
  "deckifyr.nav.build",
  "deckifyr.build.run",
];
export const RING_CLASS = "deckifyr-guidance-target";

const ID_RE = /^[a-z][a-z0-9-]*(\.[a-z0-9-]+)+$/;
const OPS = new Set(["highlight", "clear", "condition"]);

type Op = "highlight" | "clear" | "condition";
type Request = { op: Op; id?: string; seq: number };

let ringed: Element | null = null;

function parse(data: unknown): Request | null {
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const d = data as Record<string, unknown>;
  if (d.type !== "guidance" || d.v !== GUIDANCE_VERSION) return null;
  if (typeof d.op !== "string" || !OPS.has(d.op)) return null;
  if (typeof d.seq !== "number" || !Number.isInteger(d.seq)) return null;
  if (d.op === "clear") return { op: "clear", seq: d.seq };
  if (typeof d.id !== "string" || !ID_RE.test(d.id)) return null;
  return { op: d.op as Op, id: d.id, seq: d.seq };
}

function isShown(el: Element): boolean {
  return el.isConnected && el.closest("[hidden]") === null && el.getClientRects().length > 0;
}

function findShown(id: string): Element | null {
  // Compare attributes rather than building a selector from the id.
  for (const el of Array.from(document.querySelectorAll("[data-target]"))) {
    if (el.getAttribute("data-target") === id && isShown(el)) return el;
  }
  return null;
}

export function clearRing(): void {
  if (ringed) ringed.classList.remove(RING_CLASS);
  ringed = null;
}

function highlight(id: string): "shown" | "absent" | "unknown" {
  if (!GUIDANCE_TARGETS.includes(id)) {
    clearRing();
    return "unknown";
  }
  const el = findShown(id);
  if (!el) {
    clearRing();
    return "absent";
  }
  if (el === ringed && el.classList.contains(RING_CLASS)) return "shown";
  clearRing();
  el.classList.add(RING_CLASS);
  ringed = el;
  if (typeof (el as HTMLElement).scrollIntoView === "function") {
    (el as HTMLElement).scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  return "shown";
}

export function handleGuidanceMessage(event: MessageEvent): void {
  if (window.parent === window) return; // not framed: nothing to answer
  if (event.origin !== window.location.origin || event.source !== window.parent) return;
  const req = parse(event.data);
  if (!req) return;
  if (req.op === "clear") {
    clearRing();
    return;
  }
  const state = req.op === "highlight" ? highlight(req.id as string) : "unknown";
  (event.source as Window).postMessage(
    { type: "guidance-reply", v: GUIDANCE_VERSION, op: req.op, id: req.id, seq: req.seq, state },
    window.location.origin,
  );
}

let installed = false;

/** Start answering the host. Safe to call more than once. */
export function installGuidance(): void {
  if (installed) return;
  installed = true;
  window.addEventListener("message", handleGuidanceMessage);
}
