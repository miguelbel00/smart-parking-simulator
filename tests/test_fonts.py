from types import SimpleNamespace

from ui.fonts import font_family


def test_font_family_uses_platform_named_font(monkeypatch) -> None:
    widget = object()
    requested_names: list[tuple[str, object]] = []

    def nametofont(name: str, root: object) -> SimpleNamespace:
        requested_names.append((name, root))
        family = {"TkDefaultFont": "Platform Sans", "TkFixedFont": "Platform Mono"}[name]
        return SimpleNamespace(actual=lambda option: family)

    monkeypatch.setattr("ui.fonts.tkfont.nametofont", nametofont)

    assert font_family(widget) == "Platform Sans"
    assert font_family(widget, fixed=True) == "Platform Mono"
    assert requested_names == [("TkDefaultFont", widget), ("TkFixedFont", widget)]
