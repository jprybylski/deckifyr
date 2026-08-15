"""Color-token derivation (spec section 7.4, issue #11).

A `design.yaml` `colors:` entry may be a literal hex string (as always)
or a `ColorDerivation` -- a small structured description of how to
compute that token's color from another one via a simple HSL-space
transform (lighten/darken/saturate/desaturate) or by mixing two colors
together, rather than a hand-picked literal. Color math goes through
stdlib `colorsys` (RGB<->HLS conversion) rather than a new third-party
dependency -- `colorsys` already supplies the one genuinely non-trivial
part (HSL space conversion); lighten/darken/saturate/desaturate/mix are
each a few lines once that exists, which doesn't clear the bar this
repo otherwise holds new dependencies to (Pillow/pyarrow/pymupdf are
each pulled in for real domain-specific parsing/rendering work, not a
handful of arithmetic operations).

`resolve_color_tokens` is the single place `colors:` derivations get
expanded to literal hex strings, called once from `deckifyr.cli.
_load_project` right after `design.yaml` is parsed -- see that
function's own comment for why resolving there (not in `deckifyr.plan`)
is what makes every existing `design.colors.get(token, token)` call
site in both `deckifyr.plan` and `deckifyr.pptx.compose` keep working
unchanged.
"""

from __future__ import annotations

import colorsys

from pydantic import BaseModel, ConfigDict, model_validator

from deckifyr.schema.errors import ColorResolutionError

_NUMERIC_OPERATIONS = ("lighten", "darken", "saturate", "desaturate")


class ColorDerivation(BaseModel):
    """One `colors:` entry computed from another token/literal instead of
    a hand-picked literal hex value. `base` may name a `colors:` token or
    a literal hex value, the same "token or bare literal" convention
    every other color-bearing field in `design.yaml` already uses.
    Exactly one of `lighten`/`darken`/`saturate`/`desaturate`/`mix` must
    be set; `weight` (0.0-1.0, default 0.5 when `mix` is set) is only
    valid alongside `mix` -- it's the fraction of `mix`'s own color
    blended in (0.0 = all `base`, 1.0 = all `mix`).
    """

    model_config = ConfigDict(extra="forbid")

    base: str
    lighten: float | None = None
    darken: float | None = None
    saturate: float | None = None
    desaturate: float | None = None
    mix: str | None = None
    weight: float | None = None

    @model_validator(mode="after")
    def _check_operation(self) -> "ColorDerivation":
        numeric_ops = {name: getattr(self, name) for name in _NUMERIC_OPERATIONS}
        set_numeric = [name for name, value in numeric_ops.items() if value is not None]
        if self.mix is not None:
            if set_numeric:
                raise ValueError(
                    "a color derivation may set `mix` or one of "
                    "lighten/darken/saturate/desaturate, not both"
                )
        elif self.weight is not None:
            raise ValueError("`weight` is only valid alongside `mix`")
        elif len(set_numeric) != 1:
            raise ValueError(
                "a color derivation needs exactly one of lighten/darken/"
                "saturate/desaturate/mix"
            )
        for name, value in {**numeric_ops, "weight": self.weight}.items():
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"color derivation {name} {value!r} must be between 0.0 and 1.0"
                )
        return self


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    raw = value.lstrip("#")
    r, g, b = (int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (r, g, b)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, channel)) * 255):02X}" for channel in rgb)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _lighten(hex_color: str, amount: float) -> str:
    h, l, s = colorsys.rgb_to_hls(*_hex_to_rgb(hex_color))
    return _rgb_to_hex(colorsys.hls_to_rgb(h, _clamp01(l + amount), s))


def _darken(hex_color: str, amount: float) -> str:
    h, l, s = colorsys.rgb_to_hls(*_hex_to_rgb(hex_color))
    return _rgb_to_hex(colorsys.hls_to_rgb(h, _clamp01(l - amount), s))


def _saturate(hex_color: str, amount: float) -> str:
    h, l, s = colorsys.rgb_to_hls(*_hex_to_rgb(hex_color))
    return _rgb_to_hex(colorsys.hls_to_rgb(h, l, _clamp01(s + amount)))


def _desaturate(hex_color: str, amount: float) -> str:
    h, l, s = colorsys.rgb_to_hls(*_hex_to_rgb(hex_color))
    return _rgb_to_hex(colorsys.hls_to_rgb(h, l, _clamp01(s - amount)))


def _mix(hex_a: str, hex_b: str, weight: float) -> str:
    a = _hex_to_rgb(hex_a)
    b = _hex_to_rgb(hex_b)
    r, g, b = (a_c * (1.0 - weight) + b_c * weight for a_c, b_c in zip(a, b))
    return _rgb_to_hex((r, g, b))


def resolve_color_tokens(colors: dict[str, "str | ColorDerivation"]) -> dict[str, str]:
    """Resolve every `colors:` entry to a literal hex string, following
    `base`/`mix` derivation chains to arbitrary depth (so a derivation
    based on another derivation just works). A `base`/`mix` name that
    isn't itself a `colors:` key is treated as a literal, the same
    fallback `design.colors.get(token, token)` already uses at every
    consumption site -- this function's only failure mode is a circular
    derivation chain, reported as `ColorResolutionError`.
    """
    resolved: dict[str, str] = {}

    def _lookup(name: str, chain: tuple[str, ...]) -> str:
        if name in resolved:
            return resolved[name]
        if name not in colors:
            return name
        if name in chain:
            cycle = " -> ".join((*chain, name))
            raise ColorResolutionError(f"circular color derivation: {cycle}")
        value = colors[name]
        literal = value if isinstance(value, str) else _apply(value, (*chain, name))
        resolved[name] = literal
        return literal

    def _apply(derivation: ColorDerivation, chain: tuple[str, ...]) -> str:
        base = _lookup(derivation.base, chain)
        if derivation.lighten is not None:
            return _lighten(base, derivation.lighten)
        if derivation.darken is not None:
            return _darken(base, derivation.darken)
        if derivation.saturate is not None:
            return _saturate(base, derivation.saturate)
        if derivation.desaturate is not None:
            return _desaturate(base, derivation.desaturate)
        assert derivation.mix is not None  # enforced by ColorDerivation's own validator
        weight = derivation.weight if derivation.weight is not None else 0.5
        return _mix(base, _lookup(derivation.mix, chain), weight)

    for name in colors:
        _lookup(name, ())
    return resolved
