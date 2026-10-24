"""
게임 이름 목록 (디스코드가 공개해 둔 '실행 파일 ↔ 게임' 목록)
================================================================

왜 필요한가요?
    철권 8 의 프로그램 이름은 Polaris-Win64-Shipping.exe 처럼 게임 이름과 전혀 달라요.
    디스코드는 "지금 하는 게임 표시" 를 위해 '프로그램 이름 → 게임 이름 · 스팀 번호' 목록을 누구나 받을 수 있게
    공개해 두었어요. (약 2만 5천 게임) 그걸 받아 두고, 실행 중인 프로그램 이름으로 어떤 게임인지 알아내요.

- 디스코드 프로그램 · 계정 · 로그인은 필요 없어요. 공개된 목록 파일 하나를 내려받기만 해요. (아무것도 보내지 않아요)
- 하루에 한 번만 받아서 data 폴더에 저장해 둬요. (인터넷이 안 되면 저장해 둔 것을 써요)
- 공식 문서로 약속된 주소는 아니라서, 바뀌거나 막히면 이 기능만 조용히 건너뛰어요. (프로그램은 그대로 돌아요)
- 같은 프로그램 이름을 여러 게임이 쓰면 하나로 단정하지 않아요.
"""

import json
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import requests

STR_URL = "https://discord.com/api/v10/applications/detectable"
N_MAX_BYTES = 40 * 1024 * 1024        # 이보다 크면 받다가 그만둬요
F_MAX_AGE_SEC = 24 * 60 * 60          # 하루가 지나면 다시 받아요
F_RETRY_SEC = 60 * 60                 # 실패하면 한 시간 뒤에 다시
F_TIMEOUT_SEC = 30.0

# 너무 흔한 프로그램 이름은 어떤 게임인지 알 수 없어서 쓰지 않아요.
SET_GENERIC_EXES = {
    "game.exe", "launcher.exe", "start.exe", "main.exe", "client.exe", "setup.exe", "run.exe", "app.exe", "bin.exe",
    "win64.exe", "win32.exe", "gamelauncher.exe", "play.exe", "application.exe", "program.exe", "updater.exe",
    "installer.exe", "editor.exe", "server.exe", "demo.exe", "test.exe",
}

_objLock = threading.Lock()
_dictIndex: Optional[Dict[str, List[Tuple[str, str]]]] = None   # 프로그램 이름(소문자) → [(게임 이름, 스팀 번호 또는 "")]
_dictBySteam: Dict[str, List[str]] = {}                          # 스팀 번호 → 게임 이름들 (디스코드 목록에 올라 있는 이름)
_fLoadedAt = 0.0          # 이 목록을 받은 시각
_fLastAttemptAt = 0.0
_bRefreshing = False


def _ExeBaseName(strExe: str) -> str:
    """'>폴더/Game.exe' → 'game.exe' (디스코드 목록은 앞에 기호나 폴더가 붙기도 해요)"""
    strExe = (strExe or "").strip().lstrip(">").replace("\\", "/")
    return strExe.split("/")[-1].strip().lower()


def BuildIndex(listGames: list) -> Dict[str, List[Tuple[str, str]]]:
    """디스코드 목록(JSON) → 프로그램 이름으로 찾는 표. 윈도우용 .exe 만 담아요."""
    dictIndex: Dict[str, List[Tuple[str, str]]] = {}
    for dictGame in listGames if isinstance(listGames, list) else []:
        if not isinstance(dictGame, dict):
            continue
        strName = str(dictGame.get("name") or "").strip()
        if not strName:
            continue
        listSteam = [str(dictSku.get("id")) for dictSku in (dictGame.get("third_party_skus") or [])
                     if isinstance(dictSku, dict) and dictSku.get("distributor") == "steam" and str(dictSku.get("id", "")).isdigit()]
        strSteamId = listSteam[0] if len(set(listSteam)) == 1 else ""   # 스팀 번호가 여러 개면 고르지 않아요
        for dictExe in dictGame.get("executables") or []:
            if not isinstance(dictExe, dict) or dictExe.get("os") != "win32":
                continue
            strBase = _ExeBaseName(str(dictExe.get("name") or ""))
            if not strBase.endswith(".exe") or len(strBase) < 7 or strBase in SET_GENERIC_EXES:
                continue
            listEntries = dictIndex.setdefault(strBase, [])
            if (strName, strSteamId) not in listEntries:
                listEntries.append((strName, strSteamId))
    return dictIndex


def Lookup(strExe: str) -> Optional[Tuple[str, str]]:
    """프로그램 이름 → (게임 이름, 스팀 번호 또는 ""). 모르거나 게임이 여럿이라 애매하면 None."""
    with _objLock:
        dictIndex = _dictIndex
    if not dictIndex:
        return None
    listEntries = dictIndex.get(_ExeBaseName(strExe))
    if not listEntries:
        return None
    if len(listEntries) == 1:
        return listEntries[0]
    setSteamIds = {strSteamId for _, strSteamId in listEntries}
    if len(setSteamIds) == 1 and "" not in setSteamIds:
        return listEntries[0]      # 이름만 조금씩 다를 뿐 같은 스팀 게임
    return None                    # 서로 다른 게임이 같은 이름을 써요 → 고르지 않아요


def NamesFor(strGameId: str) -> List[str]:
    """게임 열쇠(스팀 번호 또는 'exe:프로그램이름')로 디스코드 목록에 올라 있는 게임 이름들을 돌려줘요. 모르면 빈 목록.
    프로그램 이름이 여러 게임에 쓰여서 애매하면(Lookup 이 None) 빈 목록이에요."""
    strGameId = str(strGameId or "").strip()
    with _objLock:
        dictBySteam = _dictBySteam
    if strGameId.isdigit():
        return list(dictBySteam.get(strGameId, []))
    if strGameId.lower().startswith("exe:"):
        objFound = Lookup(strGameId[4:])
        if objFound is not None:
            strName, strSteamId = objFound
            listNames = [strName]
            for strOther in dictBySteam.get(strSteamId, []) if strSteamId else []:
                if strOther not in listNames:
                    listNames.append(strOther)
            return listNames
    return []


def IsLoaded() -> bool:
    with _objLock:
        return bool(_dictIndex)


def _SetIndex(dictIndex: Optional[Dict[str, List[Tuple[str, str]]]], fLoadedAt: float) -> None:
    global _dictIndex, _fLoadedAt, _dictBySteam
    dictBySteam: Dict[str, List[str]] = {}
    for listEntries in (dictIndex or {}).values():
        for strName, strSteamId in listEntries:
            if strSteamId and strName not in dictBySteam.setdefault(strSteamId, []):
                dictBySteam[strSteamId].append(strName)
    with _objLock:
        _dictIndex, _fLoadedAt, _dictBySteam = dictIndex, fLoadedAt, dictBySteam


def _LoadCache(strCachePath: str) -> bool:
    try:
        with open(strCachePath, "r", encoding="utf-8") as objFile:
            dictData = json.load(objFile)
        dictIndex = {strExe: [(str(listItem[0]), str(listItem[1])) for listItem in listEntries]
                     for strExe, listEntries in dictData["index"].items()}
        _SetIndex(dictIndex, float(dictData["fetched_at"]))
        return True
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return False


def _SaveCache(strCachePath: str, dictIndex: Dict[str, List[Tuple[str, str]]], fFetchedAt: float) -> None:
    os.makedirs(os.path.dirname(strCachePath), exist_ok=True)
    strTemp = strCachePath + ".tmp"
    with open(strTemp, "w", encoding="utf-8") as objFile:
        json.dump({"fetched_at": fFetchedAt, "index": dictIndex}, objFile, ensure_ascii=False, separators=(",", ":"))
    os.replace(strTemp, strCachePath)


def Download() -> list:
    """공개 목록을 받아요. (크기 제한 · 시간 제한) 실패하면 예외."""
    with requests.get(STR_URL, timeout=F_TIMEOUT_SEC, stream=True, headers={"User-Agent": "BangsongHelper"}) as objResponse:
        objResponse.raise_for_status()
        baData = bytearray()
        for baChunk in objResponse.iter_content(chunk_size=1 << 16):
            baData.extend(baChunk)
            if len(baData) > N_MAX_BYTES:
                raise ValueError("목록이 너무 커요")
    listGames = json.loads(bytes(baData).decode("utf-8"))
    if not isinstance(listGames, list) or not listGames:
        raise ValueError("목록 모양이 달라요")
    return listGames


def EnsureLoaded(strCachePath: str, fnLog: Optional[Callable[[str], None]] = None, fnDownload: Callable[[], list] = Download) -> None:
    """저장해 둔 목록을 바로 불러오고, 오래됐으면 뒤에서 새로 받아요. (화면이 멈추지 않아요)"""
    global _bRefreshing, _fLastAttemptAt
    fnLog = fnLog or (lambda strMessage: None)
    if not IsLoaded():
        _LoadCache(strCachePath)
    fNow = time.time()
    with _objLock:
        bFresh = _dictIndex is not None and fNow - _fLoadedAt < F_MAX_AGE_SEC
        bTooSoon = fNow - _fLastAttemptAt < F_RETRY_SEC
        if bFresh or bTooSoon or _bRefreshing:
            return
        _bRefreshing = True
        _fLastAttemptAt = fNow

    def _Work():
        global _bRefreshing
        try:
            dictIndex = BuildIndex(fnDownload())
            if not dictIndex:
                raise ValueError("쓸 수 있는 게임이 없어요")
            fFetched = time.time()
            _SetIndex(dictIndex, fFetched)
            try:
                _SaveCache(strCachePath, dictIndex, fFetched)
            except OSError:
                pass
            fnLog(f"[게임 목록] 디스코드 공개 게임 목록을 받았어요. ({len(dictIndex):,}개 프로그램)")
        except Exception as objError:   # 인터넷이 안 되거나 주소가 바뀌어도 프로그램은 그대로 돌아요.
            fnLog(f"[게임 목록] 디스코드 공개 목록을 받지 못했어요 (저장해 둔 목록이 있으면 그걸 써요): {objError}")
        finally:
            with _objLock:
                _bRefreshing = False

    threading.Thread(target=_Work, name="discord-games", daemon=True).start()
