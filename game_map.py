"""
스팀 게임 ↔ 치지직 카테고리 '짝꿍 목록' 관리 모듈 (data/game_map.txt)
=====================================================================

왜 필요한가요?
    스팀은 "ELDEN RING NIGHTREIGN", 치지직은 "엘든 링 나이트레인" 처럼
    같은 게임인데 이름이 달라서, 이름으로 검색하면 자꾸 엇갈려요.

어떻게 해결하나요?
    이름 대신 '절대 안 바뀌는 번호' 끼리 짝을 지어 텍스트 파일에 적어둬요.
        - 스팀 쪽   : gameid (예: 2622380)
        - 치지직 쪽 : 카테고리 종류 + 카테고리 ID (방송 설정 변경 API 에 실제로 들어가는 값)

    파일 한 줄의 모양:
        스팀gameid = 카테고리종류 | 카테고리ID | 치지직카테고리이름   # 메모(스팀 게임 이름)
    예:
        2622380 = GAME | ELDEN_RING_NIGHTREIGN | 엘든 링 나이트레인   # ELDEN RING NIGHTREIGN

    - '#' 뒤는 사람이 보는 메모라서 프로그램은 무시해요.
    - 치지직카테고리이름 칸은 화면 표시용이라 비워도 돼요.
    - 메모장으로 직접 고쳐도 되고, 프로그램에서 카테고리를 골라 적용하면 자동으로 한 줄 추가돼요.
    - 잘못 적은 줄은 건너뛰고 "몇 번째 줄이 이상해요" 라고 알려줘요. (파일 전체가 망가지지 않아요)

    스팀 밖 게임(롤, 발로란트 등)은 gameid 대신 'exe:프로그램이름' 을 열쇠로 써요. (game_detect.py 참고)
        exe:valorant-win64-shipping.exe = GAME | VALORANT | 발로란트   # VALORANT
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from app_paths import DataPath
from game_detect import IsValidKey, NormalizeKey

STR_GAME_MAP_PATH = DataPath("game_map.txt")

LIST_VALID_CATEGORY_TYPES = ["GAME", "SPORTS", "ETC"]

# 파일이 없을 때 맨 위에 적어주는 설명서
STR_FILE_HEADER = """\
# ============================================================================
#  스팀 게임 ↔ 치지직 카테고리 짝꿍 목록
#
#  한 줄 모양:
#    스팀gameid = 카테고리종류 | 카테고리ID | 치지직카테고리이름   # 메모
#
#  - 스팀gameid      : 숫자 ([보기] → [방송 상태] 의 '플레이 중' 옆 ID)
#                      스팀 밖 게임은 exe:프로그램이름.exe (예: exe:valorant-win64-shipping.exe)
#  - 카테고리종류    : GAME / SPORTS / ETC 중 하나
#  - 카테고리ID      : 치지직 카테고리 ID (프로그램에서 카테고리를 골라 적용하면 자동으로 채워져요)
#  - 치지직카테고리이름 : 화면에 보여줄 이름 (비워도 됨)
#  - '#' 뒤는 메모라서 무시돼요.
# ============================================================================
"""


@dataclass
class GameMapEntry:
    """짝꿍 한 쌍."""

    strSteamGameId: str        # 스팀 gameid (숫자 글자) 또는 exe:프로그램이름.exe
    strCategoryType: str       # GAME / SPORTS / ETC
    strCategoryId: str         # 치지직 카테고리 ID
    strCategoryValue: str = ""  # 치지직 카테고리 이름 (표시용)
    strMemo: str = ""          # '#' 뒤 메모 (보통 스팀 게임 이름)

    def ToLine(self) -> str:
        strLine = f"{self.strSteamGameId} = {self.strCategoryType} | {self.strCategoryId} | {self.strCategoryValue}"
        if self.strMemo:
            strLine += f"   # {self.strMemo}"
        return strLine


class GameMap:
    """짝꿍 목록 파일을 읽고, 찾고, 고치는 관리자예요.

    사용 예:
        objMap = GameMap()
        objEntry = objMap.Get("2622380")     # 없으면 None
        objMap.Set(GameMapEntry("2622380", "GAME", "ELDEN_RING_NIGHTREIGN", "엘든 링 나이트레인", "ELDEN RING NIGHTREIGN"))
    """

    def __init__(self, strPath: str = STR_GAME_MAP_PATH):
        self.strPath = strPath
        self.listLines: List[str] = []              # 파일의 모든 줄 (메모/빈 줄 포함, 원래 모양 그대로)
        self.dictEntries: Dict[str, GameMapEntry] = {}
        self.dictLineIndex: Dict[str, int] = {}     # gameid → 몇 번째 줄인지
        self.listWarnings: List[str] = []           # 잘못된 줄 안내
        self.Load()

    # -------------------------------------------------------------------
    # 읽기
    # -------------------------------------------------------------------
    def Load(self) -> List[str]:
        """파일을 다시 읽어요. 돌려주는 값: 잘못된 줄 안내 목록 (없으면 빈 목록)"""
        if not os.path.exists(self.strPath):
            self.listLines = STR_FILE_HEADER.splitlines()
            self._WriteFile()
        else:
            with open(self.strPath, "r", encoding="utf-8-sig") as objFile:
                self.listLines = objFile.read().splitlines()

        self.dictEntries, self.dictLineIndex, self.listWarnings = {}, {}, []
        for nIndex, strLine in enumerate(self.listLines):
            objEntry, strWarning = self._ParseLine(strLine)
            if strWarning:
                self.listWarnings.append(f"game_map.txt {nIndex + 1}번째 줄: {strWarning}")
            if objEntry:
                if objEntry.strSteamGameId in self.dictEntries:
                    self.listWarnings.append(
                        f"game_map.txt {nIndex + 1}번째 줄: gameid {objEntry.strSteamGameId} 가 또 나와서 이 줄을 사용해요."
                    )
                self.dictEntries[objEntry.strSteamGameId] = objEntry
                self.dictLineIndex[objEntry.strSteamGameId] = nIndex
        return self.listWarnings

    @staticmethod
    def _ParseLine(strLine: str):
        """한 줄을 해석해요. 돌려주는 값: (짝꿍 또는 None, 경고 글자 또는 "")"""
        # '#' 앞은 내용, 뒤는 메모
        strContent, _, strMemo = strLine.partition("#")
        strContent, strMemo = strContent.strip(), strMemo.strip()
        if not strContent:
            return None, ""  # 빈 줄이나 메모만 있는 줄

        strGameId, strEqual, strRight = strContent.partition("=")
        strGameId = NormalizeKey(strGameId)
        if not strEqual:
            return None, "'=' 가 없어요. (예: 2622380 = GAME | 카테고리ID | 이름)"
        if not IsValidKey(strGameId):
            return None, f"'{strGameId}' 는 스팀 gameid(숫자) 또는 exe:프로그램이름.exe 여야 해요."

        listParts = [strPart.strip() for strPart in strRight.split("|")]
        if len(listParts) < 2 or not listParts[1]:
            return None, "'카테고리종류 | 카테고리ID' 가 필요해요."
        strCategoryType = listParts[0].upper()
        if strCategoryType not in LIST_VALID_CATEGORY_TYPES:
            return None, f"카테고리종류 '{listParts[0]}' 는 {LIST_VALID_CATEGORY_TYPES} 중 하나여야 해요."

        return GameMapEntry(
            strSteamGameId=strGameId,
            strCategoryType=strCategoryType,
            strCategoryId=listParts[1],
            strCategoryValue=" | ".join(listParts[2:]).strip(),
            strMemo=strMemo,
        ), ""

    # -------------------------------------------------------------------
    # 찾기
    # -------------------------------------------------------------------
    def Get(self, strSteamGameId: Optional[str]) -> Optional[GameMapEntry]:
        if not strSteamGameId:
            return None
        return self.dictEntries.get(NormalizeKey(str(strSteamGameId)))

    def ListEntries(self) -> List[GameMapEntry]:
        return list(self.dictEntries.values())

    # -------------------------------------------------------------------
    # 고치기 (사용자가 적어둔 다른 줄과 메모는 그대로 지켜요)
    # -------------------------------------------------------------------
    def Set(self, objEntry: GameMapEntry) -> None:
        """짝꿍을 추가하거나, 이미 있으면 그 줄만 바꿔요. 바로 파일에 저장돼요."""
        objEntry.strSteamGameId = NormalizeKey(objEntry.strSteamGameId)
        if not IsValidKey(objEntry.strSteamGameId):
            raise ValueError("스팀 gameid(숫자) 또는 exe:프로그램이름.exe 여야 해요.")
        if objEntry.strCategoryType not in LIST_VALID_CATEGORY_TYPES:
            raise ValueError(f"카테고리종류는 {LIST_VALID_CATEGORY_TYPES} 중 하나여야 해요.")

        # 메모를 따로 안 줬으면 예전 메모를 그대로 살려요.
        objOld = self.dictEntries.get(objEntry.strSteamGameId)
        if objOld and not objEntry.strMemo:
            objEntry.strMemo = objOld.strMemo

        if objEntry.strSteamGameId in self.dictLineIndex:
            self.listLines[self.dictLineIndex[objEntry.strSteamGameId]] = objEntry.ToLine()
        else:
            self.listLines.append(objEntry.ToLine())
        self._WriteFile()
        self.Load()

    def Remove(self, strSteamGameId: str) -> bool:
        """짝꿍을 지워요. 지웠으면 True."""
        strSteamGameId = NormalizeKey(strSteamGameId)
        if strSteamGameId not in self.dictLineIndex:
            return False
        del self.listLines[self.dictLineIndex[strSteamGameId]]
        self._WriteFile()
        self.Load()
        return True

    def _WriteFile(self) -> None:
        os.makedirs(os.path.dirname(self.strPath), exist_ok=True)
        strTempPath = self.strPath + ".tmp"
        with open(strTempPath, "w", encoding="utf-8") as objFile:
            objFile.write("\n".join(self.listLines) + "\n")
        os.replace(strTempPath, self.strPath)
