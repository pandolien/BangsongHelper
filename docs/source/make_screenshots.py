"""
안내서(PDF)용 스크린샷 만들기
=============================

진짜 프로그램 화면을 '가짜 설정값 · 가짜 채팅 / 후원' 으로 띄워서 img/ 폴더에 PNG 로 저장해요.
- 화면에 창이 뜨지 않아요. (offscreen)
- 치지직 · 스팀에 아무 요청도 보내지 않고, data/ 폴더의 진짜 파일도 건드리지 않아요. (모두 임시 폴더 사용)

실행:  ..\\..\\.venv\\Scripts\\python.exe make_screenshots.py
그다음 build_pdf.bat 을 실행하면 PDF 가 다시 만들어져요.
"""

import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
STR_HERE = os.path.dirname(os.path.abspath(__file__))
STR_ROOT = os.path.dirname(os.path.dirname(STR_HERE))
STR_IMG = os.path.join(STR_HERE, "img")
sys.path.insert(0, STR_ROOT)

import socketio  # noqa: F401,E402  (PySide6 보다 먼저)
import config_manager  # noqa: E402
import game_map  # noqa: E402

TMP = tempfile.mkdtemp()
CFG = os.path.join(TMP, "init.json")


def Main() -> None:
    # ---------------------------------------------------------------- 가짜 설정
    dictConfig = json.loads(json.dumps(config_manager.DICT_DEFAULT_CONFIG))
    dictConfig["steam"].update(api_key="0123456789ABCDEF0123456789ABCDEF", steam_id="76561198012345678")
    dictConfig["chzzk"].update(client_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890", client_secret="secret-secret-secret",
                               channel_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", access_token="A", refresh_token="R",
                               token_expire_at=time.time() + 86400)
    dictConfig["app"].update(auto_sync_category=True, auto_donation=True)
    json.dump(dictConfig, open(CFG, "w", encoding="utf-8"))
    shutil.copy(os.path.join(STR_ROOT, "data", "game_map.txt"), os.path.join(TMP, "game_map.txt"))
    game_map.GameMap.__init__.__defaults__ = (os.path.join(TMP, "game_map.txt"),)
    fnRealLoad, fnRealSave = config_manager.LoadConfig, config_manager.SaveConfig
    config_manager.SaveConfig.__defaults__ = (CFG,)

    # 채팅 연결은 가짜로 (치지직에 접속하지 않아요)
    import gui.chat_hub as hub_mod

    class FakeSession:
        def __init__(self, objClient, fnOnChat=None, fnOnDonation=None, fnOnStatus=None, **kwargs):
            self.fnOnStatus, self.bRun = fnOnStatus, False

        @property
        def bIsRunning(self):
            return self.bRun

        def Start(self):
            self.bRun = True
            if self.fnOnStatus:
                self.fnOnStatus("connected", "채팅 받기 시작!")

        def Stop(self):
            self.bRun = False

    hub_mod.ChzzkChatSession = FakeSession
    import youtube.youtube_chat as ytc
    ytc.YouTubeQuotaTracker.__init__.__defaults__ = (os.path.join(TMP, "youtube_quota.json"),)
    import gui.main_window as mw
    import gui.donation_window as dwm
    import gui.mission_window as mwm
    import gui.chat_window as cwm
    dwm.DonationWindow.__init__.__defaults__ = (None, None, os.path.join(TMP, "donations.json"))
    mwm.MissionWindow.__init__.__defaults__ = (None, None, None, None, os.path.join(TMP, "missions.json"),
                                               os.path.join(TMP, "mission_timer.txt"))
    mw.LoadConfig = lambda: fnRealLoad(CFG)
    mw.SaveConfig = lambda dictValue, strPath=CFG: fnRealSave(dictValue, strPath)

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication, QMenu, QTabWidget
    from chzzk import ChzzkDonationMessage, ChzzkLiveStatus, ChzzkLiveSetting, ParseChatMessage
    from steam import SteamApiClient

    objApp = QApplication(sys.argv)
    nFontId = QFontDatabase.addApplicationFont("C:/Windows/Fonts/malgun.ttf")
    objApp.setFont(QFont(QFontDatabase.applicationFontFamilies(nFontId)[0], 9))

    def Pump(fSec=0.2):
        fEnd = time.time() + fSec
        while time.time() < fEnd:
            objApp.processEvents()
            time.sleep(0.02)

    def Save(objWidget, strName):
        Pump()
        objWidget.grab().save(os.path.join(STR_IMG, strName))
        print("saved", strName)

    os.makedirs(STR_IMG, exist_ok=True)
    with mock.patch.object(mw.MainWindow, "OnRefreshClicked", lambda self: None), \
            mock.patch.object(mw.MainWindow, "OnLoadSettingClicked", lambda self: None), \
            mock.patch.object(mw.MainWindow, "_AutoSyncCategory", lambda self, objGame: None):
        objWin = mw.MainWindow()
        objWin.resize(780, 720)
        objTabs = objWin.centralWidget().findChild(QTabWidget)

        # ---------------------------------------------------------------- 대시보드
        objSteam = SteamApiClient.ParsePlayerSummary({"steamid": "76561198012345678", "personaname": "스트리머닉네임",
                                                      "personastate": 1, "communityvisibilitystate": 3,
                                                      "gameid": "2622380", "gameextrainfo": "ELDEN RING NIGHTREIGN"})
        objWin._ShowSteam(objSteam)
        objWin.setLastRunningExes = set()
        objWin._UpdateCurrentGame(bAutoSync=False)
        objWin._ShowChzzk(ChzzkLiveStatus("c", "내 방송국", "OPEN", "오늘도 나이트레인!", "GAME", "Elden_Ring_Nightreign",
                                          "ELDEN RING 밤의 통치자", 12, None, "live-detail"))
        objWin.lblLastUpdated.setText("마지막 갱신 21:00:00")
        objWin.txtLog.clear()
        for strLine in ["[스팀] 스트리머닉네임 님은 지금 [ELDEN RING NIGHTREIGN] (ID: 2622380) 플레이 중!",
                        "[치지직] 방송 중 / 출처: live-detail", "[후원] 후원 받기 자동 시작 — 후원 목록 창을 안 열어도 기록돼요."]:
            objWin.Log(strLine)
        objTabs.setCurrentIndex(0)
        Save(objWin, "dashboard_tab.png")

        # ---------------------------------------------------------------- 방송 관리 (스크롤 안쪽 전체)
        objWin._ShowLiveSetting(ChzzkLiveSetting("오늘도 나이트레인!", "GAME", "Elden_Ring_Nightreign", "ELDEN RING 밤의 통치자",
                                                 ["엘든링", "소울라이크"]))
        objTabs.setCurrentIndex(1)
        Pump()
        objInner = objTabs.currentWidget().widget()
        objInner.resize(760, objInner.sizeHint().height())
        Save(objInner, "manage_tab.png")

        # ---------------------------------------------------------------- 게임 짝
        objTabs.setCurrentIndex(2)
        objWin.editMapGameId.setText("VALORANT-Win64-Shipping.exe")
        objWin.editMapMemo.setText("발로란트")
        objWin.editMapCategoryQuery.setText("발로란트")
        from chzzk import ChzzkCategory
        objWin.cmbMapCategory.addItem("발로란트  [GAME]", ChzzkCategory("GAME", "Valorant", "발로란트"))
        Save(objWin, "gamemap_tab.png")

        # ---------------------------------------------------------------- 설정
        objTabs.setCurrentIndex(3)
        Save(objWin, "settings_tab.png")

        # ---------------------------------------------------------------- 방송 도우미 (채팅 + 후원 + 미션)
        objStream = objWin.objStreamWindow
        objWin.OnOpenChatWindowClicked()
        Pump()
        objHub = objWin.objChatHub
        dtNow = datetime.now()
        for strNick, strText, strRole in [("스트리머닉네임", "어서오세요~ 오늘은 나이트레인!", "streamer"),
                                          ("매니저", "공지 확인 부탁드려요", "streaming_channel_manager"),
                                          ("시청자A", "안녕하세요!", "common_user"), ("시청자B", "오늘 몇 판 하시나요?", "common_user"),
                                          ("도배러", "ㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋ", "common_user")]:
            objHub.sigChat.emit(ParseChatMessage({"senderChannelId": strNick, "chatChannelId": "cc",
                                                  "messageTime": int(dtNow.timestamp() * 1000), "content": strText,
                                                  "userRoleCode": strRole, "profile": {"nickname": strNick}}))
        # 유튜브 채팅 (동시 송출) — 가짜로 몇 줄
        from youtube import YouTubeChatMessage
        objWin.objChatWindow.editYouTube.setText("https://www.youtube.com/live/xxxxxxxxxxx")
        objWin.objYouTubeHub.sigStatus.emit("connected", "")
        for strNick, strText, bMember in [("YT시청자", "유튜브에서 왔어요!", False), ("멤버님", "오늘도 화이팅", True)]:
            objWin.objYouTubeHub.sigChat.emit(YouTubeChatMessage(strNick, strText, dtNow, bMember=bMember))
        for strNick, nAmount, strText, strType, nAgo in [("후원자A", 1000, "고양이 웃긴 영상 모음", "VIDEO", 9),
                                                          ("후원자B", 5000, "화이팅!", "CHAT", 7),
                                                          ("후원자C", 10000, "미션: 노데스로 보스 잡기", "CHAT", 5),
                                                          ("후원자D", 3000, "레전드 클립 모음", "VIDEO", 2)]:
            objHub.sigDonation.emit(ChzzkDonationMessage(strNick, nAmount, strText, strType, dtNow - timedelta(minutes=nAgo)))
        from gui.youtube_hub import SuperChatToDonation
        objWin.objYouTubeHub.sigDonation.emit(SuperChatToDonation(YouTubeChatMessage(
            "슈챗러", "유튜브에서도 응원해요", dtNow, strType="superChatEvent", strAmountText="₩5,000",
            nAmountMicros=5_000_000_000, strCurrency="KRW")))
        Pump()
        objWin.objDonationWindow.listRecords[0].strState = "done"
        objWin.objDonationWindow._RefreshRow(0)
        objMissionView = objWin.objMissionWindow
        # 타이머 파일은 임시 폴더에 쓰지만, 화면에는 진짜 위치를 보여줘요.
        objMissionView.lblTimerPath.setText(os.path.join(STR_ROOT, "data", "mission_timer.txt"))
        objMissionView.AddMission(mwm.MissionRecord(dtNow, "후원자E", 20000, "30분 안에 보스 클리어", 1800))
        objMissionView._ToggleRun([0])
        objMissionView.listMissions[0].fEndAt = time.time() + 437  # 07:17 남은 것처럼
        objMissionView._OnTick()
        objStream.resize(1240, 820)
        objWin.objDonationWindow.tblDonations.clearSelection()
        objMissionView.tblMissions.clearSelection()
        Save(objStream, "stream_window.png")

        # ---------------------------------------------------------------- 미션 설정 펼친 모습
        objMissionView._ToggleSettings()
        Pump()
        Save(objMissionView.grpSettings, "mission_settings.png")
        objMissionView._ToggleSettings()

        # ---------------------------------------------------------------- 채팅 닉네임 메뉴
        class _GrabMenu(QMenu):
            def exec(self, *args):  # 띄우는 대신 그림으로 저장해요.
                self.adjustSize()
                self.grab().save(os.path.join(STR_IMG, "chat_menu.png"))
                print("saved chat_menu.png")

        with mock.patch.object(cwm, "QMenu", _GrabMenu):
            objChat = objWin.objChatWindow
            objTarget = next(objMsg for objMsg in objChat.dictMessages.values() if objMsg.strNickname == "도배러")
            objChat._ShowUserMenu(objTarget, objChat.mapToGlobal(objChat.rect().center()))

        # ---------------------------------------------------------------- 테스트 도구
        objWin.objDonationWindow.OnTestToolClicked()
        objTest = objWin.objDonationWindow.objTestDialog
        objTest.txtCheck.setPlainText("[성공] 1. 로그인 돼 있어요.\n"
                                      "[성공] 2. 접속 주소를 받고 채팅 서버에 연결했어요.\n"
                                      "[성공] 3. 채팅 받기 신청 성공 (채팅 메시지 조회 권한 OK)\n"
                                      "[성공] 4. 후원 받기 신청 성공 (후원 조회 권한 OK) — 영상 · 채팅 후원이 들어와요.\n"
                                      "— 점검 끝 —")
        objTest.resize(560, 560)
        Save(objTest, "test_dialog.png")

        # ---------------------------------------------------------------- 후원 권한 경고
        objHub.sigDonationState.emit(False, "개발자 센터에서 '후원 조회' 권한을 켜고, 프로그램에서 로그아웃 → 다시 로그인해 주세요.")
        Pump()
        objWarn = objWin.objDonationWindow.lblDonationWarning
        Save(objWarn, "donation_warning.png")

        objMissionView.Shutdown()
        objStream.close()
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    Main()
