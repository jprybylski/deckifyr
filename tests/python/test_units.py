import pytest

from deckifyr.schema.units import EMU_PER_CM, EMU_PER_INCH, EMU_PER_MM, EMU_PER_POINT, parse_length
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
