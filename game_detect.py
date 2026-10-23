"""
스팀 밖 게임 감지 모듈 (실행 중인 프로그램 보기)
==================================================

왜 필요한가요?
    스팀 API 는 '스팀으로 켠 게임' 만 알려줘요.
    리그 오브 레전드, 발로란트, 메이플스토리처럼 스팀 밖에서 켜는 게임은 모르죠.
    그래서 내 컴퓨터에서 '지금 실행 중인 프로그램(exe)' 을 보고 무슨 게임인지 알아내요.

어떻게 짝을 짓나요?
    data/game_map.txt 에 스팀 gameid 대신 'exe:프로그램이름' 을 열쇠로 적어요.
        exe:valorant-win64-shipping.exe = GAME | VALORANT | 발로란트   # VALORANT
    (프로그램 이름은 대소문자를 구분하지 않아요. 항상 소문자로 저장해요)

주의
    - 윈도우 전용이에요. (다른 OS 에서는 아무것도 감지하지 않아요)
    - 게임 PC 와 방송 PC 가 다르면, 프로그램 감지는 '이 프로그램이 켜진 PC' 만 볼 수 있어요.
      (스팀 게임은 스팀 서버에 물어보니까 PC 가 달라도 돼요)
"""

import ctypes
import os
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

STR_EXE_KEY_PREFIX = "exe:"

# 잘 알려진 '스팀 밖' 게임들: 프로그램 이름(소문자) → 치지직에서 검색할 이름
# 짝이 없어도 "이 게임 하는 중" 으로 알아보고, 카테고리 검색어를 미리 채워주는 데만 써요.
# (카테고리 ID 는 사용자가 직접 골라서 짝으로 저장해요)
DICT_KNOWN_GAMES = {
    "league of legends.exe": "리그 오브 레전드",
    "valorant-win64-shipping.exe": "발로란트",
    "polaris-win64-shipping.exe": "철권 8",   # 철권 8 의 프로그램 이름 (개발 코드명 Polaris)
    "maplestory.exe": "메이플스토리",
    "lostark.exe": "로스트아크",
    "dnf.exe": "던전앤파이터",
    "overwatch.exe": "오버워치",
    "diablo iv.exe": "디아블로 4",
    "wow.exe": "월드 오브 워크래프트",
    "hearthstone.exe": "하스스톤",
    "starcraft.exe": "스타크래프트",
    "tslgame.exe": "PUBG: 배틀그라운드",
    "fortniteclient-win64-shipping.exe": "포트나이트",
    "robloxplayerbeta.exe": "로블록스",
    "minecraft.windows.exe": "마인크래프트",
}

# '실행 중인 프로그램에서 고르기' 목록에서 뺄 윈도우 기본 프로그램들
SET_IGNORED_PICK_EXES = {
    "explorer.exe", "applicationframehost.exe", "textinputhost.exe", "systemsettings.exe",
    "shellexperiencehost.exe", "searchhost.exe", "startmenuexperiencehost.exe", "searchapp.exe",
    "lockapp.exe", "python.exe", "pythonw.exe", "cmd.exe", "conhost.exe", "windowsterminal.exe",
}


# 스팀이 '플레이 중' 으로 보여주지만 게임이 아닌 프로그램들 (스팀 appid)
# 이걸 켜 둔 것만으로 카테고리가 바뀌면 안 돼요. (예: 스팀으로 OBS 를 켜면 'OBS Studio 플레이 중' 으로 떠요)
DICT_NON_GAME_STEAM_APPS = {
    "431960": "Wallpaper Engine",
    "1905180": "OBS Studio",
    "1366800": "Crosshair X",
    "3419430": "Bongo Cat",
    "250820": "SteamVR",
    "993090": "Lossless Scaling",
    "629520": "Soundpad",
}


def IsNonGameSteamApp(strAppId: Optional[str]) -> bool:
    return str(strAppId or "") in DICT_NON_GAME_STEAM_APPS


@dataclass
class DetectedGame:
    """지금 하는 게임 하나. (스팀이든 프로그램 감지든 같은 모양으로 다뤄요)

    strGameId   : 짝 목록의 열쇠. 스팀이면 gameid("2622380"), 프로그램이면 "exe:이름.exe"
    strGameName : 화면에 보여줄 이름 (짝을 처음 만들 때 메모와 검색어로도 써요)
    strSource   : "steam" / "process" / "folder"(게임 설치 폴더에서 찾음)
    """

    strGameId: str
    strGameName: str
    strSource: str

    @property
    def bIsPlaying(self) -> bool:  # 스팀 상태 상자(SteamPlayerStatus)와 같은 이름으로 쓸 수 있게
        return True

    @property
    def strSourceName(self) -> str:
        return {"steam": "스팀", "folder": "게임 폴더 감지"}.get(self.strSource, "프로그램 감지")


# ---------------------------------------------------------------------------
# 열쇠(짝 목록의 왼쪽 칸) 도우미
# ---------------------------------------------------------------------------

def ExeKey(strExeName: str) -> str:
    """프로그램 이름 → 짝 목록 열쇠 ("VALORANT.exe" → "exe:valorant.exe")"""
    return STR_EXE_KEY_PREFIX + os.path.basename(strExeName.strip()).lower()


def IsExeKey(strKey: str) -> bool:
    return strKey.startswith(STR_EXE_KEY_PREFIX)


def NormalizeKey(strKey: Optional[str]) -> str:
    """짝 목록 열쇠를 같은 모양으로 맞춰요. (exe 는 소문자로)"""
    strKey = (strKey or "").strip()
    if strKey.lower().startswith(STR_EXE_KEY_PREFIX):
        return ExeKey(strKey[len(STR_EXE_KEY_PREFIX):])
    return strKey


def IsValidKey(strKey: str) -> bool:
    """스팀 gameid(숫자) 또는 exe:이름.exe 모양이면 True."""
    if strKey.isdigit():
        return True
    if not IsExeKey(strKey):
        return False
    strExe = strKey[len(STR_EXE_KEY_PREFIX):]
    return strExe.endswith(".exe") and len(strExe) > 4 and not any(ch in strExe for ch in "=|#\\/")


def KeyFromInput(strText: str) -> Optional[str]:
    """사람이 입력한 글자 → 짝 목록 열쇠. 숫자는 스팀 gameid, .exe 로 끝나면 프로그램. 이상하면 None."""
    strText = strText.strip().strip('"')
    if strText.lower().startswith(STR_EXE_KEY_PREFIX):
        strText = strText[len(STR_EXE_KEY_PREFIX):]
    if strText.isdigit():
        return strText
    if strText.lower().endswith(".exe"):
        strKey = ExeKey(strText)
        return strKey if IsValidKey(strKey) else None
    return None


def KeyToDisplay(strKey: str) -> str:
    """짝 목록 열쇠 → 화면 표시용 ("exe:valorant.exe" → "valorant.exe")"""
    return strKey[len(STR_EXE_KEY_PREFIX):] if IsExeKey(strKey) else strKey


# ---------------------------------------------------------------------------
# 실행 중인 프로그램 읽기 (윈도우 기본 기능 사용 → 따로 설치할 라이브러리 없음)
# ---------------------------------------------------------------------------

_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _ProcessTable() -> Dict[int, str]:
    """실행 중인 모든 프로그램: 프로세스 번호(pid) → 프로그램 이름. (윈도우가 아니면 빈 사전)"""
    if sys.platform != "win32":
        return {}
    objKernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    objKernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    objKernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    objKernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    objKernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    objKernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    hSnapshot = objKernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not hSnapshot or hSnapshot == _INVALID_HANDLE_VALUE:
        return {}
    dictTable = {}
    try:
        objEntry = _PROCESSENTRY32W()
        objEntry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        bOk = objKernel32.Process32FirstW(hSnapshot, ctypes.byref(objEntry))
        while bOk:
            dictTable[objEntry.th32ProcessID] = objEntry.szExeFile
            bOk = objKernel32.Process32NextW(hSnapshot, ctypes.byref(objEntry))
    finally:
        objKernel32.CloseHandle(hSnapshot)
    return dictTable


def ListRunningExeNames() -> Set[str]:
    """지금 실행 중인 프로그램 이름들 (소문자)."""
    return {strName.lower() for strName in _ProcessTable().values()}


def ListWindowedPrograms() -> List[Tuple[str, str]]:
    """화면에 창이 떠 있는 프로그램들: [(프로그램 이름, 창 제목)]
    '실행 중인 프로그램에서 고르기' 목록용이에요. 아는 게임이 맨 위에 와요.
    """
    if sys.platform != "win32":
        return []
    dictTable = _ProcessTable()
    objUser32 = ctypes.WinDLL("user32", use_last_error=True)
    fnEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    objUser32.EnumWindows.argtypes = [fnEnumProc, wintypes.LPARAM]
    objUser32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    objUser32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    objUser32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    objUser32.IsWindowVisible.argtypes = [wintypes.HWND]

    nMyPid = os.getpid()
    dictPrograms: Dict[str, str] = {}  # 프로그램 이름 → 창 제목 (같은 프로그램은 한 번만)

    def _OnWindow(hWnd, _lParam):
        if not objUser32.IsWindowVisible(hWnd):
            return True
        nLength = objUser32.GetWindowTextLengthW(hWnd)
        if nLength <= 0:
            return True
        nPid = wintypes.DWORD()
        objUser32.GetWindowThreadProcessId(hWnd, ctypes.byref(nPid))
        strExe = dictTable.get(nPid.value, "")
        if not strExe or nPid.value == nMyPid or strExe.lower() in SET_IGNORED_PICK_EXES:
            return True
        objBuffer = ctypes.create_unicode_buffer(nLength + 1)
        objUser32.GetWindowTextW(hWnd, objBuffer, nLength + 1)
        dictPrograms.setdefault(strExe, objBuffer.value)
        return True

    objUser32.EnumWindows(fnEnumProc(_OnWindow), 0)
    return sorted(dictPrograms.items(), key=lambda tupleItem: (tupleItem[0].lower() not in DICT_KNOWN_GAMES,
                                                                tupleItem[0].lower()))


# ---------------------------------------------------------------------------
# 게임 설치 폴더에서 실행된 프로그램 = 게임 (목록에 없는 스팀 밖 게임도 알아보려고)
# ---------------------------------------------------------------------------

# 경로(소문자)에 이 글자가 들어 있으면 '게임 설치 폴더' 로 봐요.
LIST_GAME_DIR_MARKERS = [
    "\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\xboxgames\\", "\\nexon\\",
    "\\gog galaxy\\games\\", "\\gog games\\", "\\ubisoft game launcher\\games\\", "\\ea games\\",
    "\\electronic arts\\", "\\_retail_\\", "\\kakaogames\\", "\\smilegate\\", "\\pearlabyss\\",
    "\\netmarble\\", "\\ncsoft\\", "\\hoyoplay\\games\\", "\\wemade\\",
]

# 게임 폴더에 있어도 게임이 아닌 프로그램 (프로그램 이름에 이 글자가 들어 있으면 빼요)
LIST_NON_GAME_EXE_WORDS = [
    "launcher", "crash", "report", "update", "patch", "helper", "service", "anticheat", "battleye", "be_service",
    "setup", "install", "redist", "dxsetup", "overlay", "wallpaper", "riotclient", "vanguard", "socialclub",
    "bootstrap", "cefprocess", "webview", "browser", "uninst", "unins0", "steam", "epicgames", "galaxyclient",
    "eadesktop", "eabackground", "upc.exe", "ubisoftconnect", "battle.net", "agent.exe", "bugsplat", "sentry",
]

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _ProcessPath(nPid: int) -> str:
    """프로세스 번호 → 실행 파일 전체 경로. (못 읽으면 "": 윈도우 시스템 · 안티치트로 보호되는 프로그램 등)"""
    objKernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    objKernel32.OpenProcess.restype = wintypes.HANDLE
    objKernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    objKernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                       ctypes.POINTER(wintypes.DWORD)]
    objKernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    hProcess = objKernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, nPid)
    if not hProcess:
        return ""
    try:
        objBuffer = ctypes.create_unicode_buffer(1024)
        nSize = wintypes.DWORD(1024)
        if objKernel32.QueryFullProcessImageNameW(hProcess, 0, objBuffer, ctypes.byref(nSize)):
            return objBuffer.value
        return ""
    finally:
        objKernel32.CloseHandle(hProcess)


_RE_ACF_FIELD = re.compile(r'"(appid|installdir|name)"\s+"([^"]*)"', re.I)
_dictManifestCache: Dict[str, Tuple[float, Dict[str, Tuple[str, str]]]] = {}   # 스팀 라이브러리 → (읽은 시각, 폴더이름 → (게임번호, 이름))
F_MANIFEST_CACHE_SEC = 120.0
DICT_FOLDER_STEAM_IDS: Dict[str, str] = {}   # 방금 찾은 프로그램 이름(소문자) → 스팀 게임번호 (ListFolderGames 가 채워요)


def SteamAppFromExePath(strExePath: str) -> Optional[Tuple[str, str]]:
    """스팀 라이브러리 안의 프로그램이면 (스팀 게임번호, 게임 이름) 을 돌려줘요. 아니면 None.

    예) D:\\SteamLibrary\\steamapps\\common\\TEKKEN 8\\Polaris\\Binaries\\Win64\\Polaris-Win64-Shipping.exe
        → 같은 steamapps 폴더의 appmanifest_1778820.acf 에서 installdir = "TEKKEN 8" 인 것을 찾아 ("1778820", "TEKKEN 8")
    프로그램 이름(Polaris-...)은 게임 이름과 달라도, 설치 폴더 이름으로 어떤 게임인지 정확히 알 수 있어요.
    """
    strLower = (strExePath or "").replace("/", "\\").lower()
    strMarker = "\\steamapps\\common\\"
    nIndex = strLower.find(strMarker)
    if nIndex < 0:
        return None
    strNorm = (strExePath or "").replace("/", "\\")
    strSteamApps = strNorm[:nIndex + len("\\steamapps")]
    listRest = strNorm[nIndex + len(strMarker):].split("\\")
    if not listRest or not listRest[0]:
        return None
    dictFolders = _SteamManifests(strSteamApps)
    return dictFolders.get(listRest[0].lower())


def _SteamManifests(strSteamAppsDir: str) -> Dict[str, Tuple[str, str]]:
    import time
    fNow = time.monotonic()
    objCached = _dictManifestCache.get(strSteamAppsDir.lower())
    if objCached is not None and fNow - objCached[0] < F_MANIFEST_CACHE_SEC:
        return objCached[1]
    dictFolders: Dict[str, Tuple[str, str]] = {}
    try:
        for strFile in os.listdir(strSteamAppsDir):
            if not (strFile.lower().startswith("appmanifest_") and strFile.lower().endswith(".acf")):
                continue
            try:
                with open(os.path.join(strSteamAppsDir, strFile), "r", encoding="utf-8", errors="replace") as objFile:
                    strText = objFile.read(8192)  # 필요한 값은 맨 앞에 있어요
            except OSError:
                continue
            dictFields = {strKey.lower(): strValue for strKey, strValue in _RE_ACF_FIELD.findall(strText)}
            strAppId, strInstallDir = dictFields.get("appid", ""), dictFields.get("installdir", "")
            if strAppId.isdigit() and strInstallDir:
                dictFolders[strInstallDir.lower()] = (strAppId, dictFields.get("name") or strInstallDir)
    except OSError:
        pass
    _dictManifestCache[strSteamAppsDir.lower()] = (fNow, dictFolders)
    return dictFolders


def IsGameFolderPath(strPath: str) -> bool:
    """게임 설치 폴더 안의 '게임 같은' 프로그램이면 True. (런처 · 업데이트 · 안티치트 등은 빼요)"""
    strLower = (strPath or "").lower()
    if not strLower.endswith(".exe") or not any(strMarker in strLower for strMarker in LIST_GAME_DIR_MARKERS):
        return False
    strExe = os.path.basename(strLower)
    return not any(strWord in strExe for strWord in LIST_NON_GAME_EXE_WORDS)


def _CleanWindowTitle(strTitle: str) -> str:
    """창 제목을 게임 이름으로 다듬어요. "ELDEN RING™  " → "ELDEN RING", "Game (DX12) v1.2" → "Game"""
    import re
    strTitle = re.sub(r"[™®©]", "", strTitle or "")
    strTitle = re.sub(r"\s*[(\[](dx\d+|directx.*?|vulkan|opengl|64-?bit|32-?bit|shipping|x64)[)\]]", "", strTitle, flags=re.I)
    strTitle = re.sub(r"\s+v?\d+(\.\d+){1,3}\S*$", "", strTitle)  # 끝의 버전 번호
    return re.sub(r"\s+", " ", strTitle).strip(" -|")


def ListFolderGames() -> List[Tuple[str, str]]:
    """게임 설치 폴더에서 실행 중이고 창이 떠 있는 프로그램들: [(프로그램 이름, 게임 이름)]
    게임 이름은 창 제목에서 가져와요. (창 제목이 없으면 프로그램 이름)
    """
    if sys.platform != "win32":
        return []
    dictTable = _ProcessTable()
    objUser32 = ctypes.WinDLL("user32", use_last_error=True)
    fnEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    objUser32.EnumWindows.argtypes = [fnEnumProc, wintypes.LPARAM]
    objUser32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    objUser32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    objUser32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    objUser32.IsWindowVisible.argtypes = [wintypes.HWND]

    dictTitles: Dict[int, str] = {}  # 프로세스 번호 → 창 제목 (창이 떠 있는 것만)

    def _OnWindow(hWnd, _lParam):
        if objUser32.IsWindowVisible(hWnd):
            nPid = wintypes.DWORD()
            objUser32.GetWindowThreadProcessId(hWnd, ctypes.byref(nPid))
            nLength = objUser32.GetWindowTextLengthW(hWnd)
            strTitle = ""
            if nLength > 0:
                objBuffer = ctypes.create_unicode_buffer(nLength + 1)
                objUser32.GetWindowTextW(hWnd, objBuffer, nLength + 1)
                strTitle = objBuffer.value
            if strTitle or nPid.value not in dictTitles:
                dictTitles[nPid.value] = dictTitles.get(nPid.value) or strTitle
        return True

    objUser32.EnumWindows(fnEnumProc(_OnWindow), 0)

    listGames: List[Tuple[str, str]] = []
    setSeen = set()
    for nPid, strTitle in dictTitles.items():
        strExe = dictTable.get(nPid, "")
        if not strExe or strExe.lower() in setSeen:
            continue
        strPath = _ProcessPath(nPid)
        if IsGameFolderPath(strPath):
            setSeen.add(strExe.lower())
            objSteamApp = SteamAppFromExePath(strPath)
            if objSteamApp is not None:   # 스팀 게임이면 이름 · 번호를 스팀 설치 정보에서 (창 제목보다 정확해요)
                DICT_FOLDER_STEAM_IDS[strExe.lower()] = objSteamApp[0]
                listGames.append((strExe, objSteamApp[1]))
                continue
            strName = _CleanWindowTitle(strTitle) or os.path.splitext(strExe)[0]
            listGames.append((strExe, strName))
    return listGames


# ---------------------------------------------------------------------------
# 지금 하는 게임 고르기
# ---------------------------------------------------------------------------

def DetectProcessGame(setRunningExes: Set[str], listMappedKeys: List[str]) -> Optional[DetectedGame]:
    """실행 중인 프로그램 중에서 게임을 찾아요.

    1순위: 짝 목록에 적어둔 프로그램 (사용자가 직접 정한 것이니까)
    2순위: 잘 알려진 게임 목록에 있는 프로그램 (짝은 아직 없음 → 짝 만들기를 도와줘요)
    """
    for strKey in listMappedKeys:
        if IsExeKey(strKey) and KeyToDisplay(strKey) in setRunningExes:
            strExe = KeyToDisplay(strKey)
            return DetectedGame(strKey, DICT_KNOWN_GAMES.get(strExe, strExe), "process")
    for strExe, strName in DICT_KNOWN_GAMES.items():
        if strExe in setRunningExes:
            return DetectedGame(ExeKey(strExe), strName, "process")
    return None


def PickCurrentGame(objSteamStatus, setRunningExes: Set[str], listMappedKeys: List[str],
                    listFolderGames: Optional[List[Tuple[str, str]]] = None) -> Optional[DetectedGame]:
    """지금 하는 게임을 골라요. 순서:
    1) 스팀에서 게임 중 (Wallpaper Engine · OBS Studio 처럼 게임이 아닌 스팀 프로그램은 빼요)
    2) 짝 목록에 있는 프로그램 / 잘 알려진 게임 프로그램
    3) 게임 설치 폴더에서 실행 중인 프로그램 (에픽 · 넥슨 · 엑스박스 등 목록에 없는 게임도) — 이름은 창 제목
    """
    if objSteamStatus is not None and getattr(objSteamStatus, "bIsPlaying", False) and objSteamStatus.strGameId \
            and not IsNonGameSteamApp(objSteamStatus.strGameId):
        return DetectedGame(objSteamStatus.strGameId, objSteamStatus.strGameName or objSteamStatus.strGameId, "steam")
    objGame = DetectProcessGame(setRunningExes, listMappedKeys)
    if objGame is not None:
        return objGame
    for strExe, strName in listFolderGames or []:
        strSteamId = DICT_FOLDER_STEAM_IDS.get(strExe.lower())
        if strSteamId and not IsNonGameSteamApp(strSteamId):
            return DetectedGame(strSteamId, strName, "steam")   # 스팀 게임으로 취급 (스팀 API 키 없이도 돼요)
        if strSteamId:
            continue  # 스팀 도구(Wallpaper Engine 등)는 게임이 아니에요.
        return DetectedGame(ExeKey(strExe), strName, "folder")
    return None
