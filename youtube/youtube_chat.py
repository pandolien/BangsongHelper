"""
유튜브 라이브 채팅 받기 (뒤쪽 스레드에서 계속 가져오기) + 오늘 사용량 기록
=========================================================================

치지직은 소켓으로 채팅이 '밀려 오지만', 유튜브 공식 API 는 '가서 가져와야' 해요.
그래서 유튜브가 알려준 간격(pollingIntervalMillis)마다 가져오되, 사용량을 아끼려고 최소 간격을 지켜요.

알림 함수 (모두 뒤쪽 스레드에서 불려요. GUI 라면 신호로 넘겨서 화면을 고쳐야 해요)
    fnOnChat(YouTubeChatMessage)     : 일반 채팅
    fnOnSuperChat(YouTubeChatMessage): 슈퍼챗 · 슈퍼 스티커
    fnOnStatus(상태, 설명)            : "connecting" / "connected" / "reconnecting" / "stopped" / "error"
"""

import json
import os
import threading
from typing import Callable, Optional

from app_paths import RecordPath

from .youtube_api import QuotaDayKey, YouTubeApiClient, YouTubeApiError, YouTubeChatMessage, YouTubeLiveInfo

N_DAILY_QUOTA = 10_000
N_FIRST_SHOW = 5              # 연결하자마자 보여줄 '최근 채팅' 수 (예전 채팅이 한꺼번에 쏟아지지 않게)
N_RETRY_FIRST_SEC = 5
N_RETRY_MAX_SEC = 60
STR_QUOTA_FILE = RecordPath("youtube_quota.json")


class YouTubeQuotaTracker:
    """오늘(미국 태평양 시간 기준) 쓴 유튜브 API 사용량을 세서 파일에 기억해요. (프로그램을 껐다 켜도 이어서)
    구글이 실제로 센 값과 조금 다를 수 있어요. (다른 프로그램이 같은 키를 쓰면 그만큼 더 쓰여요)
    """

    def __init__(self, strPath: str = STR_QUOTA_FILE):
        self.strPath = strPath
        self.objLock = threading.Lock()
        self.strDay, self.nUsed = QuotaDayKey(), 0
        try:
            with open(strPath, "r", encoding="utf-8") as objFile:
                dictData = json.load(objFile)
            if dictData.get("day") == self.strDay:
                self.nUsed = int(dictData.get("used") or 0)
        except (OSError, ValueError, TypeError):
            pass

    def Add(self, nCost: int) -> int:
        with self.objLock:
            strToday = QuotaDayKey()
            if strToday != self.strDay:  # 날이 바뀌었으면 다시 0부터
                self.strDay, self.nUsed = strToday, 0
            self.nUsed += nCost
            try:
                os.makedirs(os.path.dirname(self.strPath), exist_ok=True)
                with open(self.strPath, "w", encoding="utf-8") as objFile:
                    json.dump({"day": self.strDay, "used": self.nUsed}, objFile)
            except OSError:
                pass
            return self.nUsed

    @property
    def nUsedToday(self) -> int:
        with self.objLock:
            return self.nUsed if self.strDay == QuotaDayKey() else 0


class YouTubeChatSession:
    def __init__(self, objClient: YouTubeApiClient, strInput: str, fMinIntervalSec: float = 8.0,
                 fnOnChat: Optional[Callable[[YouTubeChatMessage], None]] = None,
                 fnOnSuperChat: Optional[Callable[[YouTubeChatMessage], None]] = None,
                 fnOnStatus: Optional[Callable[[str, str], None]] = None):
        self.objClient = objClient
        self.strInput = strInput
        self.fMinIntervalSec = max(2.0, float(fMinIntervalSec))
        self.fnOnChat = fnOnChat
        self.fnOnSuperChat = fnOnSuperChat
        self.fnOnStatus = fnOnStatus
        self.objStopEvent = threading.Event()
        self.objThread: Optional[threading.Thread] = None
        self.objLiveInfo: Optional[YouTubeLiveInfo] = None

    @property
    def bIsRunning(self) -> bool:
        return self.objThread is not None and self.objThread.is_alive()

    def Start(self) -> None:
        if self.bIsRunning:
            return
        self.objStopEvent.clear()
        self.objThread = threading.Thread(target=self._RunLoop, name="YouTubeChatSession", daemon=True)
        self.objThread.start()

    def Stop(self) -> None:
        self.objStopEvent.set()

    # -------------------------------------------------------------------
    def _Notify(self, strState: str, strMessage: str) -> None:
        if self.fnOnStatus:
            try:
                self.fnOnStatus(strState, strMessage)
            except Exception:
                pass

    def _Emit(self, objMessage: YouTubeChatMessage) -> None:
        fnTarget = self.fnOnSuperChat if objMessage.bIsSuperChat else self.fnOnChat
        if fnTarget:
            try:
                fnTarget(objMessage)
            except Exception:
                pass

    def _RunLoop(self) -> None:
        strPageToken = ""
        bFirst = True
        nRetrySec = N_RETRY_FIRST_SEC
        self._Notify("connecting", "유튜브 방송을 찾는 중...")
        while not self.objStopEvent.is_set():
            try:
                if self.objLiveInfo is None:
                    self.objLiveInfo = self.objClient.ResolveLive(self.strInput)
                    self._Notify("connected", f"유튜브 채팅 연결: {self.objLiveInfo.strTitle} ({self.objLiveInfo.strChannelTitle})")
                listMessages, strPageToken, nWaitMs = self.objClient.ListChatMessages(self.objLiveInfo.strLiveChatId, strPageToken)
                if bFirst:  # 처음엔 최근 몇 개만 (예전 채팅이 한꺼번에 쏟아지지 않게)
                    listMessages, bFirst = listMessages[-N_FIRST_SHOW:], False
                for objMessage in listMessages:
                    self._Emit(objMessage)
                if nRetrySec != N_RETRY_FIRST_SEC:  # 문제가 있었다가 다시 잘 되면 알려요.
                    self._Notify("connected", "유튜브 채팅 다시 연결됐어요.")
                nRetrySec = N_RETRY_FIRST_SEC
                self.objStopEvent.wait(max(nWaitMs / 1000.0, self.fMinIntervalSec))
            except YouTubeApiError as objError:
                if objError.bFatal or objError.strReason in ("badInput", "notLive", "noActiveChat", "channelNotFound", "keyMissing"):
                    self._Notify("error", str(objError))
                    break
                self._Notify("reconnecting", f"{objError} → {nRetrySec}초 뒤에 다시 시도해요.")
                self.objStopEvent.wait(nRetrySec)
                nRetrySec = min(nRetrySec * 2, N_RETRY_MAX_SEC)
            except Exception as objError:  # 예상 못 한 문제도 프로그램이 꺼지지 않게
                self._Notify("reconnecting", f"유튜브 채팅 문제: {objError} → {nRetrySec}초 뒤에 다시 시도해요.")
                self.objStopEvent.wait(nRetrySec)
                nRetrySec = min(nRetrySec * 2, N_RETRY_MAX_SEC)
        self._Notify("stopped", "")
