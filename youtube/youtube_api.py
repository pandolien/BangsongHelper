"""
유튜브(YouTube) 공식 Data API v3 — 라이브 채팅 읽기
====================================================

필요한 것: Google Cloud 의 'YouTube Data API v3' API 키 하나 (구글 계정 로그인은 필요 없어요)
    공개 방송의 채팅은 API 키만으로 읽을 수 있어요.

순서
    1) 방송 주소 → 영상 ID          (예: https://www.youtube.com/watch?v=XXXXXXXXXXX → XXXXXXXXXXX)
       채널 주소(@이름)만 있으면 → 그 채널에서 지금 방송 중인 영상을 찾아요. (사용량 100점이라 비싸요)
    2) 영상 ID → 채팅방 ID           (videos.list, 1점)
    3) 채팅방 ID → 채팅 가져오기      (liveChatMessages.list, 5점) 를 유튜브가 알려준 간격마다 반복

하루 사용량(quota)
    구글 프로젝트마다 하루 10,000점. 채팅 가져오기 한 번에 5점이라 간격을 너무 짧게 하면 금방 바닥나요.
    매일 미국 태평양 시간 자정(한국 오후 4~5시)에 다시 채워져요.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import requests

DICT_DEFAULT_YOUTUBE_URLS = {
    "data_api_base": "https://www.googleapis.com/youtube/v3",
}

F_DEFAULT_TIMEOUT_SEC = 10.0

# API 호출 하나당 사용량(점)
DICT_QUOTA_COST = {"videos": 1, "channels": 1, "search": 100, "liveChat/messages": 5}

# 유튜브 오류 이유 → 알기 쉬운 말
DICT_REASON_TEXT = {
    "quotaExceeded": "오늘 유튜브 API 사용량(10,000점)을 다 썼어요. 한국 시간 오후 4~5시쯤 다시 채워져요.",
    "dailyLimitExceeded": "오늘 유튜브 API 사용량을 다 썼어요. 한국 시간 오후 4~5시쯤 다시 채워져요.",
    "rateLimitExceeded": "유튜브에 너무 자주 요청했어요. 잠시 후 다시 시도해요.",
    "keyInvalid": "유튜브 API 키가 올바르지 않아요. [설정] 탭의 키를 확인해 주세요.",
    "keyExpired": "유튜브 API 키가 만료됐어요. Google Cloud 에서 새 키를 만들어 주세요.",
    "accessNotConfigured": "Google Cloud 프로젝트에서 'YouTube Data API v3' 를 사용 설정해 주세요.",
    "liveChatEnded": "방송이 끝나서 채팅이 닫혔어요.",
    "liveChatDisabled": "이 방송은 채팅이 꺼져 있어요.",
    "liveChatNotFound": "채팅방을 찾을 수 없어요. 방송 주소를 확인해 주세요.",
    "forbidden": "이 채팅을 읽을 권한이 없어요. (비공개 · 회원 전용 방송일 수 있어요)",
    "videoNotFound": "영상을 찾을 수 없어요. 방송 주소를 확인해 주세요.",
}
# 다시 시도해도 소용없는 오류 (연결을 멈춰요)
SET_FATAL_REASONS = {"quotaExceeded", "dailyLimitExceeded", "keyInvalid", "keyExpired", "accessNotConfigured",
                     "liveChatEnded", "liveChatDisabled", "liveChatNotFound", "forbidden", "videoNotFound"}

RE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class YouTubeApiError(Exception):
    """유튜브 API 오류. strReason: 유튜브가 준 오류 이유 (예: quotaExceeded), nHttpStatus: HTTP 번호"""

    def __init__(self, strMessage: str, strReason: str = "", nHttpStatus: Optional[int] = None):
        super().__init__(strMessage)
        self.strReason = strReason
        self.nHttpStatus = nHttpStatus

    @property
    def bFatal(self) -> bool:
        return self.strReason in SET_FATAL_REASONS


@dataclass
class YouTubeLiveInfo:
    """방송 하나의 정보."""
    strVideoId: str
    strLiveChatId: str
    strTitle: str
    strChannelTitle: str


@dataclass
class YouTubeChatMessage:
    """유튜브 채팅 한 줄 (또는 슈퍼챗)."""
    strNickname: str
    strText: str
    dtTime: datetime
    strAuthorChannelId: str = ""
    bOwner: bool = False         # 방송 주인
    bModerator: bool = False     # 모더레이터
    bMember: bool = False        # 채널 멤버
    bVerified: bool = False      # 인증 배지
    strType: str = "textMessageEvent"   # textMessageEvent / superChatEvent / superStickerEvent / newSponsorEvent ...
    strAmountText: str = ""      # 슈퍼챗 금액 글자 (예: "₩10,000")
    nAmountMicros: int = 0       # 슈퍼챗 금액 × 1,000,000
    strCurrency: str = ""        # 슈퍼챗 통화 (예: KRW)

    @property
    def bIsSuperChat(self) -> bool:
        return self.strType in ("superChatEvent", "superStickerEvent")

    @property
    def nAmountKrw(self) -> int:
        """원화 슈퍼챗이면 원 단위 금액, 다른 통화면 0 (환율은 계산하지 않아요)"""
        return self.nAmountMicros // 1_000_000 if self.strCurrency == "KRW" else 0

    @property
    def strRoleName(self) -> str:
        if self.bOwner:
            return "주인"
        if self.bModerator:
            return "모더"
        if self.bMember:
            return "멤버"
        return ""


def ParseVideoInput(strInput: str) -> Tuple[str, str]:
    """사람이 넣은 글자를 해석해요. 돌려주는 값: ("video", 영상ID) / ("handle", "@이름") / ("channel", "UC...") / ("", "")

    되는 모양:
        https://www.youtube.com/watch?v=XXXXXXXXXXX   https://youtu.be/XXXXXXXXXXX
        https://www.youtube.com/live/XXXXXXXXXXX      XXXXXXXXXXX (영상 ID 만)
        https://www.youtube.com/@채널이름  /  @채널이름 (→ 지금 방송 중인 영상을 찾아요)
        https://www.youtube.com/channel/UCxxxxxxxx
    """
    strInput = (strInput or "").strip()
    if not strInput:
        return "", ""
    objMatch = re.search(r"(?:[?&]v=|youtu\.be/|/live/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", strInput)
    if objMatch:
        return "video", objMatch.group(1)
    objMatch = re.search(r"/channel/(UC[A-Za-z0-9_-]{20,})", strInput)
    if objMatch:
        return "channel", objMatch.group(1)
    objMatch = re.search(r"(?:^|/)(@[A-Za-z0-9._\-가-힣]+)", strInput)
    if objMatch:
        return "handle", objMatch.group(1)
    if RE_VIDEO_ID.match(strInput):
        return "video", strInput
    if re.match(r"^UC[A-Za-z0-9_-]{20,}$", strInput):
        return "channel", strInput
    return "", ""


def _ParseTime(strValue: str) -> datetime:
    """'2026-10-11T08:00:00.123+00:00' → 내 컴퓨터 시간"""
    try:
        return datetime.fromisoformat(strValue.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except (ValueError, AttributeError):
        return datetime.now()


def ParseChatItem(dictItem: dict) -> Optional[YouTubeChatMessage]:
    """liveChatMessages.list 의 item 하나 → 채팅 상자. (화면에 안 보여줄 종류면 None)"""
    dictSnippet = dictItem.get("snippet") or {}
    dictAuthor = dictItem.get("authorDetails") or {}
    strType = dictSnippet.get("type", "")
    if strType in ("chatEndedEvent", "messageDeletedEvent", "userBannedEvent", "tombstone", "pollEvent"):
        return None
    strText = dictSnippet.get("displayMessage") or ""
    strAmountText, nMicros, strCurrency = "", 0, ""
    if strType == "superChatEvent":
        dictSuper = dictSnippet.get("superChatDetails") or {}
        strAmountText = dictSuper.get("amountDisplayString", "")
        nMicros = int(dictSuper.get("amountMicros") or 0)
        strCurrency = dictSuper.get("currency", "")
        strText = dictSuper.get("userComment") or ""
    elif strType == "superStickerEvent":
        dictSticker = dictSnippet.get("superStickerDetails") or {}
        strAmountText = dictSticker.get("amountDisplayString", "")
        nMicros = int(dictSticker.get("amountMicros") or 0)
        strCurrency = dictSticker.get("currency", "")
        strText = ((dictSticker.get("superStickerMetadata") or {}).get("altText")) or "(슈퍼 스티커)"
    return YouTubeChatMessage(
        strNickname=dictAuthor.get("displayName") or "(알 수 없음)",
        strText=strText,
        dtTime=_ParseTime(dictSnippet.get("publishedAt", "")),
        strAuthorChannelId=dictAuthor.get("channelId", ""),
        bOwner=bool(dictAuthor.get("isChatOwner")),
        bModerator=bool(dictAuthor.get("isChatModerator")),
        bMember=bool(dictAuthor.get("isChatSponsor")),
        bVerified=bool(dictAuthor.get("isVerified")),
        strType=strType or "textMessageEvent",
        strAmountText=strAmountText,
        nAmountMicros=nMicros,
        strCurrency=strCurrency,
    )


class YouTubeApiClient:
    """유튜브 Data API 심부름꾼.

    fnOnQuota(점수): API 를 부를 때마다 쓴 사용량을 알려줘요. (오늘 사용량 기록용)
    """

    def __init__(self, strApiKey: str, dictUrls: Optional[dict] = None, fTimeoutSec: float = F_DEFAULT_TIMEOUT_SEC,
                 fnOnQuota=None):
        strApiKey = (strApiKey or "").strip()
        if not strApiKey:
            raise YouTubeApiError("유튜브 API 키가 비어 있어요. [설정] 탭에서 넣어 주세요.", "keyMissing")
        self.strApiKey = strApiKey
        self.fTimeoutSec = fTimeoutSec
        self.fnOnQuota = fnOnQuota or (lambda nCost: None)
        self.dictUrls = dict(DICT_DEFAULT_YOUTUBE_URLS)
        for strKey, strValue in (dictUrls or {}).items():
            if isinstance(strValue, str) and strValue.strip():
                self.dictUrls[strKey] = strValue.strip()
        self.objSession = requests.Session()

    # -------------------------------------------------------------------
    def _Get(self, strPath: str, dictParams: dict) -> dict:
        strUrl = self.dictUrls["data_api_base"].rstrip("/") + "/" + strPath
        self.fnOnQuota(DICT_QUOTA_COST.get(strPath, 1))  # 실패한 요청도 사용량이 들어요.
        try:
            objResponse = self.objSession.get(strUrl, params=dict(dictParams, key=self.strApiKey), timeout=self.fTimeoutSec)
        except requests.Timeout as objError:
            raise YouTubeApiError(f"유튜브 서버가 {self.fTimeoutSec:.0f}초 안에 답하지 않았어요.", "timeout") from objError
        except requests.RequestException as objError:
            raise YouTubeApiError("유튜브 서버에 연결할 수 없어요. 인터넷 연결을 확인해 주세요.", "network") from objError
        try:
            dictBody = objResponse.json()
        except ValueError:
            dictBody = {}
        if objResponse.status_code != 200:
            dictError = dictBody.get("error") or {}
            listErrors = dictError.get("errors") or [{}]
            strReason = listErrors[0].get("reason", "") or dictError.get("status", "")
            strText = DICT_REASON_TEXT.get(strReason) or f"유튜브 오류 (HTTP {objResponse.status_code}): {dictError.get('message', '')}"
            raise YouTubeApiError(strText, strReason, objResponse.status_code)
        return dictBody

    # -------------------------------------------------------------------
    def ResolveChannelId(self, strHandle: str) -> str:
        """@이름 → 채널 ID (1점)"""
        dictBody = self._Get("channels", {"part": "id", "forHandle": strHandle})
        listItems = dictBody.get("items") or []
        if not listItems:
            raise YouTubeApiError(f"'{strHandle}' 채널을 찾을 수 없어요.", "channelNotFound")
        return listItems[0]["id"]

    def FindLiveVideoOfChannel(self, strChannelId: str) -> str:
        """채널에서 지금 방송 중인 영상 ID 찾기 (100점! 방송 주소를 직접 넣으면 아낄 수 있어요)"""
        dictBody = self._Get("search", {"part": "id", "channelId": strChannelId, "eventType": "live",
                                        "type": "video", "maxResults": 1})
        listItems = dictBody.get("items") or []
        if not listItems:
            raise YouTubeApiError("이 채널은 지금 방송 중이 아니에요.", "notLive")
        return listItems[0]["id"]["videoId"]

    def GetLiveInfo(self, strVideoId: str) -> YouTubeLiveInfo:
        """영상 ID → 채팅방 ID · 제목 (1점)"""
        dictBody = self._Get("videos", {"part": "liveStreamingDetails,snippet", "id": strVideoId})
        listItems = dictBody.get("items") or []
        if not listItems:
            raise YouTubeApiError(DICT_REASON_TEXT["videoNotFound"], "videoNotFound")
        dictItem = listItems[0]
        dictSnippet = dictItem.get("snippet") or {}
        strChatId = (dictItem.get("liveStreamingDetails") or {}).get("activeLiveChatId", "")
        if not strChatId:
            raise YouTubeApiError("이 영상은 지금 라이브 채팅이 없어요. (방송 중이 아니거나 채팅이 꺼져 있어요)", "noActiveChat")
        return YouTubeLiveInfo(strVideoId, strChatId, dictSnippet.get("title", ""), dictSnippet.get("channelTitle", ""))

    def ResolveLive(self, strInput: str) -> YouTubeLiveInfo:
        """방송 주소 / 채널 주소 → 방송 정보 (채팅방 ID 포함)"""
        strKind, strValue = ParseVideoInput(strInput)
        if strKind == "video":
            return self.GetLiveInfo(strValue)
        if strKind == "handle":
            return self.GetLiveInfo(self.FindLiveVideoOfChannel(self.ResolveChannelId(strValue)))
        if strKind == "channel":
            return self.GetLiveInfo(self.FindLiveVideoOfChannel(strValue))
        raise YouTubeApiError("유튜브 방송 주소(또는 @채널이름)를 알아볼 수 없어요.", "badInput")

    def ListChatMessages(self, strLiveChatId: str, strPageToken: str = "") -> Tuple[List[YouTubeChatMessage], str, int]:
        """채팅 가져오기 (5점). 돌려주는 값: (채팅들, 다음 페이지표, 다음 요청까지 기다릴 밀리초)"""
        dictParams = {"liveChatId": strLiveChatId, "part": "snippet,authorDetails", "maxResults": 2000}
        if strPageToken:
            dictParams["pageToken"] = strPageToken
        dictBody = self._Get("liveChat/messages", dictParams)
        listMessages = [objMessage for objMessage in (ParseChatItem(dictItem) for dictItem in dictBody.get("items") or [])
                        if objMessage is not None]
        if dictBody.get("offlineAt"):
            raise YouTubeApiError(DICT_REASON_TEXT["liveChatEnded"], "liveChatEnded")
        return listMessages, dictBody.get("nextPageToken", ""), int(dictBody.get("pollingIntervalMillis") or 5000)


def QuotaDayKey() -> str:
    """유튜브 사용량은 미국 태평양 시간 기준으로 하루가 바뀌어요. 그 날짜를 'YYYY-MM-DD' 로 (서머타임은 대충 -8시간으로)"""
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(hours=8)).strftime("%Y-%m-%d")
