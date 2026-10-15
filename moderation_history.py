"""
제한 기록 (이 프로그램으로 한 제한)
===================================

시청자를 임시 제한 · 활동 제한 · 메시지 가리기 한 일을 남겨 둬요. ('이 시청자 정보' 창에서 보여줘요)

- 치지직은 제한 이력을 알려주지 않아요. 그래서 '이 프로그램으로 한 것' 만 기록해요.
  (치지직 스튜디오 등 다른 곳에서 한 제한은 알 수 없어요)
- 파일: data/moderation_history.json  (시험용 설정이면 moderation_history_test.json)
- 최근 1000건만 남겨요. 시청자 닉네임이 들어 있으니 남에게 보내지 마세요.
"""

import json
import os
import threading
from datetime import datetime
from typing import List, Optional

from app_paths import RecordPath

STR_HISTORY_FILE = RecordPath("moderation_history.json")
N_MAX_ENTRIES = 1000


class ModerationHistory:
    def __init__(self, strPath: str = STR_HISTORY_FILE, nMax: int = N_MAX_ENTRIES):
        self.strPath = strPath
        self.nMax = nMax
        self.objLock = threading.Lock()
        self.listEntries: List[dict] = []
        self._Load()

    def _Load(self) -> None:
        try:
            with open(self.strPath, "r", encoding="utf-8") as objFile:
                listItems = json.load(objFile)
        except (OSError, ValueError):
            return
        for dictItem in listItems if isinstance(listItems, list) else []:
            if isinstance(dictItem, dict) and dictItem.get("time") and dictItem.get("action"):
                self.listEntries.append({
                    "time": str(dictItem["time"]), "channelId": str(dictItem.get("channelId", "")),
                    "nickname": str(dictItem.get("nickname", "")), "action": str(dictItem["action"]),
                    "detail": str(dictItem.get("detail", "")),
                })
        del self.listEntries[:-self.nMax]

    def _Save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.strPath), exist_ok=True)
            strTemp = self.strPath + ".tmp"
            with open(strTemp, "w", encoding="utf-8") as objFile:
                json.dump(self.listEntries, objFile, ensure_ascii=False, indent=1)
            os.replace(strTemp, self.strPath)
        except OSError:
            pass  # 기록을 못 써도 제한 기능은 멈추지 않아요.

    def Add(self, strChannelId: str, strNickname: str, strAction: str, strDetail: str = "",
            dtTime: Optional[datetime] = None) -> None:
        with self.objLock:
            self.listEntries.append({
                "time": (dtTime or datetime.now()).isoformat(timespec="seconds"), "channelId": strChannelId or "",
                "nickname": strNickname or "", "action": strAction, "detail": strDetail or "",
            })
            del self.listEntries[:-self.nMax]
            self._Save()

    def ListFor(self, strChannelId: str) -> List[dict]:
        """그 시청자에게 한 일들 (오래된 것부터)."""
        if not strChannelId:
            return []
        with self.objLock:
            return [dictItem for dictItem in self.listEntries if dictItem["channelId"] == strChannelId]
