"""
스팀(Steam) Web API 연동 모듈
================================

이 파일이 하는 일 (한 줄 요약)
    "스팀 친구 목록에서 보이는 '지금 OO 게임 하는 중' 정보를 프로그램으로 가져온다."

어떻게 동작하나요?
    1) 스팀 서버에 "이 사람(SteamID64) 프로필 좀 보여줘!" 하고 편지(HTTP 요청)를 보냅니다.
       이때 편지에 '출입증(API 키)'을 꼭 같이 넣어야 스팀이 답장을 해줘요.
    2) 스팀이 JSON 이라는 정리된 답장을 보내줍니다.
    3) 답장 안에 `gameid`(게임 번호)와 `gameextrainfo`(게임 이름)가 들어 있으면
       → "지금 게임 중!" 이라고 판단합니다.
    4) 없으면 → `personastate`(접속 상태 숫자)를 보고 온라인/오프라인을 알려줍니다.

사용 API: https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/
"""

from dataclasses import dataclass
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# 상수(바뀌지 않는 값) 모음
# ---------------------------------------------------------------------------

# 스팀 서버 주소 기본값입니다. 편지를 보낼 '우체통 주소' 라고 생각하면 돼요.
# 실제로는 data/init.json 의 "urls" → "steam" 값이 있으면 그걸 먼저 써요.
DICT_DEFAULT_STEAM_URLS = {
    "player_summaries": "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/",
}

# 서버가 너무 늦게 답하면 무한정 기다리지 않도록, 최대 몇 초 기다릴지 정합니다.
F_DEFAULT_TIMEOUT_SEC = 10.0

# 스팀은 접속 상태를 숫자로 알려줘요. 숫자를 사람이 읽을 수 있는 말로 바꾸는 사전입니다.
DICT_PERSONA_STATE = {
    0: "오프라인",
    1: "온라인",
    2: "다른 용무 중",
    3: "자리 비움",
    4: "다시 알림(Snooze)",
    5: "거래 희망",
    6: "게임 희망",
}


# ---------------------------------------------------------------------------
# 예외(에러) 클래스
# ---------------------------------------------------------------------------

class SteamApiError(Exception):
    """스팀 API 를 쓰다가 문제가 생겼을 때 던지는 '우리만의 에러' 입니다.

    왜 따로 만드나요?
        인터넷이 끊겼든, 키가 틀렸든, 사용하는 쪽에서는
        `except SteamApiError:` 한 줄로 전부 잡을 수 있게 하려고요.
    """


# ---------------------------------------------------------------------------
# 결과를 담는 상자(데이터 클래스)
# ---------------------------------------------------------------------------

@dataclass
class SteamPlayerStatus:
    """스팀 유저 한 명의 '지금 상태' 를 담는 상자입니다."""

    strSteamId: str             # 17자리 스팀 고유 번호
    strPersonaName: str         # 스팀 닉네임
    nPersonaState: int          # 접속 상태 숫자 (0=오프라인, 1=온라인 ...)
    strPersonaState: str        # 접속 상태를 한국어로 바꾼 글자
    bIsPlaying: bool            # 지금 게임을 하고 있으면 True
    strGameId: Optional[str]    # 게임 번호 (예: "730" = 카운터 스트라이크 2), 없으면 None
    strGameName: Optional[str]  # 게임 이름, 없으면 None
    bIsProfilePublic: bool      # 프로필이 '공개' 인지 (비공개면 게임 정보가 안 보여요)
    strProfileUrl: str          # 스팀 프로필 주소
    strAvatarUrl: str           # 프로필 사진 주소

    @property
    def bIsOnline(self) -> bool:
        """0(오프라인)만 아니면 접속해 있는 거예요."""
        return self.nPersonaState != 0

    def ToDisplayText(self) -> str:
        """사람이 읽기 좋은 한 줄 문장으로 바꿔 줍니다."""
        if self.bIsPlaying:
            return f"{self.strPersonaName} 님은 지금 [{self.strGameName}] (ID: {self.strGameId}) 플레이 중!"
        if not self.bIsProfilePublic:
            return f"{self.strPersonaName} 님의 프로필이 비공개라 게임 정보를 볼 수 없어요. (상태: {self.strPersonaState})"
        if self.bIsOnline:
            return f"{self.strPersonaName} 님은 온라인이지만 게임은 안 하고 있어요. (상태: {self.strPersonaState})"
        return f"{self.strPersonaName} 님은 오프라인이에요."


# ---------------------------------------------------------------------------
# 스팀 API 클라이언트
# ---------------------------------------------------------------------------

class SteamApiClient:
    """스팀 서버와 대화하는 '심부름꾼' 입니다.

    사용 예:
        objClient = SteamApiClient(strApiKey="내_API_키")
        objStatus = objClient.GetPlayerStatus("76561198000000000")
        print(objStatus.ToDisplayText())
    """

    def __init__(self, strApiKey: str, fTimeoutSec: float = F_DEFAULT_TIMEOUT_SEC, dictUrls: Optional[dict] = None):
        # API 키가 비어 있으면 스팀이 답을 안 해주니까, 미리 막아요.
        if not strApiKey or not strApiKey.strip():
            raise SteamApiError("스팀 API 키가 비어 있어요. data/init.json 의 steam.api_key 를 채워주세요.")

        self.strApiKey = strApiKey.strip()
        self.fTimeoutSec = fTimeoutSec

        # 기본 주소 위에 init.json 에서 받은 주소를 덮어써요. (빈 칸은 무시)
        self.dictUrls = dict(DICT_DEFAULT_STEAM_URLS)
        for strKey, strValue in (dictUrls or {}).items():
            if isinstance(strValue, str) and strValue.strip():
                self.dictUrls[strKey] = strValue.strip()

        # Session 은 '같은 우체국 창구를 계속 쓰는 것' 과 같아서, 여러 번 요청할 때 더 빨라요.
        self.objSession = requests.Session()

    # -------------------------------------------------------------------
    # 1단계: 스팀 서버에서 '날것의' 프로필 데이터를 받아오기
    # -------------------------------------------------------------------
    def FetchPlayerSummary(self, strSteamId: str) -> dict:
        """스팀 서버에 요청을 보내고, 플레이어 한 명의 원본 데이터(dict)를 돌려줍니다."""

        strSteamId = (strSteamId or "").strip()

        # SteamID64 는 항상 숫자 17자리예요. 모양이 다르면 요청 전에 알려줍니다.
        if not (strSteamId.isdigit() and len(strSteamId) == 17):
            raise SteamApiError(f"SteamID64 는 숫자 17자리여야 해요. 입력값: '{strSteamId}'")

        # 편지에 적을 내용(쿼리 파라미터)
        dictParams = {"key": self.strApiKey, "steamids": strSteamId}

        try:
            objResponse = self.objSession.get(
                self.dictUrls["player_summaries"], params=dictParams, timeout=self.fTimeoutSec
            )
        except requests.Timeout as objError:
            raise SteamApiError(f"스팀 서버가 {self.fTimeoutSec}초 안에 답하지 않았어요.") from objError
        except requests.ConnectionError as objError:
            raise SteamApiError("스팀 서버에 연결할 수 없어요. 인터넷 연결을 확인해 주세요.") from objError
        except requests.RequestException as objError:
            # 위에서 못 잡은 나머지 '인터넷 요청 관련 문제' 를 모두 여기서 잡아요.
            raise SteamApiError(f"스팀 요청 중 알 수 없는 문제가 생겼어요: {objError}") from objError

        # HTTP 상태 코드 확인: 200 이면 성공, 그 외는 실패예요.
        if objResponse.status_code == 403:
            raise SteamApiError("스팀이 요청을 거절했어요(403). API 키가 올바른지 확인해 주세요.")
        if objResponse.status_code == 429:
            raise SteamApiError("요청을 너무 자주 보냈어요(429). 잠시 후 다시 시도해 주세요.")
        if objResponse.status_code != 200:
            raise SteamApiError(f"스팀 서버 오류 (HTTP {objResponse.status_code})")

        # 답장(JSON 글자)을 파이썬 사전(dict)으로 바꿔요.
        try:
            dictBody = objResponse.json()
        except ValueError as objError:
            raise SteamApiError("스팀 응답을 읽을 수 없어요 (JSON 형식이 아님).") from objError

        # 답장의 모양: {"response": {"players": [ {...플레이어 정보...} ]}}
        listPlayers = dictBody.get("response", {}).get("players", [])
        if not listPlayers:
            raise SteamApiError(f"SteamID '{strSteamId}' 에 해당하는 유저를 찾을 수 없어요.")

        return listPlayers[0]

    # -------------------------------------------------------------------
    # 2단계: 날것의 데이터를 '보기 좋은 상자' 로 정리하기
    # -------------------------------------------------------------------
    @staticmethod
    def ParsePlayerSummary(dictPlayer: dict) -> SteamPlayerStatus:
        """원본 dict 를 SteamPlayerStatus 상자에 차곡차곡 옮겨 담습니다."""

        nPersonaState = int(dictPlayer.get("personastate", 0))

        # communityvisibilitystate 가 3 이면 '공개' 프로필이에요. (1 = 비공개)
        bIsProfilePublic = int(dictPlayer.get("communityvisibilitystate", 1)) == 3

        # [핵심 로직]
        # 게임을 하고 있으면 스팀이 'gameid'(번호)와 'gameextrainfo'(이름)를 넣어줘요.
        # 게임을 안 하면 이 칸이 아예 없어요. 그래서 .get() 으로 '있으면 가져오고 없으면 None' 처리!
        strGameId = dictPlayer.get("gameid")
        strGameName = dictPlayer.get("gameextrainfo")

        # 게임 번호든 이름이든 하나라도 있으면 '게임 중' 으로 판단해요.
        bIsPlaying = bool(strGameId or strGameName)

        # 가끔 이름 없이 번호만 오는 경우(스팀 비(非)게임 앱 등)를 대비해요.
        if bIsPlaying and not strGameName:
            strGameName = f"알 수 없는 게임 (ID: {strGameId})"

        return SteamPlayerStatus(
            strSteamId=str(dictPlayer.get("steamid", "")),
            strPersonaName=dictPlayer.get("personaname", "(이름 없음)"),
            nPersonaState=nPersonaState,
            strPersonaState=DICT_PERSONA_STATE.get(nPersonaState, f"알 수 없음({nPersonaState})"),
            bIsPlaying=bIsPlaying,
            strGameId=str(strGameId) if strGameId else None,
            strGameName=strGameName,
            bIsProfilePublic=bIsProfilePublic,
            strProfileUrl=dictPlayer.get("profileurl", ""),
            strAvatarUrl=dictPlayer.get("avatarfull", ""),
        )

    # -------------------------------------------------------------------
    # 1단계 + 2단계를 한 번에!
    # -------------------------------------------------------------------
    def GetPlayerStatus(self, strSteamId: str) -> SteamPlayerStatus:
        """SteamID 를 넣으면 정리된 상태 상자를 돌려주는 '원스톱' 함수예요."""
        dictPlayer = self.FetchPlayerSummary(strSteamId)
        return self.ParsePlayerSummary(dictPlayer)
