"""Explicit-unit length parsing (spec section 7.3).

User-facing YAML always spells units out (`0.75in`, `18pt`, `2.5cm`);
internally everything is normalized to PowerPoint EMUs (English Metric
Units, 914400 per inch) since that's what python-pptx and the OOXML
format expect. Unitless numbers are only meaningful once a document has
decided whether it wants strict or permissive geometry -- that decision
lives with the caller, not here, so `parse_length` takes `strict`
explicitly rather than reading it from module state.
"""

from __future__ import annotations

import re

from deckifyr.schema.errors import ErrorCode, UnitParseError

EMU_PER_INCH = 914_400
EMU_PER_POINT = EMU_PER_INCH // 72  # 12700
EMU_PER_CM = 360_000
EMU_PER_MM = 36_000

_UNIT_TO_EMU = {
    "in": EMU_PER_INCH,
    "pt": EMU_PER_POINT,
    "cm": EMU_PER_CM,
    "mm": EMU_PER_MM,
}

_LENGTH_RE = re.compile(
    r"^\s*(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>in|pt|cm|mm)?\s*$"
)


def parse_length(raw: str | int | float, *, strict: bool = True) -> int:
    """Parse a length like `"0.75in"` into whole EMUs.

    A bare number (no unit suffix) is rejected when `strict` is True
    (spec section 7.3: "Unitless geometry should be rejected in strict
    mode"); non-strict mode treats a bare number as already-EMU, which is
    useful for values deckifyr itself produces internally (e.g. from a
    prior merge pass) without re-stringifying them.
    """
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if strict:
            raise UnitParseError(
                f"unitless length {raw!r} is not allowed in strict mode; "
                "use an explicit unit string such as '1in', '18pt', or '2.5cm'",
                code=ErrorCode.UNIT_REQUIRED,
            )
        return round(raw)

    match = _LENGTH_RE.match(raw)
    if not match:
        raise UnitParseError(
            f"could not parse {raw!r} as a length; expected a number "
            "followed by one of in/pt/cm/mm, e.g. '0.75in'"
        )

    unit = match.group("unit")
    if unit is None:
        if strict:
            raise UnitParseError(
                f"length {raw!r} has no unit; expected one of in/pt/cm/mm "
                "(unitless geometry is rejected in strict mode)",
                code=ErrorCode.UNIT_REQUIRED,
            )
        return round(float(match.group("value")))

    value = float(match.group("value"))
    return round(value * _UNIT_TO_EMU[unit])


def emu_to_inches(emu: int) -> float:
    return emu / EMU_PER_INCH
