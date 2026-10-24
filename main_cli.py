"""
명령줄(CLI) 실행 프로그램
==========================

터미널에서 이렇게 써요:
    python main_cli.py status                 → 스팀 + 치지직 상태를 한 번 보여줘요
    python main_cli.py watch                  → 30초마다 계속 새로고침해서 보여줘요 (Ctrl+C 로 종료)
    python main_cli.py login                  → 치지직 계정 연동 (방송 관리 기능용)
    python main_cli.py logout                 → 계정 연동 해제
    python main_cli.py setting                → 내 방송 설정(제목/카테고리/태그) 보기
    python main_cli.py set-title "새 제목"     → 방송 제목 바꾸기
    python main_cli.py set-category "발로란트" → 카테고리 검색 후 첫 번째 결과로 바꾸기
    python main_cli.py chat "안녕하세요"       → 채팅 보내기
    python main_cli.py notice "공지 내용"      → 채팅 공지 등록
    python main_cli.py sync-game              → 지금 하는 게임(스팀 또는 실행 중인 프로그램)으로 치지직 카테고리 맞추기
                                                (짝이 없으면 골라서 data/game_map.txt 에 저장)
    python main_cli.py game-map               → 스팀 게임 ↔ 치지직 카테고리 짝꿍 목록 보기
    python main_cli.py game-map-add 2622380 "나이트레인" --memo "ELDEN RING NIGHTREIGN"
    python main_cli.py game-map-add VALORANT-Win64-Shipping.exe "발로란트"
                                              → 짝 직접 추가/수정 (스팀 gameid 또는 프로그램 이름, 검색 결과에서 번호로 고르기)
    python main_cli.py game-map-remove 2622380 → 짝 삭제
    python main_cli.py make-upload-config     → 개인정보 뺀 업로드용 설정 파일(data/init_upload.json) 만들기
"""

import argparse
import sys
import time
from typing import Optional

from chzzk import ChzzkApiClient, ChzzkApiError, ChzzkAuthRequiredError, LoginWithBrowser
from game_detect import DetectedGame, KeyFromInput, KeyToDisplay, ListFolderGames, ListRunningExeNames, PickCurrentGame
from category_match import FallbackCategory, FindCategoryForGame, IsFallbackCategory
from game_map import GameMap, GameMapEntry
from config_manager import (
    STR_CONFIG_PATH, STR_UPLOAD_CONFIG_PATH, ImportConfig, MakeUploadConfig, LoadConfig, StoreTokenToConfig,
    TokenFromConfig,
)
from steam import SteamApiClient, SteamApiError


def CreateSteamClient(dictConfig: dict) -> SteamApiClient:
    return SteamApiClient(dictConfig["steam"]["api_key"], dictUrls=dictConfig["urls"]["steam"])


def CreateChzzkClient(dictConfig: dict) -> ChzzkApiClient:
    dictChzzk = dictConfig["chzzk"]
    return ChzzkApiClient(
        strClientId=dictChzzk["client_id"],
        strClientSecret=dictChzzk["client_secret"],
        objTokenInfo=TokenFromConfig(dictConfig),
        # 토큰이 자동 갱신되면 → 바로 data/init.json 에 저장 (Refresh Token 은 일회용이라 꼭 필요!)
        fnOnTokenRefreshed=lambda objToken: StoreTokenToConfig(dictConfig, objToken),
        dictUrls=dictConfig["urls"]["chzzk"],
    )


def DetectCurrentGame(dictConfig: dict, bPrintSteamError: bool = True) -> Optional[DetectedGame]:
    """지금 하는 게임을 찾아요. 스팀에서 게임 중이면 스팀, 아니면 실행 중인 프로그램. (스팀 키는 없어도 돼요)"""
    objSteamStatus = None
    if dictConfig["steam"]["api_key"]:
        try:
            objSteamStatus = CreateSteamClient(dictConfig).GetPlayerStatus(dictConfig["steam"]["steam_id"])
        except SteamApiError as objError:
            if bPrintSteamError:
                print(f"[스팀]  [오류] {objError}")
    try:
        setExes = ListRunningExeNames()
        import discord_games
        from app_paths import DataPath
        discord_games.EnsureLoaded(DataPath("discord_games.json"))  # 저장해 둔 게임 이름 목록을 불러와요 (오래됐으면 뒤에서 새로 받아요)
        listFolderGames = (ListFolderGames(bool(dictConfig["app"].get("use_discord_game_list", True)))
                           if dictConfig["app"].get("auto_detect_folder_games", True) else [])
    except OSError:
        setExes, listFolderGames = set(), []
    return PickCurrentGame(objSteamStatus, setExes, [objEntry.strSteamGameId for objEntry in GameMap().ListEntries()],
                           listFolderGames)


def PrintStatus(dictConfig: dict) -> None:
    """스팀과 치지직 상태를 각각 가져와서 출력해요. 한쪽이 실패해도 다른 쪽은 보여줘요."""
    print("=" * 50)
    print(time.strftime("[%H:%M:%S] 상태 확인"))

    # --- 스팀 ---
    try:
        objSteamStatus = CreateSteamClient(dictConfig).GetPlayerStatus(dictConfig["steam"]["steam_id"])
        print("[스팀]  " + objSteamStatus.ToDisplayText())
    except SteamApiError as objError:
        print(f"[스팀]  [오류] {objError}")

    # --- 지금 하는 게임 (스팀 + 실행 중인 프로그램) ---
    objGame = DetectCurrentGame(dictConfig, bPrintSteamError=False)
    if objGame is None:
        print("[게임]  감지된 게임 없음")
    else:
        objEntry = GameMap().Get(objGame.strGameId)
        strMapped = (objEntry.strCategoryValue or objEntry.strCategoryId) if objEntry else "짝 없음"
        print(f"[게임]  {objGame.strGameName} ({objGame.strSourceName}: {KeyToDisplay(objGame.strGameId)}) → 치지직 짝: {strMapped}")

    # --- 치지직 ---
    try:
        objLive = CreateChzzkClient(dictConfig).GetLiveDetail(dictConfig["chzzk"]["channel_id"])
        print("[치지직] " + objLive.ToDisplayText())
    except ChzzkApiError as objError:
        print(f"[치지직] [오류] {objError}")


def ImportOldConfig(strSourcePath: str) -> int:
    """이전 버전 폴더의 설정 파일을 지금 설정으로 가져와요. (새 버전으로 옮길 때 한 번)"""
    if not strSourcePath.strip():
        print("이전 버전의 설정 파일 경로를 적어 주세요.\n"
              "   예) run.bat import-config \"D:\\이전폴더\\data\\init.json\"")
        return 2
    dictInfo = ImportConfig(strSourcePath.strip().strip('"'))
    listFound = [strLabel for bFound, strLabel in (
        (dictInfo["bChzzkKeys"], "치지직 Client ID / Secret"), (dictInfo["bChzzkLogin"], "치지직 로그인"),
        (dictInfo["bSteam"], "스팀 API 키"), (dictInfo["bYouTube"], "유튜브 API 키")) if bFound]
    print(f"이전 설정을 가져왔어요 → {STR_CONFIG_PATH}")
    print("  이어받은 것: " + (" · ".join(listFound) if listFound else "(키 · 로그인 정보는 비어 있었어요)") + " + 프로그램 설정")
    print(f"  새로 생긴 칸 {len(dictInfo['listAdded'])}개는 기본값으로 채웠어요.")
    print(f"  (예전 설정은 {STR_CONFIG_PATH}.bak 으로 백업했어요)")
    return 0


def RunCommand(objArgs: argparse.Namespace, dictConfig: dict) -> int:
    strCommand = objArgs.strCommand or "status"

    if strCommand == "import-config":
        return ImportOldConfig(objArgs.strText)

    if strCommand == "status":
        PrintStatus(dictConfig)
        return 0

    if strCommand == "watch":
        nInterval = int(objArgs.nInterval or dictConfig["app"]["refresh_interval_sec"])
        print(f"{nInterval}초마다 새로고침해요. 끝내려면 Ctrl+C 를 누르세요.")
        try:
            while True:
                PrintStatus(dictConfig)
                time.sleep(nInterval)
        except KeyboardInterrupt:
            print("\n종료합니다.")
        return 0

    objChzzk = CreateChzzkClient(dictConfig)

    if strCommand == "login":
        print("브라우저가 열리면 치지직에서 [동의] 를 눌러주세요...")
        LoginWithBrowser(objChzzk, dictConfig["chzzk"]["redirect_uri"])
        print("계정 연동 완료! 토큰이 data/init.json 에 저장되었어요.")
        return 0

    if strCommand == "logout":
        try:
            objChzzk.RevokeToken()
        finally:
            StoreTokenToConfig(dictConfig, None)
        print("로그아웃 완료.")
        return 0

    if strCommand == "setting":
        objSetting = objChzzk.GetLiveSetting()
        print(f"제목     : {objSetting.strDefaultLiveTitle}")
        print(f"카테고리 : {objSetting.strCategoryValue} ({objSetting.strCategoryType}/{objSetting.strCategoryId})")
        print(f"태그     : {', '.join(objSetting.listTags) or '-'}")
        return 0

    if strCommand == "set-title":
        objSetting = objChzzk.UpdateLiveSetting(strDefaultLiveTitle=objArgs.strText)
        print(f"제목 변경 완료: {objSetting.strDefaultLiveTitle}")
        return 0

    if strCommand == "set-category":
        return ChangeCategoryByName(objChzzk, objArgs.strText)

    if strCommand == "chat":
        strMessageId = objChzzk.SendChatMessage(objArgs.strText)
        print(f"채팅 전송 완료 (messageId: {strMessageId})")
        return 0

    if strCommand == "notice":
        objChzzk.RegisterChatNotice(strMessage=objArgs.strText)
        print("공지 등록 완료")
        return 0

    if strCommand == "sync-game":
        return SyncSteamGame(dictConfig, objChzzk)

    if strCommand == "make-upload-config":
        MakeUploadConfig(dictConfig)
        print(f"업로드용 설정 파일을 만들었어요 (키 · ID · 토큰은 빈칸): {STR_UPLOAD_CONFIG_PATH}")
        return 0

    if strCommand == "game-map-add":
        return AddGameMap(objChzzk, objArgs.strText, objArgs.strText2.strip(), objArgs.strMemo or "")

    if strCommand == "game-map-remove":
        if GameMap().Remove(KeyFromInput(objArgs.strText) or objArgs.strText.strip()):
            print(f"짝 삭제: {objArgs.strText}")
            return 0
        print(f"gameid '{objArgs.strText}' 짝이 없어요.")
        return 1

    if strCommand == "game-map":
        objGameMap = GameMap()
        for strWarning in objGameMap.listWarnings:
            print(f"[경고] {strWarning}")
        listEntries = objGameMap.ListEntries()
        print(f"짝꿍 목록 ({len(listEntries)}개) - {objGameMap.strPath}")
        for objEntry in listEntries:
            print(f"  {KeyToDisplay(objEntry.strSteamGameId):>8}  {objEntry.strMemo or '-'}  →  "
                  f"{objEntry.strCategoryValue or '-'} [{objEntry.strCategoryType} / {objEntry.strCategoryId}]")
        return 0

    print(f"알 수 없는 명령이에요: {strCommand}")
    return 1


def SyncSteamGame(dictConfig: dict, objChzzk: ChzzkApiClient) -> int:
    """지금 하는 게임(스팀 또는 실행 중인 프로그램)에 맞춰 치지직 카테고리를 바꿔요.

    1) data/game_map.txt 에 짝이 있으면 → 바로 적용
    2) 없으면 → 검색 결과를 번호로 보여주고 고르게 한 뒤, 고른 것을 짝으로 저장 (다음부터는 자동)
    """
    objSteamStatus = DetectCurrentGame(dictConfig)
    if objSteamStatus is None:
        print("하고 있는 게임을 찾지 못해서 바꿀 카테고리가 없어요.")
        print("  (스팀 밖 게임이면 game-map-add <프로그램이름.exe> \"검색어\" 로 짝을 먼저 만들어 주세요)")
        return 1
    print(f"지금 게임: {objSteamStatus.strGameName} ({objSteamStatus.strSourceName}: {KeyToDisplay(objSteamStatus.strGameId)})")

    objGameMap = GameMap()
    objEntry = objGameMap.Get(objSteamStatus.strGameId)
    if objEntry is not None:
        objChzzk.UpdateLiveSetting(strCategoryType=objEntry.strCategoryType, strCategoryId=objEntry.strCategoryId)
        print(f"짝 목록대로 카테고리 변경: {objEntry.strCategoryValue or objEntry.strCategoryId}")
        return 0

    print("짝 목록에 없는 게임이에요. 자동으로 찾아볼게요...")
    objResult = FindCategoryForGame(objChzzk, objSteamStatus.strGameId, objSteamStatus.strGameName)
    if objResult.objBest is not None:
        objCategory = objResult.objBest
        print(f"자동으로 찾았어요: {objCategory.strCategoryValue} ({objResult.strStage + ', ' if objResult.strStage else ''}검색어 '{objResult.strMatchedQuery}')")
    else:
        print("확실한 짝을 못 찾았어요. 맞는 치지직 카테고리를 골라주세요. (치지직에 없는 게임이면 0 = 종합 게임)")
        objCategory = PickCategory(objChzzk, objResult.listQueries[0] if objResult.listQueries else objSteamStatus.strGameName)
        if objCategory is None:
            return 1
    if IsFallbackCategory(objCategory.strCategoryId):
        objChzzk.UpdateLiveSetting(strCategoryType=objCategory.strCategoryType, strCategoryId=objCategory.strCategoryId)
        print(f"카테고리 변경: {objCategory.strCategoryValue} (종합 게임은 짝으로 저장하지 않아요)")
        return 0

    objChzzk.UpdateLiveSetting(strCategoryType=objCategory.strCategoryType, strCategoryId=objCategory.strCategoryId)
    objGameMap.Set(GameMapEntry(
        strSteamGameId=objSteamStatus.strGameId,
        strCategoryType=objCategory.strCategoryType,
        strCategoryId=objCategory.strCategoryId,
        strCategoryValue=objCategory.strCategoryValue,
        strMemo=objSteamStatus.strGameName,
    ))
    print(f"카테고리 변경: {objCategory.strCategoryValue}")
    print(f"짝 저장: {objSteamStatus.strGameName} ↔ {objCategory.strCategoryValue} (다음부터는 자동)")
    return 0


def PickCategory(objChzzk: ChzzkApiClient, strQuery: str):
    """검색 결과를 번호로 보여주고 하나를 고르게 해요. 취소하면 None.
    숫자가 아닌 글자를 입력하면 그 글자로 다시 검색해요.
    """
    while True:
        listCategories = objChzzk.SearchCategory(strQuery)
        print(f"\n'{strQuery}' 검색 결과:")
        for nIndex, objCategory in enumerate(listCategories, 1):
            print(f"  {nIndex:>2}. {objCategory.strCategoryValue} [{objCategory.strCategoryType}]")
        if not listCategories:
            print("  (결과 없음) 치지직에서 쓰는 한글 이름으로 검색해 보세요. 예: 나이트레인")
        print("   0. 종합 게임 (치지직에 없는 게임)")
        strAnswer = input("번호 입력 / 다른 검색어 입력 / 그냥 Enter 는 취소: ").strip()
        if not strAnswer:
            print("취소했어요.")
            return None
        if strAnswer == "0":
            return FallbackCategory()
        if strAnswer.isdigit() and 1 <= int(strAnswer) <= len(listCategories):
            return listCategories[int(strAnswer) - 1]
        strQuery = strAnswer  # 숫자가 아니면 새 검색어로 다시 검색


def AddGameMap(objChzzk: ChzzkApiClient, strGameId: str, strQuery: str, strMemo: str = "") -> int:
    """게임(스팀 gameid 또는 프로그램 이름)과 치지직 카테고리 짝을 직접 추가(또는 수정)해요. 방송 카테고리는 안 바꿔요."""
    strInput = strGameId
    strGameId = KeyFromInput(strInput)
    if strGameId is None:
        print("사용법: run.bat game-map-add <스팀gameid 또는 프로그램이름.exe> \"치지직 카테고리 검색어\" [--memo \"게임 이름\"]")
        return 1
    objGameMap = GameMap()
    objOld = objGameMap.Get(strGameId)
    if objOld is not None:
        print(f"이미 짝이 있어요: {objOld.strCategoryValue or objOld.strCategoryId} → 새로 고르면 바뀌어요.")

    objCategory = PickCategory(objChzzk, strQuery or strMemo or KeyToDisplay(strGameId))
    if objCategory is None:
        return 1
    objGameMap.Set(GameMapEntry(
        strSteamGameId=strGameId,
        strCategoryType=objCategory.strCategoryType,
        strCategoryId=objCategory.strCategoryId,
        strCategoryValue=objCategory.strCategoryValue,
        strMemo=strMemo.replace("#", ""),
    ))
    print(f"짝 {'수정' if objOld else '추가'}: {KeyToDisplay(strGameId)} ↔ {objCategory.strCategoryValue}")
    return 0


def ChangeCategoryByName(objChzzk: ChzzkApiClient, strQuery: str) -> int:
    listCategories = objChzzk.SearchCategory(strQuery)
    if not listCategories:
        print(f"'{strQuery}' 로 검색된 카테고리가 없어요.")
        return 1
    objCategory = listCategories[0]
    objChzzk.UpdateLiveSetting(strCategoryType=objCategory.strCategoryType, strCategoryId=objCategory.strCategoryId)
    print(f"카테고리 변경 완료: {objCategory.strCategoryValue} ({objCategory.strCategoryType})")
    return 0


def main() -> int:
    objParser = argparse.ArgumentParser(description="스팀 + 치지직 상태 조회/제어 도구")
    objParser.add_argument(
        "strCommand", nargs="?", default="status",
        choices=["status", "watch", "login", "logout", "setting", "set-title",
                 "set-category", "chat", "notice", "sync-game", "game-map", "game-map-add",
                 "game-map-remove", "make-upload-config", "import-config"],
        metavar="명령",
    )
    objParser.add_argument("strText", nargs="?", default="", metavar="내용")
    objParser.add_argument("strText2", nargs="?", default="", metavar="내용2")
    objParser.add_argument("--memo", dest="strMemo", help="game-map-add 때 적을 메모 (스팀 게임 이름)")
    objParser.add_argument("--interval", dest="nInterval", type=int, help="watch 새로고침 간격(초)")
    objArgs = objParser.parse_args()

    # 윈도우 콘솔에서 이모지/한글이 깨지지 않게 해요.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        dictConfig = LoadConfig()
        return RunCommand(objArgs, dictConfig)
    except ChzzkAuthRequiredError as objError:
        print(f"{objError}\n   → 먼저 'python main_cli.py login' 을 실행해 주세요.")
    except (ChzzkApiError, SteamApiError, RuntimeError) as objError:
        print(f"[오류] {objError}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
