"""
설정 파일(data/init.json) 관리 모듈
====================================

API 키 같은 '비밀 정보' 를 코드 안에 직접 쓰면, 코드를 친구에게 보여줄 때 비밀도 같이 새어 나가요.
그래서 비밀과 설정값은 data/init.json 이라는 별도 파일에 넣고, 이 모듈로 읽고 써요.
(init.json 은 절대 깃허브 등에 올리지 마세요!)

init.json 안에 들어가는 것
    steam : 스팀 API 키, SteamID64
    chzzk : 치지직 Client ID/Secret, 채널 ID, 로그인 리디렉션 주소, 토큰
    urls  : 스팀/치지직 서버 주소들 (서버 주소가 바뀌면 여기만 고치면 돼요)
    app   : 자동 새로고침 간격 등 프로그램 설정
"""

import json
import os
import threading
from typing import Optional

from app_paths import STR_APP_DIR, DataPath
from chzzk import DICT_DEFAULT_CHZZK_URLS, STR_DEFAULT_REDIRECT_URI, ChzzkTokenInfo
from steam import DICT_DEFAULT_STEAM_URLS
from youtube import DICT_DEFAULT_YOUTUBE_URLS

STR_BASE_DIR = STR_APP_DIR  # exe 로 실행하면 exe 가 있는 폴더 (app_paths.py 참고)
STR_CONFIG_PATH = DataPath("init.json")
# 깃허브 등에 올려도 되는 '개인정보 뺀' 설정 파일 (키 · ID · 토큰은 빈칸)
STR_UPLOAD_CONFIG_PATH = DataPath("init_upload.json")

# 자물쇠: 토큰 저장(뒤쪽 일꾼)과 설정 저장(화면)이 동시에 같은 파일을 쓰다 부딪히지 않게 해요.
OBJ_SAVE_LOCK = threading.RLock()

# 개인정보라서 업로드용 파일에서는 비워야 하는 칸들: (구역, 칸 이름)
LIST_PRIVATE_KEYS = [
    ("steam", "api_key"), ("steam", "steam_id"),
    ("chzzk", "client_id"), ("chzzk", "client_secret"), ("chzzk", "channel_id"),
    ("chzzk", "access_token"), ("chzzk", "refresh_token"), ("chzzk", "token_expire_at"),
    ("youtube", "api_key"), ("youtube", "default_target"),
]

# init.json 이 없거나 칸이 비었을 때 쓰는 '기본 양식'
DICT_DEFAULT_CONFIG = {
    "steam": {"api_key": "", "steam_id": ""},
    # 유튜브 공식 Data API: API 키 · 마지막에 연결한 방송 주소 · 채팅 가져오는 최소 간격(초, 짧을수록 사용량 많이 씀)
    "youtube": {"api_key": "", "default_target": "", "min_interval_sec": 8},
    "chzzk": {
        "client_id": "",
        "client_secret": "",
        "channel_id": "",
        "redirect_uri": STR_DEFAULT_REDIRECT_URI,
        "access_token": "",
        "refresh_token": "",
        "token_expire_at": 0,
    },
    "urls": {
        "steam": dict(DICT_DEFAULT_STEAM_URLS),
        "youtube": dict(DICT_DEFAULT_YOUTUBE_URLS),
        "chzzk": dict(DICT_DEFAULT_CHZZK_URLS),
    },
    # auto_donation: 프로그램을 켜면 후원 받기를 자동으로 시작 (후원 목록 창을 안 열어도 기록돼요)
    # auto_fallback_various: 자동 맞추기 때 짝을 못 찾으면 '종합 게임' 으로
    # auto_detect_folder_games: 게임 설치 폴더(에픽 · 넥슨 등)에서 실행된 프로그램도 게임으로 알아보기
    "app": {"refresh_interval_sec": 30, "auto_sync_category": False, "auto_donation": True, "auto_fallback_various": True,
            "auto_detect_folder_games": True},
}


def _DeepCopy(dictValue: dict) -> dict:
    return json.loads(json.dumps(dictValue))


def _MergeInto(dictTarget: dict, dictSource: dict) -> None:
    """dictSource 의 값을 dictTarget 에 '칸 단위로' 덮어써요. (안쪽 사전도 끝까지 들어가서)"""
    for strKey, objValue in dictSource.items():
        if isinstance(objValue, dict) and isinstance(dictTarget.get(strKey), dict):
            _MergeInto(dictTarget[strKey], objValue)
        else:
            dictTarget[strKey] = objValue


def LoadConfig(strPath: str = STR_CONFIG_PATH) -> dict:
    """init.json 을 읽어요.

    - 파일이 없거나 비어 있으면 → 기본 양식으로 새로 만들어 저장해요. (열어서 채우기 쉽게!)
    - 일부 칸만 적혀 있으면 → 빠진 칸은 기본값으로 채우고, 새 칸이 생겼으면 파일에도 추가해요.
    """
    dictConfig = _DeepCopy(DICT_DEFAULT_CONFIG)
    dictLoaded = {}

    # init.json 이 아직 없으면(새 컴퓨터) → 업로드용 파일이 있으면 그걸 양식으로 써요.
    # (바꿔둔 URL 같은 공용 설정을 그대로 이어받기 위해서)
    if not os.path.exists(strPath) and strPath == STR_CONFIG_PATH and os.path.exists(STR_UPLOAD_CONFIG_PATH):
        try:
            with open(STR_UPLOAD_CONFIG_PATH, "r", encoding="utf-8") as objFile:
                _MergeInto(dictConfig, json.load(objFile))
        except (OSError, ValueError):
            pass  # 업로드용 파일이 이상하면 그냥 기본값으로 시작

    if os.path.exists(strPath):
        try:
            with open(strPath, "r", encoding="utf-8") as objFile:
                strText = objFile.read()
            dictLoaded = json.loads(strText) if strText.strip() else {}
        except (OSError, ValueError) as objError:
            raise RuntimeError(f"{strPath} 를 읽을 수 없어요 (JSON 형식 확인): {objError}") from objError
        if not isinstance(dictLoaded, dict):
            raise RuntimeError(f"{strPath} 의 맨 바깥은 {{ }} 형태여야 해요.")

    _MergeInto(dictConfig, dictLoaded)

    # 파일이 없었거나, 기본 양식에 있는 칸이 파일에 빠져 있었다면 → 채운 내용을 저장해 둬요.
    if dictConfig != dictLoaded:
        SaveConfig(dictConfig, strPath)

    return dictConfig


def SaveConfig(dictConfig: dict, strPath: str = STR_CONFIG_PATH) -> None:
    """설정을 init.json 에 저장해요. (저장 도중 꺼져도 파일이 깨지지 않게 임시 파일을 거쳐요)"""
    with OBJ_SAVE_LOCK:
        os.makedirs(os.path.dirname(strPath), exist_ok=True)
        strTempPath = strPath + ".tmp"
        with open(strTempPath, "w", encoding="utf-8") as objFile:
            json.dump(dictConfig, objFile, ensure_ascii=False, indent=2)
        os.replace(strTempPath, strPath)


def MakeUploadConfig(dictConfig: dict, strPath: str = STR_UPLOAD_CONFIG_PATH) -> dict:
    """개인정보(키 · ID · 토큰)를 빈칸으로 바꾼 '업로드용' 설정 파일을 만들어요.

    URL · 새로고침 간격 같은 공용 설정은 그대로 두고,
    자동 카테고리 변경은 다른 사람이 받았을 때 깜짝 놀라지 않도록 꺼둬요.
    """
    dictUpload = _DeepCopy(dictConfig)
    for strSection, strKey in LIST_PRIVATE_KEYS:
        objDefault = DICT_DEFAULT_CONFIG.get(strSection, {}).get(strKey, "")
        dictUpload.setdefault(strSection, {})[strKey] = objDefault
    dictUpload.setdefault("app", {})["auto_sync_category"] = False
    SaveConfig(dictUpload, strPath)
    return dictUpload


def TokenFromConfig(dictConfig: dict) -> Optional[ChzzkTokenInfo]:
    """설정 안에 저장된 치지직 토큰을 꺼내요. 없으면 None."""
    dictChzzk = dictConfig.get("chzzk", {})
    if not dictChzzk.get("refresh_token"):
        return None
    return ChzzkTokenInfo(
        strAccessToken=dictChzzk.get("access_token", ""),
        strRefreshToken=dictChzzk["refresh_token"],
        fExpireAt=float(dictChzzk.get("token_expire_at") or 0),
    )


def StoreTokenToConfig(dictConfig: dict, objTokenInfo: Optional[ChzzkTokenInfo]) -> None:
    """새 토큰을 설정에 넣고 바로 init.json 에 저장해요. (None 이면 토큰 삭제 = 로그아웃)"""
    with OBJ_SAVE_LOCK:
        dictChzzk = dictConfig.setdefault("chzzk", {})
        dictChzzk["access_token"] = objTokenInfo.strAccessToken if objTokenInfo else ""
        dictChzzk["refresh_token"] = objTokenInfo.strRefreshToken if objTokenInfo else ""
        dictChzzk["token_expire_at"] = objTokenInfo.fExpireAt if objTokenInfo else 0
        SaveConfig(dictConfig)
