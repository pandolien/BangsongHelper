"""
테스트 도구 창
==============

실제 후원이나 문제 상황을 기다리지 않고, 프로그램이 제대로 반응하는지 시험해 보는 창이에요.

① 가짜 후원 · 채팅 보내기
    - 내 프로그램 안에서만 보여요. (치지직에는 아무것도 안 보내요)
    - 후원 목록 · 채팅창에 '(테스트)' 로 표시되고, 파일에 저장되지 않아요.

② 실패 상황 흉내
    - 후원 권한 없음(403) / 연결 끊김 → 다시 연결 / 연결 오류 / 로그인 풀림
    - 화면이 어떻게 알려주는지 확인하고 [원래 상태로] 로 되돌려요.

③ 실제 연결 점검
    - 치지직에 진짜로 접속해서 로그인 → 접속 주소 → 채팅 받기 → 후원 받기 를 하나씩 확인해요.
    - 점검용으로 연결을 하나 더 잠깐 써요. (치지직은 한 사람당 동시에 3개까지)
"""

from datetime import datetime
from typing import Callable, Optional

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from chzzk import ChzzkChatMessage, ChzzkChatSession, ChzzkDonationMessage
from gui.chat_hub import ChatHub

N_CHECK_TIMEOUT_MS = 15000   # 실제 연결 점검을 최대 몇 초 기다릴지
N_FAKE_RECONNECT_MS = 3000   # '연결 끊김' 흉내 후 몇 초 뒤에 다시 연결된 척할지
STR_TEST_TAG = "[테스트]"


class _CheckBridge(QObject):
    """점검용 연결(뒤쪽 스레드)의 소식을 화면 스레드로 넘겨줘요."""
    sigStatus = Signal(str, str)
    sigDonationState = Signal(object, str)


class TestDialog(QDialog):
    def __init__(self, objHub: ChatHub, fnLog: Optional[Callable[[str], None]] = None,
                 objParent: Optional[QWidget] = None):
        super().__init__(objParent)
        self.setWindowTitle("테스트 도구")
        self.resize(560, 620)
        self.objHub = objHub
        self.fnLog = fnLog or (lambda strMessage: None)
        self.objCheckSession: Optional[ChzzkChatSession] = None
        self.dictCheck = {}
        self.objCheckBridge = _CheckBridge()
        self.objCheckBridge.sigStatus.connect(self._OnCheckStatus)
        self.objCheckBridge.sigDonationState.connect(self._OnCheckDonationState)
        self.objCheckTimer = QTimer(self)
        self.objCheckTimer.setSingleShot(True)
        self.objCheckTimer.timeout.connect(lambda: self._FinishCheck("시간 초과 — 치지직이 15초 안에 답하지 않았어요."))
        self._BuildUi()

    # ===================================================================
    # 화면
    # ===================================================================
    def _BuildUi(self) -> None:
        objLayout = QVBoxLayout(self)

        # --- ① 가짜 후원 · 채팅 ---
        objFakeBox = QGroupBox("① 가짜 후원 · 채팅 보내기 (내 프로그램에서만 보여요, 저장 안 됨)")
        objFakeGrid = QGridLayout(objFakeBox)
        self.editNick = QLineEdit("테스트시청자")
        self.spinAmount = QSpinBox()
        self.spinAmount.setRange(0, 10_000_000)
        self.spinAmount.setSingleStep(1000)
        self.spinAmount.setValue(1000)
        self.spinAmount.setSuffix(" 원")
        self.editText = QLineEdit("테스트 영상 제목 / 후원 메시지")
        objFakeGrid.addWidget(QLabel("닉네임"), 0, 0)
        objFakeGrid.addWidget(self.editNick, 0, 1)
        objFakeGrid.addWidget(QLabel("금액"), 0, 2)
        objFakeGrid.addWidget(self.spinAmount, 0, 3)
        objFakeGrid.addWidget(QLabel("내용"), 1, 0)
        objFakeGrid.addWidget(self.editText, 1, 1, 1, 3)
        objFakeRow = QHBoxLayout()
        for strLabel, strType in (("영상 후원", "VIDEO"), ("채팅 후원", "CHAT"), ("미션 후원", "MISSION")):
            btnItem = QPushButton(strLabel)
            btnItem.clicked.connect(lambda _=False, strType=strType: self.SendFakeDonation(strType))
            objFakeRow.addWidget(btnItem)
        btnFakeChat = QPushButton("채팅 한 줄")
        btnFakeChat.clicked.connect(self.SendFakeChat)
        objFakeRow.addWidget(btnFakeChat)
        objFakeGrid.addLayout(objFakeRow, 2, 0, 1, 4)
        btnClearTest = QPushButton("테스트 후원 · 미션 지우기")
        btnClearTest.clicked.connect(self.OnClearTestClicked)
        objFakeGrid.addWidget(btnClearTest, 3, 0, 1, 4)
        objLayout.addWidget(objFakeBox)

        # --- ② 실패 상황 흉내 ---
        objFailBox = QGroupBox("② 실패 상황 흉내 (화면이 어떻게 알려주는지 확인)")
        objFailGrid = QGridLayout(objFailBox)
        listFails = [
            ("후원 권한 없음 (403)", self.FakeDonationDenied),
            ("연결 끊김 → 다시 연결", self.FakeReconnect),
            ("연결 오류", lambda: self._FakeStatus("error", f"{STR_TEST_TAG} 채팅 연결 문제: 인터넷 연결이 끊겼어요.")),
            ("로그인 풀림", lambda: self._FakeStatus("error", f"{STR_TEST_TAG} 토큰 갱신 실패 - 다시 로그인해 주세요.")),
        ]
        for nIndex, (strLabel, fnAction) in enumerate(listFails):
            btnItem = QPushButton(strLabel)
            btnItem.clicked.connect(fnAction)
            objFailGrid.addWidget(btnItem, nIndex // 2, nIndex % 2)
        btnRestore = QPushButton("원래 상태로")
        btnRestore.setStyleSheet("font-weight: bold;")
        btnRestore.clicked.connect(self.RestoreRealState)
        objFailGrid.addWidget(btnRestore, 2, 0, 1, 2)
        objLayout.addWidget(objFailBox)

        # --- ③ 실제 연결 점검 ---
        objCheckBox = QGroupBox("③ 실제 연결 점검 (치지직에 진짜로 접속해서 확인)")
        objCheckLayout = QVBoxLayout(objCheckBox)
        self.btnCheck = QPushButton("연결 점검 시작")
        self.btnCheck.clicked.connect(self.StartCheck)
        objCheckLayout.addWidget(self.btnCheck)
        self.txtCheck = QPlainTextEdit()
        self.txtCheck.setReadOnly(True)
        self.txtCheck.setPlaceholderText("로그인 → 접속 주소 → 채팅 받기 → 후원 받기 를 하나씩 확인해요.")
        objCheckLayout.addWidget(self.txtCheck, 1)
        objLayout.addWidget(objCheckBox, 1)

    # ===================================================================
    # ① 가짜 후원 · 채팅
    # ===================================================================
    def SendFakeDonation(self, strType: str) -> None:
        objDonation = ChzzkDonationMessage(
            strNickname=self.editNick.text().strip() or "테스트시청자",
            nPayAmount=self.spinAmount.value(),
            strText=self.editText.text(),
            strDonationType=strType,
            dtTime=datetime.now(),
            dictRaw={"donationType": strType, "test": True},
            bTest=True,
        )
        # 진짜 후원과 똑같은 길(공유기 신호)로 보내요 → 채팅창 · 후원 목록이 진짜처럼 반응해요.
        self.objHub.sigDonation.emit(objDonation)
        self.fnLog(f"{STR_TEST_TAG} 가짜 {strType} 후원 보냄: {objDonation.strNickname} {objDonation.nPayAmount:,}원")

    def SendFakeChat(self) -> None:
        objMessage = ChzzkChatMessage(
            strNickname=self.editNick.text().strip() or "테스트시청자",
            strContent=f"{STR_TEST_TAG} {self.editText.text()}",
            strUserRole="common_user",
            strSenderChannelId="test-viewer",
            dtTime=datetime.now(),
            # chatChannelId 를 비워 둬요 → 닉네임 메뉴의 제한 · 가리기가 꺼져서 진짜 요청이 나가지 않아요.
            strChatChannelId="",
        )
        self.objHub.sigChat.emit(objMessage)

    def OnClearTestClicked(self) -> None:
        objParent = self.parent()
        fnRemove = getattr(objParent, "RemoveTestRecords", None)
        if fnRemove is None:
            self.fnLog(f"{STR_TEST_TAG} 후원 목록 창에서 테스트 도구를 열어야 지울 수 있어요.")
            return
        nRemoved = fnRemove()
        fnRemoveMissions = getattr(objParent, "fnRemoveTestMissions", None)
        nMissions = fnRemoveMissions() if fnRemoveMissions else 0
        self.fnLog(f"{STR_TEST_TAG} 테스트 후원 {nRemoved}건 · 테스트 미션 {nMissions}개를 지웠어요.")

    # ===================================================================
    # ② 실패 상황 흉내
    # ===================================================================
    def _FakeStatus(self, strState: str, strMessage: str) -> None:
        self.objHub.sigStatus.emit(strState, strMessage)

    def FakeDonationDenied(self) -> None:
        self.objHub.sigDonationState.emit(
            False, f"{STR_TEST_TAG} 개발자 센터에서 '후원 조회' 권한을 켜고, 프로그램에서 로그아웃 → 다시 로그인해 주세요.")
        self._FakeStatus("connected", f"{STR_TEST_TAG} 후원 알림 없이 채팅만 받아요 (개발자 센터 '후원 조회' 권한 필요)")

    def FakeReconnect(self) -> None:
        self._FakeStatus("reconnecting", f"{STR_TEST_TAG} {N_FAKE_RECONNECT_MS // 1000}초 뒤에 다시 연결해요...")
        QTimer.singleShot(N_FAKE_RECONNECT_MS,
                          lambda: self._FakeStatus("connected", f"{STR_TEST_TAG} 다시 연결됐어요. 채팅 받기 시작!"))

    def RestoreRealState(self) -> None:
        """흉내 낸 상태를 지우고, 공유기의 진짜 연결 상태로 화면을 되돌려요."""
        if self.objHub.bIsRunning:
            # 진짜 후원 신청 결과는 다시 연결해야 정확히 알 수 있어요. (흉내가 기억을 덮어썼을 수 있어서)
            self.objHub.Connect()
            self.fnLog(f"{STR_TEST_TAG} 원래 상태로: 다시 연결해서 진짜 상태를 확인해요.")
        else:
            self.objHub.sigDonationState.emit(None, "")
            self._FakeStatus("stopped", "")
            self.fnLog(f"{STR_TEST_TAG} 원래 상태로: 연결 안 됨")

    # ===================================================================
    # ③ 실제 연결 점검
    # ===================================================================
    def _CheckLog(self, strText: str) -> None:
        self.txtCheck.appendPlainText(strText)

    def StartCheck(self) -> None:
        self.txtCheck.clear()
        objClient = self.objHub.fnGetClient()
        if objClient is None:
            self._CheckLog("[실패] 치지직 Client ID / Secret 이 없어요. 메인 창 [설정] 메뉴에서 입력해 주세요.")
            return
        if not objClient.bIsLoggedIn:
            self._CheckLog("[실패] 로그인 안 됨 → 메인 창 맨 위 [치지직 로그인] 을 눌러 주세요.")
            return
        self._CheckLog("[성공] 1. 로그인 돼 있어요.")
        self._CheckLog("[진행] 2. 채팅 서버 접속 주소를 받는 중...")
        self.dictCheck = {"bChat": False, "bDone": False}
        self.btnCheck.setEnabled(False)
        self.objCheckSession = ChzzkChatSession(
            objClient,
            fnOnStatus=self.objCheckBridge.sigStatus.emit,
            fnOnDonationState=self.objCheckBridge.sigDonationState.emit,
        )
        self.objCheckSession.Start()
        self.objCheckTimer.start(N_CHECK_TIMEOUT_MS)

    def _OnCheckStatus(self, strState: str, strMessage: str) -> None:
        if self.dictCheck.get("bDone"):
            return
        if strState == "connected" and "채팅" in strMessage and not self.dictCheck["bChat"]:
            self.dictCheck["bChat"] = True
            self._CheckLog("[성공] 2. 접속 주소를 받고 채팅 서버에 연결했어요.")
            self._CheckLog("[성공] 3. 채팅 받기 신청 성공 (채팅 메시지 조회 권한 OK)")
            self._CheckLog("[진행] 4. 후원 받기 신청 결과를 기다리는 중...")
        elif strState == "error":
            self._CheckLog(f"[실패] 오류: {strMessage}")
            self._FinishCheck("")

    def _OnCheckDonationState(self, objOk, strReason: str) -> None:
        if self.dictCheck.get("bDone") or objOk is None:
            return
        if objOk:
            self._CheckLog("[성공] 4. 후원 받기 신청 성공 (후원 조회 권한 OK) — 영상 · 채팅 후원이 들어와요.")
        else:
            self._CheckLog(f"[실패] 4. 후원 받기 신청 실패 — {strReason}")
        self._FinishCheck("")

    def _FinishCheck(self, strExtra: str) -> None:
        if self.dictCheck.get("bDone"):
            return
        self.dictCheck["bDone"] = True
        self.objCheckTimer.stop()
        if strExtra:
            self._CheckLog(f"[실패] {strExtra}")
        if self.objCheckSession is not None:
            self.objCheckSession.Stop()  # 점검용 연결은 바로 닫아요.
            self.objCheckSession = None
        self._CheckLog("— 점검 끝 —")
        self.btnCheck.setEnabled(True)
        self.fnLog(f"{STR_TEST_TAG} 연결 점검: " + " / ".join(
            strLine for strLine in self.txtCheck.toPlainText().splitlines() if strLine.startswith(("[성공]", "[실패]"))))

    def closeEvent(self, objEvent) -> None:  # noqa: N802
        if self.objCheckSession is not None:
            self._FinishCheck("창을 닫아서 점검을 멈췄어요.")
        super().closeEvent(objEvent)
