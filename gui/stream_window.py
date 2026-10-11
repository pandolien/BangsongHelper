"""
방송 도우미 창 (채팅 + 후원 목록 + 미션을 한 화면에)
=====================================================

    ┌──────────────── 방송 도우미 ────────────────┐
    │ 10:00 [미션 진행 중] ...   (항상 보여요)       │
    ├──────────────┬───────────────────────────────┤
    │              │ 후원 목록 (대기 2)              │
    │  실시간 채팅  ├───────────────────────────────┤
    │              │ 미션 (1)                        │
    └──────────────┴───────────────────────────────┘

- 왼쪽: 실시간 채팅 (닉네임을 누르면 임시 제한 · 가리기 메뉴). 연결 상태와 [연결] 버튼도 여기 있어요.
- 오른쪽 위: 후원 목록 / 오른쪽 아래: 미션 (탭 없이 둘 다 한 번에 보여요)
- 경계선(가운데 세로 · 오른쪽 가로)을 끌어서 크기를 바꿀 수 있어요.
- 미션의 큰 타이머는 맨 위 타이머 줄과 겹쳐서 숨기고, 미션 설정은 [설정 열기] 로 접고 펴요.
- 맨 위에는 진행 중인 미션 타이머를 항상 작게 보여줘요.

이 창이 열려 있는 동안 채팅 연결을 붙잡아요. (안쪽 화면들은 따로 연결을 잡지 않아요)
"""

from typing import Optional

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QLabel, QSplitter, QVBoxLayout, QWidget

from gui.chat_hub import ChatHub
from gui.chat_window import ChatWindow
from gui.donation_window import DonationWindow
from gui.mission_window import MissionWindow

N_TAB_DONATION, N_TAB_MISSION = 0, 1   # 어느 쪽을 보여줄지 (예전 탭 번호와 같은 값)


class StreamToolsWindow(QWidget):
    sigCountsChanged = Signal(int, int)  # (후원 대기 수, 남은 미션 수) — 메인 창 버튼 숫자용

    def __init__(self, objHub: ChatHub, objChatView: ChatWindow, objDonationView: DonationWindow,
                 objMissionView: MissionWindow, objParent: Optional[QWidget] = None):
        super().__init__(objParent, Qt.WindowType.Window)
        self.setWindowTitle("방송 도우미")
        self.resize(1240, 820)
        self.objHub = objHub
        self.objChatView = objChatView
        self.objDonationView = objDonationView
        self.objMissionView = objMissionView
        self.nPending = objDonationView.nPendingCount
        self.nActiveMissions = 0

        objLayout = QVBoxLayout(self)
        objLayout.setContentsMargins(6, 6, 6, 6)

        # 맨 위: 진행 중인 미션 타이머 (항상 보여요)
        self.lblMissionBar = QLabel()
        self.lblMissionBar.setWordWrap(True)
        self.lblMissionBar.hide()
        objLayout.addWidget(self.lblMissionBar)

        # 안쪽 화면들: 따로 뜨는 창 → 이 창 안의 화면으로, 연결은 이 창이 잡아요.
        for objView in (objChatView, objDonationView, objMissionView):
            objView.bManageHub = False
            objView.setWindowFlags(Qt.WindowType.Widget)
        objDonationView.SetConnectRowVisible(False)  # 연결 상태 · 버튼은 채팅 쪽에 하나만
        objDonationView.SetCompact(True)
        objMissionView.SetCompact(True)

        # 오른쪽: 위 후원 목록 / 아래 미션 (가로 경계선을 끌어서 높이 조절)
        self.grpDonation = self._WrapInGroup(objDonationView, "후원 목록")
        self.grpMission = self._WrapInGroup(objMissionView, "미션")
        self.objRightSplitter = QSplitter(Qt.Orientation.Vertical)
        self.objRightSplitter.addWidget(self.grpDonation)
        self.objRightSplitter.addWidget(self.grpMission)
        self.objRightSplitter.setSizes([380, 340])
        self.objRightSplitter.setChildrenCollapsible(False)

        # 왼쪽 채팅 | 오른쪽 후원 · 미션 (세로 경계선을 끌어서 너비 조절)
        self.objSplitter = QSplitter(Qt.Orientation.Horizontal)
        self.objSplitter.addWidget(objChatView)
        self.objSplitter.addWidget(self.objRightSplitter)
        self.objSplitter.setStretchFactor(0, 2)
        self.objSplitter.setStretchFactor(1, 3)
        self.objSplitter.setSizes([460, 780])
        self.objSplitter.setChildrenCollapsible(False)
        objLayout.addWidget(self.objSplitter, 1)

        objDonationView.sigPendingChanged.connect(self._OnPendingChanged)
        objMissionView.sigActiveChanged.connect(self._OnActiveMissionsChanged)
        objMissionView.sigTimerText.connect(self._OnMissionTimer)
        objMissionView._UpdateSummary()    # 저장돼 있던 미션 수를 바로 반영
        objMissionView.strLastBarText = None  # 위쪽 타이머 줄을 지금 상태로 한 번 다시 보내게 해요.
        objMissionView._UpdateBigTimer()
        objDonationView._UpdateSummary()

    # -------------------------------------------------------------------
    @staticmethod
    def _WrapInGroup(objView: QWidget, strTitle: str) -> QGroupBox:
        """화면을 제목 달린 상자에 넣어요. (제목에 대기 · 미션 수를 보여줘요)"""
        grpBox = QGroupBox(strTitle)
        grpBox.setStyleSheet("QGroupBox { font-weight: bold; } QGroupBox QWidget { font-weight: normal; }")
        objLayout = QVBoxLayout(grpBox)
        objLayout.setContentsMargins(4, 4, 4, 4)
        objLayout.addWidget(objView)
        return grpBox

    def ShowTab(self, nTab: Optional[int] = None) -> None:
        """창을 열고 (이미 열려 있으면 앞으로) 보여줘요. nTab 쪽(후원 / 미션) 표에 바로 손이 가게 해요."""
        self.show()
        self.raise_()
        self.activateWindow()
        if nTab == N_TAB_DONATION:
            self.objDonationView.tblDonations.setFocus()
        elif nTab == N_TAB_MISSION:
            self.objMissionView.tblMissions.setFocus()

    def _OnPendingChanged(self, nWait: int) -> None:
        self.nPending = nWait
        self.grpDonation.setTitle(f"후원 목록 (대기 {nWait})" if nWait else "후원 목록")
        self.sigCountsChanged.emit(self.nPending, self.nActiveMissions)

    def _OnActiveMissionsChanged(self, nActive: int) -> None:
        self.nActiveMissions = nActive
        self.grpMission.setTitle(f"미션 ({nActive})" if nActive else "미션")
        self.sigCountsChanged.emit(self.nPending, self.nActiveMissions)

    def _OnMissionTimer(self, strHtml: str) -> None:
        self.lblMissionBar.setText(strHtml)
        self.lblMissionBar.setVisible(bool(strHtml))

    # -------------------------------------------------------------------
    def showEvent(self, objEvent) -> None:  # noqa: N802
        # 최소화했다 다시 띄운 것(spontaneous)은 빼요. ('연결 끊기' 한 걸 멋대로 다시 잇지 않게)
        if not objEvent.spontaneous():
            self.objHub.Join(self)
        super().showEvent(objEvent)

    def closeEvent(self, objEvent) -> None:  # noqa: N802
        self.objHub.Leave(self)
        # 유튜브는 채팅을 가져올 때마다 하루 사용량이 들어서, 창을 닫으면 끊어요.
        objYouTubeHub = getattr(self.objChatView, "objYouTubeHub", None)
        if objYouTubeHub is not None:
            objYouTubeHub.Disconnect()
        super().closeEvent(objEvent)
