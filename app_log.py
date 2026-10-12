"""
로그 파일 (Log 폴더)
====================

프로그램에서 일어난 일(후원 · 미션 · 연결 · 오류 ...)을 파일로 남겨요.

    Log/2026-10-12.log      ← 하루에 파일 하나, 한 줄에 하나씩
    2026-10-12 21:30:15 [후원] 영상 후원 1,000원 시청자A — 고양이 영상

- 오늘 포함 7일치만 남기고, 더 오래된 파일은 자동으로 지워요. (날짜 이름 형식인 파일만 지워요)
- 로그 쓰기가 실패해도(폴더 권한 · 디스크 문제 등) 프로그램은 멈추지 않아요.
- 처리되지 않은 오류(예외)도 여기에 남겨요. → InstallExceptionHook()
- 프로그램 폴더(run.bat 이 있는 폴더, exe 면 exe 가 있는 폴더) 안의 Log 폴더에 저장해요.

주의: 후원 로그에는 시청자 닉네임과 후원 메시지가 들어가요. Log 폴더는 남에게 보내지 마세요.
"""

import os
import re
import sys
import threading
import traceback
from datetime import date, datetime, timedelta
from typing import Callable, List

from app_paths import STR_APP_DIR

STR_LOG_DIR = os.path.join(STR_APP_DIR, "Log")
N_KEEP_DAYS = 7  # 오늘 포함 며칠치를 남길지
RE_LOG_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.log$")


class AppLogger:
    def __init__(self, strDir: str = STR_LOG_DIR, nKeepDays: int = N_KEEP_DAYS,
                 fnNow: Callable[[], datetime] = datetime.now):
        self.strDir = strDir
        self.nKeepDays = nKeepDays
        self.fnNow = fnNow  # 시험할 때 날짜를 바꿔 끼우려고 따로 받아요.
        self.objLock = threading.Lock()  # 뒤쪽 일꾼 스레드에서도 쓰니까 자물쇠를 걸어요.
        self.strLastDay = ""             # 마지막으로 쓴 날짜 (날짜가 바뀌면 오래된 파일을 정리해요)
        self.bBroken = False             # 폴더를 못 만들면 더 시도하지 않아요.

    # -------------------------------------------------------------------
    def LogPath(self, dtDay: date) -> str:
        return os.path.join(self.strDir, dtDay.strftime("%Y-%m-%d") + ".log")

    def Write(self, strMessage: str) -> None:
        """한 줄(여러 줄이면 이어서 들여쓰기) 남겨요. 실패해도 조용히 넘어가요."""
        if self.bBroken:
            return
        try:
            with self.objLock:
                dtNow = self.fnNow()
                strDay = dtNow.strftime("%Y-%m-%d")
                if strDay != self.strLastDay:
                    os.makedirs(self.strDir, exist_ok=True)
                    self.strLastDay = strDay
                    self.Cleanup(dtNow.date())
                listLines = str(strMessage).splitlines() or [""]
                strText = listLines[0] + "".join("\n    " + strLine for strLine in listLines[1:])
                # 파일을 쓸 때마다 열고 닫아요. (파일이 계속 잠겨 있지 않아서 직접 열어 보거나 지워도 돼요)
                with open(self.LogPath(dtNow.date()), "a", encoding="utf-8") as objFile:
                    objFile.write(f"{dtNow.strftime('%Y-%m-%d %H:%M:%S')} {strText}\n")
        except OSError:
            self.bBroken = True

    def LogException(self, strWhere: str) -> None:
        """지금 처리 중인 예외를 자세히 남겨요. (except 안에서 불러요)"""
        self.Write(f"[오류] {strWhere}\n{traceback.format_exc().rstrip()}")

    def Cleanup(self, dtToday: date) -> List[str]:
        """오늘 포함 nKeepDays 일보다 오래된 로그 파일을 지워요. 돌려주는 값: 지운 파일 이름들"""
        listRemoved: List[str] = []
        dtOldest = dtToday - timedelta(days=self.nKeepDays - 1)
        try:
            listNames = os.listdir(self.strDir)
        except OSError:
            return listRemoved
        for strName in listNames:
            objMatch = RE_LOG_NAME.match(strName)  # 날짜 이름이 아닌 파일은 건드리지 않아요.
            if not objMatch:
                continue
            try:
                dtFile = date(int(objMatch.group(1)), int(objMatch.group(2)), int(objMatch.group(3)))
                if dtFile < dtOldest:
                    os.remove(os.path.join(self.strDir, strName))
                    listRemoved.append(strName)
            except (ValueError, OSError):
                continue
        return listRemoved


# 프로그램 전체가 같이 쓰는 로그
OBJ_LOGGER = AppLogger()


def Write(strMessage: str) -> None:
    OBJ_LOGGER.Write(strMessage)


def LogException(strWhere: str) -> None:
    OBJ_LOGGER.LogException(strWhere)


def InstallExceptionHook() -> None:
    """처리되지 않은 오류가 나면 로그에도 남기게 해요. (원래 하던 출력은 그대로 해요)"""
    fnOriginalHook = sys.excepthook

    def _Hook(objType, objValue, objTraceback):
        Write("[오류] 처리되지 않은 오류\n" + "".join(traceback.format_exception(objType, objValue, objTraceback)).rstrip())
        fnOriginalHook(objType, objValue, objTraceback)

    sys.excepthook = _Hook

    fnOriginalThreadHook = threading.excepthook

    def _ThreadHook(objArgs):
        Write(f"[오류] 스레드 '{getattr(objArgs.thread, 'name', '?')}' 에서 처리되지 않은 오류\n" + "".join(
            traceback.format_exception(objArgs.exc_type, objArgs.exc_value, objArgs.exc_traceback)).rstrip())
        fnOriginalThreadHook(objArgs)

    threading.excepthook = _ThreadHook
