"""
미션 창 (미션 받기 + 타이머)
============================

치지직 공식 API 는 '미션 후원' 을 따로 알려주지 않아요. (후원 종류는 채팅 / 영상 뿐)
그래서 들어오는 후원에서 미션을 골라내서, 이 창에서 타이머와 함께 관리해요.

미션이 등록되는 방법
    1) 후원 메시지가 정한 단어(기본: "미션")로 시작하면 → 자동 등록   예) "미션: 노데스로 보스 잡기"
    2) 후원 종류가 MISSION 이면 → 자동 등록 (치지직이 보내준다면)
    3) 후원 목록에서 [미션으로 만들기] / 이 창에서 [미션 추가]

타이머
    - [시작] 을 누르면 제한 시간이 줄어들어요. 일시정지 · 재개, +1분 / -1분 가능
    - 시간이 끝나면 '시간 초과' 로 빨갛게 바뀌고 소리로 알려줘요. (성공 / 실패는 직접 눌러요)
    - 맨 위에 진행 중인 미션의 큰 타이머가 나와요.
    - OBS 용 타이머 파일(data/mission_timer.txt)을 1초마다 써요.
      OBS → 소스 추가 → 텍스트(GDI+) → '파일에서 읽기' 체크 → 이 파일을 고르면 방송 화면에 타이머가 나와요.

저장
    미션은 data/missions.json 에 저장돼서 프로그램을 다시 켜도 남아요. (진행 중이던 타이머도 이어져요)
"""

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app_paths import STR_DATA_DIR
from chzzk import ChzzkDonationMessage, RE_EMOJI_PLACEHOLDER
from gui.bg_task import RunTask
from gui.chat_hub import ChatHub

STR_MISSION_FILE = os.path.join(STR_DATA_DIR, "missions.json")
STR_TIMER_FILE = os.path.join(STR_DATA_DIR, "mission_timer.txt")
N_MAX_SAVED_MISSIONS = 1000

# 상태 → (화면 글자, 색)
DICT_MISSION_STATE = {
    "wait": ("대기", "#e67700"),
    "run": ("진행 중", "#1971c2"),
    "pause": ("일시정지", "#868e96"),
    "timeout": ("시간 초과", "#e03131"),
    "success": ("성공", "#2f9e44"),
    "fail": ("실패", "#c92a2a"),
    "reject": ("거절", "#868e96"),
}
SET_FINISHED_STATES = {"success", "fail", "reject"}   # 끝난 미션

# 설정 기본값 (data/init.json 의 app 칸에 저장돼요)
DICT_DEFAULT_MISSION_SETTINGS = {
    "mission_default_min": 10,          # 기본 제한 시간(분)
    "mission_prefix_enabled": True,     # 메시지가 정한 단어로 시작하면 자동 등록
    "mission_prefix": "미션",
    "mission_sound": True,              # 시간이 끝나면 소리
    "mission_timer_file": True,         # OBS 용 타이머 파일 쓰기
    "mission_chat_announce": False,     # 시작 · 결과를 채팅으로 알리기
}

N_COL_TIME, N_COL_NICK, N_COL_AMOUNT, N_COL_TEXT, N_COL_LEFT, N_COL_STATE = range(6)


def FormatSec(fSec: float) -> str:
    """남은 초 → '05:23' (1시간 넘으면 '1:05:23')"""
    nSec = max(0, int(fSec + 0.999))  # 0.2초 남았을 때 00:00 이 아니라 00:01 로 보이게 올림
    nHour, nRest = divmod(nSec, 3600)
    return f"{nHour}:{nRest // 60:02d}:{nRest % 60:02d}" if nHour else f"{nRest // 60:02d}:{nRest % 60:02d}"


@dataclass
class MissionRecord:
    """미션 하나."""

    dtTime: datetime
    strNickname: str
    nAmount: int
    strText: str
    nDurationSec: int            # 처음 정한 제한 시간
    strState: str = "wait"
    fEndAt: float = 0.0          # 진행 중일 때: 끝나는 시각 (time.time() 기준)
    fRemainSec: float = -1.0     # 대기 · 일시정지일 때: 남은 시간
    bTest: bool = False          # 테스트 미션 (저장 · 채팅 알림 안 함)

    def __post_init__(self):
        if self.fRemainSec < 0:
            self.fRemainSec = float(self.nDurationSec)

    @property
    def fLeftSec(self) -> float:
        if self.strState == "run":
            return max(0.0, self.fEndAt - time.time())
        if self.strState == "timeout":
            return 0.0
        return self.fRemainSec

    @property
    def bFinished(self) -> bool:
        return self.strState in SET_FINISHED_STATES

    def Start(self) -> None:
        if self.fRemainSec <= 0:
            self.fRemainSec = float(self.nDurationSec)  # 시간이 다 된 미션을 다시 시작하면 처음부터
        self.fEndAt = time.time() + self.fRemainSec
        self.strState = "run"

    def Pause(self) -> None:
        self.fRemainSec = self.fLeftSec
        self.strState = "pause"

    def AddSec(self, nSec: int) -> None:
        if self.strState == "run":
            self.fEndAt = max(time.time(), self.fEndAt + nSec)
        elif self.strState == "timeout" and nSec > 0:
            self.fRemainSec = float(nSec)  # 시간 초과된 미션에 시간을 더 주면 → 다시 진행
            self.Start()
        else:
            self.fRemainSec = max(0.0, self.fRemainSec + nSec)

    def Finish(self, strState: str) -> None:
        self.fRemainSec = self.fLeftSec
        self.strState = strState

    def ToDict(self) -> dict:
        return {"time": self.dtTime.isoformat(timespec="seconds"), "nickname": self.strNickname, "amount": self.nAmount,
                "text": self.strText, "duration": self.nDurationSec, "state": self.strState,
                "end_at": self.fEndAt, "remain": self.fRemainSec}

    @staticmethod
    def FromDict(dictItem: dict) -> "MissionRecord":
        strState = dictItem.get("state", "wait")
        return MissionRecord(
            dtTime=datetime.fromisoformat(dictItem["time"]),
            strNickname=str(dictItem.get("nickname", "")),
            nAmount=int(dictItem.get("amount") or 0),
            strText=str(dictItem.get("text", "")),
            nDurationSec=int(dictItem.get("duration") or 600),
            strState=strState if strState in DICT_MISSION_STATE else "wait",
            fEndAt=float(dictItem.get("end_at") or 0),
            fRemainSec=float(dictItem.get("remain") if dictItem.get("remain") is not None else -1),
        )


class _AddMissionDialog(QDialog):
    """[미션 추가] 창: 닉네임 · 금액 · 내용 · 제한 시간."""

    def __init__(self, nDefaultMin: int, objParent: Optional[QWidget] = None):
        super().__init__(objParent)
        self.setWindowTitle("미션 추가")
        objForm = QFormLayout(self)
        self.editNick = QLineEdit()
        self.editNick.setPlaceholderText("후원자 닉네임 (비워도 됨)")
        self.spinAmount = QSpinBox()
        self.spinAmount.setRange(0, 100_000_000)
        self.spinAmount.setSingleStep(1000)
        self.spinAmount.setSuffix(" 원")
        self.editText = QLineEdit()
        self.editText.setPlaceholderText("미션 내용 (예: 노데스로 보스 잡기)")
        self.spinMin = QSpinBox()
        self.spinMin.setRange(1, 600)
        self.spinMin.setValue(nDefaultMin)
        self.spinMin.setSuffix(" 분")
        objForm.addRow("닉네임", self.editNick)
        objForm.addRow("금액", self.spinAmount)
        objForm.addRow("미션 내용", self.editText)
        objForm.addRow("제한 시간", self.spinMin)
        objButtons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        objButtons.accepted.connect(self._OnOk)
        objButtons.rejected.connect(self.reject)
        objForm.addRow(objButtons)

    def _OnOk(self) -> None:
        if not self.editText.text().strip():
            QMessageBox.information(self, "안내", "미션 내용을 입력해 주세요.")
            return
        self.accept()


class MissionWindow(QWidget):
    """미션 창."""

    sigActiveChanged = Signal(int)  # 끝나지 않은 미션 수 (메인 창 버튼 숫자용)
    sigTimerText = Signal(str)      # 진행 중인 미션의 짧은 타이머 글자 (후원 · 미션 창 맨 위에 보여줘요. 없으면 "")

    def __init__(self, objHub: ChatHub, fnLog: Optional[Callable[[str], None]] = None,
                 dictApp: Optional[dict] = None, fnSaveConfig: Optional[Callable[[], None]] = None,
                 objParent: Optional[QWidget] = None,
                 strSavePath: str = STR_MISSION_FILE, strTimerPath: str = STR_TIMER_FILE):
        super().__init__(objParent, Qt.WindowType.Window)
        self.setWindowTitle("치지직 미션")
        self.resize(760, 640)

        self.objHub = objHub
        self.bManageHub = True  # 따로 뜨는 창이면 열려 있는 동안 채팅 연결을 붙잡아요.
        self.strLastBarText: Optional[str] = None
        self.fnLog = fnLog or (lambda strMessage: None)
        self.dictApp = dictApp if dictApp is not None else {}
        for strKey, objValue in DICT_DEFAULT_MISSION_SETTINGS.items():
            self.dictApp.setdefault(strKey, objValue)
        self.fnSaveConfig = fnSaveConfig or (lambda: None)
        self.strSavePath = strSavePath
        self.strTimerPath = strTimerPath
        self.listMissions: List[MissionRecord] = []
        self.listTasks = []
        self.strLastTimerText: Optional[str] = None

        self._BuildUi()
        self._LoadMissions()
        self.objHub.sigDonation.connect(self._OnDonation)

        # 1초마다 타이머를 고쳐요.
        self.objTickTimer = QTimer(self)
        self.objTickTimer.timeout.connect(self._OnTick)
        self.objTickTimer.start(1000)
        self._OnTick()

    # ===================================================================
    # 화면
    # ===================================================================
    def _BuildUi(self) -> None:
        objLayout = QVBoxLayout(self)
        objLayout.setContentsMargins(8, 8, 8, 8)

        # --- 맨 위: 큰 타이머 ---
        objTimerBox = QWidget()
        self.wgtTimerBox = objTimerBox  # 방송 도우미 창에선 맨 위 타이머 줄과 겹쳐서 숨겨요.
        objTimerBox.setObjectName("BigTimer")
        objTimerBox.setStyleSheet("QWidget#BigTimer { background: #f1f3f5; border: 1px solid #dee2e6; border-radius: 8px; }"
                                  "QWidget#BigTimer QLabel { background: transparent; border: none; }")
        objTimerLayout = QHBoxLayout(objTimerBox)
        self.lblBigTimer = QLabel("--:--")
        objFont = QFont(self.font())
        objFont.setPointSize(30)
        objFont.setBold(True)
        self.lblBigTimer.setFont(objFont)
        self.lblBigTimer.setMinimumWidth(170)
        self.lblBigTimer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lblBigMission = QLabel("진행 중인 미션 없음")
        self.lblBigMission.setWordWrap(True)
        objTimerLayout.addWidget(self.lblBigTimer)
        objTimerLayout.addWidget(self.lblBigMission, 1)
        objLayout.addWidget(objTimerBox)

        # --- 설정 ---
        objSetBox = QGroupBox("설정")
        self.grpSettings = objSetBox    # 방송 도우미 창에선 [설정 열기] 버튼으로 접고 펴요.
        objSetLayout = QVBoxLayout(objSetBox)
        objRow1 = QHBoxLayout()
        objRow1.addWidget(QLabel("기본 제한 시간"))
        self.spinDefaultMin = QSpinBox()
        self.spinDefaultMin.setRange(1, 600)
        self.spinDefaultMin.setSuffix(" 분")
        self.spinDefaultMin.setValue(int(self.dictApp["mission_default_min"]))
        self.spinDefaultMin.valueChanged.connect(lambda nValue: self._SetSetting("mission_default_min", nValue))
        objRow1.addWidget(self.spinDefaultMin)
        self.chkSound = QCheckBox("시간이 끝나면 소리")
        self.chkSound.setChecked(bool(self.dictApp["mission_sound"]))
        self.chkSound.toggled.connect(lambda bValue: self._SetSetting("mission_sound", bValue))
        objRow1.addWidget(self.chkSound)
        self.chkChat = QCheckBox("시작 · 결과를 채팅으로 알리기")
        self.chkChat.setChecked(bool(self.dictApp["mission_chat_announce"]))
        self.chkChat.toggled.connect(lambda bValue: self._SetSetting("mission_chat_announce", bValue))
        objRow1.addWidget(self.chkChat)
        objRow1.addStretch()
        objSetLayout.addLayout(objRow1)

        objRow2 = QHBoxLayout()
        self.chkPrefix = QCheckBox("후원 메시지가")
        self.chkPrefix.setChecked(bool(self.dictApp["mission_prefix_enabled"]))
        self.chkPrefix.toggled.connect(lambda bValue: self._SetSetting("mission_prefix_enabled", bValue))
        self.editPrefix = QLineEdit(str(self.dictApp["mission_prefix"]))
        self.editPrefix.setMaximumWidth(90)
        self.editPrefix.editingFinished.connect(lambda: self._SetSetting("mission_prefix", self.editPrefix.text().strip()))
        objRow2.addWidget(self.chkPrefix)
        objRow2.addWidget(self.editPrefix)
        objRow2.addWidget(QLabel("(으)로 시작하면 자동으로 미션 등록  (미션 종류 후원은 항상 등록)"))
        objRow2.addStretch()
        objSetLayout.addLayout(objRow2)

        objRow3 = QHBoxLayout()
        self.chkTimerFile = QCheckBox("OBS 용 타이머 파일 쓰기")
        self.chkTimerFile.setChecked(bool(self.dictApp["mission_timer_file"]))
        self.chkTimerFile.toggled.connect(self._OnTimerFileToggled)
        lblTimerPath = QLabel(self.strTimerPath)
        self.lblTimerPath = lblTimerPath
        lblTimerPath.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lblTimerPath.setStyleSheet("color: #6b7280;")
        btnCopyPath = QPushButton("경로 복사")
        btnCopyPath.setToolTip("OBS → 텍스트(GDI+) → '파일에서 읽기' 에 이 경로를 넣으면 방송 화면에 타이머가 나와요.")
        btnCopyPath.clicked.connect(lambda: QApplication.clipboard().setText(self.strTimerPath))
        objRow3.addWidget(self.chkTimerFile)
        objRow3.addWidget(lblTimerPath, 1)
        objRow3.addWidget(btnCopyPath)
        objSetLayout.addLayout(objRow3)
        objLayout.addWidget(objSetBox)

        # --- 표 ---
        objFilterRow = QHBoxLayout()
        self.lblSummary = QLabel()
        self.lblSummary.setStyleSheet("font-weight: bold;")
        self.chkHideFinished = QCheckBox("끝난 미션 숨기기")
        self.chkHideFinished.toggled.connect(self._ApplyFilter)
        objFilterRow.addWidget(self.lblSummary, 1)
        objFilterRow.addWidget(self.chkHideFinished)
        self.btnToggleSettings = QPushButton("설정 열기")
        self.btnToggleSettings.setToolTip("기본 제한 시간 · 자동 등록 단어 · OBS 타이머 파일 · 채팅 알림")
        self.btnToggleSettings.clicked.connect(self._ToggleSettings)
        self.btnToggleSettings.hide()  # 방송 도우미 창(작게 보기)에서만 보여요.
        objFilterRow.addWidget(self.btnToggleSettings)
        objLayout.addLayout(objFilterRow)

        self.tblMissions = QTableWidget(0, 6)
        self.tblMissions.setHorizontalHeaderLabels(["시간", "닉네임", "금액", "미션 내용", "남은 시간", "상태"])
        self.tblMissions.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tblMissions.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tblMissions.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tblMissions.verticalHeader().setVisible(False)
        objHeader = self.tblMissions.horizontalHeader()
        for nCol in (N_COL_TIME, N_COL_NICK, N_COL_AMOUNT, N_COL_LEFT, N_COL_STATE):
            objHeader.setSectionResizeMode(nCol, QHeaderView.ResizeMode.ResizeToContents)
        objHeader.setSectionResizeMode(N_COL_TEXT, QHeaderView.ResizeMode.Stretch)
        self.tblMissions.cellDoubleClicked.connect(lambda nRow, _nCol: self._ToggleRun([nRow]))
        self.tblMissions.itemSelectionChanged.connect(self._UpdateButtons)
        objLayout.addWidget(self.tblMissions, 1)

        # --- 버튼 ---
        objRowA = QHBoxLayout()
        btnAdd = QPushButton("미션 추가...")
        btnAdd.clicked.connect(self.OnAddClicked)
        self.btnStart = QPushButton("시작 / 일시정지")
        self.btnStart.clicked.connect(lambda: self._ToggleRun(self._SelectedRows()))
        btnMinus = QPushButton("-1분")
        btnMinus.clicked.connect(lambda: self._AddTime(-60))
        btnPlus = QPushButton("+1분")
        btnPlus.clicked.connect(lambda: self._AddTime(60))
        for btnItem in (btnAdd, self.btnStart, btnMinus, btnPlus):
            objRowA.addWidget(btnItem)
        objRowA.addStretch()
        objLayout.addLayout(objRowA)

        objRowB = QHBoxLayout()
        for strLabel, strState in (("성공", "success"), ("실패", "fail"), ("거절", "reject")):
            btnItem = QPushButton(strLabel)
            btnItem.clicked.connect(lambda _=False, strState=strState: self._FinishSelected(strState))
            objRowB.addWidget(btnItem)
        btnBack = QPushButton("대기로 되돌리기")
        btnBack.clicked.connect(self._ResetSelected)
        btnDelete = QPushButton("삭제")
        btnDelete.clicked.connect(self._DeleteSelected)
        objRowB.addWidget(btnBack)
        objRowB.addStretch()
        objRowB.addWidget(btnDelete)
        objLayout.addLayout(objRowB)

        lblHelp = QLabel("더블클릭: 시작 ↔ 일시정지.  시간이 끝나면 '시간 초과' 로 바뀌어요 → 성공 / 실패를 눌러 마무리하세요.  "
                         "시간 초과된 미션에 +1분을 누르면 다시 진행돼요.")
        lblHelp.setWordWrap(True)
        lblHelp.setStyleSheet("color: #6b7280;")
        objLayout.addWidget(lblHelp)
        self.lblHelp = lblHelp
        self.tblMissions.setToolTip(lblHelp.text())

    def SetCompact(self, bCompact: bool) -> None:
        """방송 도우미 창 안에서 작게 보기: 큰 타이머 · 도움말 숨기고, 설정은 [설정 열기] 로 접어요."""
        self.wgtTimerBox.setVisible(not bCompact)
        self.lblHelp.setVisible(not bCompact)
        self.btnToggleSettings.setVisible(bCompact)
        self.grpSettings.setVisible(not bCompact)
        self.btnToggleSettings.setText("설정 열기")

    def _ToggleSettings(self) -> None:
        bShow = self.grpSettings.isHidden()
        self.grpSettings.setVisible(bShow)
        self.btnToggleSettings.setText("설정 닫기" if bShow else "설정 열기")

    def _SetSetting(self, strKey: str, objValue) -> None:
        self.dictApp[strKey] = objValue
        try:
            self.fnSaveConfig()
        except OSError as objError:
            self.fnLog(f"[경고] 설정 저장 실패: {objError}")

    def _OnTimerFileToggled(self, bChecked: bool) -> None:
        self._SetSetting("mission_timer_file", bChecked)
        self.strLastTimerText = None
        if not bChecked:
            self._WriteTimerFile("")  # 끄면 방송 화면의 타이머도 지워요.
            self.strLastTimerText = None
        self._OnTick()

    # ===================================================================
    # 미션 받기
    # ===================================================================
    def _OnDonation(self, objDonation: ChzzkDonationMessage) -> None:
        """후원이 오면 미션인지 확인해요. (미션 종류이거나, 메시지가 정한 단어로 시작하면)"""
        strText = RE_EMOJI_PLACEHOLDER.sub(lambda objMatch: f"[{objMatch.group(1)}]", objDonation.strText or "").strip()
        strPrefix = str(self.dictApp.get("mission_prefix", "")).strip()
        # "[미션] 보스 잡기" / "(미션) ..." / "【미션】..." 처럼 괄호로 시작해도 알아보게 앞 괄호를 떼고 봐요.
        strCheck = strText.lstrip(" [(【<「『")
        if objDonation.strDonationType == "MISSION":
            strMission = strText
        elif self.dictApp.get("mission_prefix_enabled") and strPrefix and strCheck.startswith(strPrefix):
            # "미션: 보스 잡기" / "미션 보스 잡기" / "[미션] 보스 잡기" → "보스 잡기"
            strMission = strCheck[len(strPrefix):].lstrip(" :：])】>」』-~").strip() or strText
        else:
            return
        self.AddMission(MissionRecord(
            dtTime=objDonation.dtTime, strNickname=objDonation.strNickname, nAmount=objDonation.nPayAmount,
            strText=strMission, nDurationSec=int(self.dictApp["mission_default_min"]) * 60, bTest=objDonation.bTest,
        ))

    def AddFromDonationRecord(self, objRecord) -> None:
        """후원 목록의 한 줄을 미션으로 만들어요. ([미션으로 만들기] 버튼)"""
        self.AddMission(MissionRecord(
            dtTime=objRecord.dtTime, strNickname=objRecord.strNickname, nAmount=objRecord.nPayAmount,
            strText=objRecord.strText, nDurationSec=int(self.dictApp["mission_default_min"]) * 60,
            bTest=getattr(objRecord, "bTest", False),
        ))

    def OnAddClicked(self) -> None:
        objDialog = _AddMissionDialog(int(self.dictApp["mission_default_min"]), self)
        if objDialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.AddMission(MissionRecord(
            dtTime=datetime.now(), strNickname=objDialog.editNick.text().strip() or "-",
            nAmount=objDialog.spinAmount.value(), strText=objDialog.editText.text().strip(),
            nDurationSec=objDialog.spinMin.value() * 60,
        ))

    def AddMission(self, objMission: MissionRecord) -> None:
        nRow = self._AddRow(objMission)
        self._Save()
        self._UpdateSummary()
        self.fnLog(f"[미션] {'(테스트) ' if objMission.bTest else ''}새 미션: {objMission.strNickname} "
                   f"{objMission.nAmount:,}원 — {objMission.strText} (제한 {FormatSec(objMission.nDurationSec)})")
        if not self.tblMissions.isRowHidden(nRow):
            self.tblMissions.scrollToBottom()

    # ===================================================================
    # 표
    # ===================================================================
    def _AddRow(self, objMission: MissionRecord) -> int:
        self.listMissions.append(objMission)
        nRow = self.tblMissions.rowCount()
        self.tblMissions.insertRow(nRow)
        bToday = objMission.dtTime.date() == datetime.now().date()
        strNick = objMission.strNickname + (" (테스트)" if objMission.bTest else "")
        listCells = [objMission.dtTime.strftime("%H:%M" if bToday else "%m-%d %H:%M"), strNick,
                     f"{objMission.nAmount:,}원", objMission.strText, "", ""]
        for nCol, strCell in enumerate(listCells):
            objItem = QTableWidgetItem(strCell)
            if nCol in (N_COL_AMOUNT, N_COL_LEFT):
                objItem.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if nCol == N_COL_TEXT:
                objItem.setToolTip(strCell)
            self.tblMissions.setItem(nRow, nCol, objItem)
        self._PaintRow(nRow)
        self._ApplyFilterToRow(nRow)
        return nRow

    def _PaintRow(self, nRow: int) -> None:
        objMission = self.listMissions[nRow]
        strState, strColor = DICT_MISSION_STATE[objMission.strState]
        objStateItem = self.tblMissions.item(nRow, N_COL_STATE)
        objStateItem.setText(strState)
        objStateItem.setForeground(QBrush(QColor(strColor)))
        objLeftItem = self.tblMissions.item(nRow, N_COL_LEFT)
        objLeftItem.setText("-" if objMission.bFinished else FormatSec(objMission.fLeftSec))
        objLeftItem.setForeground(QBrush(QColor("#e03131" if objMission.strState == "timeout" else
                                                "#1971c2" if objMission.strState == "run" else "#1f2937")))
        strTextColor = "#9ca3af" if objMission.bFinished else ""
        for nCol in (N_COL_TIME, N_COL_NICK, N_COL_AMOUNT, N_COL_TEXT):
            self.tblMissions.item(nRow, nCol).setForeground(QBrush(QColor(strTextColor)) if strTextColor else QBrush())

    def _ApplyFilter(self) -> None:
        for nRow in range(self.tblMissions.rowCount()):
            self._ApplyFilterToRow(nRow)

    def _ApplyFilterToRow(self, nRow: int) -> None:
        self.tblMissions.setRowHidden(nRow, self.chkHideFinished.isChecked() and self.listMissions[nRow].bFinished)

    def _SelectedRows(self) -> List[int]:
        return sorted({objIndex.row() for objIndex in self.tblMissions.selectionModel().selectedRows()})

    def _RequireSelection(self) -> List[int]:
        listRows = self._SelectedRows()
        if not listRows:
            QMessageBox.information(self, "안내", "목록에서 미션을 먼저 골라 주세요.")
        return listRows

    def _UpdateButtons(self) -> None:
        listRows = self._SelectedRows()
        bAnyRunning = any(self.listMissions[nRow].strState == "run" for nRow in listRows)
        self.btnStart.setText("일시정지" if bAnyRunning else "시작 / 재개")

    def _UpdateSummary(self) -> None:
        nActive = sum(1 for objMission in self.listMissions if not objMission.bFinished)
        nRunning = sum(1 for objMission in self.listMissions if objMission.strState == "run")
        nSuccess = sum(1 for objMission in self.listMissions if objMission.strState == "success")
        nFail = sum(1 for objMission in self.listMissions if objMission.strState == "fail")
        self.lblSummary.setText(f"남은 미션 {nActive}개 (진행 중 {nRunning})   |   성공 {nSuccess} · 실패 {nFail}")
        self.sigActiveChanged.emit(nActive)
        self._UpdateButtons()

    # ===================================================================
    # 미션 조작
    # ===================================================================
    def _ToggleRun(self, listRows: List[int]) -> None:
        if not listRows:
            self._RequireSelection()
            return
        bPause = any(self.listMissions[nRow].strState == "run" for nRow in listRows)
        for nRow in listRows:
            objMission = self.listMissions[nRow]
            if objMission.bFinished:
                continue
            if bPause:
                if objMission.strState == "run":
                    objMission.Pause()
            elif objMission.strState != "run":
                objMission.Start()
                self._Announce(objMission, f"[미션 시작] {objMission.strNickname}님 미션: {objMission.strText} "
                                           f"(제한 {FormatSec(objMission.fLeftSec)})")
            self._PaintRow(nRow)
        self._AfterChange()

    def _AddTime(self, nSec: int) -> None:
        for nRow in self._RequireSelection():
            objMission = self.listMissions[nRow]
            if not objMission.bFinished:
                objMission.AddSec(nSec)
                self._PaintRow(nRow)
        self._AfterChange()

    def _FinishSelected(self, strState: str) -> None:
        strName = DICT_MISSION_STATE[strState][0]
        for nRow in self._RequireSelection():
            objMission = self.listMissions[nRow]
            objMission.Finish(strState)
            self._PaintRow(nRow)
            self._ApplyFilterToRow(nRow)
            self.fnLog(f"[미션] {strName}: {objMission.strNickname} — {objMission.strText}")
            if strState != "reject":
                self._Announce(objMission, f"[미션 {strName}] {objMission.strNickname}님 미션: {objMission.strText}")
        self._AfterChange()

    def _ResetSelected(self) -> None:
        for nRow in self._RequireSelection():
            objMission = self.listMissions[nRow]
            objMission.strState = "wait"
            objMission.fRemainSec = float(objMission.nDurationSec)
            self._PaintRow(nRow)
            self._ApplyFilterToRow(nRow)
        self._AfterChange()

    def _DeleteSelected(self) -> None:
        listRows = self._RequireSelection()
        if not listRows:
            return
        if QMessageBox.question(self, "확인", f"미션 {len(listRows)}개를 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        for nRow in reversed(listRows):  # 뒤에서부터 지워야 줄 번호가 안 꼬여요.
            del self.listMissions[nRow]
            self.tblMissions.removeRow(nRow)
        self._AfterChange()

    def RemoveTestMissions(self) -> int:
        nRemoved = 0
        for nRow in range(len(self.listMissions) - 1, -1, -1):
            if self.listMissions[nRow].bTest:
                del self.listMissions[nRow]
                self.tblMissions.removeRow(nRow)
                nRemoved += 1
        self._AfterChange()
        return nRemoved

    def _AfterChange(self) -> None:
        self._Save()
        self._UpdateSummary()
        self._OnTick()

    def _Announce(self, objMission: MissionRecord, strMessage: str) -> None:
        """'채팅으로 알리기' 가 켜져 있으면 채팅으로 보내요. (테스트 미션은 안 보내요)"""
        if objMission.bTest or not self.dictApp.get("mission_chat_announce"):
            return
        objClient = self.objHub.fnGetClient()
        if objClient is None or not objClient.bIsLoggedIn:
            self.fnLog("[미션] 채팅 알림을 못 보냈어요: 치지직 로그인이 필요해요.")
            return
        strMessage = strMessage if len(strMessage) <= 100 else strMessage[:99] + "…"

        def _Done(objResult):
            if isinstance(objResult, Exception):
                self.fnLog(f"[미션] 채팅 알림 실패: {objResult}")

        RunTask(self.listTasks, lambda: objClient.SendChatMessage(strMessage), _Done)

    # ===================================================================
    # 1초마다: 타이머 · 시간 초과 · 큰 타이머 · OBS 파일
    # ===================================================================
    def _OnTick(self) -> None:
        bChanged = False
        for nRow, objMission in enumerate(self.listMissions):
            if objMission.strState == "run":
                if objMission.fLeftSec <= 0:
                    objMission.Finish("timeout")
                    bChanged = True
                    self.fnLog(f"[미션] 시간 초과: {objMission.strNickname} — {objMission.strText}")
                    if self.dictApp.get("mission_sound"):
                        QApplication.beep()
                    self._Announce(objMission, f"[미션 시간 초과] {objMission.strNickname}님 미션: {objMission.strText}")
                self._PaintRow(nRow)
        if bChanged:
            self._Save()
            self._UpdateSummary()
        self._UpdateBigTimer()

    def _UpdateBigTimer(self) -> None:
        listRunning = sorted((objMission for objMission in self.listMissions if objMission.strState == "run"),
                             key=lambda objMission: objMission.fLeftSec)
        listTimeout = [objMission for objMission in self.listMissions if objMission.strState == "timeout"]
        if listRunning:
            objMission = listRunning[0]
            self.lblBigTimer.setText(FormatSec(objMission.fLeftSec))
            self.lblBigTimer.setStyleSheet("color: #e03131;" if objMission.fLeftSec <= 30 else "color: #1971c2;")
            strMore = f"<br><span style='color:#6b7280'>그 밖에 진행 중 {len(listRunning) - 1}개</span>" if len(listRunning) > 1 else ""
            self.lblBigMission.setText(f"<b>{objMission.strText}</b><br>{objMission.strNickname} · {objMission.nAmount:,}원{strMore}")
        elif listTimeout:
            objMission = listTimeout[-1]
            self.lblBigTimer.setText("00:00")
            self.lblBigTimer.setStyleSheet("color: #e03131;")
            self.lblBigMission.setText(f"<b style='color:#e03131'>시간 초과!</b> {objMission.strText}<br>"
                                       f"{objMission.strNickname} · 성공 / 실패를 눌러 마무리하세요.")
        else:
            self.lblBigTimer.setText("--:--")
            self.lblBigTimer.setStyleSheet("color: #adb5bd;")
            self.lblBigMission.setText("진행 중인 미션 없음 — 미션을 고르고 [시작] 을 누르세요.")

        # 후원 · 미션 창 맨 위의 짧은 타이머
        if listRunning:
            objMission = listRunning[0]
            strColor = "#e03131" if objMission.fLeftSec <= 30 else "#1971c2"
            strMore = f" 외 {len(listRunning) - 1}개" if len(listRunning) > 1 else ""
            strBar = (f"<span style='font-size:15px; font-weight:bold; color:{strColor}'>{FormatSec(objMission.fLeftSec)}</span>"
                      f"&nbsp;&nbsp;<b>[미션 진행 중]</b> {objMission.strText} — {objMission.strNickname}{strMore}")
        elif listTimeout:
            strBar = f"<b style='color:#e03131'>[미션 시간 초과]</b> {listTimeout[-1].strText} — 성공 / 실패를 눌러 마무리하세요."
        else:
            strBar = ""
        if strBar != self.strLastBarText:
            self.strLastBarText = strBar
            self.sigTimerText.emit(strBar)

        if self.dictApp.get("mission_timer_file"):
            listLines = [f"[미션] {objMission.strText} - {objMission.strNickname}  {FormatSec(objMission.fLeftSec)}"
                         for objMission in listRunning]
            listLines += [f"[미션] {objMission.strText} - 시간 초과!" for objMission in listTimeout]
            self._WriteTimerFile("\n".join(listLines))

    def _WriteTimerFile(self, strText: str) -> None:
        if strText == self.strLastTimerText:
            return  # 바뀐 게 없으면 안 써요.
        try:
            os.makedirs(os.path.dirname(self.strTimerPath), exist_ok=True)
            with open(self.strTimerPath, "w", encoding="utf-8") as objFile:  # OBS 는 UTF-8 파일을 읽어요.
                objFile.write(strText)
            self.strLastTimerText = strText
        except OSError as objError:
            self.fnLog(f"[경고] 타이머 파일을 쓸 수 없어요: {objError}")
            self.strLastTimerText = strText  # 매초 같은 경고가 쌓이지 않게

    # ===================================================================
    # 저장 / 불러오기
    # ===================================================================
    def _LoadMissions(self) -> None:
        if not os.path.exists(self.strSavePath):
            self._UpdateSummary()
            return
        try:
            with open(self.strSavePath, "r", encoding="utf-8") as objFile:
                listItems = json.load(objFile)
        except (OSError, ValueError) as objError:
            self.fnLog(f"[경고] 미션 기록을 읽을 수 없어요 ({self.strSavePath}): {objError}")
            self._UpdateSummary()
            return
        nLoaded = 0
        for dictItem in listItems if isinstance(listItems, list) else []:
            try:
                self._AddRow(MissionRecord.FromDict(dictItem))
                nLoaded += 1
            except (KeyError, TypeError, ValueError):
                continue
        if nLoaded:
            self.fnLog(f"[미션] 예전 미션 {nLoaded}개를 불러왔어요.")
        self._UpdateSummary()

    def _Save(self) -> None:
        listItems = [objMission.ToDict() for objMission in self.listMissions if not objMission.bTest][-N_MAX_SAVED_MISSIONS:]
        try:
            os.makedirs(os.path.dirname(self.strSavePath), exist_ok=True)
            strTempPath = self.strSavePath + ".tmp"
            with open(strTempPath, "w", encoding="utf-8") as objFile:
                json.dump(listItems, objFile, ensure_ascii=False, indent=1)
            os.replace(strTempPath, self.strSavePath)
        except OSError as objError:
            self.fnLog(f"[경고] 미션 저장 실패: {objError}")

    # ===================================================================
    # 창 열기 / 닫기 (열려 있는 동안은 채팅 연결을 붙잡아요)
    # ===================================================================
    def showEvent(self, objEvent) -> None:  # noqa: N802
        # 후원 · 미션 창의 탭으로 들어가 있으면(bManageHub=False) 연결은 바깥 창이 잡아요.
        if self.bManageHub and not objEvent.spontaneous():
            self.objHub.Join(self)
        super().showEvent(objEvent)

    def closeEvent(self, objEvent) -> None:  # noqa: N802
        if self.bManageHub:
            self.objHub.Leave(self)
        super().closeEvent(objEvent)

    def Shutdown(self) -> None:
        """프로그램을 끌 때: 방송 화면에 멈춘 타이머가 남지 않게 파일을 비워요. (미션 자체는 저장돼 있어요)"""
        self.objTickTimer.stop()
        if self.dictApp.get("mission_timer_file"):
            self._WriteTimerFile("")
