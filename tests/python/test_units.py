import pytest

from deckifyr.schema.units import (
    EMU_PER_CM,
    EMU_PER_INCH,
    EMU_PER_MM,
    EMU_PER_POINT,
    format_length,
    parse_length,
)
from deckifyr.schema.errors import UnitParseError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1in", EMU_PER_INCH),
        ("0.5in", EMU_PER_INCH // 2),
        ("18pt", 18 * EMU_PER_POINT),
        ("2.5cm", round(2.5 * EMU_PER_CM)),
        ("10mm", 10 * EMU_PER_MM),
        ("-0.25in", -round(0.25 * EMU_PER_INCH)),
    ],
)
def test_parse_length_units(raw, expected):
    assert parse_length(raw) == expected


def test_parse_length_rejects_unitless_in_strict_mode():
    with pytest.raises(UnitParseError):
        parse_length("1.5")


def test_parse_length_allows_unitless_when_not_strict():
    assert parse_length("100", strict=False) == 100


def test_parse_length_rejects_garbage():
    with pytest.raises(UnitParseError):
        parse_length("wide", strict=False)


def test_parse_length_accepts_numeric_input_when_not_strict():
    assert parse_length(914400, strict=False) == 914400


def test_parse_length_rejects_numeric_input_in_strict_mode():
    with pytest.raises(UnitParseError):
        parse_length(914400, strict=True)


@pytest.mark.parametrize(
    "raw",
    ["1in", "2.5cm", "10pt", "5mm"],
)
def test_format_length_round_trips_clean_values(raw):
    emu = parse_length(raw)
    unit = raw[-2:]
    formatted = format_length(emu, unit)
    assert formatted == raw
    assert parse_length(formatted) == emu


def test_format_length_rejects_unsupported_unit():
    with pytest.raises(UnitParseError):
        format_length(EMU_PER_INCH, "px")


def test_format_length_of_value_that_does_not_round_cleanly_is_still_parseable():
    # 333333 EMU is not a clean number of inches -- formatting must still
    # produce something `parse_length` can consume, even though the
    # round trip loses precision beyond the 4-decimal-place cutoff (up to
    # half of 0.0001in, i.e. ~46 EMU).
    emu = 333333
    formatted = format_length(emu, "in")
    round_tripped = parse_length(formatted)
    assert abs(round_tripped - emu) <= round(EMU_PER_INCH * 0.0001)
