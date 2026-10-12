"""
알림 소리 설정 창
=================

후원 소리 · 구독 소리를 각각 크기(0~100%)와 음 높이(낮게 · 보통 · 높게)로 맞춰요.
- 바꾸는 즉시 적용되고, 슬라이더를 놓거나 높이를 고르면 바로 들려줘요.
- 켜고 끄기는 후원 목록 위의 체크박스에서 해요.
"""

from typing import Callable, Dict, Optional

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from gui.alarm import NormalizePitch, NormalizeVolume

LIST_PITCH_LABELS = [("낮게", "low"), ("보통", "mid"), ("높게", "high")]
# 종류 → (칸 제목, 설명)
LIST_KINDS = [("donation", "후원 소리", "도 → 미 (두 음)  ·  영상 · 채팅 후원, 유튜브 슈퍼챗"),
              ("subscription", "구독 소리", "솔 → 도 → 미 (세 음)  ·  구독")]


class AlarmSettingsDialog(QDialog):
    def __init__(self, fnGetStyle: Callable[[str], tuple], fnApply: Callable[[str, int, str, bool], None],
                 fnPreview: Callable[[str], None], objParent: Optional[QWidget] = None):
        """fnGetStyle(종류) → (크기, 높이) / fnApply(종류, 크기, 높이, 저장할지) / fnPreview(종류) → 들려주기"""
        super().__init__(objParent)
        self.setWindowTitle("알림 소리 설정")
        self.fnGetStyle, self.fnApply, self.fnPreview = fnGetStyle, fnApply, fnPreview
        self.dictSliders: Dict[str, QSlider] = {}
        self.dictCombos: Dict[str, QComboBox] = {}
        self.dictLabels: Dict[str, QLabel] = {}

        objLayout = QVBoxLayout(self)
        lblHelp = QLabel("크기와 음 높이를 후원 · 구독 따로 맞춰요. 바꾸면 바로 들려줘요.\n"
                         "켜고 끄기는 후원 목록 위의 [후원 소리] [구독 소리] 체크박스에서 해요.")
        lblHelp.setObjectName("Help")
        lblHelp.setWordWrap(True)
        objLayout.addWidget(lblHelp)

        for strKind, strTitle, strDesc in LIST_KINDS:
            objBox = QGroupBox(strTitle)
            objBoxLayout = QVBoxLayout(objBox)
            lblDesc = QLabel(strDesc)
            lblDesc.setObjectName("Help")
            objBoxLayout.addWidget(lblDesc)

            objSliderRow = QHBoxLayout()
            objSliderRow.addWidget(QLabel("크기"))
            sldVolume = QSlider(Qt.Orientation.Horizontal)
            sldVolume.setRange(0, 100)
            sldVolume.setSingleStep(5)
            sldVolume.setPageStep(10)
            lblVolume = QLabel()
            lblVolume.setMinimumWidth(64)
            objSliderRow.addWidget(sldVolume, 1)
            objSliderRow.addWidget(lblVolume)
            objBoxLayout.addLayout(objSliderRow)

            objPitchRow = QHBoxLayout()
            objPitchRow.addWidget(QLabel("음 높이"))
            cmbPitch = QComboBox()
            for strLabel, strValue in LIST_PITCH_LABELS:
                cmbPitch.addItem(strLabel, strValue)
            objPitchRow.addWidget(cmbPitch)
            objPitchRow.addStretch()
            btnPlay = QPushButton("▶ 들어 보기")
            objPitchRow.addWidget(btnPlay)
            objBoxLayout.addLayout(objPitchRow)
            objLayout.addWidget(objBox)

            self.dictSliders[strKind], self.dictCombos[strKind], self.dictLabels[strKind] = sldVolume, cmbPitch, lblVolume
            sldVolume.valueChanged.connect(lambda nValue, k=strKind: self._OnVolumeChanged(k, nValue))
            sldVolume.sliderReleased.connect(lambda k=strKind: self._Commit(k))
            cmbPitch.currentIndexChanged.connect(lambda _n, k=strKind: self._Commit(k))
            btnPlay.clicked.connect(lambda _=False, k=strKind: self.fnPreview(k))

        btnClose = QPushButton("닫기")
        btnClose.setObjectName("Primary")
        btnClose.clicked.connect(self.accept)
        objCloseRow = QHBoxLayout()
        objCloseRow.addStretch()
        objCloseRow.addWidget(btnClose)
        objLayout.addLayout(objCloseRow)
        self.Reload()

    def Reload(self) -> None:
        """지금 설정 값을 화면에 보여줘요. (다시 열 때마다)"""
        for strKind in self.dictSliders:
            nVolume, strPitch = self.fnGetStyle(strKind)
            for objWidget in (self.dictSliders[strKind], self.dictCombos[strKind]):
                objWidget.blockSignals(True)
            self.dictSliders[strKind].setValue(NormalizeVolume(nVolume))
            self.dictCombos[strKind].setCurrentIndex(max(0, self.dictCombos[strKind].findData(NormalizePitch(strPitch))))
            for objWidget in (self.dictSliders[strKind], self.dictCombos[strKind]):
                objWidget.blockSignals(False)
            self._ShowVolume(strKind)

    def _ShowVolume(self, strKind: str) -> None:
        nValue = self.dictSliders[strKind].value()
        self.dictLabels[strKind].setText("무음" if nValue == 0 else f"{nValue}%")

    def _Current(self, strKind: str) -> tuple:
        return self.dictSliders[strKind].value(), self.dictCombos[strKind].currentData()

    def _OnVolumeChanged(self, strKind: str, _nValue: int) -> None:
        self._ShowVolume(strKind)
        nVolume, strPitch = self._Current(strKind)
        if self.dictSliders[strKind].isSliderDown():
            self.fnApply(strKind, nVolume, strPitch, False)   # 끄는 중에는 적용만 (놓을 때 저장 + 들려줘요)
        else:
            self._Commit(strKind)                              # 키보드 · 마우스 휠로 바꿀 때

    def _Commit(self, strKind: str) -> None:
        nVolume, strPitch = self._Current(strKind)
        self.fnApply(strKind, nVolume, strPitch, True)
        self.fnPreview(strKind)
