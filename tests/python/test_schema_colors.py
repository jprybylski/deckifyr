import pytest

from deckifyr.schema.colors import ColorDerivation, resolve_color_tokens
from deckifyr.schema.errors import ColorResolutionError


def test_resolve_color_tokens_passes_through_plain_literals():
    colors = {"primary": "#2457A6", "accent": "#D14D32"}
    assert resolve_color_tokens(colors) == colors


def test_resolve_color_tokens_darken_matches_known_hls_value():
    colors = {
        "primary": "#2457A6",
        "secondary": ColorDerivation(base="primary", darken=0.2),
    }
    resolved = resolve_color_tokens(colors)
    assert resolved["primary"] == "#2457A6"
    # #2457A6 -> HLS, lightness -0.2, back to RGB -- verified against
    # colorsys directly rather than hand-computed.
    import colorsys

    r, g, b = (int(colors["primary"][i : i + 2], 16) / 255.0 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    expected_rgb = colorsys.hls_to_rgb(h, max(0.0, l - 0.2), s)
    expected_hex = "#" + "".join(f"{round(c * 255):02X}" for c in expected_rgb)
    assert resolved["secondary"] == expected_hex


def test_resolve_color_tokens_lighten_increases_lightness():
    import colorsys

    colors = {"primary": "#202020", "lighter": ColorDerivation(base="primary", lighten=0.3)}
    resolved = resolve_color_tokens(colors)

    def _lightness(hex_value: str) -> float:
        r, g, b = (int(hex_value[i : i + 2], 16) / 255.0 for i in (1, 3, 5))
        return colorsys.rgb_to_hls(r, g, b)[1]

    assert _lightness(resolved["lighter"]) > _lightness(resolved["primary"])


def test_resolve_color_tokens_saturate_and_desaturate_move_saturation():
    import colorsys

    colors = {
        "primary": "#2457A6",
        "saturated": ColorDerivation(base="primary", saturate=0.3),
        "desaturated": ColorDerivation(base="primary", desaturate=0.3),
    }
    resolved = resolve_color_tokens(colors)

    def _saturation(hex_value: str) -> float:
        r, g, b = (int(hex_value[i : i + 2], 16) / 255.0 for i in (1, 3, 5))
        return colorsys.rgb_to_hls(r, g, b)[2]

    base_s = _saturation(resolved["primary"])
    assert _saturation(resolved["saturated"]) >= base_s
    assert _saturation(resolved["desaturated"]) <= base_s


def test_resolve_color_tokens_mix_blends_toward_the_second_color():
    colors = {
        "primary": "#000000",
        "accent": "#FFFFFF",
        "blend": ColorDerivation(base="primary", mix="accent", weight=0.5),
    }
    resolved = resolve_color_tokens(colors)
    assert resolved["blend"] == "#808080"


def test_resolve_color_tokens_mix_defaults_weight_to_half():
    colors = {
        "primary": "#000000",
        "accent": "#FFFFFF",
        "blend": ColorDerivation(base="primary", mix="accent"),
    }
    resolved = resolve_color_tokens(colors)
    assert resolved["blend"] == "#808080"


def test_resolve_color_tokens_mix_toward_a_literal_not_in_colors():
    colors = {
        "primary": "#000000",
        "blend": ColorDerivation(base="primary", mix="#FFFFFF", weight=0.5),
    }
    resolved = resolve_color_tokens(colors)
    assert resolved["blend"] == "#808080"


def test_resolve_color_tokens_follows_multi_level_chains():
    colors = {
        "primary": "#2457A6",
        "secondary": ColorDerivation(base="primary", darken=0.1),
        "tertiary": ColorDerivation(base="secondary", darken=0.1),
    }
    resolved = resolve_color_tokens(colors)
    assert resolved["tertiary"] != resolved["secondary"] != resolved["primary"]


def test_resolve_color_tokens_treats_unknown_base_as_a_literal():
    colors = {"secondary": ColorDerivation(base="#123456", darken=0.1)}
    resolved = resolve_color_tokens(colors)
    assert resolved["secondary"] != "#123456"  # darkened, but did not raise


def test_resolve_color_tokens_detects_a_direct_cycle():
    colors = {
        "a": ColorDerivation(base="b", darken=0.1),
        "b": ColorDerivation(base="a", lighten=0.1),
    }
    with pytest.raises(ColorResolutionError):
        resolve_color_tokens(colors)


def test_resolve_color_tokens_detects_a_self_cycle():
    colors = {"a": ColorDerivation(base="a", darken=0.1)}
    with pytest.raises(ColorResolutionError):
        resolve_color_tokens(colors)


def test_resolve_color_tokens_detects_a_cycle_through_mix():
    colors = {
        "a": ColorDerivation(base="primary", mix="b"),
        "b": ColorDerivation(base="primary", mix="a"),
        "primary": "#2457A6",
    }
    with pytest.raises(ColorResolutionError):
        resolve_color_tokens(colors)
