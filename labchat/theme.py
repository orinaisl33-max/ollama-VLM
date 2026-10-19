"""Shared light/dark palettes, dialog styles and non-destructive transcript recoloring."""

import gc
import re
from pathlib import Path

from PySide6.QtGui import QColor, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QTextEdit

# Central color translation also covers locally styled secondary dialogs.
DARK_COLORS = {
    "#f4f7f8": "#121a25",
    "#182b36": "#e6edf5",
    "#ffffff": "#1d2735",
    "#f0f5f5": "#253140",
    "#243b48": "#dce5ef",
    "#dfe5fa": "#304365",
    "#253a86": "#c3d3ff",
    "#71818b": "#a3b1c1",
    "#84939b": "#8593a5",
    "#dde3f0": "#3a4a63",
    "#647781": "#adbacb",
    "#236b5d": "#9be1c8",
    "#e3f1eb": "#1b3c35",
    "#8c5a23": "#ffd29b",
    "#fff0dc": "#493520",
    "#edf1fc": "#25334a",
    "#2b4098": "#a7bbff",
    "#8c3c16": "#ffd29b",
    "#dce5e8": "#3a485b",
    "#e7edf1": "#344152",
    "#cad8dc": "#44556a",
    "#344e5a": "#d7e3ee",
    "#d5e0e4": "#41516a",
    "#eef2fc": "#2d3b52",
    "#aab8e2": "#7188b2",
    "#dfe6fa": "#364b70",
    "#87969e": "#8c9aab",
    "#f2f5f6": "#24303f",
    "#e2e8eb": "#364354",
    "#22347e": "#c8d5ff",
    "#e5e9f4": "#2d3c57",
    "#8590b1": "#99a9cc",
    "#f7f9fe": "#1a2432",
    "#a53f3f": "#ffb3ac",
    "#fff5f4": "#402c30",
    "#edceca": "#765156",
    "#243e49": "#dde8f3",
    "#e4eafa": "#2c4165",
    "#243986": "#b4c9ff",
    "#eef1f5": "#283546",
    "#c9d5d9": "#57677c",
    "#b8c5d3": "#71839a",
    "#d7dfe7": "#425065",
    "#edf1f5": "#273447",
    "#edf3ff": "#233453",
    "#f0f3f8": "#182334",
    "#7c5b23": "#f7d89c",
    "#fff4df": "#403422",
    "#f0dfbb": "#726043",
    "#cbd7e3": "#45586f",
    "#eef2f6": "#253243",
    "#f0f3fc": "#2b3952",
}


def current_theme():
    app = QApplication.instance()
    return "dark" if app and app.property("appearance") == "dark" else "light"


def theme_color(light_color):
    return (
        DARK_COLORS.get(light_color.lower(), light_color)
        if current_theme() == "dark"
        else light_color
    )


def themed_css(css):
    if current_theme() == "light":
        return css
    css = re.sub(r"(background(?:-color)?\s*:\s*)white\b", r"\1#1d2735", css)
    return re.sub(r"#[0-9a-fA-F]{6}\b", lambda m: DARK_COLORS.get(m[0].lower(), m[0]), css)


def local_style(widget, css):
    widget.setProperty("lightStyle", css)
    widget.setStyleSheet(themed_css(css))


def _retint_document(document, colors):
    ranges = []
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                brush = fragment.charFormat().foreground()
                if brush.style().value != 0 and brush.color().name() in colors:
                    ranges.append(
                        (fragment.position(), fragment.length(), colors[brush.color().name()])
                    )
            iterator += 1
        marker = block.charFormat()
        marker_color = marker.foreground().color().name()
        if marker.foreground().style().value == 0 or marker_color in colors:
            marker.setForeground(QColor(colors.get(marker_color, theme_color("#182b36"))))
            QTextCursor(block).setBlockCharFormat(marker)
        block = block.next()
    for position, length, color in ranges:
        cursor = QTextCursor(document)
        cursor.setPosition(position)
        cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.mergeCharFormat(fmt)

    def frames(frame):
        fmt = frame.frameFormat()
        color = fmt.background().color().name()
        if fmt.background().style().value != 0 and color in colors:
            fmt.setBackground(QColor(colors[color]))
            frame.setFrameFormat(fmt)
        for child in frame.childFrames():
            frames(child)

    frames(document.rootFrame())


def apply_theme(window, mode=None):
    app = QApplication.instance()
    previous = current_theme()
    mode = mode or previous
    if mode not in ("light", "dark"):
        raise ValueError("Unknown appearance")
    if (
        mode == previous
        and app.property("appliedThemeStyle") == app.styleSheet()
        and app.styleSheet()
        and app.property("appliedThemePalette") == app.palette()
    ):
        # New dialogs already inherit the app theme. Avoid rebuilding every
        # existing widget's style just to open another window or restore prefs.
        window.setPalette(app.palette())
        return
    app.setProperty("appearance", mode)
    QApplication.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f4f7f8",
        QPalette.ColorRole.WindowText: "#182b36",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f0f5f5",
        QPalette.ColorRole.Text: "#182b36",
        QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#243b48",
        QPalette.ColorRole.Highlight: "#dfe5fa",
        QPalette.ColorRole.HighlightedText: "#253a86",
        QPalette.ColorRole.PlaceholderText: "#71818b",
        QPalette.ColorRole.ToolTipBase: "#182b36",
        QPalette.ColorRole.ToolTipText: "#ffffff",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(theme_color(color)))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(theme_color("#84939b"))
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(theme_color("#84939b"))
    )
    QApplication.setPalette(palette)
    # Explicit palettes must be updated for windows that were already opened.
    # Creating Python wrappers can trigger cyclic GC. Keep it out of Qt's
    # native widget-list traversal, then retain the snapshot while applying.
    collecting = gc.isenabled()
    gc.disable()
    try:
        widgets = app.allWidgets()
    finally:
        if collecting:
            gc.enable()
    for widget in widgets:
        if not widget.isWindow():
            continue
        widget.setPalette(palette)
    window.setPalette(palette)
    css = """
            QWidget { color: #182b36; font-family: ".AppleSystemUIFont", "PingFang TC";
                      font-size: 14px; }
            QWidget#root, QDialog, QMessageBox { background: #f4f7f8; }
            QTabWidget::pane { background: white; border: 1px solid #d5e0e4; }
            QTabBar::tab { background: #edf1f5; color: #344e5a; padding: 9px 16px; }
            QTabBar::tab:selected { background: white; color: #253a86; }
            QLabel { background: transparent; border: none; }
            QLabel#brand { font-size: 25px; font-weight: 700; }
            QLabel#brand[compact="true"] { font-size: 21px; }
            QLabel#headerLogo { background: #ffffff; border: 1px solid #dde3f0;
                               border-radius: 20px; }
            QLabel#attachmentStatus { color: #236b5d; font-size: 12px; font-weight: 700; }
            QLabel#muted, QLabel#keyboardHint { color: #647781; font-size: 12px; }
            QLabel#badge { color: #236b5d; background: #e3f1eb; border-radius: 13px;
                           padding: 6px 12px; font-size: 12px; }
            QLabel#badge[offline="true"] { color: #8c5a23; background: #fff0dc; }
            QLabel#welcomeMark { background: #edf1fc; color: #2b4098; font-size: 32px;
                                 font-weight: 700; border-radius: 24px;
                                 min-width: 88px; max-width: 88px; min-height: 88px; max-height: 88px; }
            QLabel#welcomeTitle { font-size: 24px; font-weight: 600; padding: 12px 0 4px; }
            QLabel#countdown { color: #253a86; background: #edf1fc; border-radius: 7px;
                               padding: 6px 9px; font-weight: 600; }
            QLabel#countdown[urgent="true"] { color: #8c3c16; background: #fff0dc; }
            QLabel#status { color: #647781; font-size: 12px; padding: 0 3px; }
            QStackedWidget#conversation { background: white; border: 1px solid #dce5e8;
                                         border-radius: 16px; }
            QTextEdit#transcript { background: white; color: #182b36; border: none;
                                  padding: 22px; font-size: 15px; selection-background-color: #dfe5fa; }
            QFrame#composerDivider { background: #e7edf1; border: none; }
            QFrame#composer { background: white; border: 1px solid #cad8dc; border-radius: 16px; }
            QTextEdit#prompt { background: white; color: #182b36; border: none;
                              padding: 4px; font-size: 15px; selection-background-color: #dfe5fa; }
            QTextEdit#prompt:disabled { color: #647781; background: white; }
            QPushButton { color: #344e5a; background: white; border: 1px solid #d5e0e4;
                          border-radius: 9px; padding: 8px 13px; min-height: 20px; }
            QPushButton:hover { background: #eef2fc; border-color: #aab8e2; }
            QPushButton:pressed { background: #dfe6fa; }
            QPushButton:focus { border: 1px solid #2b4098; }
            QPushButton:disabled { color: #87969e; background: #f2f5f6; border-color: #e2e8eb; }
            QPushButton#primary { background: #2b4098; border-color: #2b4098; color: white; font-weight: 600; }
            QPushButton#primary:hover { background: #22347e; }
            QPushButton#primary:disabled { background: #e5e9f4; color: #8590b1; border-color: #e5e9f4; }
            QPushButton#suggestion { background: #f7f9fe; padding: 13px; }
            QPushButton#stop { color: #a53f3f; background: #fff5f4; border-color: #edceca; }
            QComboBox { color: #243e49; background: white; border: 1px solid #d5e0e4;
                        border-radius: 8px; padding: 8px 12px; min-height: 20px; }
            QComboBox::drop-down { border: none; width: 28px; }
            QComboBox:disabled { color: #87969e; background: #f2f5f6; }
            QComboBox QAbstractItemView { color: #243e49; background: white;
                                        selection-background-color: #e4eafa;
                                        selection-color: #243986; padding: 6px; }
            QLineEdit { color: #182b36; background: #ffffff; border: 1px solid #d5e0e4;
                        border-radius: 7px; padding: 7px 9px; selection-background-color: #dfe5fa; }
            QLineEdit:focus { border-color: #2b4098; }
            QLineEdit:disabled { color: #84939b; background: #eef1f5; }
            QScrollBar:vertical { background: transparent; width: 9px; margin: 6px 1px; }
            QScrollBar::handle:vertical { background: #c9d5d9; border-radius: 4px; min-height: 30px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            QCheckBox { spacing: 8px; background: transparent; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px;
                                   border: 1px solid #b8c5d3; background: #ffffff; }
            QCheckBox::indicator:hover { border-color: #2b4098; }
            QCheckBox::indicator:checked { background: #2b4098; border-color: #2b4098;
                                           image: url("@CHECK_ICON@"); }
            QCheckBox:disabled { color: #87969e; }
            QCheckBox::indicator:disabled { border-color: #d7dfe7; background: #eef1f5; }
            QToolTip { background: #182b36; color: white; padding: 6px; border: none; }
        """.replace(
        "@CHECK_ICON@",
        (Path(__file__).resolve().parents[1] / "assets" / "check.svg").as_posix(),
    )

    css = themed_css(css)
    if mode == "dark":
        css += """
            QPushButton#primary, QCheckBox::indicator:checked { background:#415fc4; color:white; }
            QPushButton#primary:hover { background:#4d6ed7; }
            QLabel#headerLogo, QLabel#welcomeMark { background:#f3f6ff; }
            QPushButton#primary:disabled { background:#2d3c57; color:#99a9cc; }
            QToolTip { background:#0e1420; color:#e6edf5; border:1px solid #41516a; }
        """
    app.setStyleSheet(css)
    app.setProperty("appliedThemeStyle", css)
    app.setProperty("appliedThemePalette", app.palette())
    for widget in widgets:
        style = widget.property("lightStyle")
        if style:
            widget.setStyleSheet(themed_css(style))
    if mode != previous:
        colors = (
            DARK_COLORS if mode == "dark" else {value: key for key, value in DARK_COLORS.items()}
        )
        for widget in widgets:
            if isinstance(widget, QTextEdit):
                scroll = widget.verticalScrollBar().value()
                # Avoid reformatting editable inputs, which would alter drafts and undo.
                if widget.isReadOnly():
                    _retint_document(widget.document(), colors)
                widget.verticalScrollBar().setValue(scroll)
            widget.update()
