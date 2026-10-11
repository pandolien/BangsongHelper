"""
유튜브 채팅 연결 공유기 (YouTubeHub)
====================================

유튜브 채팅(뒤쪽 스레드)의 소식을 화면 스레드로 넘겨줘요. 치지직 ChatHub 와 같은 역할이에요.

    sigChat(YouTubeChatMessage)   : 일반 채팅 → 채팅창에 [YT] 로 보여줘요.
    sigDonation(ChzzkDonationMessage): 슈퍼챗을 '후원' 모양으로 바꾼 것 → 후원 목록 · 미션 · 채팅창 노란 줄
    sigStatus(상태, 설명)
    sigQuota(오늘 사용량)

유튜브는 채팅을 가져올 때마다 사용량(하루 10,000점)이 들어서, 방송 도우미 창을 닫으면 연결도 끊어요.
"""

from typing import Callable, Optional

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import QObject, Signal

from chzzk import ChzzkDonationMessage
from youtube import YouTubeApiClient, YouTubeApiError, YouTubeChatMessage, YouTubeChatSession, YouTubeQuotaTracker

STR_YOUTUBE_DONATION_TYPE = "YOUTUBE"  # 후원 목록에서 유튜브 슈퍼챗을 나타내는 종류


def SuperChatToDonation(objMessage: YouTubeChatMessage) -> ChzzkDonationMessage:
    """유튜브 슈퍼챗 → 후원 목록 · 미션이 알아듣는 '후원' 상자. 원화가 아니면 금액은 0, 원래 금액은 글자로 붙여요."""
    strText = objMessage.strText
    if objMessage.strCurrency != "KRW" and objMessage.strAmountText:
        strText = f"{strText} ({objMessage.strAmountText})" if strText else f"({objMessage.strAmountText})"
    return ChzzkDonationMessage(
        strNickname=objMessage.strNickname,
        nPayAmount=objMessage.nAmountKrw,
        strText=strText,
        strDonationType=STR_YOUTUBE_DONATION_TYPE,
        dtTime=objMessage.dtTime,
        dictRaw={"source": "youtube", "type": objMessage.strType, "amount": objMessage.strAmountText,
                 "currency": objMessage.strCurrency, "micros": objMessage.nAmountMicros},
    )


class YouTubeHub(QObject):
    sigChat = Signal(object)
    sigDonation = Signal(object)
    sigStatus = Signal(str, str)
    sigQuota = Signal(int)

    def __init__(self, fnGetConfig: Callable[[], dict]):
        """fnGetConfig: 지금 설정(dict) 을 돌려주는 함수 (API 키 · 최소 간격 · URL 을 그때그때 읽어요)"""
        super().__init__()
        self.fnGetConfig = fnGetConfig
        self.objSession: Optional[YouTubeChatSession] = None
        self.objQuota = YouTubeQuotaTracker()
        self.strLastState = "stopped"
        self.sigStatus.connect(self._Remember)

    def _Remember(self, strState: str, _strMessage: str) -> None:
        self.strLastState = strState

    @property
    def bIsRunning(self) -> bool:
        return self.objSession is not None and self.objSession.bIsRunning

    @property
    def nQuotaUsed(self) -> int:
        return self.objQuota.nUsedToday

    def _OnQuota(self, nCost: int) -> None:  # 뒤쪽 스레드에서 불려요 → 신호로 넘겨요.
        self.sigQuota.emit(self.objQuota.Add(nCost))

    def Connect(self, strInput: str) -> bool:
        """유튜브 방송 주소(또는 @채널이름)로 채팅을 받기 시작해요."""
        dictConfig = self.fnGetConfig()
        dictYouTube = dictConfig.get("youtube", {})
        try:
            objClient = YouTubeApiClient(dictYouTube.get("api_key", ""), dictUrls=dictConfig.get("urls", {}).get("youtube"),
                                         fnOnQuota=self._OnQuota)
        except YouTubeApiError as objError:
            self.sigStatus.emit("error", str(objError))
            return False
        if not strInput.strip():
            self.sigStatus.emit("error", "[설정] → 유튜브 방송 주소(또는 @채널이름)를 넣고 저장해 주세요.")
            return False
        self.Disconnect()
        objSession = YouTubeChatSession(objClient, strInput.strip(),
                                        fMinIntervalSec=float(dictYouTube.get("min_interval_sec") or 8))
        # 지금 연결에서 온 소식만 받아요. (끊은 예전 연결이 늦게 보내는 '연결 끝' 이 새 연결 상태를 덮어쓰지 않게)
        objSession.fnOnChat = lambda objMessage: self.objSession is objSession and self.sigChat.emit(objMessage)
        objSession.fnOnSuperChat = lambda objMessage: self.objSession is objSession and \
            self.sigDonation.emit(SuperChatToDonation(objMessage))
        objSession.fnOnStatus = lambda strState, strMessage: self.objSession is objSession and \
            self.sigStatus.emit(strState, strMessage)
        self.objSession = objSession
        objSession.Start()
        return True

    def Disconnect(self) -> None:
        if self.objSession is not None:
            self.objSession.Stop()
            self.objSession = None
            self.sigStatus.emit("stopped", "")
