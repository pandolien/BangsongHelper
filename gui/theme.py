"""
화면 색상(테마)
===============

프로그램 전체 색을 '색 이름표' 몇 개로 정하고, 그걸로 화면 꾸미기 규칙(스타일시트)을 만들어요.

- 미리 만든 색 묶음(프리셋): 라이트 · 다크 · 치지직 그린
- 프리셋을 고른 뒤 색을 하나씩 바꿀 수도 있어요. (바꾼 색만 따로 기억해요)
- 저장 위치: data/init.json 의 "theme" 칸
    "theme": {"preset": "라이트", "colors": {"accent": "#ff0000"}}   ← colors 는 프리셋에서 바꾼 색만
"""

import os
import tempfile
from typing import Callable, Optional

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

# 색 이름표: (칸 이름, 화면에 보이는 이름)
LIST_COLOR_KEYS = [
    ("bg", "창 배경"),
    ("card", "상자 배경"),
    ("input", "입력칸 배경"),
    ("text", "글자"),
    ("subtext", "설명 글자"),
    ("border", "테두리"),
    ("accent", "포인트 색 (제목 · 주요 버튼)"),
    ("live", "방송 중"),
    ("good", "정상 (로그인됨)"),
    ("warn", "주의 (로그인 필요 · 오류)"),
    ("off", "꺼짐"),
    ("log_bg", "로그 배경"),
    ("log_text", "로그 글자"),
]

DICT_PRESETS = {
    "라이트": {
        "bg": "#f1f3f5", "card": "#ffffff", "input": "#ffffff", "text": "#1f2937", "subtext": "#6b7280",
        "border": "#d5d9de", "accent": "#00875a", "live": "#e03131", "good": "#2f9e44", "warn": "#e67700",
        "off": "#868e96", "log_bg": "#ffffff", "log_text": "#374151",
    },
    "다크": {
        "bg": "#18191c", "card": "#232428", "input": "#2b2d31", "text": "#e5e7eb", "subtext": "#9ca3af",
        "border": "#3a3c42", "accent": "#4dabf7", "live": "#ff4d4f", "good": "#37b24d", "warn": "#f59f00",
        "off": "#6b7280", "log_bg": "#111214", "log_text": "#c9cdd3",
    },
    "치지직 그린": {
        "bg": "#0e0f12", "card": "#1a1b1f", "input": "#22242a", "text": "#f1f3f5", "subtext": "#8b9099",
        "border": "#2c2e35", "accent": "#00ffa3", "live": "#ff3b5c", "good": "#00d68f", "warn": "#ffb020",
        "off": "#5c616b", "log_bg": "#0a0b0d", "log_text": "#b8bec7",
    },
}
STR_DEFAULT_PRESET = "라이트"


def ThemeColors(dictTheme: Optional[dict]) -> dict:
    """설정의 "theme" 칸 → 실제로 쓸 색 사전. (프리셋 + 바꾼 색)"""
    dictTheme = dictTheme or {}
    dictColors = dict(DICT_PRESETS.get(dictTheme.get("preset"), DICT_PRESETS[STR_DEFAULT_PRESET]))
    for strKey, strColor in (dictTheme.get("colors") or {}).items():
        if strKey in dictColors and QColor(strColor).isValid():
            dictColors[strKey] = strColor
    return dictColors


def _Mix(strColor: str, strBase: str, fRatio: float) -> str:
    """strColor 를 fRatio 만큼 strBase 위에 옅게 칠한 색. (색 막대 배경용)"""
    objA, objB = QColor(strColor), QColor(strBase)
    return QColor(
        round(objA.red() * fRatio + objB.red() * (1 - fRatio)),
        round(objA.green() * fRatio + objB.green() * (1 - fRatio)),
        round(objA.blue() * fRatio + objB.blue() * (1 - fRatio)),
    ).name()


def TextOn(strColor: str) -> str:
    """그 색 위에 올릴 글자 색. 밝은 배경이면 검정, 어두운 배경이면 흰색."""
    objColor = QColor(strColor)
    fLight = 0.299 * objColor.red() + 0.587 * objColor.green() + 0.114 * objColor.blue()
    return "#111111" if fLight > 160 else "#ffffff"


def _ArrowImage(strName: str, strPoints: str, strColor: str) -> str:
    """작은 세모 그림(SVG) 파일을 만들고 경로를 돌려줘요. (숫자 칸 · 고르기 칸의 화살표)

    색을 입히면 Qt 가 화살표를 그려주지 않아서 직접 그림을 만들어 줘야 해요.
    """
    strDir = os.path.join(tempfile.gettempdir(), "chzzkControl_theme")
    strPath = os.path.join(strDir, f"{strName}_{strColor.lstrip('#')}.svg")
    if not os.path.exists(strPath):
        try:
            os.makedirs(strDir, exist_ok=True)
            with open(strPath, "w", encoding="utf-8") as objFile:
                objFile.write('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="5" viewBox="0 0 8 5">'
                              f'<polygon points="{strPoints}" fill="{strColor}"/></svg>')
        except OSError:
            return ""  # 못 만들면 화살표 없이
    return strPath.replace("\\", "/")


def BuildPalette(c: dict) -> QPalette:
    """색 사전 → 기본 색판(팔레트). 스타일시트가 안 닿는 창(방송 도우미 등)의 배경 · 글자도 같은 색으로 칠해요."""
    objPalette = QPalette()
    for eRole, strKey in (
        (QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Base, "input"), (QPalette.ColorRole.AlternateBase, "card"),
        (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.PlaceholderText, "subtext"),
        (QPalette.ColorRole.Button, "input"), (QPalette.ColorRole.ButtonText, "text"),
        (QPalette.ColorRole.ToolTipBase, "card"), (QPalette.ColorRole.ToolTipText, "text"),
        (QPalette.ColorRole.Highlight, "accent"),
    ):
        objPalette.setColor(eRole, QColor(c[strKey]))
    objPalette.setColor(QPalette.ColorRole.HighlightedText, QColor(TextOn(c["accent"])))
    for eRole in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        objPalette.setColor(QPalette.ColorGroup.Disabled, eRole, QColor(c["subtext"]))
    return objPalette


def BuildStyleSheet(c: dict) -> str:
    """색 사전 → 프로그램 전체에 입힐 스타일시트."""
    dictChip = {strState: (c[strState], TextOn(c[strState])) for strState in ("live", "good", "warn", "off")}
    strArrowUp = _ArrowImage("up", "0,5 4,0 8,5", c["subtext"])
    strArrowDown = _ArrowImage("down", "0,0 8,0 4,5", c["subtext"])
    return f"""
        QMainWindow, QDialog, QWidget#Central {{ background: {c["bg"]}; }}
        QWidget {{ color: {c["text"]}; }}
        QToolTip {{ background: {c["card"]}; color: {c["text"]}; border: 1px solid {c["border"]}; }}
        QScrollArea {{ background: transparent; border: none; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QSplitter::handle {{ background: {c["bg"]}; }}
        QSplitter::handle:hover {{ background: {c["accent"]}; }}

        QFrame#Header {{ background: {c["card"]}; border: none; border-bottom: 3px solid {c["accent"]}; }}
        QLabel#HeaderTitle {{ font-size: 12pt; font-weight: bold; }}
        QMenuBar {{ background: {c["card"]}; color: {c["text"]}; }}
        QMenuBar::item:selected {{ background: {_Mix(c["accent"], c["card"], 0.2)}; }}
        QMenu {{ background: {c["card"]}; color: {c["text"]}; border: 1px solid {c["border"]}; }}
        QMenu::item {{ padding: 5px 24px; }}
        QMenu::item:selected {{ background: {c["accent"]}; color: {TextOn(c["accent"])}; }}
        QMenu::separator {{ height: 1px; background: {c["border"]}; margin: 4px 8px; }}
        QStatusBar {{ background: {c["card"]}; border-top: 1px solid {c["border"]}; }}
        QLabel#AppTitle {{ font-size: 14pt; font-weight: bold; color: {c["accent"]}; }}
        QLabel#ColumnTitle {{ font-size: 11pt; font-weight: bold; padding: 2px 8px;
                              border-left: 4px solid {c["accent"]}; }}

        QLabel#Chip {{ border-radius: 11px; padding: 3px 12px; font-weight: bold;
                       background: {c["border"]}; color: {c["text"]}; }}
        QLabel#Chip[state="live"] {{ background: {dictChip["live"][0]}; color: {dictChip["live"][1]}; }}
        QLabel#Chip[state="good"] {{ background: {dictChip["good"][0]}; color: {dictChip["good"][1]}; }}
        QLabel#Chip[state="warn"] {{ background: {dictChip["warn"][0]}; color: {dictChip["warn"][1]}; }}
        QLabel#Chip[state="off"]  {{ background: {dictChip["off"][0]};  color: {dictChip["off"][1]}; }}

        QGroupBox {{ background: {c["card"]}; border: 1px solid {c["border"]}; border-radius: 8px;
                     margin-top: 12px; padding: 12px 8px 8px 8px; font-weight: bold; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c["accent"]}; }}
        QGroupBox QLabel, QGroupBox QCheckBox {{ font-weight: normal; background: transparent; }}
        QLabel#Help {{ color: {c["subtext"]}; font-weight: normal; }}
        QLabel#SubTitle {{ color: {c["accent"]}; font-weight: bold; }}
        QLabel#Value {{ font-weight: bold; }}

        QPushButton {{ background: {c["input"]}; border: 1px solid {c["border"]}; border-radius: 6px;
                       padding: 5px 12px; }}
        QPushButton:hover {{ border-color: {c["accent"]}; }}
        QPushButton:pressed {{ background: {_Mix(c["accent"], c["input"], 0.25)}; }}
        QPushButton:disabled {{ color: {c["subtext"]}; }}
        QPushButton#Primary {{ background: {c["accent"]}; color: {TextOn(c["accent"])}; border: none; font-weight: bold; }}
        QPushButton#Primary:hover {{ background: {_Mix("#ffffff", c["accent"], 0.15)}; }}

        QLineEdit, QComboBox, QSpinBox, QTableWidget {{ background: {c["input"]}; border: 1px solid {c["border"]};
                       border-radius: 5px; padding: 4px; selection-background-color: {c["accent"]};
                       selection-color: {TextOn(c["accent"])}; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {c["accent"]}; }}
        QSpinBox {{ padding-right: 20px; }}
        QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 18px; border: none; }}
        QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border: none; }}
        QSpinBox::up-arrow {{ image: url({strArrowUp}); width: 8px; height: 5px; }}
        QSpinBox::down-arrow, QComboBox::down-arrow {{ image: url({strArrowDown}); width: 8px; height: 5px; }}
        QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 18px; border: none; }}
        QComboBox QAbstractItemView {{ background: {c["input"]}; color: {c["text"]}; }}
        QTableWidget {{ gridline-color: {c["border"]}; }}
        QHeaderView::section {{ background: {c["card"]}; color: {c["text"]}; border: none;
                                border-bottom: 1px solid {c["border"]}; padding: 4px; font-weight: bold; }}
        QTabWidget::pane {{ border: 1px solid {c["border"]}; background: {c["card"]}; }}
        QTabBar::tab {{ background: {c["bg"]}; padding: 6px 14px; border: 1px solid {c["border"]}; }}
        QTabBar::tab:selected {{ background: {c["card"]}; color: {c["accent"]}; font-weight: bold; }}

        QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {c["subtext"]}; border-radius: 3px;
                                background: {c["input"]}; }}
        QCheckBox::indicator:checked {{ background: {c["accent"]}; border-color: {c["accent"]}; }}
        QCheckBox::indicator:disabled {{ background: {c["card"]}; border-color: {c["border"]}; }}
        QCheckBox:disabled, QLabel:disabled {{ color: {c["subtext"]}; }}

        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
        QScrollBar::handle {{ background: {c["border"]}; border-radius: 5px; min-height: 24px; min-width: 24px; }}
        QScrollBar::handle:hover {{ background: {c["subtext"]}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

        QTextBrowser#Chat {{ background: {c["card"]}; color: {c["text"]}; border: 1px solid {c["border"]};
                              border-radius: 6px; }}
        QPlainTextEdit#Log {{ background: {c["log_bg"]}; color: {c["log_text"]}; border: 1px solid {c["border"]};
                              border-radius: 6px; }}

        QWidget#LoginBar {{ border-radius: 6px; }}
        QWidget#LoginBar[state="on"]   {{ background: {_Mix(c["good"], c["card"], 0.15)}; border: 1px solid {c["good"]}; }}
        QWidget#LoginBar[state="off"]  {{ background: {_Mix(c["warn"], c["card"], 0.15)}; border: 1px solid {c["warn"]}; }}
        QWidget#LoginBar[state="none"] {{ background: {c["card"]}; border: 1px solid {c["border"]}; }}
        QWidget#PendingBar {{ background: {_Mix(c["accent"], c["card"], 0.12)}; border: 1px solid {c["accent"]};
                              border-radius: 6px; }}
        QWidget#LoginBar QLabel, QWidget#PendingBar QLabel {{ background: transparent; border: none; }}
    """


class ThemeDialog(QDialog):
    """색상 고르기 창. 고르는 동안 fnPreview 로 바로바로 화면에 입혀 봐요."""

    def __init__(self, dictTheme: Optional[dict], fnPreview: Callable[[dict], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("색상 설정")
        self.fnPreview = fnPreview
        dictTheme = dictTheme or {}
        self.strPreset = dictTheme.get("preset") if dictTheme.get("preset") in DICT_PRESETS else STR_DEFAULT_PRESET
        self.dictOverrides = {k: v for k, v in (dictTheme.get("colors") or {}).items() if QColor(v).isValid()}

        objLayout = QVBoxLayout(self)
        self.cmbPreset = QComboBox()
        self.cmbPreset.addItems(list(DICT_PRESETS))
        self.cmbPreset.setCurrentText(self.strPreset)
        self.cmbPreset.currentTextChanged.connect(self._OnPresetChanged)
        objPresetRow = QHBoxLayout()
        objPresetRow.addWidget(QLabel("기본 색 묶음"))
        objPresetRow.addWidget(self.cmbPreset, 1)
        objLayout.addLayout(objPresetRow)

        lblHelp = QLabel("색 버튼을 눌러 하나씩 바꿀 수 있어요. 바꾸는 즉시 화면에 보여요.")
        lblHelp.setObjectName("Help")
        objLayout.addWidget(lblHelp)

        objForm = QFormLayout()
        self.dictButtons = {}
        for strKey, strLabel in LIST_COLOR_KEYS:
            btnColor = QPushButton()
            btnColor.setMinimumWidth(140)
            btnColor.clicked.connect(lambda _=False, k=strKey: self._OnPickColor(k))
            objForm.addRow(strLabel, btnColor)
            self.dictButtons[strKey] = btnColor
        objLayout.addLayout(objForm)

        objButtonRow = QHBoxLayout()
        btnReset = QPushButton("바꾼 색 지우기")
        btnReset.setToolTip("하나씩 바꾼 색을 지우고 고른 색 묶음 그대로 돌아가요.")
        btnReset.clicked.connect(self._OnReset)
        btnCancel = QPushButton("취소")
        btnCancel.clicked.connect(self.reject)
        btnSave = QPushButton("저장")
        btnSave.setObjectName("Primary")
        btnSave.clicked.connect(self.accept)
        objButtonRow.addWidget(btnReset)
        objButtonRow.addStretch()
        objButtonRow.addWidget(btnCancel)
        objButtonRow.addWidget(btnSave)
        objLayout.addLayout(objButtonRow)

        self._Refresh()

    def GetTheme(self) -> dict:
        """설정에 저장할 "theme" 칸."""
        return {"preset": self.strPreset, "colors": dict(self.dictOverrides)}

    def _Refresh(self) -> None:
        dictColors = ThemeColors(self.GetTheme())
        for strKey, btnColor in self.dictButtons.items():
            strColor = dictColors[strKey]
            strMark = "  (바꿈)" if strKey in self.dictOverrides else ""
            btnColor.setText(strColor + strMark)
            # 버튼 자체를 그 색으로 칠해요. (스타일시트보다 버튼 개별 지정이 우선)
            btnColor.setStyleSheet(f"background: {strColor}; color: {TextOn(strColor)}; "
                                   f"border: 1px solid #888888; border-radius: 6px; padding: 5px 12px;")
        self.fnPreview(dictColors)

    def _OnPresetChanged(self, strPreset: str) -> None:
        self.strPreset = strPreset
        self.dictOverrides.clear()  # 다른 묶음으로 바꾸면 하나씩 바꾼 색은 지워요.
        self._Refresh()

    def _OnPickColor(self, strKey: str) -> None:
        objNow = QColor(ThemeColors(self.GetTheme())[strKey])
        objColor = QColorDialog.getColor(objNow, self, "색 고르기")
        if objColor.isValid():
            self.dictOverrides[strKey] = objColor.name()
            self._Refresh()

    def _OnReset(self) -> None:
        self.dictOverrides.clear()
        self._Refresh()
