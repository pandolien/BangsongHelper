"""
치지직 실시간 채팅 받기 (세션 / Socket.IO)
===========================================

채팅을 '받는' 방법은 '보내는' 방법과 달라요.
    보내기 : 편지 한 통 보내고 끝 (HTTP 요청)
    받기   : 전화를 걸어 놓고 계속 듣고 있어야 해요 (소켓 연결)

순서 (전화 걸기에 비유하면)
    1) 치지직에게 "전화번호 주세요" → GetSessionUrl() 로 접속 주소를 받아요.
    2) 그 주소로 전화를 걸어요(소켓 연결).
    3) 치지직이 "SYSTEM / connected" 로 '세션 키(통화 번호표)' 를 알려줘요.
    4) 세션 키로 "채팅 들려주세요", "후원도 들려주세요" 하고 신청(구독)해요.
    5) 이제 채팅이 올 때마다 "CHAT" 이벤트, 후원은 "DONATION" 이벤트가 와요.
    6) 전화가 끊기면 잠깐 쉬었다가 1번부터 다시 해요. (자동 재연결)

주의
    - 치지직은 Socket.IO 2.x 방식만 지원해서 python-socketio 4.x 버전을 써야 해요.
    - 개발자 센터에서 '채팅 메시지 조회' (후원은 '후원 조회') 권한을 켜고,
      권한을 바꿨다면 프로그램에서 다시 로그인해야 해요.
    - 한 사람당 동시에 3개까지만 연결할 수 있어요.
"""

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

import socketio

from .chzzk_api import ChzzkApiClient, ChzzkApiError, ChzzkAuthRequiredError

# 재연결할 때 기다리는 시간(초): 3초 → 6초 → 12초 → ... 최대 60초
N_RECONNECT_FIRST_SEC = 3
N_RECONNECT_MAX_SEC = 60

# 채팅 안의 이모티콘 자리표시 모양: {:이모티콘이름:}
RE_EMOJI_PLACEHOLDER = re.compile(r"\{:([^:{}]+):\}")

# 채팅 보낸 사람의 역할 → 한국어 이름
DICT_ROLE_NAMES = {
    "streamer": "스트리머",
    "streaming_channel_manager": "매니저",
    "streaming_chat_manager": "채팅 매니저",
    "common_user": "",
}


# ---------------------------------------------------------------------------
# 받은 메시지를 담는 상자
# ---------------------------------------------------------------------------

@dataclass
class ChzzkChatMessage:
    """채팅 한 줄."""

    strNickname: str
    strContent: str              # 이모티콘 자리표시({:이름:})가 들어있는 원래 글자
    strUserRole: str             # streamer / streaming_channel_manager / common_user ...
    strSenderChannelId: str
    dtTime: datetime
    dictEmojis: Dict[str, str] = field(default_factory=dict)  # 이모티콘 이름 → 그림 주소
    listBadgeUrls: List[str] = field(default_factory=list)
    bVerified: bool = False
    strChatChannelId: str = ""   # 임시 제한 · 메시지 가리기에 써요.
    nMessageTime: int = 0        # 메시지 보낸 시각(밀리초 그대로). 메시지 가리기에 써요.

    @property
    def strRoleName(self) -> str:
        return DICT_ROLE_NAMES.get(self.strUserRole, "")

    @property
    def strPlainContent(self) -> str:
        """이모티콘을 [이름] 글자로 바꾼 내용 (터미널 출력용)."""
        return RE_EMOJI_PLACEHOLDER.sub(lambda objMatch: f"[{objMatch.group(1)}]", self.strContent)


@dataclass
class ChzzkDonationMessage:
    """후원 한 건."""

    strNickname: str
    nPayAmount: int              # 원 단위
    strText: str
    strDonationType: str         # CHAT(채팅 후원) / VIDEO(영상 후원) / 그 밖의 종류는 받은 그대로 (예: MISSION)
    dtTime: datetime
    dictEmojis: Dict[str, str] = field(default_factory=dict)
    dictRaw: Dict = field(default_factory=dict)  # 받은 원본 (문서에 없는 새 종류가 오면 모양을 확인하려고)
    bTest: bool = False          # 테스트 도구로 만든 가짜 후원이면 True (저장하지 않아요)

    @property
    def bIsKnownType(self) -> bool:
        """공식 문서에 있는 종류(CHAT / VIDEO)인지."""
        return self.strDonationType in ("CHAT", "VIDEO")


def _ToDict(objData) -> dict:
    """치지직은 내용을 'JSON 글자' 로 보낼 때도 있고 'dict' 로 보낼 때도 있어서 둘 다 dict 로 맞춰요."""
    if isinstance(objData, dict):
        return objData
    if isinstance(objData, (str, bytes)):
        try:
            objParsed = json.loads(objData)
            return objParsed if isinstance(objParsed, dict) else {}
        except ValueError:
            return {}
    return {}


def ParseChatMessage(objData) -> ChzzkChatMessage:
    dictData = _ToDict(objData)
    dictProfile = dictData.get("profile") or {}
    if isinstance(dictProfile, str):  # 프로필이 또 한 번 JSON 글자로 싸여 오는 경우
        dictProfile = _ToDict(dictProfile)
    nTimeMs = int(dictData.get("messageTime") or 0)
    return ChzzkChatMessage(
        strNickname=dictProfile.get("nickname") or "(알 수 없음)",
        strContent=dictData.get("content") or "",
        strUserRole=dictData.get("userRoleCode") or "common_user",
        strSenderChannelId=dictData.get("senderChannelId") or "",
        dtTime=datetime.fromtimestamp(nTimeMs / 1000) if nTimeMs else datetime.now(),
        dictEmojis=dict(dictData.get("emojis") or {}),
        listBadgeUrls=[dictBadge.get("imageUrl", "") for dictBadge in (dictProfile.get("badges") or [])
                       if isinstance(dictBadge, dict)],
        bVerified=bool(dictProfile.get("verifiedMark")),
        strChatChannelId=dictData.get("chatChannelId") or "",
        nMessageTime=nTimeMs,
    )


def ParseDonationMessage(objData) -> ChzzkDonationMessage:
    dictData = _ToDict(objData)
    try:
        nPayAmount = int(str(dictData.get("payAmount") or "0").replace(",", ""))
    except ValueError:
        nPayAmount = 0
    return ChzzkDonationMessage(
        strNickname=dictData.get("donatorNickname") or "익명",
        nPayAmount=nPayAmount,
        strText=dictData.get("donationText") or "",
        # 공식 문서에는 CHAT / VIDEO 뿐이지만, 다른 종류(미션 등)가 오면 바꾸지 않고 그대로 둬요.
        strDonationType=str(dictData.get("donationType") or "CHAT").upper(),
        dtTime=datetime.now(),
        dictEmojis=dict(dictData.get("emojis") or {}),
        dictRaw=dict(dictData),
    )


# ---------------------------------------------------------------------------
# 실시간 채팅 연결 관리자
# ---------------------------------------------------------------------------

class ChzzkChatSession:
    """치지직 채팅을 실시간으로 듣고 있는 '전화기' 예요.

    사용 예:
        objSession = ChzzkChatSession(objClient, fnOnChat=print)
        objSession.Start()   # 뒤에서(다른 스레드) 계속 듣기 시작
        ...
        objSession.Stop()    # 그만 듣기

    알림 함수들 (모두 '뒤쪽 스레드' 에서 불려요. GUI 라면 신호(Signal)로 넘겨서 화면을 고쳐야 해요)
        fnOnChat(ChzzkChatMessage)       : 채팅이 왔을 때
        fnOnDonation(ChzzkDonationMessage): 후원이 왔을 때
        fnOnStatus(str 상태, str 설명)    : 연결 상태가 바뀔 때
        fnOnDonationState(bool, str 이유) : 후원 알림 신청 결과 (False 면 후원이 안 와요. 보통 '후원 조회' 권한 문제)
            상태: "connecting" / "connected" / "reconnecting" / "stopped" / "error"
    """

    def __init__(
        self,
        objClient: ChzzkApiClient,
        fnOnChat: Optional[Callable[[ChzzkChatMessage], None]] = None,
        fnOnDonation: Optional[Callable[[ChzzkDonationMessage], None]] = None,
        fnOnStatus: Optional[Callable[[str, str], None]] = None,
        bSubscribeDonation: bool = True,
        fnOnDonationState: Optional[Callable[[bool, str], None]] = None,
    ):
        self.objClient = objClient
        self.fnOnChat = fnOnChat
        self.fnOnDonation = fnOnDonation
        self.fnOnStatus = fnOnStatus
        self.bSubscribeDonation = bSubscribeDonation
        self.fnOnDonationState = fnOnDonationState

        self.objStopEvent = threading.Event()   # "이제 그만!" 깃발
        self.objThread: Optional[threading.Thread] = None
        self.objSocket: Optional[socketio.Client] = None
        self.strSessionKey: Optional[str] = None

    @property
    def bIsRunning(self) -> bool:
        return self.objThread is not None and self.objThread.is_alive()

    # -------------------------------------------------------------------
    # 시작 / 끝
    # -------------------------------------------------------------------
    def Start(self) -> None:
        if self.bIsRunning:
            return
        self.objStopEvent.clear()
        self.objThread = threading.Thread(target=self._RunLoop, name="ChzzkChatSession", daemon=True)
        self.objThread.start()

    def Stop(self) -> None:
        self.objStopEvent.set()
        objSocket = self.objSocket
        if objSocket is not None:
            try:
                objSocket.disconnect()
            except Exception:  # 이미 끊겼으면 괜찮아요.
                pass

    # -------------------------------------------------------------------
    # 뒤쪽 스레드에서 도는 '연결 → 듣기 → 끊기면 다시' 반복
    # -------------------------------------------------------------------
    def _RunLoop(self) -> None:
        nWaitSec = N_RECONNECT_FIRST_SEC
        while not self.objStopEvent.is_set():
            self._NotifyStatus("connecting", "채팅 서버에 연결하는 중...")
            try:
                self._ConnectOnce()          # 연결이 끊길 때까지 여기서 기다려요.
                nWaitSec = N_RECONNECT_FIRST_SEC  # 한 번이라도 잘 붙었으면 기다리는 시간 초기화
            except ChzzkAuthRequiredError as objError:
                # 로그인이 풀린 경우엔 다시 시도해도 소용없어요.
                self._NotifyStatus("error", str(objError))
                break
            except ChzzkApiError as objError:
                strHint = ""
                if objError.nHttpStatus == 403:
                    strHint = " → 개발자 센터에서 '채팅 메시지 조회' 권한을 켜고 다시 로그인해 주세요."
                self._NotifyStatus("error", f"{objError}{strHint}")
                if objError.nHttpStatus in (401, 403):
                    break
            except Exception as objError:  # 소켓 쪽 문제 (인터넷 끊김 등)
                self._NotifyStatus("error", f"채팅 연결 문제: {objError}")

            if self.objStopEvent.is_set():
                break
            self._NotifyStatus("reconnecting", f"{nWaitSec}초 뒤에 다시 연결해요...")
            self.objStopEvent.wait(nWaitSec)
            nWaitSec = min(nWaitSec * 2, N_RECONNECT_MAX_SEC)

        self._NotifyStatus("stopped", "채팅 연결을 끝냈어요.")

    def _ConnectOnce(self) -> None:
        """한 번 연결해서, 끊길 때까지 듣고 있어요."""
        strUrl = self.objClient.GetSessionUrl()

        # 치지직 권장 설정: 자동 재연결은 끄고(주소가 일회용이라), 웹소켓으로만 연결
        objSocket = socketio.Client(reconnection=False)
        self.objSocket = objSocket
        self.strSessionKey = None

        @objSocket.on("SYSTEM")
        def _OnSystem(objData):
            dictData = _ToDict(objData)
            strType = dictData.get("type")
            dictInner = _ToDict(dictData.get("data"))
            if strType == "connected":
                # 통화 번호표(세션 키)를 받았어요 → 이걸로 채팅/후원을 신청해요.
                self.strSessionKey = dictInner.get("sessionKey")
                threading.Thread(target=self._Subscribe, daemon=True).start()
            elif strType == "subscribed":
                strEvent = dictInner.get("eventType", "")
                if strEvent == "DONATION":
                    self._NotifyDonationState(True, "")
                self._NotifyStatus("connected", f"{'채팅' if strEvent == 'CHAT' else '후원'} 받기 시작!")
            elif strType == "revoked":
                self._NotifyStatus("error", "권한이 취소됐어요. 개발자 센터 권한을 확인하고 다시 로그인해 주세요.")

        @objSocket.on("CHAT")
        def _OnChat(objData):
            if self.fnOnChat:
                self.fnOnChat(ParseChatMessage(objData))

        @objSocket.on("DONATION")
        def _OnDonation(objData):
            if self.fnOnDonation:
                self.fnOnDonation(ParseDonationMessage(objData))

        objSocket.connect(strUrl, transports=["websocket"])
        if self.objStopEvent.is_set():
            objSocket.disconnect()
            return
        objSocket.wait()  # 연결이 끊길 때까지 기다려요.
        self.objSocket = None

    def _Subscribe(self) -> None:
        """세션 키로 채팅(그리고 후원) 이벤트를 신청해요."""
        if not self.strSessionKey:
            self._NotifyStatus("error", "세션 키를 받지 못했어요.")
            return
        try:
            self.objClient.SubscribeChatEvent(self.strSessionKey)
        except ChzzkApiError as objError:
            strHint = " → '채팅 메시지 조회' 권한을 켜고 다시 로그인해 주세요." if objError.nHttpStatus == 403 else ""
            self._NotifyStatus("error", f"채팅 구독 실패: {objError}{strHint}")
            return
        if self.bSubscribeDonation:
            try:
                self.objClient.SubscribeDonationEvent(self.strSessionKey)
            except ChzzkApiError as objError:
                # 후원 권한이 없어도 채팅은 계속 볼 수 있게 해요.
                if objError.nHttpStatus == 403:
                    strReason = "개발자 센터에서 '후원 조회' 권한을 켜고, 프로그램에서 로그아웃 → 다시 로그인해 주세요."
                    self._NotifyStatus("connected", "후원 알림 없이 채팅만 받아요 (개발자 센터 '후원 조회' 권한 필요)")
                else:
                    strReason = f"후원 알림 구독 실패: {objError}"
                    self._NotifyStatus("connected", strReason)
                self._NotifyDonationState(False, strReason)

    def _NotifyDonationState(self, bOk: bool, strReason: str) -> None:
        if self.fnOnDonationState:
            try:
                self.fnOnDonationState(bOk, strReason)
            except Exception:
                pass

    def _NotifyStatus(self, strState: str, strMessage: str) -> None:
        if self.fnOnStatus:
            try:
                self.fnOnStatus(strState, strMessage)
            except Exception:
                pass
