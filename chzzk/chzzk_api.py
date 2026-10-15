"""
치지직(CHZZK) Open API 연동 모듈
==================================

이 파일이 하는 일 (한 줄 요약)
    "치지직 방송이 켜져 있는지, 제목·카테고리·시청자 수는 몇인지 알아내고,
     (로그인했다면) 방송 제목을 바꾸거나 채팅을 보낼 수 있게 해준다."

꼭 알아야 할 두 종류의 '출입증'
    ① Client 인증 (Client-Id + Client-Secret 헤더)
       - 개발자 센터에서 앱을 만들면 받는 '앱 출입증' 이에요.
       - 누구나 볼 수 있는 정보(라이브 목록, 채널 정보, 카테고리 검색)에 써요.
    ② Access Token 인증 (Authorization: Bearer xxx 헤더)
       - 방송하는 '본인' 이 치지직에 로그인해서 "이 앱이 내 방송을 관리해도 돼요" 라고
         허락해야 받을 수 있는 '본인 출입증' 이에요.
       - 방송 제목 바꾸기, 채팅 보내기, 공지 등록처럼 '내 방송을 건드리는' 일에 써요.
       - 하루(86400초)가 지나면 만료되므로, Refresh Token 으로 새로 받아야 해요.
         (이 모듈이 자동으로 해줍니다!)

[중요] 라이브 상세(live-detail) 에 대한 사실
    공식 Open API 에는 "특정 채널 하나의 방송 상태" 를 바로 알려주는 주소가 없어요.
    (공식 /open/v1/lives 는 '지금 방송 중인 전체 목록' 을 시청자 많은 순으로 줄 뿐이에요.)
    그래서 이 모듈은:
      - 1순위: 치지직 웹사이트가 내부적으로 쓰는 live-detail 주소(비공식)를 사용하고,
      - 2순위: 그게 실패하면 공식 /open/v1/lives 목록을 몇 페이지 뒤져서 찾아봅니다.
    비공식 주소는 치지직이 예고 없이 바꿀 수 있다는 점을 기억해 주세요.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional
from urllib.parse import urlencode

import requests


# ---------------------------------------------------------------------------
# 상수(바뀌지 않는 값) 모음
# ---------------------------------------------------------------------------

# 치지직 주소(URL) 기본값 모음.
# 실제로는 data/init.json 의 "urls" → "chzzk" 값이 있으면 그걸 먼저 써요.
# (치지직이 주소를 바꿔도 코드를 고치지 않고 init.json 만 고치면 되도록!)
#   - *_base / authorize : 완전한 주소
#   - 나머지             : 기본 주소(base) 뒤에 붙는 '경로'
#   - live_detail 의 {channelId} 자리에는 채널 ID 가 들어가요.
DICT_DEFAULT_CHZZK_URLS = {
    "open_api_base": "https://openapi.chzzk.naver.com",          # 공식 Open API 주소
    "service_api_base": "https://api.chzzk.naver.com",           # 웹사이트 내부(비공식) 주소
    "authorize": "https://chzzk.naver.com/account-interlock",    # 로그인(권한 허락) 페이지
    "live_detail": "/service/v2/channels/{channelId}/live-detail",  # (service_api_base 뒤) 비공식
    "lives": "/open/v1/lives",
    "channels": "/open/v1/channels",
    "category_search": "/open/v1/categories/search",
    "token": "/auth/v1/token",
    "token_revoke": "/auth/v1/token/revoke",
    "live_setting": "/open/v1/lives/setting",
    "chat_send": "/open/v1/chats/send",
    "chat_notice": "/open/v1/chats/notice",
    "chat_settings": "/open/v1/chats/settings",
    "session_auth": "/open/v1/sessions/auth",                        # 실시간 채팅 받기용 접속 주소 발급
    "session_subscribe_chat": "/open/v1/sessions/events/subscribe/chat",
    "session_subscribe_donation": "/open/v1/sessions/events/subscribe/donation",
    "session_subscribe_subscription": "/open/v1/sessions/events/subscribe/subscription",
    "subscribers": "/open/v1/channels/subscribers",
    "chat_blind": "/open/v1/chats/blind-message",                    # 채팅 메시지 가리기
    "temporary_restrict": "/open/v1/temporary-restrict-channels",    # 임시 제한 (30초 → 60초 ... 치지직이 정함)
    "restrict": "/open/v1/restrict-channels",                        # 활동 제한
}

F_DEFAULT_TIMEOUT_SEC = 10.0

# 토큰 만료 '조금 전에' 미리 새로 받아두기 위한 여유 시간(초)
N_TOKEN_REFRESH_MARGIN_SEC = 60

# 채팅 한 번에 보낼 수 있는 최대 글자 수 (공식 문서 기준)
N_MAX_CHAT_LENGTH = 100

# 일부 서버는 '브라우저인 척' 하지 않으면 요청을 막아요.
STR_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

# 카테고리 종류 (방송 설정 변경 시 사용)
LIST_CATEGORY_TYPES = ["GAME", "SPORTS", "ETC"]

# 토큰 갱신 때 서버가 이 번호로 답하면 = 'Refresh Token 이 틀렸거나 만료됨' → 다시 로그인해야 해요.
# (그 밖의 실패 = 인터넷 끊김, 서버 점검 등 잠깐 문제 → 토큰을 지우지 않아요)
SET_TOKEN_REJECTED_STATUS = {400, 401, 403}


# ---------------------------------------------------------------------------
# 예외(에러) 클래스
# ---------------------------------------------------------------------------

class ChzzkApiError(Exception):
    """치지직 API 를 쓰다가 문제가 생겼을 때 던지는 에러예요.

    nHttpStatus : 서버가 준 HTTP 번호 (예: 401 = 출입증 문제, 404 = 없음)
                  인터넷 자체가 안 될 때는 None 이에요.
    """

    def __init__(self, strMessage: str, nHttpStatus: Optional[int] = None):
        super().__init__(strMessage)
        self.nHttpStatus = nHttpStatus


class ChzzkAuthRequiredError(ChzzkApiError):
    """'본인 출입증(Access Token)' 이 필요한데 없을 때 던지는 에러예요.
    이 에러가 나오면 → 로그인(계정 연동)을 먼저 해야 한다는 뜻!
    """


# ---------------------------------------------------------------------------
# 결과를 담는 상자(데이터 클래스)
# ---------------------------------------------------------------------------

@dataclass
class ChzzkLiveStatus:
    """채널 하나의 '지금 방송 상태' 를 담는 상자예요."""

    strChannelId: str
    strChannelName: str
    strStatus: str                   # "OPEN"(방송 중) 또는 "CLOSE"(방송 꺼짐)
    strLiveTitle: str                # 방송 제목
    strCategoryType: Optional[str]   # GAME / SPORTS / ETC
    strLiveCategory: Optional[str]   # 카테고리 ID (예: "League_of_Legends")
    strLiveCategoryValue: Optional[str]  # 카테고리 한글 이름 (예: "리그 오브 레전드")
    nConcurrentUserCount: int        # 지금 보고 있는 시청자 수
    strOpenDate: Optional[str]       # 방송 시작 시각
    strSource: str                   # 어디서 가져온 정보인지 ("live-detail" / "open-lives")

    @property
    def bIsLive(self) -> bool:
        return self.strStatus == "OPEN"

    def ToDisplayText(self) -> str:
        if not self.bIsLive:
            return f"[{self.strChannelName}] 지금은 방송 중이 아니에요. (마지막 제목: {self.strLiveTitle or '-'})"
        strCategory = self.strLiveCategoryValue or self.strLiveCategory or "카테고리 없음"
        return (
            f"[{self.strChannelName}] 방송 중!\n"
            f"   제목: {self.strLiveTitle}\n"
            f"   카테고리: {strCategory}\n"
            f"   시청자: {self.nConcurrentUserCount:,}명"
        )


@dataclass
class ChzzkLiveSetting:
    """내 방송의 '기본 설정' (다음 방송에도 쓰이는 제목/카테고리/태그) 상자예요."""

    strDefaultLiveTitle: str
    strCategoryType: Optional[str]
    strCategoryId: Optional[str]
    strCategoryValue: Optional[str]
    listTags: List[str] = field(default_factory=list)


@dataclass
class ChzzkCategory:
    """카테고리 검색 결과 하나."""

    strCategoryType: str
    strCategoryId: str
    strCategoryValue: str
    strPosterImageUrl: Optional[str] = None


@dataclass
class ChzzkTokenInfo:
    """로그인 후 받은 '본인 출입증' 묶음."""

    strAccessToken: str
    strRefreshToken: str
    fExpireAt: float  # 만료되는 시각 (time.time() 기준 초)

    @property
    def bIsExpired(self) -> bool:
        return time.time() >= self.fExpireAt - N_TOKEN_REFRESH_MARGIN_SEC


# ---------------------------------------------------------------------------
# 치지직 API 클라이언트
# ---------------------------------------------------------------------------

class ChzzkApiClient:
    """치지직 서버와 대화하는 '심부름꾼' 이에요.

    사용 예 (조회만):
        objClient = ChzzkApiClient("클라이언트ID", "클라이언트시크릿")
        objLive = objClient.GetLiveDetail("채널ID")
        print(objLive.ToDisplayText())

    사용 예 (방송 관리 - 로그인 필요):
        objClient.SetToken(objTokenInfo)
        objClient.UpdateLiveSetting(strDefaultLiveTitle="새 제목")
        objClient.SendChatMessage("안녕하세요!")
    """

    def __init__(
        self,
        strClientId: str,
        strClientSecret: str,
        objTokenInfo: Optional[ChzzkTokenInfo] = None,
        fnOnTokenRefreshed: Optional[Callable[[Optional[ChzzkTokenInfo]], None]] = None,
        fTimeoutSec: float = F_DEFAULT_TIMEOUT_SEC,
        dictUrls: Optional[dict] = None,
    ):
        if not strClientId or not strClientSecret:
            raise ChzzkApiError("Client ID / Client Secret 이 비어 있어요. data/init.json 의 chzzk 항목을 채워주세요.")

        self.strClientId = strClientId.strip()
        self.strClientSecret = strClientSecret.strip()
        self.objTokenInfo = objTokenInfo
        # 토큰이 새로 바뀌면 불러줄 함수 (예: data/init.json 에 저장하기)
        self.fnOnTokenRefreshed = fnOnTokenRefreshed
        self.fTimeoutSec = fTimeoutSec
        self.SetUrls(dictUrls)

        self.objSession = requests.Session()
        self.objSession.headers.update({"User-Agent": STR_USER_AGENT})

        # 자물쇠: 여러 작업이 '동시에' 토큰을 갱신하면 일회용 Refresh Token 이 두 번 쓰여 망가져요.
        # 그래서 토큰을 만질 때는 한 번에 한 명만 들어오도록 자물쇠를 채워요.
        self.objTokenLock = threading.RLock()

    def SetUrls(self, dictUrls: Optional[dict]) -> None:
        """기본 주소 위에 init.json 에서 받은 주소를 덮어써요. (빈 칸은 무시하고 기본값 유지)
        URL 만 바뀌었을 때는 심부름꾼을 새로 만들지 않고 이것만 불러요. (토큰을 그대로 이어 쓰려고)
        """
        dictNewUrls = dict(DICT_DEFAULT_CHZZK_URLS)
        for strKey, strValue in (dictUrls or {}).items():
            if isinstance(strValue, str) and strValue.strip():
                dictNewUrls[strKey] = strValue.strip()
        self.dictUrls = dictNewUrls

    # ===================================================================
    # 공통: 요청 보내기 (모든 API 가 이 함수 하나를 거쳐 가요)
    # ===================================================================

    def _OpenUrl(self, strKey: str) -> str:
        """공식 Open API 주소 만들기: 기본 주소 + 경로 (예: https://openapi... + /open/v1/lives)"""
        return self.dictUrls["open_api_base"].rstrip("/") + self.dictUrls[strKey]

    def _ServiceUrl(self, strKey: str, **kwargs) -> str:
        """비공식 서비스 주소 만들기. {channelId} 같은 빈칸은 kwargs 로 채워요."""
        return self.dictUrls["service_api_base"].rstrip("/") + self.dictUrls[strKey].format(**kwargs)

    def _BuildClientHeaders(self) -> dict:
        """'앱 출입증' 헤더를 만들어요."""
        return {
            "Client-Id": self.strClientId,
            "Client-Secret": self.strClientSecret,
            "Content-Type": "application/json",
        }

    def _BuildUserHeaders(self) -> dict:
        """'본인 출입증' 헤더를 만들어요. 만료됐으면 자동으로 새로 받아와요."""
        with self.objTokenLock:
            if self.objTokenInfo is None:
                raise ChzzkAuthRequiredError("이 기능은 치지직 계정 연동(로그인)이 필요해요.")

            if self.objTokenInfo.bIsExpired:
                self.RefreshAccessToken()

            return {
                "Authorization": f"Bearer {self.objTokenInfo.strAccessToken}",
                "Content-Type": "application/json",
            }

    def _Request(
        self,
        strMethod: str,
        strUrl: str,
        bUseUserToken: bool = False,
        dictParams: Optional[dict] = None,
        dictJson: Optional[dict] = None,
        dictExtraHeaders: Optional[dict] = None,
        bRetryOnAuthFail: bool = True,
        bSendClientAuth: bool = True,
    ):
        """실제로 편지를 보내고, 답장에서 'content'(알맹이)만 꺼내 돌려주는 함수예요.

        치지직 답장의 모양은 항상 이래요:
            {"code": 200, "message": null, "content": { ...진짜 내용... }}

        bSendClientAuth=False 면 앱 출입증(Client-Secret)을 붙이지 않아요. (비공식 주소처럼 필요 없는 곳에 비밀을 보내지 않게)
        """

        if bUseUserToken:
            dictHeaders = self._BuildUserHeaders()
        elif bSendClientAuth:
            dictHeaders = self._BuildClientHeaders()
        else:
            dictHeaders = {}
        if dictExtraHeaders:
            dictHeaders.update(dictExtraHeaders)

        try:
            objResponse = self.objSession.request(
                strMethod,
                strUrl,
                headers=dictHeaders,
                params=dictParams,
                json=dictJson,
                timeout=self.fTimeoutSec,
            )
        except requests.Timeout as objError:
            raise ChzzkApiError(f"치지직 서버가 {self.fTimeoutSec}초 안에 답하지 않았어요.") from objError
        except requests.ConnectionError as objError:
            raise ChzzkApiError("치지직 서버에 연결할 수 없어요. 인터넷 연결을 확인해 주세요.") from objError
        except requests.RequestException as objError:
            raise ChzzkApiError(f"치지직 요청 중 알 수 없는 문제가 생겼어요: {objError}") from objError

        # 401 = 출입증이 틀렸거나 만료됨.
        # 본인 토큰을 쓰던 중이라면 → 한 번만 토큰을 새로 받아서 다시 시도해 봐요.
        if objResponse.status_code == 401 and bUseUserToken and bRetryOnAuthFail and self.objTokenInfo:
            strUsedToken = dictHeaders["Authorization"].removeprefix("Bearer ")
            with self.objTokenLock:
                # 다른 작업이 이미 새 토큰을 받아놨다면, 또 갱신하지 않고 그걸 그대로 써요.
                if self.objTokenInfo and self.objTokenInfo.strAccessToken == strUsedToken:
                    self.RefreshAccessToken()
            return self._Request(
                strMethod, strUrl, bUseUserToken, dictParams, dictJson, dictExtraHeaders,
                bRetryOnAuthFail=False,  # 무한 반복 방지!
                bSendClientAuth=bSendClientAuth,
            )

        # 답장을 dict 로 바꿔요. (에러일 때도 메시지가 들어있을 수 있어서 먼저 시도)
        try:
            dictBody = objResponse.json() if objResponse.content else {}
        except ValueError:
            dictBody = {}

        if not (200 <= objResponse.status_code < 300):
            strServerMsg = dictBody.get("message") or objResponse.text[:200]
            raise ChzzkApiError(
                self._ExplainHttpError(objResponse.status_code, strServerMsg),
                nHttpStatus=objResponse.status_code,
            )

        return dictBody.get("content") if isinstance(dictBody, dict) else None

    @staticmethod
    def _ExplainHttpError(nStatus: int, strServerMsg: str) -> str:
        """HTTP 에러 번호를 초등학생도 알 수 있는 말로 바꿔줘요."""
        dictExplain = {
            400: "요청 내용이 잘못됐어요 (400)",
            401: "출입증(인증)이 틀렸거나 만료됐어요 (401)",
            403: "이 일을 할 권한이 없어요 (403) - 개발자 센터에서 API 권한(Scope)을 확인하세요",
            404: "찾는 대상이 없어요 (404)",
            429: "요청을 너무 자주 보냈어요 (429) - 잠시 후 다시 시도하세요",
        }
        strBase = dictExplain.get(nStatus, f"치지직 서버 오류 (HTTP {nStatus})")
        return f"{strBase}: {strServerMsg}" if strServerMsg else strBase

    # ===================================================================
    # 1. 조회 기능 (앱 출입증만 있으면 OK)
    # ===================================================================

    def GetLiveDetail(self, strChannelId: str, nFallbackMaxPages: int = 5) -> ChzzkLiveStatus:
        """채널 하나의 방송 상태를 가져와요.

        1순위: live-detail(비공식) → 2순위: 공식 라이브 목록에서 찾기
        """
        strChannelId = (strChannelId or "").strip()
        if not strChannelId:
            raise ChzzkApiError("채널 ID 가 비어 있어요.")

        strFirstError = ""
        try:
            return self._GetLiveDetailFromService(strChannelId)
        except ChzzkApiError as objError:
            # 1순위가 실패해도 포기하지 않고 2순위로 넘어가요.
            strFirstError = str(objError)

        objLive = self.FindLiveInOpenList(strChannelId, nMaxPages=nFallbackMaxPages)
        if objLive is not None:
            return objLive

        # 공식 목록에서도 못 찾았어요 → '방송 꺼짐' 으로 판단 (단, 시청자 적은 방송은 못 찾을 수도 있음)
        return ChzzkLiveStatus(
            strChannelId=strChannelId,
            strChannelName=self._TryGetChannelName(strChannelId),
            strStatus="CLOSE",
            strLiveTitle="",
            strCategoryType=None,
            strLiveCategory=None,
            strLiveCategoryValue=None,
            nConcurrentUserCount=0,
            strOpenDate=None,
            strSource=f"open-lives(추정, live-detail 실패: {strFirstError})",
        )

    def _GetLiveDetailFromService(self, strChannelId: str) -> ChzzkLiveStatus:
        """비공식 live-detail 주소로 방송 상세 정보를 가져와요."""
        strUrl = self._ServiceUrl("live_detail", channelId=strChannelId)
        dictContent = self._Request("GET", strUrl, bSendClientAuth=False)

        # content 가 비어 있으면 = 한 번도 방송한 적이 없는 채널이에요.
        if not dictContent:
            return ChzzkLiveStatus(
                strChannelId=strChannelId,
                strChannelName=self._TryGetChannelName(strChannelId),
                strStatus="CLOSE",
                strLiveTitle="",
                strCategoryType=None,
                strLiveCategory=None,
                strLiveCategoryValue=None,
                nConcurrentUserCount=0,
                strOpenDate=None,
                strSource="live-detail",
            )

        dictChannel = dictContent.get("channel") or {}
        return ChzzkLiveStatus(
            strChannelId=strChannelId,
            strChannelName=dictChannel.get("channelName", strChannelId),
            strStatus=dictContent.get("status", "CLOSE"),
            strLiveTitle=dictContent.get("liveTitle") or "",
            strCategoryType=dictContent.get("categoryType"),
            strLiveCategory=dictContent.get("liveCategory"),
            strLiveCategoryValue=dictContent.get("liveCategoryValue"),
            nConcurrentUserCount=int(dictContent.get("concurrentUserCount") or 0),
            strOpenDate=dictContent.get("openDate"),
            strSource="live-detail",
        )

    def GetLiveList(self, nSize: int = 20, strNext: Optional[str] = None) -> dict:
        """[공식] 지금 방송 중인 라이브 목록 한 페이지를 가져와요.

        돌려주는 값: {"data": [...], "page": {"next": "다음페이지표"}}
        """
        dictParams = {"size": max(1, min(nSize, 20))}
        if strNext:
            dictParams["next"] = strNext
        return self._Request("GET", self._OpenUrl("lives"), dictParams=dictParams) or {}

    def FindLiveInOpenList(self, strChannelId: str, nMaxPages: int = 5) -> Optional[ChzzkLiveStatus]:
        """[공식] 라이브 목록을 한 장씩 넘기며 내 채널을 찾아요. 못 찾으면 None."""
        strNext = None
        for _ in range(nMaxPages):
            dictPage = self.GetLiveList(nSize=20, strNext=strNext)
            for dictLive in dictPage.get("data", []):
                if dictLive.get("channelId") == strChannelId:
                    return ChzzkLiveStatus(
                        strChannelId=strChannelId,
                        strChannelName=dictLive.get("channelName", strChannelId),
                        strStatus="OPEN",  # 목록에 있다 = 방송 중
                        strLiveTitle=dictLive.get("liveTitle") or "",
                        strCategoryType=dictLive.get("categoryType"),
                        strLiveCategory=dictLive.get("liveCategory"),
                        strLiveCategoryValue=dictLive.get("liveCategoryValue"),
                        nConcurrentUserCount=int(dictLive.get("concurrentUserCount") or 0),
                        strOpenDate=dictLive.get("openDate"),
                        strSource="open-lives",
                    )
            strNext = (dictPage.get("page") or {}).get("next")
            if not strNext:
                break  # 마지막 페이지까지 다 봤어요.
        return None

    def GetChannels(self, listChannelIds: List[str]) -> List[dict]:
        """[공식] 채널 ID 들로 채널 정보(이름, 프로필 사진, 팔로워 수)를 가져와요."""
        dictParams = {"channelIds": ",".join(listChannelIds)}
        dictContent = self._Request("GET", self._OpenUrl("channels"), dictParams=dictParams) or {}
        return dictContent.get("data", [])

    def _TryGetChannelName(self, strChannelId: str) -> str:
        """채널 이름을 '되면 좋고, 안 되면 ID 그대로' 가져와요."""
        try:
            listChannels = self.GetChannels([strChannelId])
            if listChannels:
                return listChannels[0].get("channelName", strChannelId)
        except ChzzkApiError:
            pass
        return strChannelId

    def SearchCategory(self, strQuery: str, nSize: int = 20) -> List[ChzzkCategory]:
        """[공식] 카테고리를 이름으로 검색해요. (방송 카테고리 바꿀 때 ID 를 알아내는 용도)"""
        dictParams = {"query": strQuery, "size": max(1, min(nSize, 50))}
        dictContent = self._Request(
            "GET", self._OpenUrl("category_search"), dictParams=dictParams
        ) or {}
        return [
            ChzzkCategory(
                strCategoryType=dictItem.get("categoryType", ""),
                strCategoryId=dictItem.get("categoryId", ""),
                strCategoryValue=dictItem.get("categoryValue", ""),
                strPosterImageUrl=dictItem.get("posterImageUrl"),
            )
            for dictItem in dictContent.get("data", [])
        ]

    # ===================================================================
    # 2. 로그인(계정 연동) 관련
    # ===================================================================

    def BuildAuthorizeUrl(self, strRedirectUri: str, strState: str) -> str:
        """사용자가 브라우저에서 열어야 할 '권한 허락 페이지' 주소를 만들어요."""
        dictQuery = {"clientId": self.strClientId, "redirectUri": strRedirectUri, "state": strState}
        return f"{self.dictUrls['authorize']}?{urlencode(dictQuery)}"

    def IssueToken(self, strCode: str, strState: str) -> ChzzkTokenInfo:
        """허락 후 받은 '임시 쿠폰(code)' 을 '본인 출입증(Access Token)' 으로 바꿔요."""
        dictBody = {
            "grantType": "authorization_code",
            "clientId": self.strClientId,
            "clientSecret": self.strClientSecret,
            "code": strCode,
            "state": strState,
        }
        dictContent = self._Request("POST", self._OpenUrl("token"), dictJson=dictBody)
        return self._SaveTokenFromContent(dictContent)

    def RefreshAccessToken(self) -> ChzzkTokenInfo:
        """만료된 출입증을 Refresh Token 으로 새로 받아와요.
        주의: Refresh Token 은 '한 번 쓰면 버려지는' 일회용이라, 새로 받은 것을 꼭 저장해야 해요!
        """
        with self.objTokenLock:
            if self.objTokenInfo is None or not self.objTokenInfo.strRefreshToken:
                raise ChzzkAuthRequiredError("Refresh Token 이 없어요. 다시 로그인(계정 연동)해 주세요.")

            dictBody = {
                "grantType": "refresh_token",
                "refreshToken": self.objTokenInfo.strRefreshToken,
                "clientId": self.strClientId,
                "clientSecret": self.strClientSecret,
            }
            try:
                dictContent = self._Request("POST", self._OpenUrl("token"), dictJson=dictBody)
            except ChzzkApiError as objError:
                if objError.nHttpStatus not in SET_TOKEN_REJECTED_STATUS:
                    # 인터넷 끊김 · 서버 점검(5xx) 같은 '잠깐 문제' 는 토큰을 지우면 안 돼요.
                    # (지우면 멀쩡한 Refresh Token 까지 버려져서 다시 로그인해야 해요) → 다음에 다시 시도
                    raise ChzzkApiError(f"토큰 갱신을 잠시 못 했어요. 잠시 후 다시 시도해 주세요. ({objError})",
                                        nHttpStatus=objError.nHttpStatus) from objError
                # 서버가 'Refresh Token 이 틀렸다/만료됐다' 고 답했을 때만 → 다시 로그인하는 수밖에 없어요.
                self.objTokenInfo = None
                if self.fnOnTokenRefreshed:
                    self.fnOnTokenRefreshed(None)  # 저장된 (죽은) 토큰도 지워요.
                raise ChzzkAuthRequiredError(f"토큰 갱신 실패 - 다시 로그인해 주세요. ({objError})") from objError
            return self._SaveTokenFromContent(dictContent)

    def RevokeToken(self) -> None:
        """출입증을 '폐기' 해요 (로그아웃).
        Access Token 만 버리면 Refresh Token 으로 다시 새 출입증을 받을 수 있어서, 둘 다 버려요.
        """
        if self.objTokenInfo is None:
            return
        listTokens = [(self.objTokenInfo.strRefreshToken, "refresh_token"),
                      (self.objTokenInfo.strAccessToken, "access_token")]
        objFirstError: Optional[ChzzkApiError] = None
        try:
            for strToken, strHint in listTokens:
                if not strToken:
                    continue
                dictBody = {
                    "clientId": self.strClientId,
                    "clientSecret": self.strClientSecret,
                    "token": strToken,
                    "tokenTypeHint": strHint,
                }
                try:
                    self._Request("POST", self._OpenUrl("token_revoke"), dictJson=dictBody)
                except ChzzkApiError as objError:
                    objFirstError = objFirstError or objError  # 하나가 실패해도 나머지는 계속 버려요.
            if objFirstError is not None:
                raise objFirstError
        finally:
            self.objTokenInfo = None
            if self.fnOnTokenRefreshed:
                self.fnOnTokenRefreshed(None)

    def SetToken(self, objTokenInfo: Optional[ChzzkTokenInfo]) -> None:
        self.objTokenInfo = objTokenInfo

    @property
    def bIsLoggedIn(self) -> bool:
        return self.objTokenInfo is not None

    def _SaveTokenFromContent(self, dictContent: Optional[dict]) -> ChzzkTokenInfo:
        """토큰 응답을 상자에 담고, '바뀌었어요!' 하고 알려줘요."""
        if not dictContent or "accessToken" not in dictContent:
            raise ChzzkApiError("토큰 응답에 accessToken 이 없어요.")

        nExpiresIn = int(dictContent.get("expiresIn") or 86400)
        self.objTokenInfo = ChzzkTokenInfo(
            strAccessToken=dictContent["accessToken"],
            strRefreshToken=dictContent.get("refreshToken", ""),
            fExpireAt=time.time() + nExpiresIn,
        )
        if self.fnOnTokenRefreshed:
            self.fnOnTokenRefreshed(self.objTokenInfo)
        return self.objTokenInfo

    # ===================================================================
    # 3. 방송 관리 기능 (본인 출입증 필요)
    # ===================================================================

    def GetLiveSetting(self) -> ChzzkLiveSetting:
        """내 방송의 기본 설정(제목/카테고리/태그)을 가져와요."""
        dictContent = self._Request("GET", self._OpenUrl("live_setting"), bUseUserToken=True) or {}
        return self._ParseLiveSetting(dictContent)

    def UpdateLiveSetting(
        self,
        strDefaultLiveTitle: Optional[str] = None,
        strCategoryType: Optional[str] = None,
        strCategoryId: Optional[str] = None,
        listTags: Optional[List[str]] = None,
    ) -> ChzzkLiveSetting:
        """내 방송 제목/카테고리/태그를 바꿔요. 바꾸고 싶은 것만 넣으면 돼요(None 은 그대로 둠).

        - 카테고리를 없애려면 strCategoryId="" (빈 글자) 를 넣어요.
        - 태그를 모두 지우려면 listTags=[] (빈 목록) 을 넣어요.
        """
        dictBody = {}
        if strDefaultLiveTitle is not None:
            if not strDefaultLiveTitle.strip():
                raise ChzzkApiError("방송 제목은 비워둘 수 없어요.")
            dictBody["defaultLiveTitle"] = strDefaultLiveTitle
        if strCategoryId is not None:
            if strCategoryId and strCategoryType not in LIST_CATEGORY_TYPES:
                raise ChzzkApiError(f"카테고리 타입은 {LIST_CATEGORY_TYPES} 중 하나여야 해요.")
            dictBody["categoryType"] = strCategoryType or ""
            dictBody["categoryId"] = strCategoryId
        if listTags is not None:
            dictBody["tags"] = listTags

        if not dictBody:
            raise ChzzkApiError("바꿀 내용이 하나도 없어요.")

        dictContent = self._Request(
            "PATCH", self._OpenUrl("live_setting"), bUseUserToken=True, dictJson=dictBody
        )
        # 응답이 비어 있으면 최신 설정을 다시 읽어와요.
        return self._ParseLiveSetting(dictContent) if dictContent else self.GetLiveSetting()

    @staticmethod
    def _ParseLiveSetting(dictContent: dict) -> ChzzkLiveSetting:
        dictCategory = dictContent.get("category") or {}
        return ChzzkLiveSetting(
            strDefaultLiveTitle=dictContent.get("defaultLiveTitle", ""),
            strCategoryType=dictCategory.get("categoryType"),
            strCategoryId=dictCategory.get("categoryId"),
            strCategoryValue=dictCategory.get("categoryValue"),
            listTags=list(dictContent.get("tags") or []),
        )

    # ===================================================================
    # 4. 채팅 관리 기능 (본인 출입증 필요)
    # ===================================================================

    def SendChatMessage(self, strMessage: str) -> str:
        """내 방송 채팅창에 메시지를 보내요 (챗봇처럼!). 보낸 메시지의 ID 를 돌려줘요."""
        strMessage = self._CheckChatMessage(strMessage)
        dictContent = self._Request(
            "POST", self._OpenUrl("chat_send"), bUseUserToken=True, dictJson={"message": strMessage}
        ) or {}
        return dictContent.get("messageId", "")

    def RegisterChatNotice(self, strMessage: Optional[str] = None, strMessageId: Optional[str] = None) -> None:
        """채팅창 위쪽에 '공지' 를 등록해요.
        - strMessage: 새 글을 공지로 등록
        - strMessageId: 이미 보낸 채팅 하나를 공지로 고정
        """
        if strMessage:
            dictBody = {"message": self._CheckChatMessage(strMessage)}
        elif strMessageId:
            dictBody = {"messageId": strMessageId}
        else:
            raise ChzzkApiError("공지로 등록할 메시지나 메시지 ID 를 넣어주세요.")
        self._Request("POST", self._OpenUrl("chat_notice"), bUseUserToken=True, dictJson=dictBody)

    def GetChatSettings(self) -> dict:
        """채팅 설정(슬로우 모드, 팔로워 전용 등)을 가져와요."""
        return self._Request("GET", self._OpenUrl("chat_settings"), bUseUserToken=True) or {}

    def UpdateChatSettings(self, dictSettings: dict) -> None:
        """채팅 설정을 바꿔요. (GetChatSettings 로 받은 dict 를 고쳐서 넣으면 편해요)"""
        self._Request("PUT", self._OpenUrl("chat_settings"), bUseUserToken=True, dictJson=dictSettings)

    def BlindChatMessage(self, strChatChannelId: str, nMessageTime: int, strSenderChannelId: str) -> None:
        """채팅 메시지 하나를 가려요. (권한: 채팅 메시지 쓰기) 값들은 실시간 채팅 메시지에 들어 있어요."""
        self._Request("POST", self._OpenUrl("chat_blind"), bUseUserToken=True, dictJson={
            "chatChannelId": strChatChannelId,
            "messageTime": nMessageTime,
            "senderChannelId": strSenderChannelId,
        })

    # ===================================================================
    # 4-2. 시청자 제한 (본인 출입증 필요, 권한: 활동제한 쓰기 / 활동제한 조회)
    # ===================================================================

    def TemporaryRestrict(self, strTargetChannelId: str, strChatChannelId: str) -> None:
        """시청자를 '임시 제한' 해요. 제한 시간은 치지직이 정해요. (처음 30초, 또 하면 60초 ...)"""
        self._Request("POST", self._OpenUrl("temporary_restrict"), bUseUserToken=True,
                      dictJson={"targetChannelId": strTargetChannelId, "chatChannelId": strChatChannelId})

    def ReleaseTemporaryRestrict(self, strTargetChannelId: str, strChatChannelId: str) -> None:
        """임시 제한을 풀어줘요."""
        self._Request("DELETE", self._OpenUrl("temporary_restrict"), bUseUserToken=True,
                      dictJson={"targetChannelId": strTargetChannelId, "chatChannelId": strChatChannelId})

    def AddRestriction(self, strTargetChannelId: str) -> None:
        """시청자를 '활동 제한' 해요. (풀어줄 때까지 계속)"""
        self._Request("POST", self._OpenUrl("restrict"), bUseUserToken=True,
                      dictJson={"targetChannelId": strTargetChannelId})

    def RemoveRestriction(self, strTargetChannelId: str) -> None:
        """활동 제한을 풀어줘요."""
        self._Request("DELETE", self._OpenUrl("restrict"), bUseUserToken=True,
                      dictJson={"targetChannelId": strTargetChannelId})

    def ListRestrictions(self, nMaxPages: int = 20) -> List[dict]:
        """활동 제한한 시청자 목록. [{restrictedChannelId, restrictedChannelName, createdDate, releaseDate}]"""
        listAll, strNext = [], None
        for _ in range(nMaxPages):
            dictParams = {"size": 30}
            if strNext:
                dictParams["next"] = strNext
            dictContent = self._Request("GET", self._OpenUrl("restrict"), bUseUserToken=True, dictParams=dictParams) or {}
            listAll.extend(dictContent.get("data") or [])
            strNext = (dictContent.get("page") or {}).get("next")
            if not strNext:
                break
        return listAll

    def FindSubscriber(self, strChannelId: str, nMaxPages: int = 10, nSize: int = 50) -> dict:
        """구독자 목록에서 그 시청자를 찾아요. (권한: 구독 조회)

        치지직은 이름으로 찾는 기능이 없어서 50명씩 넘겨 가며 훑어요. (nMaxPages 쪽까지만)
        돌려주는 값: {"found": 찾은 항목 또는 None, "bAll": 끝까지 다 봤는지, "nChecked": 훑어본 사람 수}
        """
        nChecked = 0
        for nPage in range(nMaxPages):
            dictContent = self._Request("GET", self._OpenUrl("subscribers"), bUseUserToken=True,
                                        dictParams={"page": nPage, "size": nSize, "sort": "RECENT"}) or {}
            listData = dictContent.get("data") or []
            for dictItem in listData:
                nChecked += 1
                if dictItem.get("channelId") == strChannelId:
                    return {"found": dictItem, "bAll": False, "nChecked": nChecked}
            if len(listData) < nSize:  # 마지막 쪽까지 봤어요.
                return {"found": None, "bAll": True, "nChecked": nChecked}
        return {"found": None, "bAll": False, "nChecked": nChecked}

    # ===================================================================
    # 5. 실시간 채팅 받기 (세션) - 본인 출입증 필요
    #    자세한 흐름은 chzzk_session.py 를 보세요.
    # ===================================================================

    def GetSessionUrl(self) -> str:
        """실시간 채팅을 받을 '전화번호(소켓 접속 주소)' 를 받아와요. 한 번 쓰면 끝이라 접속할 때마다 새로 받아요."""
        dictContent = self._Request("GET", self._OpenUrl("session_auth"), bUseUserToken=True) or {}
        strUrl = dictContent.get("url")
        if not strUrl:
            raise ChzzkApiError("채팅 접속 주소(url)를 받지 못했어요.")
        return strUrl

    def SubscribeChatEvent(self, strSessionKey: str) -> None:
        """'이 연결로 내 방송 채팅을 보내주세요' 하고 신청해요. (권한: 채팅 메시지 조회)"""
        self._Request("POST", self._OpenUrl("session_subscribe_chat"), bUseUserToken=True,
                      dictParams={"sessionKey": strSessionKey})

    def SubscribeDonationEvent(self, strSessionKey: str) -> None:
        """'후원 알림도 보내주세요' 하고 신청해요. (권한: 후원 조회)"""
        self._Request("POST", self._OpenUrl("session_subscribe_donation"), bUseUserToken=True,
                      dictParams={"sessionKey": strSessionKey})

    def SubscribeSubscriptionEvent(self, strSessionKey: str) -> None:
        """'구독 알림도 보내주세요' 하고 신청해요. (권한: 구독 조회)"""
        self._Request("POST", self._OpenUrl("session_subscribe_subscription"), bUseUserToken=True,
                      dictParams={"sessionKey": strSessionKey})

    @staticmethod
    def _CheckChatMessage(strMessage: str) -> str:
        strMessage = (strMessage or "").strip()
        if not strMessage:
            raise ChzzkApiError("빈 메시지는 보낼 수 없어요.")
        if len(strMessage) > N_MAX_CHAT_LENGTH:
            raise ChzzkApiError(f"채팅은 최대 {N_MAX_CHAT_LENGTH}자까지만 보낼 수 있어요. (지금 {len(strMessage)}자)")
        return strMessage
