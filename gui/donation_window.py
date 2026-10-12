"""
후원 목록 창 (영상 후원 관리)
==============================

들어온 후원(영상 / 채팅)을 표로 모아 보고, 한 줄씩 '봄 / 넘김' 을 표시해서 대기열처럼 관리해요.

할 수 있는 것
    - 시간 · 종류 · 닉네임 · 금액 · 내용(영상 후원이면 영상 제목) 보기
    - 대기 / 봄 / 넘김 표시 (더블클릭하면 대기 ↔ 봄)
    - 영상만 / 채팅만 / 대기만 골라 보기
    - 합계 금액, 대기 건수

할 수 없는 것 (치지직 공식 API 에 없어요)
    - 영상을 직접 재생 · 건너뛰기 · 멈추기 → 치지직 스튜디오에서 해야 해요.
    - 영상 주소(URL) 보기 → 치지직이 영상 제목만 알려줘요.

언제 후원을 받나요?
    채팅 연결(ChatHub)이 켜져 있을 때 받아요. (프로그램을 켜면 자동 시작, 또는 이 창 / 채팅창을 열었을 때)

이전 후원은요?
    받은 후원은 data/donations.json 에 저장돼서, 프로그램을 껐다 켜도 목록과 봄 / 넘김 표시가 그대로 남아요.
    단, 치지직 공식 API 에는 '지난 후원 내역' 을 가져오는 기능이 없어서,
    프로그램이 꺼져 있던 동안 들어온 후원은 가져올 수 없어요.
"""

import json
import os
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app_paths import RecordPath
from chzzk import ChzzkDonationMessage, RE_EMOJI_PLACEHOLDER
from gui.chat_hub import ChatHub
from gui.test_dialog import TestDialog

STR_STUDIO_URL = "https://studio.chzzk.naver.com/"

# 받은 후원을 저장하는 파일 (닉네임 같은 개인정보가 들어 있어서 깃허브에 올리지 않아요)
STR_DONATION_FILE = RecordPath("donations.json")
N_MAX_SAVED_DONATIONS = 3000  # 이보다 많아지면 오래된 것부터 지워요.

# 상태 → (화면 글자, 글자 색)
DICT_STATE_VIEW = {
    "wait": ("대기", "#e67700"),
    "done": ("봄", "#2f9e44"),
    "skip": ("넘김", "#868e96"),
}

# 후원 종류 → 화면 이름. (공식 문서엔 CHAT / VIDEO 뿐이에요. MISSION 은 혹시 오면 보여주려고 넣어 뒀어요)
DICT_TYPE_NAMES = {"VIDEO": "영상", "CHAT": "채팅", "MISSION": "미션", "YOUTUBE": "유튜브", "SUBSCRIPTION": "구독"}
DICT_TYPE_COLORS = {"VIDEO": "#c2255c", "MISSION": "#7048e8", "YOUTUBE": "#e03131", "SUBSCRIPTION": "#0c8599"}

# 보기 고르기 (콤보 상자 순서대로)
LIST_TYPE_FILTERS = [("전체", None), ("영상 후원만", "VIDEO"), ("미션 후원만", "MISSION"), ("채팅 후원만", "CHAT"),
                     ("유튜브 슈퍼챗만", "YOUTUBE"), ("구독만", "SUBSCRIPTION")]

# 표 칸 번호
N_COL_TIME, N_COL_TYPE, N_COL_NICK, N_COL_AMOUNT, N_COL_TEXT, N_COL_STATE = range(6)


@dataclass
class DonationRecord:
    """목록의 한 줄."""

    dtTime: datetime
    strType: str        # VIDEO / CHAT / 그 밖의 종류는 받은 그대로 (예: MISSION)
    strNickname: str
    nPayAmount: int
    strText: str        # 영상 후원이면 영상 제목, 채팅 후원이면 메시지
    strState: str = "wait"

    @property
    def strTypeName(self) -> str:
        return DICT_TYPE_NAMES.get(self.strType, self.strType)

    @property
    def bIsToday(self) -> bool:
        return self.dtTime.date() == datetime.now().date()

    def ToDict(self) -> dict:
        return {"time": self.dtTime.isoformat(timespec="seconds"), "type": self.strType, "nickname": self.strNickname,
                "amount": self.nPayAmount, "text": self.strText, "state": self.strState}

    @staticmethod
    def FromDict(dictItem: dict) -> "DonationRecord":
        strState = dictItem.get("state", "wait")
        return DonationRecord(
            dtTime=datetime.fromisoformat(dictItem["time"]),
            strType=str(dictItem.get("type") or "CHAT").upper(),
            strNickname=str(dictItem.get("nickname", "")),
            nPayAmount=int(dictItem.get("amount") or 0),
            strText=str(dictItem.get("text", "")),
            strState=strState if strState in DICT_STATE_VIEW else "wait",
        )


class DonationWindow(QWidget):
    """후원 목록 창."""

    sigPendingChanged = Signal(int)  # 대기 건수가 바뀌면 알려요. (메인 창 버튼에 숫자 표시용)

    def __init__(self, objHub: ChatHub, fnLog: Optional[Callable[[str], None]] = None,
                 objParent: Optional[QWidget] = None, strSavePath: str = STR_DONATION_FILE):
        super().__init__(objParent, Qt.WindowType.Window)
        self.setWindowTitle("치지직 후원 목록")
        self.resize(720, 520)

        self.objHub = objHub
        self.bManageHub = True  # 따로 뜨는 창이면 열려 있는 동안 채팅 연결을 붙잡아요.
        self.fnLog = fnLog or (lambda strMessage: None)
        self.listRecords: List[DonationRecord] = []
        self.strSavePath = strSavePath
        self.objTestDialog: Optional[TestDialog] = None

        self._BuildUi()
        self._LoadRecords()  # 예전에 받아 둔 후원을 불러와요.
        # 창이 닫혀 있어도 연결만 돼 있으면 후원을 받아 둬요.
        self.objHub.sigDonation.connect(self.AddDonation)
        self.objHub.sigStatus.connect(self._OnStatus)
        self.objHub.sigDonationState.connect(self._OnDonationState)
        self._OnStatus(self.objHub.strLastState, "")
        self._OnDonationState(self.objHub.objDonationOk, self.objHub.strDonationReason)
        self._UpdateSummary()

    # ===================================================================
    # 화면 만들기
    # ===================================================================
    def _BuildUi(self) -> None:
        objLayout = QVBoxLayout(self)
        objLayout.setContentsMargins(8, 8, 8, 8)

        # --- 위쪽: 연결 상태 + 합계 ---
        objTopRow = QHBoxLayout()
        self.lblStatus = QLabel()
        self.btnConnect = QPushButton("연결")
        self.btnConnect.clicked.connect(self.OnConnectClicked)
        objTopRow.addWidget(self.lblStatus, 1)
        objTopRow.addWidget(self.btnConnect)
        objLayout.addLayout(objTopRow)

        # 후원 알림을 못 받을 때 크게 보여주는 경고 (보통 '후원 조회' 권한이 없을 때)
        self.lblDonationWarning = QLabel()
        self.lblDonationWarning.setWordWrap(True)
        self.lblDonationWarning.setStyleSheet(
            "background: #fff5f5; color: #c92a2a; border: 1px solid #ffa8a8; border-radius: 6px; padding: 8px;")
        self.lblDonationWarning.hide()
        objLayout.addWidget(self.lblDonationWarning)

        self.lblSummary = QLabel()
        self.lblSummary.setStyleSheet("font-weight: bold;")
        objLayout.addWidget(self.lblSummary)

        # --- 보기 고르기 ---
        objFilterRow = QHBoxLayout()
        self.cmbType = QComboBox()
        for strLabel, _ in LIST_TYPE_FILTERS:
            self.cmbType.addItem(strLabel)
        self.cmbType.currentIndexChanged.connect(self._ApplyFilter)
        self.chkWaitOnly = QCheckBox("대기만 보기")
        self.chkWaitOnly.toggled.connect(self._ApplyFilter)
        self.chkTodayOnly = QCheckBox("오늘만 보기")
        self.chkTodayOnly.setToolTip("끄면 예전에 받은 후원도 보여요. (합계도 함께 바뀌어요)")
        self.chkTodayOnly.toggled.connect(self._ApplyFilter)
        objFilterRow.addWidget(QLabel("보기:"))
        objFilterRow.addWidget(self.cmbType)
        objFilterRow.addWidget(self.chkWaitOnly)
        objFilterRow.addWidget(self.chkTodayOnly)
        objFilterRow.addStretch()
        # 알림 소리: 후원 · 구독을 따로 켜고 끄고, 따로 들어 봐요. (실제로 소리를 내는 건 메인 창이에요)
        self.chkSound = QCheckBox("후원 소리")
        self.chkSound.setChecked(True)
        self.chkSound.setToolTip("후원이 들어오면 부드러운 '도-미' 소리를 내요. (유튜브 슈퍼챗도 같아요)")
        self.btnSoundTest = QPushButton("▶")
        self.btnSoundTest.setToolTip("후원 소리를 미리 들어 봐요.")
        self.chkSubSound = QCheckBox("구독 소리")
        self.chkSubSound.setChecked(True)
        self.chkSubSound.setToolTip("구독이 들어오면 '솔-도-미' 소리를 내요. (후원 소리와 달라요)")
        self.btnSubSoundTest = QPushButton("▶")
        self.btnSubSoundTest.setToolTip("구독 소리를 미리 들어 봐요.")
        self.btnSoundSettings = QPushButton("⚙")
        self.btnSoundSettings.setToolTip("알림 소리 크기 · 음 높이 설정")
        for btnSmall in (self.btnSoundTest, self.btnSubSoundTest, self.btnSoundSettings):
            btnSmall.setFixedWidth(34)
        objFilterRow.addWidget(self.chkSound)
        objFilterRow.addWidget(self.btnSoundTest)
        objFilterRow.addSpacing(8)
        objFilterRow.addWidget(self.chkSubSound)
        objFilterRow.addWidget(self.btnSubSoundTest)
        objFilterRow.addWidget(self.btnSoundSettings)
        objLayout.addLayout(objFilterRow)

        # --- 표 ---
        self.tblDonations = QTableWidget(0, 6)
        self.tblDonations.setHorizontalHeaderLabels(["시간", "종류", "닉네임", "금액", "내용 (영상 제목 / 메시지)", "상태"])
        self.tblDonations.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tblDonations.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tblDonations.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tblDonations.verticalHeader().setVisible(False)
        objHeader = self.tblDonations.horizontalHeader()
        for nCol in (N_COL_TIME, N_COL_TYPE, N_COL_NICK, N_COL_AMOUNT, N_COL_STATE):
            objHeader.setSectionResizeMode(nCol, QHeaderView.ResizeMode.ResizeToContents)
        objHeader.setSectionResizeMode(N_COL_TEXT, QHeaderView.ResizeMode.Stretch)
        self.tblDonations.cellDoubleClicked.connect(self.OnRowDoubleClicked)
        objLayout.addWidget(self.tblDonations, 1)

        # --- 아래쪽: 상태 바꾸기 버튼 ---
        objButtonRow = QHBoxLayout()
        btnDone = QPushButton("봄 표시")
        btnDone.clicked.connect(lambda: self._SetSelectedState("done"))
        btnSkip = QPushButton("넘김 표시")
        btnSkip.clicked.connect(lambda: self._SetSelectedState("skip"))
        btnWait = QPushButton("대기로 되돌리기")
        btnWait.clicked.connect(lambda: self._SetSelectedState("wait"))
        btnStudio = QPushButton("치지직 스튜디오 열기")
        btnStudio.setToolTip("영상 재생 · 건너뛰기는 치지직 스튜디오에서 해요. (공식 API 에 제어 기능이 없어요)")
        btnStudio.clicked.connect(lambda: webbrowser.open(STR_STUDIO_URL))
        btnClear = QPushButton("목록 지우기")
        btnClear.clicked.connect(self.OnClearClicked)
        btnTest = QPushButton("테스트 도구")
        btnTest.setToolTip("실패 상황 흉내 · 실제 연결 점검")
        btnTest.clicked.connect(self.OnTestToolClicked)
        for btnItem in (btnDone, btnSkip, btnWait):
            objButtonRow.addWidget(btnItem)
        objButtonRow.addStretch()
        objButtonRow.addWidget(btnTest)
        objButtonRow.addWidget(btnStudio)
        objButtonRow.addWidget(btnClear)
        objLayout.addLayout(objButtonRow)

        lblHelp = QLabel("더블클릭: 대기 ↔ 봄.  여러 줄을 골라 한 번에 바꿀 수 있어요.  "
                         "영상 재생 · 건너뛰기는 치지직 스튜디오에서 해 주세요. (치지직 API 는 영상 제목만 알려줘요)")
        lblHelp.setWordWrap(True)
        lblHelp.setStyleSheet("color: #6b7280;")
        objLayout.addWidget(lblHelp)
        self.lblHelp = lblHelp
        self.tblDonations.setToolTip(lblHelp.text())

    # ===================================================================
    # 연결
    # ===================================================================
    def OnConnectClicked(self) -> None:
        if self.objHub.bIsRunning:
            self.objHub.Disconnect()
        else:
            self.objHub.Connect()

    def _OnStatus(self, strState: str, strMessage: str) -> None:
        dictView = {"connecting": ("#e67700", "연결 중..."), "connected": ("#2f9e44", "연결됨 — 후원을 받고 있어요"),
                    "reconnecting": ("#e67700", "다시 연결 대기"), "stopped": ("#868e96", "연결 안 됨 — 후원을 받지 않아요"),
                    "error": ("#e03131", "오류")}
        strColor, strText = dictView.get(strState, ("#868e96", strState))
        if strState == "connected" and self.objHub.objDonationOk is False:  # 채팅은 오는데 후원 신청은 거절된 경우
            strColor, strText = "#e67700", "연결됨 — 채팅만 받는 중 (후원은 안 와요)"
        strDetail = f" <span style='color:#6b7280'>({strMessage})</span>" if strState == "error" and strMessage else ""
        self.lblStatus.setText(f"<span style='color:{strColor}; font-size:14px'>●</span> <b>{strText}</b>{strDetail}")
        self.btnConnect.setText("연결 끊기" if strState in ("connecting", "connected", "reconnecting") else "연결")

    def SetCompact(self, bCompact: bool) -> None:
        """방송 도우미 창 안에서 작게 보기: 도움말을 숨겨요. (표에 마우스를 올리면 설명이 나와요)"""
        self.lblHelp.setVisible(not bCompact)

    def SetConnectRowVisible(self, bVisible: bool) -> None:
        """위쪽 연결 상태 줄을 보이거나 숨겨요. (방송 도우미 창에서는 채팅 쪽에 연결 버튼이 있어서 숨겨요)"""
        self.lblStatus.setVisible(bVisible)
        self.btnConnect.setVisible(bVisible)

    def _OnDonationState(self, objOk, strReason: str) -> None:
        """후원 알림 신청이 거절됐으면 창 위에 크게 알려요. (채팅은 와도 후원은 하나도 안 와요)"""
        if objOk is False:
            self.lblDonationWarning.setText(f"<b>후원 알림을 받을 수 없어요 — 영상 · 채팅 후원이 이 목록에 들어오지 않아요.</b><br>{strReason}")
            self.lblDonationWarning.show()
            self.fnLog(f"[후원] 후원 알림을 받을 수 없어요: {strReason}")
        else:
            self.lblDonationWarning.hide()
        self._OnStatus(self.objHub.strLastState, "")  # 위쪽 상태 글자도 맞춰요.

    def showEvent(self, objEvent) -> None:  # noqa: N802 (Qt 가 정한 이름)
        # 최소화했다 다시 띄운 것(spontaneous)은 빼요. ('연결 끊기' 한 걸 멋대로 다시 잇지 않게)
        # 후원 · 미션 창의 탭으로 들어가 있으면(bManageHub=False) 연결은 바깥 창이 잡아요.
        if self.bManageHub and not objEvent.spontaneous():
            self.objHub.Join(self)
        super().showEvent(objEvent)

    def closeEvent(self, objEvent) -> None:  # noqa: N802
        if self.bManageHub:
            self.objHub.Leave(self)
        super().closeEvent(objEvent)

    # ===================================================================
    # 목록
    # ===================================================================
    def AddDonation(self, objDonation: ChzzkDonationMessage) -> None:
        strText = RE_EMOJI_PLACEHOLDER.sub(lambda objMatch: f"[{objMatch.group(1)}]", objDonation.strText or "")
        if not objDonation.bIsKnownType:
            # 공식 문서에 없는 종류(미션 등)가 왔어요 → 모양을 확인할 수 있게 원본을 로그에 남겨요.
            self.fnLog(f"[후원] 처음 보는 후원 종류 '{objDonation.strDonationType}' 를 받았어요. 원본: {objDonation.dictRaw}")
        objRecord = DonationRecord(
            dtTime=objDonation.dtTime,
            strType=objDonation.strDonationType or "CHAT",
            strNickname=objDonation.strNickname,
            nPayAmount=objDonation.nPayAmount,
            strText=strText,
            # 구독은 '봐야 할 영상' 이 아니라서 처음부터 '봄' 으로 둬요. (대기 숫자에 안 들어가게)
            strState="done" if objDonation.strDonationType == "SUBSCRIPTION" else "wait",
        )
        nRow = self._AddRecordRow(objRecord)
        self._UpdateSummary()
        self._SaveRecords()
        # 맨 아래(새 후원)가 보이게
        if not self.tblDonations.isRowHidden(nRow):
            self.tblDonations.scrollToBottom()

    def _AddRecordRow(self, objRecord: DonationRecord) -> int:
        """목록과 표에 한 줄 추가해요. 돌려주는 값: 줄 번호"""
        self.listRecords.append(objRecord)
        nRow = self.tblDonations.rowCount()
        self.tblDonations.insertRow(nRow)
        # 오늘 후원은 시각만, 예전 후원은 날짜도 같이 보여줘요.
        strTime = objRecord.dtTime.strftime("%H:%M:%S" if objRecord.bIsToday else "%m-%d %H:%M")
        listCells = [strTime, objRecord.strTypeName, objRecord.strNickname,
                     "-" if objRecord.strType == "SUBSCRIPTION" else f"{objRecord.nPayAmount:,}원", objRecord.strText, ""]
        for nCol, strCell in enumerate(listCells):
            objItem = QTableWidgetItem(strCell)
            if nCol == N_COL_AMOUNT:
                objItem.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if nCol == N_COL_TEXT:
                objItem.setToolTip(strCell)
            self.tblDonations.setItem(nRow, nCol, objItem)
        if objRecord.strType in DICT_TYPE_COLORS:  # 영상 · 미션 · 구독은 눈에 띄게
            self.tblDonations.item(nRow, N_COL_TYPE).setForeground(QBrush(QColor(DICT_TYPE_COLORS[objRecord.strType])))
        self._PaintState(nRow)
        self._ApplyFilterToRow(nRow)
        return nRow

    def OnRowDoubleClicked(self, nRow: int, _nCol: int) -> None:
        objRecord = self.listRecords[nRow]
        objRecord.strState = "wait" if objRecord.strState == "done" else "done"
        self._RefreshRow(nRow)
        self._SaveRecords()

    def _SetSelectedState(self, strState: str) -> None:
        listRows = sorted({objIndex.row() for objIndex in self.tblDonations.selectionModel().selectedRows()})
        if not listRows:
            QMessageBox.information(self, "안내", "목록에서 후원을 먼저 골라 주세요.")
            return
        for nRow in listRows:
            self.listRecords[nRow].strState = strState
            self._RefreshRow(nRow)
        self._SaveRecords()

    def _RefreshRow(self, nRow: int) -> None:
        self._PaintState(nRow)
        self._ApplyFilterToRow(nRow)
        self._UpdateSummary()

    def _PaintState(self, nRow: int) -> None:
        objRecord = self.listRecords[nRow]
        strText, strColor = DICT_STATE_VIEW[objRecord.strState]
        objItem = self.tblDonations.item(nRow, N_COL_STATE)
        objItem.setText(strText)
        objItem.setForeground(QBrush(QColor(strColor)))
        # 끝난 줄(봄 / 넘김)은 흐리게
        strTextColor = "#9ca3af" if objRecord.strState != "wait" else ""
        for nCol in (N_COL_TIME, N_COL_NICK, N_COL_AMOUNT, N_COL_TEXT):
            objCell = self.tblDonations.item(nRow, nCol)
            objCell.setForeground(QBrush(QColor(strTextColor)) if strTextColor else QBrush())

    def OnClearClicked(self) -> None:
        if not self.listRecords:
            return
        strQuestion = (f"후원 {len(self.listRecords)}건을 목록에서 지울까요?\n"
                       "저장된 기록(data/donations.json)도 함께 지워져요.")
        if QMessageBox.question(self, "확인", strQuestion) != QMessageBox.StandardButton.Yes:
            return
        self.listRecords.clear()
        self.tblDonations.setRowCount(0)
        self._UpdateSummary()
        self._SaveRecords()

    def OnTestToolClicked(self) -> None:
        if self.objTestDialog is None:
            self.objTestDialog = TestDialog(self.objHub, fnLog=self.fnLog, objParent=self)
        self.objTestDialog.show()
        self.objTestDialog.raise_()
        self.objTestDialog.activateWindow()

    # ===================================================================
    # 저장 / 불러오기 (data/donations.json)
    # ===================================================================
    def _LoadRecords(self) -> None:
        if not os.path.exists(self.strSavePath):
            return
        try:
            with open(self.strSavePath, "r", encoding="utf-8") as objFile:
                listItems = json.load(objFile)
        except (OSError, ValueError) as objError:
            self.fnLog(f"[경고] 후원 기록을 읽을 수 없어요 ({self.strSavePath}): {objError}")
            return
        nLoaded = 0
        for dictItem in listItems if isinstance(listItems, list) else []:
            try:
                self._AddRecordRow(DonationRecord.FromDict(dictItem))
                nLoaded += 1
            except (KeyError, TypeError, ValueError):
                continue  # 망가진 줄은 건너뛰어요.
        if nLoaded:
            self.fnLog(f"[후원] 예전 후원 기록 {nLoaded}건을 불러왔어요.")
            self.tblDonations.scrollToBottom()

    def _SaveRecords(self) -> None:
        """목록을 파일에 저장해요. (저장 도중 꺼져도 파일이 깨지지 않게 임시 파일을 거쳐요)"""
        # 테스트 후원은 저장하지 않아요.
        listItems = [objRecord.ToDict() for objRecord in self.listRecords][-N_MAX_SAVED_DONATIONS:]
        try:
            os.makedirs(os.path.dirname(self.strSavePath), exist_ok=True)
            strTempPath = self.strSavePath + ".tmp"
            with open(strTempPath, "w", encoding="utf-8") as objFile:
                json.dump(listItems, objFile, ensure_ascii=False, indent=1)
            os.replace(strTempPath, self.strSavePath)
        except OSError as objError:
            self.fnLog(f"[경고] 후원 기록 저장 실패: {objError}")

    # ===================================================================
    # 보기 고르기 · 합계
    # ===================================================================
    def _ApplyFilter(self) -> None:
        for nRow in range(self.tblDonations.rowCount()):
            self._ApplyFilterToRow(nRow)
        self._UpdateSummary()  # '오늘만 보기' 면 합계도 오늘 것만

    def _ApplyFilterToRow(self, nRow: int) -> None:
        objRecord = self.listRecords[nRow]
        strTypeFilter = LIST_TYPE_FILTERS[self.cmbType.currentIndex()][1]
        bHide = (strTypeFilter is not None and objRecord.strType != strTypeFilter) or \
                (self.chkWaitOnly.isChecked() and objRecord.strState != "wait") or \
                (self.chkTodayOnly.isChecked() and not objRecord.bIsToday)
        self.tblDonations.setRowHidden(nRow, bHide)

    def _UpdateSummary(self) -> None:
        bTodayOnly = self.chkTodayOnly.isChecked()
        listShown = [objRecord for objRecord in self.listRecords if not bTodayOnly or objRecord.bIsToday]
        listVideo = [objRecord for objRecord in listShown if objRecord.strType == "VIDEO"]
        listChat = [objRecord for objRecord in listShown if objRecord.strType == "CHAT"]
        listYouTube = [objRecord for objRecord in listShown if objRecord.strType == "YOUTUBE"]
        listSub = [objRecord for objRecord in listShown if objRecord.strType == "SUBSCRIPTION"]
        listOther = [objRecord for objRecord in listShown
                     if objRecord.strType not in ("VIDEO", "CHAT", "YOUTUBE", "SUBSCRIPTION")]  # 미션 등
        nVideoWait = sum(1 for objRecord in listVideo if objRecord.strState == "wait")
        nWait = sum(1 for objRecord in listShown if objRecord.strState == "wait")
        listParts = [f"영상 후원 {len(listVideo)}건 · {sum(objRecord.nPayAmount for objRecord in listVideo):,}원 "
                     f"(대기 {nVideoWait}건)"]
        if listOther:  # 미션 같은 다른 종류가 있을 때만 보여줘요.
            strOtherName = "미션" if all(objRecord.strType == "MISSION" for objRecord in listOther) else "미션 · 기타"
            listParts.append(f"{strOtherName} {len(listOther)}건 · {sum(objRecord.nPayAmount for objRecord in listOther):,}원")
        listParts.append(f"채팅 후원 {len(listChat)}건 · {sum(objRecord.nPayAmount for objRecord in listChat):,}원")
        if listYouTube:  # 유튜브 슈퍼챗 (원화가 아닌 건 금액에 안 들어가요)
            listParts.append(f"유튜브 {len(listYouTube)}건 · {sum(objRecord.nPayAmount for objRecord in listYouTube):,}원")
        if listSub:
            listParts.append(f"구독 {len(listSub)}건")
        listParts.append(f"전체 대기 {nWait}건")
        self.lblSummary.setText(("[오늘] " if bTodayOnly else "") + "   |   ".join(listParts))
        # 메인 창 버튼 숫자는 보기와 상관없이 '전체 대기' 로 알려요.
        self.sigPendingChanged.emit(self.nPendingCount)

    @property
    def nPendingCount(self) -> int:
        return sum(1 for objRecord in self.listRecords if objRecord.strState == "wait")
