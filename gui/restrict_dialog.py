"""
활동 제한 목록 창
==================

'활동 제한' 한 시청자를 보여주고, 골라서 풀어줄 수 있어요. (권한: 활동제한 조회 / 활동제한 쓰기)
임시 제한은 짧게(30초~) 끝나서 치지직이 목록을 주지 않아요. 채팅창에서 닉네임을 눌러 풀 수 있어요.
"""

from typing import Callable, List, Optional

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from chzzk import ChzzkApiClient, ChzzkApiError
from gui.bg_task import RunTask

STR_SCOPE_HINT = "개발자 센터에서 '활동제한 조회 · 활동제한 쓰기 · 채팅 메시지 쓰기' 권한을 켜고, 프로그램에서 로그아웃 → 다시 로그인해 주세요."


def ExplainRestrictError(objError: Exception) -> str:
    """제한 관련 에러를 알기 쉬운 말로. (권한이 없으면 해결 방법도 같이)"""
    if isinstance(objError, ChzzkApiError) and objError.nHttpStatus == 403:
        return f"{objError}\n→ {STR_SCOPE_HINT}"
    return str(objError)


def _ShortDate(strValue: Optional[str]) -> str:
    """'2026-10-10T17:30:00' → '2026-10-10 17:30' (없으면 '풀 때까지')"""
    if not strValue:
        return "풀 때까지"
    return str(strValue).replace("T", " ")[:16]


class RestrictDialog(QDialog):
    def __init__(self, fnGetClient: Callable[[], Optional[ChzzkApiClient]],
                 fnLog: Optional[Callable[[str], None]] = None, objParent: Optional[QWidget] = None):
        super().__init__(objParent)
        self.setWindowTitle("활동 제한 목록")
        self.resize(520, 420)
        self.fnGetClient = fnGetClient
        self.fnLog = fnLog or (lambda strMessage: None)
        self.listTasks = []
        self.listRows: List[dict] = []

        objLayout = QVBoxLayout(self)
        self.lblInfo = QLabel("불러오는 중...")
        self.lblInfo.setWordWrap(True)
        objLayout.addWidget(self.lblInfo)

        self.tblRestrict = QTableWidget(0, 3)
        self.tblRestrict.setHorizontalHeaderLabels(["닉네임", "제한한 날", "풀리는 날"])
        self.tblRestrict.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tblRestrict.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tblRestrict.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tblRestrict.verticalHeader().setVisible(False)
        self.tblRestrict.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        objLayout.addWidget(self.tblRestrict, 1)

        objButtonRow = QHBoxLayout()
        self.btnReload = QPushButton("새로고침")
        self.btnReload.clicked.connect(self.Reload)
        self.btnRelease = QPushButton("선택한 시청자 제한 풀기")
        self.btnRelease.clicked.connect(self.OnReleaseClicked)
        btnClose = QPushButton("닫기")
        btnClose.clicked.connect(self.close)
        objButtonRow.addWidget(self.btnReload)
        objButtonRow.addWidget(self.btnRelease)
        objButtonRow.addStretch()
        objButtonRow.addWidget(btnClose)
        objLayout.addLayout(objButtonRow)

        self.Reload()

    def _Client(self) -> Optional[ChzzkApiClient]:
        objClient = self.fnGetClient()
        if objClient is None or not objClient.bIsLoggedIn:
            self.lblInfo.setText("치지직 로그인이 필요해요. 메인 창 맨 위 [치지직 로그인] 을 눌러 주세요.")
            return None
        return objClient

    def Reload(self) -> None:
        objClient = self._Client()
        if objClient is None:
            return
        self.btnReload.setEnabled(False)
        self.lblInfo.setText("불러오는 중...")

        def _Done(objResult):
            self.btnReload.setEnabled(True)
            if isinstance(objResult, Exception):
                self.lblInfo.setText(f"<span style='color:#e03131'>불러오기 실패: {ExplainRestrictError(objResult)}</span>")
                return
            self.listRows = list(objResult)
            self.tblRestrict.setRowCount(len(self.listRows))
            for nRow, dictItem in enumerate(self.listRows):
                listCells = [dictItem.get("restrictedChannelName") or dictItem.get("restrictedChannelId", ""),
                             _ShortDate(dictItem.get("createdDate")), _ShortDate(dictItem.get("releaseDate"))]
                for nCol, strCell in enumerate(listCells):
                    self.tblRestrict.setItem(nRow, nCol, QTableWidgetItem(strCell))
            self.lblInfo.setText(f"활동 제한 중인 시청자 {len(self.listRows)}명. "
                                 "(임시 제한은 금방 풀려서 여기엔 안 나와요)")

        RunTask(self.listTasks, objClient.ListRestrictions, _Done)

    def OnReleaseClicked(self) -> None:
        listRows = sorted({objIndex.row() for objIndex in self.tblRestrict.selectionModel().selectedRows()})
        if not listRows:
            QMessageBox.information(self, "안내", "제한을 풀 시청자를 목록에서 골라 주세요.")
            return
        listTargets = [self.listRows[nRow] for nRow in listRows]
        strNames = ", ".join(dictItem.get("restrictedChannelName") or "?" for dictItem in listTargets)
        if QMessageBox.question(self, "확인", f"{strNames} 님의 활동 제한을 풀까요?") != QMessageBox.StandardButton.Yes:
            return
        objClient = self._Client()
        if objClient is None:
            return
        self.btnRelease.setEnabled(False)

        def _ReleaseAll():
            listFailed = []
            for dictItem in listTargets:
                try:
                    objClient.RemoveRestriction(dictItem["restrictedChannelId"])
                except ChzzkApiError as objError:
                    listFailed.append((dictItem.get("restrictedChannelName") or "?", objError))
            return listFailed

        def _Done(objResult):
            self.btnRelease.setEnabled(True)
            if isinstance(objResult, Exception):
                QMessageBox.warning(self, "오류", ExplainRestrictError(objResult))
            elif objResult:
                QMessageBox.warning(self, "일부 실패", "\n".join(f"{strName}: {ExplainRestrictError(objError)}"
                                                              for strName, objError in objResult))
            self.fnLog(f"[제한] 활동 제한 풀기: {strNames}")
            self.Reload()

        RunTask(self.listTasks, _ReleaseAll, _Done)
