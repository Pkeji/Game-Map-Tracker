"""Theme constants for the island overlay UI."""

COLLAPSED_W = 280
COLLAPSED_H = 44
EXPANDED_W = 820
EXPANDED_H = 500
TOP_MARGIN = 0
ANIMATION_MS = 220
RECENT_ROUTES_MAX_HEIGHT = 100
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
QPushButton:checked {{
    background: {ACCENT};
    color: white;
}}
QPushButton#WindowControl {{
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    font-size: 12px;
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
QPushButton#AlertAction,
QPushButton#TopSidebarToggle {{
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
