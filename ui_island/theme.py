"""Theme constants for the island overlay UI."""

COLLAPSED_W = 280
COLLAPSED_H = 44
EXPANDED_W = 820
EXPANDED_H = 500
TOP_MARGIN = 0
ANIMATION_MS = 220
RECENT_ROUTES_MAX_HEIGHT = 100
ROUTES_LIST_MIN_HEIGHT = 160
SIDEBAR_RAIL_WIDTH = 34
WINDOW_MIN_W = 420
WINDOW_MIN_H = 240
SIDEBAR_MIN_EXPANDED_W = 760
SIDEBAR_MIN_EXPANDED_H = 420
COMPACT_ALERT_HEIGHT = 170
TRACK_JUMP_DETECT_THRESHOLD = 220
TRACK_JUMP_DETECT_LIMIT = 4
RECENT_ROUTE_ITEM_HEIGHT = 30
RECENT_ROUTE_CARD_PADDING = 28

BG = "rgba(18, 18, 20, 235)"
BG_HOVER = "rgba(28, 28, 30, 245)"
FG = "#f2f2f7"
FG_DIM = "#8e8e93"
ACCENT = "#0a84ff"
ACCENT_SOFT = "rgba(10, 132, 255, 0.16)"
BORDER = "rgba(255, 255, 255, 0.08)"
DOT_LOCKED = "#30d158"
DOT_INERTIAL = "#ffd60a"
DOT_LOST = "#ff453a"
DOT_SEARCHING = "#8e8e93"
RADIUS = 20

TOOLTIP_QSS = f"""
QToolTip {{
    background: rgba(28, 28, 30, 245);
    color: {FG};
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 8px;
    padding: 5px 8px;
    margin: 0px;
    font-size: 11px;
}}
"""


def ensure_tooltip_style() -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return

    app = QApplication.instance()
    if app is None:
        return

    marker = "_game_map_tooltip_qss_applied"
    if app.property(marker):
        return

    base = app.styleSheet().rstrip()
    if TOOLTIP_QSS not in base:
        app.setStyleSheet(f"{base}\n{TOOLTIP_QSS}".strip())
    app.setProperty(marker, True)

ISLAND_QSS = f"""
QWidget#IslandRoot {{
    background: {BG};
    border-radius: {RADIUS}px;
}}
QWidget#IslandRoot:hover {{
    background: {BG_HOVER};
}}
QLabel {{
    color: {FG};
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}}
QLabel#CoordLabel {{
    font-size: 13px;
    font-weight: 600;
}}
QLabel#StatLabel {{
    font-size: 11px;
    color: {FG_DIM};
}}
QLabel#TitleLabel {{
    font-size: 12px;
    color: {FG_DIM};
    font-weight: 600;
}}
QLabel#EmptyHint {{
    font-size: 11px;
    color: {FG_DIM};
}}
QLabel#MapHint {{
    font-size: 11px;
    color: {FG_DIM};
}}
QLabel#StateHint {{
    font-size: 11px;
    color: {FG_DIM};
    padding: 4px 8px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#AlertCard {{
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#AlertMessage {{
    font-size: 18px;
    font-weight: 700;
    color: {FG};
}}
QLabel#SidebarRailLabel {{
    font-size: 10px;
    color: {FG_DIM};
    font-weight: 600;
}}
QFrame#PanelCard {{
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#SidebarRail {{
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QWidget#RoutesScrollInner {{
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QWidget#RouteSectionBody {{
    background: transparent;
}}
QPushButton {{
    background: rgba(255, 255, 255, 0.12);
    color: {FG};
    border: none;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 11px;
}}
QPushButton:hover {{
    background: rgba(255, 255, 255, 0.20);
}}
QPushButton:pressed {{
    background: rgba(255, 255, 255, 0.28);
}}
QPushButton[headerButton="true"] {{
    background: rgba(255, 255, 255, 0.12);
    color: {FG};
    border: 1px solid transparent;
    min-height: 28px;
    max-height: 28px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
    border-radius: 8px;
}}
QPushButton[headerButton="true"]:hover {{
    background: rgba(255, 255, 255, 0.18);
}}
QPushButton[headerButton="true"]:pressed {{
    background: rgba(255, 255, 255, 0.28);
}}
QPushButton[headerButton="true"]:disabled {{
    background: rgba(255, 255, 255, 0.06);
    color: rgba(242, 242, 247, 0.45);
    border-color: rgba(255, 255, 255, 0.04);
}}
QPushButton[headerButton="true"][iconRole="lock"]:checked {{
    background: {ACCENT};
    color: white;
    border-color: {ACCENT};
}}
QPushButton[headerButton="true"][iconRole="lock"]:checked:hover {{
    background: #2590ff;
    border-color: #2590ff;
}}
QPushButton[headerButton="true"][iconRole="lock"]:checked:pressed {{
    background: #0077e6;
    border-color: #0077e6;
}}
QPushButton#HeaderWindowButton,
QPushButton#HeaderActionButton,
QPushButton#TopSidebarToggle {{
    min-height: 28px;
    max-height: 28px;
    border-radius: 8px;
}}
QPushButton#WindowControl {{
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
    padding: 0px;
    font-size: 16px;
}}
QPushButton#HeaderWindowButton {{
    min-width: 28px;
    max-width: 28px;
    padding: 0px;
    font-weight: 700;
}}
QPushButton#HeaderActionButton,
QPushButton#TopSidebarToggle {{
    padding: 0px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#HeaderWindowButton[iconRole="settings"] {{
    font-size: 14px;
}}
QPushButton#HeaderWindowButton[iconRole="minimize"] {{
    font-size: 16px;
}}
QPushButton#HeaderWindowButton[iconRole="maximize"] {{
    font-size: 15px;
}}
QPushButton#HeaderWindowButton[iconRole="close"] {{
    font-size: 18px;
}}
QPushButton#HeaderActionButton[headerIconOnly="true"],
QPushButton#TopSidebarToggle[headerIconOnly="true"] {{
    min-width: 34px;
    max-width: 34px;
    padding: 0px;
    font-size: 13px;
    font-weight: 700;
    text-align: center;
}}
QPushButton[iconRole="locate"][headerIconOnly="true"] {{
    font-size: 14px;
    font-weight: 700;
}}
QPushButton[iconRole="reset"][headerIconOnly="true"] {{
    font-size: 14px;
    font-weight: 700;
}}
QPushButton[iconRole="sidebar"][headerIconOnly="true"] {{
    color: #ffd60a;
    font-size: 13px;
    font-weight: 800;
}}
QPushButton[iconRole="terminate"][headerIconOnly="true"] {{
    color: {DOT_LOST};
    font-size: 12px;
    font-weight: 800;
}}
QPushButton#SidebarToggle {{
    min-width: 24px;
    padding: 8px 2px;
    font-size: 12px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.05);
}}
QPushButton#SidebarToggle:hover {{
    background: rgba(255, 255, 255, 0.12);
}}
QPushButton#AlertAction {{
    padding: 6px 12px;
    font-size: 11px;
}}
QToolButton#SectionHeader {{
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid {BORDER};
    border-radius: 10px;
    color: {FG};
    font-size: 10px;
    font-weight: 500;
    padding: 5px 8px;
    text-align: center;
}}
QToolButton#SectionHeader:hover {{
    background: rgba(255, 255, 255, 0.14);
}}
QLineEdit {{
    background: rgba(255, 255, 255, 0.08);
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 7px 10px;
    font-size: 11px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border: 1px solid rgba(10, 132, 255, 0.65);
    background: {ACCENT_SOFT};
}}
QCheckBox {{
    color: {FG};
    background: transparent;
    border-radius: 8px;
    font-size: 11px;
    spacing: 6px;
    padding: 4px 6px;
}}
QCheckBox:hover {{
    background: rgba(255, 255, 255, 0.08);
}}
QCheckBox:checked {{
    background: rgba(255, 255, 255, 0.12);
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.15);
    border: 1px solid rgba(255, 255, 255, 0.25);
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.35);
    border-radius: 3px;
}}
"""
