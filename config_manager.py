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

새 버전으로 옮길 때는 이전 폴더의 data/init.json 을 가져올 수 있어요. → ImportConfig
(키 · 로그인 · 설정은 그대로 이어받고, 새 버전에서 새로 생긴 칸은 기본값으로 채워요)
"""

import json
import os
import shutil
import threading
from typing import Optional

from app_paths import STR_APP_DIR, STR_CONFIG_NAME, DataPath
from chzzk import DICT_DEFAULT_CHZZK_URLS, STR_DEFAULT_REDIRECT_URI, ChzzkTokenInfo
from steam import DICT_DEFAULT_STEAM_URLS
from youtube import DICT_DEFAULT_YOUTUBE_URLS

STR_BASE_DIR = STR_APP_DIR  # exe 로 실행하면 exe 가 있는 폴더 (app_paths.py 참고)
STR_CONFIG_PATH = DataPath(STR_CONFIG_NAME)  # 기본 data/init.json (run.bat --test 면 data/init_test.json)
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
    "app": {"refresh_interval_sec": 30, "auto_refresh": False, "use_discord_game_list": True, "notice_sound": True, "auto_sync_category": False, "auto_donation": True, "auto_fallback_various": True,
            "auto_detect_folder_games": True,
            "donation_sound": True,  # donation_sound: 후원이 오면 알림 소리 / subscription_sound: 구독이 오면 알림 소리
            "subscription_sound": True,
            # 알림 소리 크기(0~100%) · 음 높이(low / mid / high). 후원 · 구독을 따로 맞춰요. ([설정] → 알림 소리...)
            "donation_sound_volume": 70, "donation_sound_pitch": "mid",
            "subscription_sound_volume": 70, "subscription_sound_pitch": "mid",
            "ask_import_old_config": True,
            # 마지막으로 업데이트 안내를 본 버전 (새 버전으로 처음 켤 때만 안내를 보여줘요)
            "last_seen_version": "",
            # 메인 화면 오른쪽에 치지직 리모컨(스튜디오 화면)을 띄울지 / 후원 목록 · 미션 화면을 보일지
            "show_remote_panel": True, "show_donation_mission": False,
            # OBS 채팅 화면 (내 컴퓨터 안에서만 열리는 작은 웹 서버). 켜면 OBS 브라우저 소스 · 독에서 채팅을 볼 수 있어요.
            "obs_overlay": False, "obs_overlay_port": 8765,
            # 치지직 스튜디오 '알림 주소' (영상 후원 알림 화면). OBS 채팅 화면 위쪽에 같이 나와요. 비밀 값이 들어 있어요.
            "obs_alert_url": ""},  # 설정이 비어 있을 때, 이전 버전 설정을 가져올지 켤 때 물어봐요
    # 화면 색: 색 묶음 이름 + 그 묶음에서 바꾼 색만 (gui/theme.py)
    "theme": {"preset": "라이트", "colors": {}},
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


def IsBlankConfig(dictConfig: dict) -> bool:
    """키 · 로그인 정보가 하나도 없는 '새로 설치한' 설정인지."""
    dictChzzk = dictConfig.get("chzzk") or {}
    dictSteam = dictConfig.get("steam") or {}
    dictYouTube = dictConfig.get("youtube") or {}
    return not any((dictChzzk.get("client_id"), dictChzzk.get("client_secret"), dictChzzk.get("refresh_token"),
                    dictSteam.get("api_key"), dictYouTube.get("api_key")))


def FindOldConfigs(strAppDir: str = STR_APP_DIR, nMax: int = 5) -> list:
    """같은 폴더 안의 다른 폴더들(이전 버전을 풀어 둔 곳)에서, 키가 들어 있는 data/init.json 을 찾아요.

    돌려주는 값: 파일 경로 목록 (최근에 쓴 것부터). 현재 폴더와 시험용 설정은 빼요.
    """
    strParent = os.path.dirname(os.path.abspath(strAppDir))
    strSelf = os.path.normcase(os.path.abspath(strAppDir))
    listFound = []
    try:
        listNames = os.listdir(strParent)
    except OSError:
        return []
    for strName in listNames:
        strDir = os.path.join(strParent, strName)
        if os.path.normcase(os.path.abspath(strDir)) == strSelf:
            continue
        strCandidate = os.path.join(strDir, "data", "init.json")
        if not os.path.isfile(strCandidate):
            continue
        try:
            with open(strCandidate, "r", encoding="utf-8") as objFile:
                dictOld = json.load(objFile)
            if isinstance(dictOld, dict) and not IsBlankConfig(dictOld):
                listFound.append((os.path.getmtime(strCandidate), strCandidate))
        except (OSError, ValueError):
            continue
    listFound.sort(reverse=True)
    return [strPath for _, strPath in listFound[:nMax]]


# 설정 파일이 맞는지 알아볼 때 보는 맨 위 칸들
TUPLE_CONFIG_SECTIONS = ("steam", "youtube", "chzzk", "urls", "app", "theme")


def _FlattenKeys(dictValue: dict, strPrefix: str = "") -> set:
    """{"a": {"b": 1}} → {"a.b"}  (칸 이름을 점으로 이어서 모아요)"""
    setKeys = set()
    for strKey, objValue in dictValue.items():
        strName = f"{strPrefix}.{strKey}" if strPrefix else strKey
        if isinstance(objValue, dict) and objValue:
            setKeys |= _FlattenKeys(objValue, strName)
        else:
            setKeys.add(strName)
    return setKeys


def DescribeImport(strSourcePath: str) -> dict:
    """이전 설정 파일을 읽어서, 가져오면 어떻게 되는지 알려줘요. (아무것도 쓰지 않아요)

    돌려주는 값:
        merged      : 지금 버전의 기본 양식 위에 이전 값을 얹은 설정 (이걸 저장하면 돼요)
        bChzzkKeys  : 치지직 Client ID / Secret 이 들어 있는지
        bChzzkLogin : 치지직 로그인 정보(토큰)가 들어 있는지
        bSteam      : 스팀 API 키가 들어 있는지
        bYouTube    : 유튜브 API 키가 들어 있는지
        listAdded   : 이전 파일에 없어서 새 버전의 기본값으로 채운 칸 이름들
    (비밀 값 자체는 돌려주지 않아요. 있는지 없는지만 알려줘요.)
    """
    if not os.path.isfile(strSourcePath):
        raise RuntimeError(f"파일을 찾을 수 없어요: {strSourcePath}")
    try:
        with open(strSourcePath, "r", encoding="utf-8") as objFile:
            dictSource = json.load(objFile)
    except (OSError, ValueError) as objError:
        raise RuntimeError(f"설정 파일을 읽을 수 없어요 (JSON 형식 확인): {objError}") from objError
    if not isinstance(dictSource, dict) or not any(isinstance(dictSource.get(strSection), dict)
                                                   for strSection in TUPLE_CONFIG_SECTIONS):
        raise RuntimeError("이 프로그램의 설정 파일(init.json)이 아닌 것 같아요.")

    dictMerged = _DeepCopy(DICT_DEFAULT_CONFIG)
    _MergeInto(dictMerged, dictSource)

    def _Get(strSection: str, strKey: str):
        dictPart = dictSource.get(strSection)
        return dictPart.get(strKey) if isinstance(dictPart, dict) else None

    return {
        "merged": dictMerged,
        "bChzzkKeys": bool(_Get("chzzk", "client_id") and _Get("chzzk", "client_secret")),
        "bChzzkLogin": bool(_Get("chzzk", "refresh_token")),
        "bSteam": bool(_Get("steam", "api_key")),
        "bYouTube": bool(_Get("youtube", "api_key")),
        "listAdded": sorted(_FlattenKeys(dictMerged) - _FlattenKeys(dictSource)),
    }


def ImportConfig(strSourcePath: str, strDestPath: str = STR_CONFIG_PATH) -> dict:
    """이전 버전의 설정 파일을 지금 설정 파일(기본 data/init.json)로 가져와요.

    - 이전 값은 그대로 이어받고, 새 버전에서 새로 생긴 칸은 기본값으로 채워요.
    - 지금 설정 파일이 있으면 '파일이름.bak' 으로 백업해 둬요. (잘못 가져왔을 때 되돌릴 수 있게)
    - 이전 설정 파일은 건드리지 않아요.
    돌려주는 값: DescribeImport 의 결과
    """
    bBothExist = os.path.exists(strSourcePath) and os.path.exists(strDestPath)
    if bBothExist and os.path.samefile(strSourcePath, strDestPath):
        raise RuntimeError("지금 쓰고 있는 설정 파일이에요. 이전 버전 폴더의 data/init.json 을 골라 주세요.")
    dictInfo = DescribeImport(strSourcePath)
    with OBJ_SAVE_LOCK:
        if os.path.exists(strDestPath):
            shutil.copy2(strDestPath, strDestPath + ".bak")
        SaveConfig(dictInfo["merged"], strDestPath)
    return dictInfo


def ReplaceInPlace(dictTarget: dict, dictSource: dict) -> None:
    """dictTarget 의 내용을 dictSource 와 똑같이 바꿔요. (dict 객체 자체는 그대로 둬요)

    프로그램 곳곳이 설정 안쪽 dict 를 붙잡고 있어서(예: 미션 창의 app 설정), 새 dict 로 갈아 끼우면
    그쪽만 옛 값을 계속 들고 있게 돼요. 그래서 안쪽부터 같은 객체에 값만 바꿔 넣어요.
    """
    for strKey in [strKey for strKey in dictTarget if strKey not in dictSource]:
        del dictTarget[strKey]
    for strKey, objValue in dictSource.items():
        if isinstance(objValue, dict) and isinstance(dictTarget.get(strKey), dict):
            ReplaceInPlace(dictTarget[strKey], objValue)
        else:
            dictTarget[strKey] = _DeepCopy({"v": objValue})["v"]


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
