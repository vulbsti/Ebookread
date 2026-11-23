"""Reading settings popover: theme, text, layout, colour, fixed-layout zoom, controls."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gdk, GLib, Gtk, PangoCairo

from ..core.config import ConfigStore, ReaderSettings
from .theme import SWATCH_CSS, THEME_CHOICES

# Reading fonts worth offering when installed: (family, generic fallback)
CURATED_FONTS = [
    ("Literata", "serif"), ("Noto Serif", "serif"), ("Source Serif 4", "serif"), ("Merriweather", "serif"),
    ("Gentium Book Basic", "serif"), ("Linux Libertine O", "serif"), ("EB Garamond", "serif"),
    ("Bitstream Charter", "serif"), ("Georgia", "serif"), ("Liberation Serif", "serif"), ("DejaVu Serif", "serif"),
    ("Atkinson Hyperlegible", "sans-serif"), ("Inter", "sans-serif"), ("Noto Sans", "sans-serif"),
    ("Ubuntu", "sans-serif"), ("Cantarell", "sans-serif"), ("Open Sans", "sans-serif"),
    ("OpenDyslexic", "sans-serif"),
]
SPACING_CHOICES = [("book", "Book default"), ("none", "None"), ("small", "Small"), ("large", "Large")]
ZOOM_CHOICES = [("fit-page", "Fit page"), ("fit-width", "Fit width"), ("100", "100%"), ("150", "150%"), ("200", "200%")]
DEBOUNCE_MS = 120


def installed_families() -> set[str]:
    return {f.get_name() for f in PangoCairo.FontMap.get_default().list_families()}


def font_choices(current_css: str) -> list[tuple[str, str]]:
    """(label, css font-family) for the font dropdown; keeps a custom current font selectable."""
    have = installed_families()
    choices = [("Default serif", "serif"), ("Default sans-serif", "sans-serif")]
    choices += [(fam, f"'{fam}', {generic}") for fam, generic in CURATED_FONTS if fam in have]
    if current_css not in {css for _, css in choices}:
        label = current_css.split(",")[0].strip().strip("'\"") or current_css
        choices.append((label, current_css))
    return choices


class SettingsPopover(Gtk.Popover):
    """Live reading settings. Every change is saved and applied immediately."""

    _css_installed = False

    def __init__(self, config: ConfigStore, on_change: Callable[[ReaderSettings], None]) -> None:
        super().__init__()
        self.config = config
        self.on_change = on_change
        self._timers: dict[str, int] = {}
        self._install_css()
        s = config.settings

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, f"set_margin_{side}")(12)
        content.set_size_request(360, -1)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.set_max_content_height(620)
        scroll.set_child(content)
        self.set_child(scroll)

        content.append(self._theme_row(s))

        # ---------------------------------------------------------- text
        text = Adw.PreferencesGroup(title="Text")
        self.publisher_row = Adw.SwitchRow(title="Book's own fonts and spacing",
                                           subtitle="Keep the publisher's design; size and colours still apply")
        self.publisher_row.set_active(s.publisher_formatting)
        self.publisher_row.connect("notify::active", lambda r, _p: (self._emit(publisher_formatting=r.get_active()),
                                                                   self._sync_sensitivity()))
        text.add(self.publisher_row)

        self._fonts = font_choices(s.font_family)
        self.font_row = Adw.ComboRow(title="Font", model=Gtk.StringList.new([l for l, _ in self._fonts]))
        self.font_row.set_selected(next((i for i, (_, css) in enumerate(self._fonts) if css == s.font_family), 0))
        self.font_row.connect("notify::selected", self._on_font_selected)
        choose = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
        choose.add_css_class("flat")
        choose.set_tooltip_text("Pick any installed font")
        choose.connect("clicked", self._choose_font)
        self.font_row.add_suffix(choose)
        text.add(self.font_row)

        size_row = Adw.SpinRow.new_with_range(12, 36, 1)
        size_row.set_title("Size")
        size_row.set_value(s.font_size)
        size_row.connect("notify::value", lambda r, _p: self._emit(font_size=int(r.get_value())))
        text.add(size_row)

        self.line_row = Adw.SpinRow.new_with_range(1.2, 2.2, 0.05)
        self.line_row.set_title("Line spacing")
        self.line_row.set_digits(2)
        self.line_row.set_value(s.line_height)
        self.line_row.connect("notify::value", lambda r, _p: self._emit_later("line_height", round(r.get_value(), 2)))
        text.add(self.line_row)

        self.para_row = self._combo("Paragraph spacing", SPACING_CHOICES, s.paragraph_spacing, "paragraph_spacing")
        text.add(self.para_row)

        self.justify_row = Adw.SwitchRow(title="Justify text", active=s.justify)
        self.justify_row.connect("notify::active", lambda r, _p: self._emit(justify=r.get_active()))
        text.add(self.justify_row)
        self.hyphen_row = Adw.SwitchRow(title="Hyphenate words", active=s.hyphenate)
        self.hyphen_row.connect("notify::active", lambda r, _p: self._emit(hyphenate=r.get_active()))
        text.add(self.hyphen_row)
        content.append(text)

        # ---------------------------------------------------------- layout
        layout = Adw.PreferencesGroup(title="Layout")
        flow_row = Adw.ActionRow(title="Pages")
        flow_box = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
        pag = Gtk.ToggleButton(label="Turn pages")
        scr = Gtk.ToggleButton(label="Scroll", group=pag)
        (scr if s.layout_mode == "scrolled" else pag).set_active(True)
        pag.connect("toggled", lambda b: b.get_active() and self._emit(layout_mode="paginated"))
        scr.connect("toggled", lambda b: b.get_active() and self._emit(layout_mode="scrolled"))
        flow_box.append(pag)
        flow_box.append(scr)
        flow_row.add_suffix(flow_box)
        layout.add(flow_row)
        layout.add(self._combo("Columns", [("auto", "Two on wide windows"), ("single", "Always one")],
                               s.columns, "columns"))
        layout.add(self._slider("Line width", 480, 1400, 20, s.max_width, "max_width",
                                fmt=lambda v: f"{int(v)} px"))
        layout.add(self._slider("Side margins", 2, 14, 1, s.margin_pct, "margin_pct", fmt=lambda v: f"{int(v)}%"))
        content.append(layout)

        # ---------------------------------------------------------- colour
        colour = Adw.PreferencesGroup(title="Colour")
        reset = Gtk.Button(label="Reset", valign=Gtk.Align.CENTER)
        reset.add_css_class("flat")
        reset.connect("clicked", self._reset_colours)
        colour.set_header_suffix(reset)
        self._colour_scales = {
            "warmth": self._slider("Warmth", 0, 100, 5, s.warmth, "warmth", fmt=lambda v: f"{int(v)}%"),
            "contrast": self._slider("Contrast", 50, 150, 5, s.contrast, "contrast", fmt=lambda v: f"{int(v)}%"),
            "saturation": self._slider("Colour", 0, 100, 5, s.saturation, "saturation",
                                       fmt=lambda v: "Grayscale" if v == 0 else f"{int(v)}%"),
            "brightness": self._slider("Brightness", 40, 100, 5, s.brightness, "brightness",
                                       fmt=lambda v: f"{int(v)}%"),
        }
        for row in self._colour_scales.values():
            colour.add(row)
        invert = Adw.SwitchRow(title="Invert PDF pages in dark themes", active=s.invert_pdf_in_dark)
        invert.connect("notify::active", lambda r, _p: self._emit(invert_pdf_in_dark=r.get_active()))
        colour.add(invert)
        content.append(colour)

        # ---------------------------------------------------------- fixed layout & window
        fixed = Adw.PreferencesGroup(title="PDFs and Comics")
        fixed.add(self._combo("Zoom", ZOOM_CHOICES, s.fxl_zoom, "fxl_zoom"))
        content.append(fixed)

        window = Adw.PreferencesGroup(title="Window")
        hide = Adw.SwitchRow(title="Hide controls while reading",
                             subtitle="They return when you move to the top or bottom edge",
                             active=s.auto_hide_controls)
        hide.connect("notify::active", lambda r, _p: self._emit(auto_hide_controls=r.get_active()))
        window.add(hide)
        content.append(window)

        self._sync_sensitivity()

    # ------------------------------------------------------------ building blocks

    @classmethod
    def _install_css(cls) -> None:
        if cls._css_installed:
            return
        provider = Gtk.CssProvider()
        provider.load_from_string(SWATCH_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        cls._css_installed = True

    def _theme_row(self, s: ReaderSettings) -> Gtk.Widget:
        box = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        first = None
        self.theme_buttons: dict[str, Gtk.ToggleButton] = {}
        for key, label in THEME_CHOICES:
            btn = Gtk.ToggleButton(label="A" if key != "system" else "")
            btn.add_css_class("theme-swatch")
            btn.add_css_class(key)
            btn.set_tooltip_text(label)
            btn.update_property([Gtk.AccessibleProperty.LABEL], [label])
            if first is None:
                first = btn
            else:
                btn.set_group(first)
            btn.set_active(s.theme == key)
            btn.connect("toggled", lambda b, k=key: b.get_active() and self._emit(theme=k))
            box.append(btn)
            self.theme_buttons[key] = btn
        return box

    def _combo(self, title: str, choices: list[tuple[str, str]], current: str, key: str) -> Adw.ComboRow:
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for _, label in choices]))
        row.set_selected(next((i for i, (v, _) in enumerate(choices) if v == current), 0))
        row.connect("notify::selected", lambda r, _p: self._emit(**{key: choices[r.get_selected()][0]}))
        return row

    def _slider(self, title: str, lo: float, hi: float, step: float, value: float, key: str, fmt) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title)
        value_label = Gtk.Label(label=fmt(value), width_chars=9, xalign=1.0)
        value_label.add_css_class("dim-label")
        value_label.add_css_class("numeric")
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        scale.set_value(value)
        scale.set_draw_value(False)
        scale.set_size_request(150, -1)
        scale.set_valign(Gtk.Align.CENTER)

        def changed(sc: Gtk.Scale) -> None:
            v = round(sc.get_value() / step) * step
            value_label.set_label(fmt(v))
            self._emit_later(key, int(v) if float(step).is_integer() else v)

        scale.connect("value-changed", changed)
        row.add_suffix(value_label)
        row.add_suffix(scale)
        row._scale = scale  # type: ignore[attr-defined]
        return row

    def _sync_sensitivity(self) -> None:
        mine = not self.publisher_row.get_active()
        for row in (self.font_row, self.line_row, self.para_row, self.justify_row, self.hyphen_row):
            row.set_sensitive(mine)

    # ------------------------------------------------------------ fonts

    def _on_font_selected(self, row: Adw.ComboRow, _p) -> None:
        idx = row.get_selected()
        if 0 <= idx < len(self._fonts):
            self._emit(font_family=self._fonts[idx][1])

    def _choose_font(self, _btn) -> None:
        dialog = Gtk.FontDialog(title="Choose a Font")

        def done(d: Gtk.FontDialog, result) -> None:
            try:
                family = d.choose_family_finish(result)
            except GLib.Error:
                return  # cancelled
            name = family.get_name()
            css = f"'{name}', {'monospace' if family.is_monospace() else 'serif'}"
            self._fonts = font_choices(css)
            self.font_row.set_model(Gtk.StringList.new([l for l, _ in self._fonts]))
            self.font_row.set_selected(next(i for i, (_, c) in enumerate(self._fonts) if c == css))

        self.popdown()
        dialog.choose_family(self.get_root(), None, None, done)

    # ------------------------------------------------------------ applying

    def _reset_colours(self, _btn) -> None:
        defaults = ReaderSettings()
        for key, row in self._colour_scales.items():
            row._scale.set_value(getattr(defaults, key))  # type: ignore[attr-defined]

    def _emit(self, **kwargs) -> None:
        updated = self.config.update(**kwargs)
        self.on_change(updated)

    def _emit_later(self, key: str, value) -> None:
        """Sliders fire continuously while dragged; apply once they pause."""
        if key in self._timers:
            GLib.source_remove(self._timers[key])

        def fire() -> bool:
            self._timers.pop(key, None)
            self._emit(**{key: value})
            return False

        self._timers[key] = GLib.timeout_add(DEBOUNCE_MS, fire)
