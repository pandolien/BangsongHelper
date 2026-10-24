"""
게임 → 치지직 카테고리 자동 짝 찾기
====================================

왜 필요한가요?
    스팀은 영어 이름("ELDEN RING NIGHTREIGN"), 치지직은 한국어 이름("ELDEN RING 밤의 통치자")을 써서
    스팀 이름으로 검색하면 0건이 나오는 경우가 많아요.

어떻게 찾나요?
    1) 스팀 상점에 '한국어 이름' 을 물어봐요. (API 키 필요 없음)
       예) 2622380 → "ELDEN RING 밤의 통치자", 1778820 → "철권 8", 2358720 → "검은 신화: 오공"
    2) 한국어 이름 → 이름 조각("Palworld / 팰월드" → "팰월드") → 영어 이름 순서로 치지직 카테고리를 검색해요.
    3) 검색어와 '이름이 똑같은' 카테고리가 있으면 → 확실한 짝 (자동 저장해도 돼요)
       비슷하기만 하면 → 후보로만 보여줘요. (예: "ELDEN RING" 으로 찾았는데 "ELDEN RING 밤의 통치자" 만 나오면 다른 게임!)
    4) 스팀에 한국어 이름이 없는 유명 게임은 아래 '한국어 이름 목록' 으로 찾아요. (예: Counter-Strike 2 → 카운터 스트라이크 2)
    5) 이름이 똑같진 않아도 '거의 똑같은' 후보가 딱 하나 있으면(띄어쓰기 · 철자만 조금 다름, 숫자 · 로마 숫자는 같음)
       '추정 짝' 으로 써요. (짝으로 저장하지는 않고, 로그에 알려요)
    6) 그래도 못 찾으면 → '종합 게임' 카테고리를 쓰게 할 수 있어요. (짝으로 저장하지는 않아요)
"""

import difflib
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

STR_STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STR_STEAM_STORESEARCH_URL = "https://store.steampowered.com/api/storesearch/"
F_TIMEOUT_SEC = 10.0

# 스팀 상점 이름은 바뀔 일이 거의 없어서, 한 번 물어본 건 기억해 둬요. (프로그램 켜져 있는 동안)
_dictNameCache: Dict[str, List[str]] = {}
_objCacheLock = threading.Lock()

# 치지직에 없는 게임에 쓰는 카테고리: (종류, ID, 이름)
TUPLE_FALLBACK_CATEGORY = ("GAME", "various_games", "종합 게임")

# 스팀 / 프로그램 이름 → 치지직에서 쓰는 한국어 이름
# (스팀 상점에 한국어 이름이 없어서 자동으로 못 찾는 유명 게임들. 모두 치지직 카테고리 이름과 똑같은지 확인했어요)
DICT_KOREAN_NAMES = {
    "Counter-Strike 2": "카운터 스트라이크 2", "Baldur's Gate 3": "발더스 게이트 3", "HELLDIVERS 2": "헬다이버즈 2",
    "PUBG: BATTLEGROUNDS": "PUBG: 배틀그라운드", "Lost Ark": "로스트아크", "Apex Legends": "에이펙스 레전드",
    "Dota 2": "도타 2", "Monster Hunter Wilds": "몬스터 헌터 와일즈", "Monster Hunter: World": "몬스터 헌터: 월드",
    "Monster Hunter Rise": "몬스터 헌터 라이즈", "Stardew Valley": "스타듀 밸리", "Terraria": "테라리아",
    "Lethal Company": "리썰 컴퍼니", "Dead by Daylight": "데드 바이 데이라이트", "Rust": "러스트", "Valheim": "발헤임",
    "Sekiro: Shadows Die Twice": "세키로: 섀도우 다이 트와이스", "Sekiro": "세키로: 섀도우 다이 트와이스",
    "DARK SOULS III": "다크 소울 3", "Hollow Knight": "할로우 나이트", "Overwatch 2": "오버워치", "Overwatch": "오버워치",
    "Path of Exile 2": "패스 오브 엑자일 2", "Ready or Not": "레디 오어 낫", "THE FINALS": "더 파이널스",
    "Hades": "하데스", "Hades II": "하데스 2", "ELDEN RING": "엘든 링", "Minecraft": "마인크래프트",
    "League of Legends": "리그 오브 레전드", "VALORANT": "발로란트", "MapleStory": "메이플스토리", "Lies of P": "P의 거짓",
    "Cyberpunk 2077": "사이버펑크 2077", "The Witcher 3: Wild Hunt": "더 위쳐 3: 와일드 헌트", "Phasmophobia": "파스모포비아",
    "Among Us": "어몽 어스", "Fall Guys": "폴가이즈", "Tom Clancy's Rainbow Six Siege": "톰 클랜시의 레인보우 식스 시즈 X",
    "Rainbow Six Siege": "톰 클랜시의 레인보우 식스 시즈 X", "Sea of Thieves": "씨 오브 시브즈",
    "Hearts of Iron IV": "하츠 오브 아이언 4", "Sid Meier's Civilization VI": "시드 마이어의 문명 VI",
    "Sid Meier's Civilization VII": "시드 마이어의 문명 VII", "Factorio": "팩토리오", "Satisfactory": "새티스팩토리",
    "Don't Starve Together": "돈 스타브 투게더", "Dave the Diver": "데이브 더 다이버", "Street Fighter 6": "스트리트 파이터 6",
    "TEKKEN 8": "철권 8", "Destiny 2": "데스티니 가디언즈", "Warframe": "워프레임", "War Thunder": "워 썬더",
    "Escape from Tarkov": "이스케이프 프롬 타르코프", "Left 4 Dead 2": "레프트 4 데드 2", "Garry's Mod": "게리 모드",
    "Project Zomboid": "프로젝트 좀보이드", "Euro Truck Simulator 2": "유로 트럭 시뮬레이터 2",
    "Slay the Spire": "슬레이 더 스파이어", "Balatro": "발라트로", "Vampire Survivors": "뱀파이어 서바이버즈",
    "It Takes Two": "잇 테이크 투", "Split Fiction": "스플릿 픽션", "Stellar Blade": "스텔라 블레이드",
    "Black Desert": "검은사막", "Diablo IV": "디아블로 4", "Sons Of The Forest": "선즈 오브 더 포레스트",
    "The Forest": "더 포레스트", "Subnautica": "서브노티카", "Palworld": "팰월드", "Enshrouded": "인슈라오디드",
    "Chained Together": "체인드 투게더", "Once Human": "Once Human",
    # 스팀 동시접속자 상위 100 에서 자동으로 못 찾았던 게임들 (치지직 이름 확인함)
    "Deadlock": "데드락", "WARDOGS": "워독스", "ARC Raiders": "아크 레이더스", "Geometry Dash": "지오메트리 대시",
    "Slay the Spire 2": "슬레이 더 스파이어 2", "The Outlast Trials": "아웃라스트 트라이얼",
    "The Witcher 3: Wild Hunt — Remastered": "더 위쳐 3: 와일드 헌트",
    "The Binding of Isaac: Rebirth": "아이작의 번제: 리버스", "Limbus Company": "림버스 컴퍼니", "Delta Force": "델타포스",
    "Team Fortress 2": "팀 포트리스 2", "Battlefield 6": "배틀필드 6", "EA SPORTS FC 26": "EA 스포츠 FC 26",
    "NARAKA: BLADEPOINT": "나라카: 블레이드포인트", "Red Dead Redemption 2": "레드 데드 리뎀션 2", "Risk of Rain 2": "리스크 오브 레인 2",
    "BeamNG.drive": "빔엔지.드라이브", "Rocket League": "로켓 리그",
    "The Elder Scrolls V: Skyrim Special Edition": "엘더스크롤 5: 스카이림", "The Elder Scrolls V: Skyrim": "엘더스크롤 5: 스카이림",
    "Yu-Gi-Oh! Master Duel": "유희왕 마스터 듀얼", "Forza Horizon 6": "포르자 호라이즌 6", "Forza Horizon 5": "포르자 호라이즌 5",
    "Warhammer 40,000: Space Marine 2": "워해머 40,000: 스페이스 마린 2", "Wuthering Waves": "명조:워더링 웨이브",
    "Farming Simulator 25": "파밍 시뮬레이터 25", "Bloons TD 6": "블룬스 TD 6", "The Sims 4": "더 심즈 4",
    "Assetto Corsa": "아세토 코르사", "Brawlhalla": "브롤할라", "Mount & Blade II: Bannerlord": "마운트 앤 블레이드 2: 배너로드",
    "World of Warships": "월드 오브 워쉽", "Hunt: Showdown 1896": "헌트: 쇼다운 1896",
    "Age of Empires II: Definitive Edition": "에이지 오브 엠파이어 2: 디피니티브 에디션", "Crusader Kings III": "크루세이더 킹즈 3",
    "Aimlabs": "에임랩스", "7 Days to Die": "세븐 데이즈 투 다이", "Dragon's Dogma 2": "드래곤즈 도그마 2",
    "Ori and the Will of the Wisps": "오리와 도깨비불", "RimWorld": "림월드", "No Man's Sky": "노 맨즈 스카이",
    "Resident Evil 4": "바이오하자드 RE:4", "Grand Theft Auto V Enhanced": "Grand Theft Auto V",
    "Grand Theft Auto V Legacy": "Grand Theft Auto V", "FiveM": "Grand Theft Auto V",   # FiveM = GTA5 멀티(RP) 프로그램
    "tModLoader": "테라리아",                                                           # tModLoader = 테라리아 모드 프로그램
    "Dressmaker": "드레스메이커",
}


@dataclass
class MatchResult:
    """자동 짝 찾기 결과."""

    objBest: Optional[object] = None                 # 확실한 짝 (ChzzkCategory) — 없으면 None
    listCandidates: List[object] = field(default_factory=list)  # 후보들 (확실하지 않을 때 고르라고 보여줄 것)
    listQueries: List[str] = field(default_factory=list)        # 실제로 검색해 본 말들
    strMatchedQuery: str = ""                        # 확실한 짝을 찾은 검색어
    objProbable: Optional[object] = None             # 이름이 거의 같은 후보 하나 (확실하진 않아요. 저장하지 않고 쓰기만 해요)


def NormalizeName(strName: str) -> str:
    """비교용으로 이름을 다듬어요: 소문자, ™®© · 띄어쓰기 · 기호 없애기."""
    strName = (strName or "").lower()
    strName = re.sub(r"[™®©]", "", strName)
    return re.sub(r"[\s\-_:;,.!?'\"`’‘“”·/\\|()\[\]{}<>~]+", "", strName)


F_PROBABLE_RATIO = 0.90      # 이 이상 닮아야 '거의 같은 이름'
F_PROBABLE_GAP = 0.05        # 2등 후보와 이만큼 차이가 나야 '딱 하나'
_RE_NUMBER_TOKEN = re.compile(r"\d+|\b(?:viii|vii|vi|iv|ix|iii|ii|xi|xii|x|v)\b", re.I)


def _NumberTokens(strName: str) -> List[str]:
    """이름 속 숫자 · 로마 숫자들 (후속작을 잘못 고르지 않게 이게 같아야 해요). "Civilization VII" → ['vii']"""
    return [strToken.lower() for strToken in _RE_NUMBER_TOKEN.findall(strName or "")]


def PickProbable(listCandidates: List[object], listQueries: List[str]):
    """이름이 똑같은 후보는 없지만 '거의 같은' 후보가 딱 하나뿐이면 그것을 돌려줘요. 아니면 None.

    조건: 닮은 정도 >= F_PROBABLE_RATIO, 숫자 · 로마 숫자가 똑같음, 2등과 F_PROBABLE_GAP 이상 차이.
    (예: 'ELDEN RING' ↔ 'ELDEN RING 밤의 통치자' 는 다른 게임이라 닮은 정도가 낮아서 안 걸려요)
    """
    listScored = []
    for objCategory in listCandidates:
        strValue = objCategory.strCategoryValue
        fBest = 0.0
        for strQuery in listQueries:
            if _NumberTokens(strValue) != _NumberTokens(strQuery):
                continue
            fBest = max(fBest, difflib.SequenceMatcher(None, NormalizeName(strValue), NormalizeName(strQuery)).ratio())
        listScored.append((fBest, objCategory))
    listScored.sort(key=lambda tupleItem: tupleItem[0], reverse=True)
    if not listScored or listScored[0][0] < F_PROBABLE_RATIO:
        return None
    if len(listScored) > 1 and listScored[0][0] - listScored[1][0] < F_PROBABLE_GAP:
        return None   # 비슷한 후보가 둘 이상이면 어느 게 맞는지 모르니까 고르지 않아요.
    return listScored[0][1]


_dictSearchCache: Dict[str, str] = {}


def SearchSteamIdByName(strName: str) -> str:
    """스팀 번호를 모르는 게임의 이름으로 스팀 상점을 검색해서, 이름이 '똑같은' 게임이 딱 하나면 그 번호를 돌려줘요.
    (없거나 여러 개면 "" — 비슷한 이름의 다른 게임 · DLC 를 고르지 않아요)"""
    strKey = NormalizeName(strName)
    if len(strKey) < 3:
        return ""
    with _objCacheLock:
        if strKey in _dictSearchCache:
            return _dictSearchCache[strKey]
    strFound = ""
    try:
        for strLang, strCc in (("english", "US"), ("korean", "KR")):
            objResponse = requests.get(STR_STEAM_STORESEARCH_URL, timeout=F_TIMEOUT_SEC,
                                       params={"term": strName, "l": strLang, "cc": strCc})
            listItems = [dictItem for dictItem in (objResponse.json().get("items") or [])
                         if isinstance(dictItem, dict) and str(dictItem.get("type", "app")) == "app"
                         and NormalizeName(str(dictItem.get("name") or "")) == strKey and str(dictItem.get("id", "")).isdigit()]
            setIds = {str(dictItem["id"]) for dictItem in listItems}
            if len(setIds) == 1:
                strFound = setIds.pop()
                break
    except (requests.RequestException, ValueError, AttributeError):
        return ""   # 실패는 기억하지 않아요 (다음에 다시 시도)
    with _objCacheLock:
        _dictSearchCache[strKey] = strFound
    return strFound


def GetSteamStoreNames(strAppId: str) -> List[str]:
    """스팀 상점에서 게임 이름을 받아요. [한국어 이름, 영어 이름] (같으면 하나, 실패하면 빈 목록)"""
    strAppId = str(strAppId or "").strip()
    if not strAppId.isdigit():
        return []
    with _objCacheLock:
        if strAppId in _dictNameCache:
            return list(_dictNameCache[strAppId])
    listNames: List[str] = []
    for strLang in ("korean", "english"):
        try:
            objResponse = requests.get(STR_STEAM_APPDETAILS_URL, timeout=F_TIMEOUT_SEC,
                                       params={"appids": strAppId, "l": strLang, "filters": "basic"})
            dictData = (objResponse.json().get(strAppId) or {}).get("data") or {}
        except (requests.RequestException, ValueError, AttributeError):
            continue  # 스팀 상점이 안 되면 그냥 있는 이름으로 찾아요.
        strName = str(dictData.get("name") or "").strip()
        if strName and strName not in listNames:
            listNames.append(strName)
    if listNames:  # 실패(빈 결과)는 기억하지 않아요. (스팀 상점이 잠깐 막혀도 다음에 다시 물어보게)
        with _objCacheLock:
            _dictNameCache[strAppId] = listNames
    return list(listNames)


def KoreanNamesFor(listNames: List[str]) -> List[str]:
    """이름들 중 '한국어 이름 목록' 에 있는 게 있으면 그 한국어 이름들을 돌려줘요."""
    dictByNorm = {NormalizeName(strKey): strValue for strKey, strValue in DICT_KOREAN_NAMES.items()}
    listResult: List[str] = []
    for strName in listNames:
        for strCandidate in [strName] + re.split(r"\s*/\s*|\s*\|\s*", strName):
            strKorean = dictByNorm.get(NormalizeName(strCandidate))
            if strKorean and strKorean not in listResult:
                listResult.append(strKorean)
    return listResult


def BuildQueries(listNames: List[str]) -> List[str]:
    """이름들로 검색어 목록을 만들어요. (앞에 있을수록 먼저 검색)

    "Palworld / 팰월드" → ["Palworld / 팰월드", "Palworld", "팰월드"]
    "HELLDIVERS™ 2"     → ["HELLDIVERS™ 2", "HELLDIVERS 2"]
    """
    listQueries: List[str] = []

    def _Add(strQuery: str) -> None:
        strQuery = re.sub(r"\s+", " ", strQuery or "").strip(" -:/")
        if len(strQuery) >= 2 and strQuery not in listQueries:
            listQueries.append(strQuery)

    for strName in listNames:
        _Add(strName)
        _Add(re.sub(r"[™®©]", "", strName))
        for strPart in re.split(r"\s*/\s*|\s*\|\s*", strName):  # "영어 / 한국어" 처럼 같이 적힌 이름 나누기
            strPart = re.sub(r"[™®©]", "", strPart)
            _Add(strPart)
            _Add(re.sub(r"\s*[(\[].*?[)\]]\s*", " ", strPart))  # 괄호 안 설명 떼기
    return listQueries


def FindCategory(objChzzkClient, listNames: List[str], nMaxQueries: int = 5) -> MatchResult:
    """게임 이름들로 치지직 카테고리를 찾아요. (인터넷 요청이 있으니 화면 스레드에서 부르지 마세요)

    objChzzkClient: SearchCategory(검색어) 가 있는 치지직 심부름꾼
    listNames     : 게임 이름들 (한국어 이름을 앞에 두면 더 잘 찾아요)
    """
    objResult = MatchResult()
    setSeenIds = set()
    for strQuery in BuildQueries(listNames)[:nMaxQueries]:
        objResult.listQueries.append(strQuery)
        try:
            listFound = objChzzkClient.SearchCategory(strQuery)
        except Exception:  # 검색 하나가 실패해도 다음 검색어로 계속해요.
            continue
        strNormQuery = NormalizeName(strQuery)
        for objCategory in listFound:
            strKey = f"{objCategory.strCategoryType}/{objCategory.strCategoryId}"
            if strKey not in setSeenIds:
                setSeenIds.add(strKey)
                objResult.listCandidates.append(objCategory)
            # 이름이 똑같으면 → 확실한 짝!
            if objResult.objBest is None and NormalizeName(objCategory.strCategoryValue) == strNormQuery:
                objResult.objBest = objCategory
                objResult.strMatchedQuery = strQuery
        if objResult.objBest is not None:
            break
    if objResult.objBest is None:
        objResult.objProbable = PickProbable(objResult.listCandidates, objResult.listQueries)
    return objResult


def FindCategoryForGame(objChzzkClient, strGameId: str, strGameName: str) -> MatchResult:
    """지금 하는 게임(스팀 gameid 또는 exe 열쇠)에 맞는 치지직 카테고리를 찾아요.

    스팀 게임이면 스팀 상점의 한국어 이름을 먼저 써요. 프로그램 감지 게임은 아는 이름(예: 리그 오브 레전드)으로 찾아요.
    """
    strSteamId = str(strGameId) if str(strGameId).isdigit() else ""
    if not strSteamId and strGameName:
        strSteamId = SearchSteamIdByName(strGameName)   # 스팀 번호를 모르면 이름으로 찾아봐요 (이름이 똑같은 게임이 하나일 때만)
    listNames = GetSteamStoreNames(strSteamId) if strSteamId else []
    if strGameName and strGameName not in listNames:
        listNames.append(strGameName)
    # 한국어 이름 목록에 있는 게임이면 그 이름을 맨 앞에 둬요. (가장 정확해요)
    listNames = KoreanNamesFor(listNames) + listNames
    return FindCategory(objChzzkClient, listNames)


def FallbackCategory():
    """'종합 게임' 카테고리 상자를 만들어요. (치지직에 없는 게임용)"""
    from chzzk import ChzzkCategory  # 순환 import 를 피하려고 여기서 불러요.
    strType, strId, strValue = TUPLE_FALLBACK_CATEGORY
    return ChzzkCategory(strCategoryType=strType, strCategoryId=strId, strCategoryValue=strValue)


def IsFallbackCategory(strCategoryId: Optional[str]) -> bool:
    return strCategoryId == TUPLE_FALLBACK_CATEGORY[1]
