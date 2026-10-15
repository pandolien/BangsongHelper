"""
시청자 정보 창
==============

채팅에서 닉네임을 누르고 [이 시청자 정보 보기...] 를 고르면 열려요.

위쪽 (치지직에 물어봐요 · 잠깐 걸려요)
    - 활동 제한 중인지, 제한 일자 · 해제 일자
    - 구독자인지 (티어 · 개월 수)
가운데
    - 이 프로그램으로 한 제한 기록 (임시 제한 · 활동 제한 · 메시지 가리기)
아래
    - 이 프로그램이 받은 그 시청자의 채팅 (프로그램을 켠 뒤부터)

치지직은 시청자의 지난 채팅이나, 다른 곳에서 한 제한 기록을 알려주지 않아요. (공식 API 에 없어요)
"""

from datetime import datetime
from typing import Callable, List, Optional

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from chzzk import ChzzkApiClient, ChzzkApiError
from gui.bg_task import BackgroundTask, RunTask
from gui.restrict_dialog import ExplainRestrictError, _ShortDate


def _TimeText(dtValue: datetime) -> str:
    return dtValue.strftime("%H:%M:%S" if dtValue.date() == datetime.now().date() else "%m-%d %H:%M:%S")


class ViewerInfoDialog(QDialog):
    def __init__(self, strNickname: str, strChannelId: str, strRoleName: str,
                 listChats: List[tuple], listHistory: List[dict],
                 fnGetClient: Callable[[], Optional[ChzzkApiClient]], objParent: Optional[QWidget] = None):
        """listChats: [(시각, 내용)] 오래된 것부터 / listHistory: ModerationHistory.ListFor 의 결과"""
        super().__init__(objParent)
        self.setWindowTitle(f"시청자 정보 — {strNickname}")
        self.resize(640, 640)
        self.strNickname, self.strChannelId = strNickname, strChannelId
        self.fnGetClient = fnGetClient
        self.listTasks: List[BackgroundTask] = []
        self.listChats = listChats

        objLayout = QVBoxLayout(self)
        lblTitle = QLabel(f"<span style='font-size:15pt; font-weight:bold'>{strNickname}</span>"
                          + (f"  <span style='color:#e03131'>[{strRoleName}]</span>" if strRoleName else ""))
        lblTitle.setTextFormat(lblTitle.textFormat().RichText)
        objLayout.addWidget(lblTitle)

        # ---- 치지직에 물어본 것 ----
        objStatusBox = QGroupBox("치지직에서 확인")
        objForm = QFormLayout(objStatusBox)
        self.lblRestrict = QLabel("확인 중...")
        self.lblSubscribe = QLabel("확인 중...")
        for lblItem in (self.lblRestrict, self.lblSubscribe):
            lblItem.setWordWrap(True)
        objForm.addRow("활동 제한", self.lblRestrict)
        objForm.addRow("구독", self.lblSubscribe)
        self.btnReload = QPushButton("다시 확인")
        self.btnReload.clicked.connect(self.Reload)
        objForm.addRow("", self.btnReload)
        objLayout.addWidget(objStatusBox)

        # ---- 이 프로그램으로 한 제한 ----
        objHistoryBox = QGroupBox(f"이 프로그램으로 한 제한 기록 ({len(listHistory)}건)")
        objHistoryLayout = QVBoxLayout(objHistoryBox)
        self.tblHistory = self._MakeTable(["시각", "한 일", "내용"])
        for dictItem in reversed(listHistory):  # 최근 것이 위로
            try:
                strTime = _TimeText(datetime.fromisoformat(dictItem["time"]))
            except (KeyError, ValueError):
                strTime = dictItem.get("time", "")
            self._AddRow(self.tblHistory, [strTime, dictItem["action"], dictItem.get("detail", "")])
        if not listHistory:
            objHistoryLayout.addWidget(self._Note("이 프로그램으로 제한한 기록이 없어요."))
        else:
            objHistoryLayout.addWidget(self.tblHistory)
        objLayout.addWidget(objHistoryBox)

        # ---- 이 프로그램이 받은 채팅 ----
        objChatBox = QGroupBox(f"이 프로그램이 받은 채팅 ({len(listChats)}개 · 프로그램을 켠 뒤부터)")
        objChatLayout = QVBoxLayout(objChatBox)
        self.tblChats = self._MakeTable(["시각", "내용"])
        for dtTime, strContent in reversed(listChats):  # 최근 것이 위로
            self._AddRow(self.tblChats, [_TimeText(dtTime), strContent])
        if not listChats:
            objChatLayout.addWidget(self._Note("이 프로그램이 켜진 뒤로 받은 채팅이 없어요."))
        else:
            objChatLayout.addWidget(self.tblChats, 1)
        self.btnCopy = QPushButton("채팅 모두 복사")
        self.btnCopy.setEnabled(bool(listChats))
        self.btnCopy.clicked.connect(self.OnCopyClicked)
        objCopyRow = QHBoxLayout()
        objCopyRow.addStretch()
        objCopyRow.addWidget(self.btnCopy)
        objChatLayout.addLayout(objCopyRow)
        objLayout.addWidget(objChatBox, 1)

        objLayout.addWidget(self._Note("치지직은 시청자의 지난 채팅이나, 치지직 스튜디오 등 다른 곳에서 한 제한 기록을 알려주지 않아요."))
        self.Reload()

    # -------------------------------------------------------------------
    @staticmethod
    def _Note(strText: str) -> QLabel:
        lblNote = QLabel(strText)
        lblNote.setObjectName("Help")
        lblNote.setWordWrap(True)
        return lblNote

    @staticmethod
    def _MakeTable(listHeaders: List[str]) -> QTableWidget:
        tblItem = QTableWidget(0, len(listHeaders))
        tblItem.setHorizontalHeaderLabels(listHeaders)
        tblItem.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tblItem.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tblItem.verticalHeader().setVisible(False)
        objHeader = tblItem.horizontalHeader()
        for nCol in range(len(listHeaders) - 1):
            objHeader.setSectionResizeMode(nCol, QHeaderView.ResizeMode.ResizeToContents)
        objHeader.setSectionResizeMode(len(listHeaders) - 1, QHeaderView.ResizeMode.Stretch)
        return tblItem

    @staticmethod
    def _AddRow(tblItem: QTableWidget, listCells: List[str]) -> None:
        nRow = tblItem.rowCount()
        tblItem.insertRow(nRow)
        for nCol, strCell in enumerate(listCells):
            objItem = QTableWidgetItem(strCell)
            objItem.setToolTip(strCell)
            tblItem.setItem(nRow, nCol, objItem)

    def OnCopyClicked(self) -> None:
        strText = "\n".join(f"{_TimeText(dtTime)} {self.strNickname}: {strContent}" for dtTime, strContent in self.listChats)
        QApplication.clipboard().setText(strText)
        self.btnCopy.setText(f"복사했어요 ({len(self.listChats)}줄)")

    # -------------------------------------------------------------------
    # 치지직에 물어보기 (뒤에서)
    # -------------------------------------------------------------------
    def Reload(self) -> None:
        objClient = self.fnGetClient()
        if not self.strChannelId:
            self.lblRestrict.setText("이 시청자의 채널 ID 를 알 수 없어요.")
            self.lblSubscribe.setText("이 시청자의 채널 ID 를 알 수 없어요.")
            return
        if objClient is None or not objClient.bIsLoggedIn:
            self.lblRestrict.setText("치지직 로그인이 필요해요.")
            self.lblSubscribe.setText("치지직 로그인이 필요해요.")
            return
        self.lblRestrict.setText("확인 중...")
        self.lblSubscribe.setText("확인 중...")
        self.btnReload.setEnabled(False)
        self.nPending = 2
        RunTask(self.listTasks, objClient.ListRestrictions, self._OnRestrictions)
        RunTask(self.listTasks, lambda: objClient.FindSubscriber(self.strChannelId), self._OnSubscriber)

    def _Finished(self) -> None:
        self.nPending -= 1
        if self.nPending <= 0:
            self.btnReload.setEnabled(True)

    def _OnRestrictions(self, objResult) -> None:
        self._Finished()
        if isinstance(objResult, Exception):
            self.lblRestrict.setText(f"확인하지 못했어요: {ExplainRestrictError(objResult)}")
            return
        dictFound = next((dictItem for dictItem in objResult if dictItem.get("restrictedChannelId") == self.strChannelId), None)
        if dictFound is None:
            self.lblRestrict.setText("활동 제한 아님")
            return
        strRelease = _ShortDate(dictFound.get("releaseDate")) if dictFound.get("releaseDate") else "풀 때까지"
        self.lblRestrict.setText(f"<span style='color:#e03131'><b>활동 제한 중</b></span> — 제한 "
                                 f"{_ShortDate(dictFound.get('createdDate'))} / 해제 {strRelease}")

    def _OnSubscriber(self, objResult) -> None:
        self._Finished()
        if isinstance(objResult, ChzzkApiError) and objResult.nHttpStatus == 403:
            self.lblSubscribe.setText("권한이 없어요 → 개발자 센터에서 '구독 조회' 권한을 켜고, 로그아웃 → 다시 로그인해 주세요.")
            return
        if isinstance(objResult, Exception):
            self.lblSubscribe.setText(f"확인하지 못했어요: {objResult}")
            return
        dictFound = objResult.get("found")
        if dictFound:
            self.lblSubscribe.setText(
                f"<b>구독 중</b> — 티어{dictFound.get('tierNo', '?')} · {dictFound.get('month', '?')}개월"
                f" (구독일 {_ShortDate(dictFound.get('createdDate'))})")
        elif objResult.get("bAll"):
            self.lblSubscribe.setText("구독자가 아니에요")
        else:
            self.lblSubscribe.setText(f"최근 구독 순 {objResult.get('nChecked', 0)}명 안에는 없어요 (더 있을 수 있어요)")
