"""
실시간 채팅 연결 '공유기' (ChatHub)
====================================

채팅창과 후원 목록 창이 '같은 연결 하나' 를 나눠 써요.
    - 치지직은 한 사람당 동시에 3개까지만 연결할 수 있어서, 창마다 따로 연결하면 금방 모자라요.
    - 연결은 여기 하나만 있고, 창들은 신호(Signal)를 받아서 각자 화면에 그려요.

규칙
    - 창이 열리면 Join(창) → 아직 연결 전이면 연결해요.
    - 창이 닫히면 Leave(창) → 열려 있는 창이 하나도 없으면 연결을 끊어요.
"""

from typing import Callable, Optional, Set

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
# (PySide6 를 먼저 부르면 socketio 가 쓰는 six 라이브러리와 충돌해서 프로그램이 꺼져요)
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import QObject, Signal

from chzzk import ChzzkApiClient, ChzzkChatSession


class ChatHub(QObject):
    """뒤쪽 스레드(채팅 연결)의 소식을 화면 스레드의 여러 창에게 나눠주는 공유기."""

    sigChat = Signal(object)        # ChzzkChatMessage
    sigDonation = Signal(object)    # ChzzkDonationMessage
    sigStatus = Signal(str, str)    # 상태, 설명
    sigDonationState = Signal(object, str)  # 후원 알림을 받을 수 있는지 (True / False / None=아직 모름), 이유

    def __init__(self, fnGetClient: Callable[[], Optional[ChzzkApiClient]]):
        super().__init__()
        # 지금 쓰는 치지직 심부름꾼을 그때그때 물어봐요. (설정을 바꾸면 바뀔 수 있어서)
        self.fnGetClient = fnGetClient
        self.objSession: Optional[ChzzkChatSession] = None
        self.setUsers: Set[object] = set()     # 지금 연결을 쓰고 있는 창들
        self.strLastState = "stopped"          # 새로 열린 창에 지금 상태를 보여주려고 기억해 둬요.
        self.objDonationOk: Optional[bool] = None  # 후원 알림 신청 결과 (None = 아직 모름)
        self.strDonationReason = ""
        self.sigStatus.connect(self._RememberStatus)
        self.sigDonationState.connect(self._RememberDonationState)

    @property
    def bIsRunning(self) -> bool:
        return self.objSession is not None and self.objSession.bIsRunning

    def _RememberStatus(self, strState: str, _strMessage: str) -> None:
        self.strLastState = strState

    def _RememberDonationState(self, objOk, strReason: str) -> None:
        self.objDonationOk, self.strDonationReason = objOk, strReason

    # -------------------------------------------------------------------
    # 연결 / 끊기
    # -------------------------------------------------------------------
    def Connect(self) -> bool:
        """연결해요. 로그인이 안 돼 있으면 오류 상태를 알리고 False."""
        objClient = self.fnGetClient()
        if objClient is None or not objClient.bIsLoggedIn:
            self.sigStatus.emit("error", "치지직 로그인이 필요해요. 메인 창 [방송 관리] 탭에서 로그인해 주세요.")
            return False
        self._StopSession()
        self.sigDonationState.emit(None, "")  # 새 연결이니 후원 신청 결과는 다시 확인해요.
        # 뒤쪽 스레드에서 불리는 알림 → 신호로 화면 스레드에 넘겨요.
        self.objSession = ChzzkChatSession(
            objClient,
            fnOnChat=self.sigChat.emit,
            fnOnDonation=self.sigDonation.emit,
            fnOnStatus=self.sigStatus.emit,
            fnOnDonationState=self.sigDonationState.emit,
        )
        self.objSession.Start()
        return True

    def Disconnect(self) -> None:
        if self._StopSession():
            self.sigStatus.emit("stopped", "")

    def _StopSession(self) -> bool:
        if self.objSession is None:
            return False
        self.objSession.Stop()
        self.objSession = None
        return True

    # -------------------------------------------------------------------
    # 창이 열리고 닫힐 때
    # -------------------------------------------------------------------
    def Join(self, objUser: object) -> None:
        """창이 열렸어요 → 연결이 없으면 연결해요."""
        self.setUsers.add(objUser)
        if not self.bIsRunning:
            self.Connect()

    def Leave(self, objUser: object) -> None:
        """창이 닫혔어요 → 남은 창이 없으면 연결을 끊어요. (보이지 않는 연결이 남지 않게)"""
        self.setUsers.discard(objUser)
        if not self.setUsers:
            self.Disconnect()
