"""
PySide6 데스크톱 프로그램 (GUI)
================================

화면 구성 (한 화면)
    맨 위 막대  방송 상태 · 시청자 · 로그인 · 지금 게임을 한눈에 + 새로고침 · 방송 도우미 · 설정 · 색상 버튼
    [상태]      스팀 · 지금 하는 게임 · 치지직 방송 상태. 정해진 시간마다 자동 새로고침
    [방송 관리] 치지직 로그인, 방송 제목/카테고리 변경, 채팅 보내기, 공지 등록
    [게임 짝]   게임(스팀 gameid / 프로그램 exe) ↔ 치지직 카테고리 짝 목록 보기 / 추가 / 수정 / 삭제
    맨 아래     로그
    [설정] 창   API 키 · ID · 새로고침 간격 / 서버 주소(URL) — 처음 한 번만 쓰니 버튼으로 따로 열어요
    [색상] 창   프로그램 색 바꾸기 (gui/theme.py)

왜 '일꾼(Worker)' 을 따로 쓰나요?
    인터넷 요청은 몇 초씩 걸릴 수 있어요. 화면을 그리는 친구(메인 스레드)가 직접 기다리면
    그동안 창이 멈춰서 '응답 없음' 이 떠요. 그래서 오래 걸리는 일은 '일꾼' 에게 맡기고,
    일꾼이 일을 끝내면 '신호(Signal)' 로 결과를 알려주게 해요.
"""

import os
import sys
import time
import traceback
from typing import Callable, Optional

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
# (PySide6 를 먼저 부르면 socketio 가 쓰는 six 라이브러리와 충돌해서 프로그램이 꺼져요)
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout,
    QSplitter, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from chzzk import (
    DICT_DEFAULT_CHZZK_URLS, ChzzkApiClient, ChzzkApiError, ChzzkCategory, ChzzkAuthRequiredError, ChzzkLiveStatus,
    LoginWithBrowser,
)
from game_detect import (
    DICT_KNOWN_GAMES, DetectedGame, KeyFromInput, KeyToDisplay, ListFolderGames, ListRunningExeNames,
    ListWindowedPrograms, PickCurrentGame,
)
from category_match import FallbackCategory, FindCategoryForGame, IsFallbackCategory, TUPLE_FALLBACK_CATEGORY
from game_map import GameMap, GameMapEntry
from gui.chat_hub import ChatHub
from gui.chat_window import ChatWindow
from gui.donation_window import DonationWindow
from gui.mission_window import MissionWindow
from gui.stream_window import N_TAB_DONATION, N_TAB_MISSION, StreamToolsWindow
from config_manager import (
    STR_CONFIG_PATH, DescribeImport, FindOldConfigs, ImportConfig, IsBlankConfig, LoadConfig, ReplaceInPlace,
    SaveConfig, StoreTokenToConfig, TokenFromConfig,
)
from steam import DICT_DEFAULT_STEAM_URLS, SteamApiClient, SteamApiError, SteamPlayerStatus
from youtube import DICT_DEFAULT_YOUTUBE_URLS
from gui.youtube_hub import YouTubeHub
from datetime import datetime
import app_log
from app_paths import B_TEST_MODE, STR_APP_DIR, STR_CONFIG_NAME
from gui.alarm import DonationAlarm
from gui.alarm_dialog import AlarmSettingsDialog
from gui.donation_window import RemoteControlUrl
from gui.remote_panel import RemotePanel
import whats_new
from obs_overlay import N_DEFAULT_PORT, IsAllowedAlertUrl, OverlayServer
from gui.theme import BuildPalette, BuildStyleSheet, ThemeColors, ThemeDialog

# URL 설정에 보여줄 '사람이 읽는 이름'. (init.json 의 칸 이름 → 화면 글자)
DICT_URL_LABELS = {
    "steam": {
        "player_summaries": "플레이어 요약 (GetPlayerSummaries)",
    },
    "youtube": {
        "data_api_base": "유튜브 Data API 기본 주소",
    },
    "chzzk": {
        "open_api_base": "Open API 기본 주소",
        "service_api_base": "서비스 API 기본 주소 (비공식)",
        "authorize": "로그인(권한 허락) 페이지",
        "live_detail": "라이브 상세 경로 (비공식)",
        "lives": "라이브 목록 경로",
        "channels": "채널 정보 경로",
        "category_search": "카테고리 검색 경로",
        "token": "토큰 발급/갱신 경로",
        "token_revoke": "토큰 폐기 경로",
        "live_setting": "방송 설정 경로",
        "chat_send": "채팅 전송 경로",
        "chat_notice": "채팅 공지 경로",
        "chat_settings": "채팅 설정 경로",
        "session_auth": "채팅 받기 접속 주소 발급 경로",
        "session_subscribe_chat": "채팅 이벤트 구독 경로",
        "session_subscribe_donation": "후원 이벤트 구독 경로",
        "session_subscribe_subscription": "구독 이벤트 구독 경로",
        "subscribers": "채널 구독자 조회 경로",
        "chat_blind": "채팅 메시지 가리기 경로",
        "temporary_restrict": "임시 제한 경로",
        "restrict": "활동 제한 경로",
    },
}
DICT_DEFAULT_URLS = {"steam": DICT_DEFAULT_STEAM_URLS, "chzzk": DICT_DEFAULT_CHZZK_URLS, "youtube": DICT_DEFAULT_YOUTUBE_URLS}

# 창 제목. (시험용 설정으로 켰으면 눈에 띄게 표시해요: run.bat --test)
STR_APP_TITLE = "방송 도우미" + (f" [테스트: {STR_CONFIG_NAME}]" if B_TEST_MODE else "")

# 공유기(ChatHub)에 '후원 받기 자동 시작' 이 연결을 쓰고 있다고 올려 두는 이름
STR_AUTO_DONATION_USER = "auto_donation"

# 경로가 아니라 'http(s):// 로 시작하는 완전한 주소' 여야 하는 칸들
SET_FULL_URL_KEYS = {"player_summaries", "open_api_base", "service_api_base", "authorize", "data_api_base"}


# ---------------------------------------------------------------------------
# 일꾼(Worker): 오래 걸리는 일을 화면 뒤에서 대신 해주는 친구
# ---------------------------------------------------------------------------

class WorkerSignals(QObject):
    """일꾼이 화면에게 보내는 '알림 종' 들이에요."""
    sigFinished = Signal(object)   # 성공! 결과물을 담아서 보냄
    sigFailed = Signal(object)     # 실패! 에러를 담아서 보냄


class Worker(QRunnable):
    def __init__(self, fnTask: Callable, *args, **kwargs):
        super().__init__()
        self.fnTask = fnTask
        self.tupleArgs = args
        self.dictKwargs = kwargs
        self.objSignals = WorkerSignals()

    def run(self):
        try:
            objResult = self.fnTask(*self.tupleArgs, **self.dictKwargs)
        except Exception as objError:  # 일꾼이 죽으면 프로그램 전체가 꺼질 수 있어서 모두 잡아요.
            if not isinstance(objError, (ChzzkApiError, SteamApiError)):
                traceback.print_exc()
                app_log.LogException("백그라운드 작업 중 오류")
            self._SafeEmit(self.objSignals.sigFailed, objError)
        else:
            self._SafeEmit(self.objSignals.sigFinished, objResult)

    @staticmethod
    def _SafeEmit(objSignal, objValue) -> None:
        """창을 이미 닫아서 받을 사람이 없으면 조용히 넘어가요."""
        try:
            objSignal.emit(objValue)
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# 메인 창
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    # 토큰 갱신은 일꾼 스레드에서 일어나요. 화면 갱신은 반드시 메인 스레드에서 해야 해서 신호로 넘겨요.
    sigTokenChanged = Signal()
    sigOverlayTitle = Signal(str)  # OBS 독 제목칸에서 온 방송 제목 (다른 스레드에서 와도 화면 스레드에서 처리돼요)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(STR_APP_TITLE)
        self.resize(1480, 820)  # 오른쪽에 치지직 리모컨이 들어가서 넓게 시작해요.

        self.objThreadPool = QThreadPool.globalInstance()
        # 아래쪽에 '무슨 일이 있었는지' 기록하는 일기장
        # (맨 먼저 만들어요. 후원 목록 창 등이 만들어지면서 바로 로그를 남길 수 있어서)
        self.txtLog = QPlainTextEdit()
        self.txtLog.setObjectName("Log")
        self.txtLog.setReadOnly(True)
        self.txtLog.setMaximumBlockCount(500)
        self.txtLog.setMinimumHeight(60)
        self.dictConfig = LoadConfig()
        self._ApplyTheme()  # 저장된 색으로 프로그램 전체를 칠해요. (다른 창들도 같이)
        self.objChzzkClient: Optional[ChzzkApiClient] = None
        self.objSteamClient: Optional[SteamApiClient] = None
        self.objLastSteamStatus: Optional[SteamPlayerStatus] = None
        self.setLastRunningExes: set = set()          # 마지막 새로고침 때 실행 중이던 프로그램들
        self.listLastFolderGames: list = []           # 마지막 새로고침 때 게임 설치 폴더에서 실행 중이던 프로그램들
        # 지금 하는 게임 (스팀에서 게임 중이면 스팀, 아니면 실행 중인 프로그램에서 찾은 것). 없으면 None
        self.objCurrentGame: Optional[DetectedGame] = None
        self.bRefreshing = False  # 새로고침이 겹치지 않게 막는 깃발

        # 스팀 게임 ↔ 치지직 카테고리 짝꿍 목록 (data/game_map.txt)
        self.objGameMap = GameMap()
        # '지금 게임으로 맞추기' 를 눌렀는데 짝이 없을 때, 다음에 적용하는 카테고리를 이 게임의 짝으로 저장해요.
        self.objPendingMapGame: Optional[DetectedGame] = None
        # 자동 카테고리 변경을 마지막으로 처리한 게임 (같은 게임으로 계속 바꾸지 않게)
        self.strLastAutoSyncGameId: Optional[str] = None
        # '지금 방송 설정' 을 한 번 불러왔는지 (로그인하면 자동으로 한 번 불러와요)
        self.bLiveSettingLoaded = False
        # 실시간 채팅창 (처음 열 때 만들어요)
        self.objChatWindow: Optional[ChatWindow] = None
        # 실시간 채팅 연결 공유기: 채팅창과 후원 목록 창이 같은 연결 하나를 나눠 써요. (치지직은 동시 연결 3개 제한)
        self.objChatHub = ChatHub(fnGetClient=lambda: self.objChzzkClient)
        # 후원 목록 창은 미리 만들어 둬요. (창이 닫혀 있어도 연결만 돼 있으면 후원을 받아 둬요)
        self.objDonationWindow = DonationWindow(self.objChatHub, fnLog=self.Log)
        self.objOverlay = OverlayServer()
        strAlertUrl = str(self.dictConfig["app"].get("obs_alert_url", "") or "").strip()
        self.objOverlay.strAlertUrl = strAlertUrl if IsAllowedAlertUrl(strAlertUrl) else ""
        self.objDonationWindow.fnGetChannelId = lambda: self.dictConfig["chzzk"].get("channel_id", "")
        # '후원 받기 자동 시작' 으로 연결을 붙잡고 있는지 (창처럼 공유기에 이름을 올려 둬요)
        self.bAutoDonationJoined = False
        # 미션 창도 미리 만들어 둬요. (창이 닫혀 있어도 미션 후원을 받아서 등록해요)
        self.objMissionWindow = MissionWindow(self.objChatHub, fnLog=self.Log, dictApp=self.dictConfig["app"],
                                              fnSaveConfig=lambda: SaveConfig(self.dictConfig))
        # 후원 알림 소리: 치지직 후원 · 유튜브 슈퍼챗이 오면 '딩동'
        # (후원 소리와 구독 소리는 소리도, 켜고 끄는 설정도 따로예요)
        self.objAlarm = DonationAlarm()
        for strKind, strPrefix in (("donation", "donation"), ("subscription", "subscription")):
            self.objAlarm.SetStyle(strKind, self.dictConfig["app"].get(f"{strPrefix}_sound_volume"),
                                   self.dictConfig["app"].get(f"{strPrefix}_sound_pitch"))
        self.dlgAlarm: Optional[AlarmSettingsDialog] = None
        try:
            self.objAlarm.Prepare()
        except Exception:  # 소리 때문에 프로그램이 안 켜지면 안 돼요.
            pass
        objDonW = self.objDonationWindow
        objDonW.chkSound.setChecked(bool(self.dictConfig["app"].get("donation_sound", True)))
        objDonW.chkSubSound.setChecked(bool(self.dictConfig["app"].get("subscription_sound", True)))
        objDonW.chkSound.toggled.connect(lambda bChecked: self.OnAlarmToggled("donation_sound", "후원", bChecked))
        objDonW.chkSubSound.toggled.connect(lambda bChecked: self.OnAlarmToggled("subscription_sound", "구독", bChecked))
        objDonW.btnSoundTest.clicked.connect(lambda: self.objAlarm.Play("donation"))
        objDonW.btnSubSoundTest.clicked.connect(lambda: self.objAlarm.Play("subscription"))
        objDonW.btnSoundSettings.clicked.connect(self.OnAlarmSettingsClicked)
        self.objChatHub.sigDonation.connect(self._OnDonationAlarm)
        # 채팅 + 후원 목록 + 미션을 한 화면에 합친 '방송 도우미' 창
        # 유튜브 채팅 (공식 Data API, API 키 필요). 슈퍼챗은 후원 목록 · 미션에도 들어가요.
        self.objYouTubeHub = YouTubeHub(fnGetConfig=lambda: self.dictConfig)
        self.objYouTubeHub.sigDonation.connect(self.objDonationWindow.AddDonation)
        self.objYouTubeHub.sigDonation.connect(self._OnDonationAlarm)
        self.objYouTubeHub.sigDonation.connect(self.objMissionWindow._OnDonation)
        self.objChatWindow = ChatWindow(self.objChatHub, fnLog=self.Log, objYouTubeHub=self.objYouTubeHub,
                                        fnGetYouTubeTarget=lambda: self.dictConfig["youtube"].get("default_target", ""))
        self._ApplyTheme()  # 채팅창이 생겼으니 채팅 칸에도 색을 입혀요.
        self.objStreamWindow = StreamToolsWindow(self.objChatHub, self.objChatWindow,
                                                 self.objDonationWindow, self.objMissionWindow)
        self.listActiveWorkers = []  # 일꾼이 일하는 도중 사라지지 않도록 붙잡아 두는 목록

        # 방송 도우미(채팅 + 후원 + 미션)를 따로 뜨는 창이 아니라 메인 화면 가운데에 넣어요.
        # (메인 창이 보이면 채팅 연결을 잡아요 → 프로그램을 켜면 바로 채팅이 보여요)
        self.objStreamWindow.setWindowFlags(Qt.WindowType.Widget)

        # 맨 위 막대 먼저 (아래 창들을 만들면서 막대의 딱지를 바로 고쳐요)
        objHeader = self._BuildHeader()

        # 메뉴에서 여는 창들 (입력칸은 미리 만들어 둬요. 닫아도 그대로 남아 있어요)
        # 만드는 순서: 방송 관리 → 방송 상태 → 게임 짝(만들면서 앞의 두 창 글자를 고쳐요)
        self.dlgManage = self._MakeWindow("방송 관리", self._BuildManageTab(), 560, 760)
        self.dlgStatus = self._MakeWindow("방송 상태 (치지직 · 스팀)", self._BuildStatusColumn(), 460, 520)
        self.dlgGameMap = self._MakeWindow("게임 짝", self._BuildGameMapTab(), 760, 680)
        self.dlgSettings = self._BuildSettingsDialog()
        self.dlgLog = self._MakeWindow("로그", self.txtLog, 760, 420)
        self._BuildMenu()

        objCentral = QWidget()
        objCentral.setObjectName("Central")
        objLayout = QVBoxLayout(objCentral)
        objLayout.setContentsMargins(0, 0, 0, 0)
        objLayout.setSpacing(0)
        objLayout.addWidget(objHeader)
        # 가운데: [채팅 (· 후원 · 미션)] | [치지직 리모컨] (경계선을 끌어서 폭 조절)
        self.objRemotePanel = RemotePanel(lambda: self.dictConfig["chzzk"].get("channel_id", ""))
        self.objRemotePanel.sigHideRequested.connect(lambda: self._SetRemotePanel(False))
        self.objBodySplitter = QSplitter(Qt.Orientation.Horizontal)
        self.objBodySplitter.setChildrenCollapsible(False)
        self.objBodySplitter.addWidget(self.objStreamWindow)
        self.objBodySplitter.addWidget(self.objRemotePanel)
        self.objBodySplitter.setStretchFactor(0, 3)
        self.objBodySplitter.setStretchFactor(1, 2)
        self.objBodySplitter.setSizes([860, 560])
        objLayout.addWidget(self.objBodySplitter, 1)
        self.setCentralWidget(objCentral)
        self.bRemoteVisible = bool(self.dictConfig["app"].get("show_remote_panel", True))
        self.objRemotePanel.setVisible(self.bRemoteVisible)
        self.objStreamWindow.SetToolsVisible(bool(self.dictConfig["app"].get("show_donation_mission", False)))
        # OBS 채팅 화면: 채팅 · 후원이 오면 같이 내보내요. (꺼져 있으면 아무 일도 안 해요)
        self.objChatWindow.fnOverlay = self.objOverlay.Publish
        self.objOverlay.fnSend = self.objChatWindow.sigOverlaySend.emit  # OBS 독 입력칸 → 채팅 보내기
        self.objOverlay.fnSetTitle = self.sigOverlayTitle.emit            # OBS 독 제목칸 → 방송 제목 바꾸기
        self.sigOverlayTitle.connect(self._OnOverlayTitle)

        # 맨 아래 상태줄: 마지막 로그 한 줄 (전체는 [보기] → 로그)
        self.lblStatusLog = QLabel("")
        self.lblStatusLog.setObjectName("Help")
        self.statusBar().addWidget(self.lblStatusLog, 1)
        listLogLines = self.txtLog.toPlainText().splitlines()
        self.lblStatusLog.setText(listLogLines[-1] if listLogLines else "")

        # 자동 새로고침 타이머 (알람 시계)
        self.objRefreshTimer = QTimer(self)
        self.objRefreshTimer.timeout.connect(self.OnRefreshClicked)
        if self.chkAutoRefresh.isChecked():  # 지난번에 [자동] 을 켜 두었으면 시작할 때부터 돌려요.
            self.objRefreshTimer.start(int(self.dictConfig["app"]["refresh_interval_sec"]) * 1000)

        self.sigTokenChanged.connect(self._UpdateLoginLabel)

        self.Log("=== 프로그램 시작 ===" + (f" (설정 파일: {STR_CONFIG_NAME})" if B_TEST_MODE else ""))
        self._RebuildClients()
        self._UpdateLoginLabel()
        for strWarning in self.objGameMap.listWarnings:
            self.Log(f"[경고] {strWarning}")
        if self._HasRequiredSettings():
            self.OnRefreshClicked()
        # 창이 뜬 다음에 물어봐요. (설정이 비어 있을 때만)
        QTimer.singleShot(0, self._OnFirstShown)
        if self.bRemoteVisible:
            QTimer.singleShot(0, self.objRemotePanel.EnsureLoaded)  # 창이 먼저 뜨고, 웹 화면은 그다음에

    # ===================================================================
    # 화면 만들기
    # ===================================================================

    def _BuildHeader(self) -> QWidget:
        """맨 위 막대: 방송 상태 · 시청자 · 로그인 · 지금 게임 (색 딱지) + 방송 제목 · 카테고리."""
        objHeader = QFrame()
        objHeader.setObjectName("Header")
        objLayout = QVBoxLayout(objHeader)
        objLayout.setContentsMargins(14, 8, 14, 8)
        objLayout.setSpacing(4)

        objRow = QHBoxLayout()
        objRow.setSpacing(8)
        if B_TEST_MODE:  # 시험용 설정으로 켰다는 표시 (진짜 방송과 헷갈리지 않게)
            lblChipTest = self._Chip(f"테스트 설정: {STR_CONFIG_NAME}")
            self._SetChip(lblChipTest, lblChipTest.text(), "warn")
            objRow.addWidget(lblChipTest)
        self.lblChipLive = self._Chip("방송 확인 전")
        self.lblChipViewers = self._Chip("시청자 -")
        self.lblChipLogin = self._Chip("로그인 확인 전")
        self.lblChipGame = self._Chip("게임 -")
        for lblChip in (self.lblChipLive, self.lblChipViewers, self.lblChipLogin, self.lblChipGame):
            objRow.addWidget(lblChip)
        objRow.addStretch()
        self.lblLastUpdated = QLabel("")
        self.lblLastUpdated.setObjectName("Help")
        self.btnHeaderLogin = QPushButton("치지직 로그인")
        self.btnHeaderLogin.setObjectName("Primary")
        self.btnHeaderLogin.setToolTip("채팅 · 후원을 받으려면 로그인이 필요해요.")
        self.btnHeaderLogin.clicked.connect(self.OnLoginClicked)
        self.btnRefresh = QPushButton("새로고침")
        self.btnRefresh.clicked.connect(self.OnRefreshClicked)
        self.chkAutoRefresh = QCheckBox("자동")
        self.chkAutoRefresh.setToolTip("[설정] 의 새로고침 간격마다 자동으로 새로고침해요. (선택은 저장돼요)\n"
                                       "스팀 게임이 바뀌면 카테고리를 자동으로 맞추는 기능도 이 [자동] 이 켜져 있어야 돌아요.")
        self.chkAutoRefresh.setChecked(bool(self.dictConfig["app"].get("auto_refresh", False)))  # (연결 전이라 저장은 안 돼요)
        self.chkAutoRefresh.toggled.connect(self.OnAutoRefreshToggled)
        for objWidget in (self.lblLastUpdated, self.btnHeaderLogin, self.btnRefresh, self.chkAutoRefresh):
            objRow.addWidget(objWidget)
        objLayout.addLayout(objRow)

        # 둘째 줄: 방송 제목 · 카테고리
        self.lblHeaderTitle = QLabel("방송 제목 -")
        self.lblHeaderTitle.setObjectName("HeaderTitle")
        self.lblHeaderTitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lblHeaderCategory = QLabel("")
        self.lblHeaderCategory.setObjectName("Help")
        objTitleRow = QHBoxLayout()
        objTitleRow.addWidget(self.lblHeaderTitle, 1)
        objTitleRow.addWidget(self.lblHeaderCategory)
        objLayout.addLayout(objTitleRow)

        # 후원 대기 · 미션 수는 창 제목에 보여줘요.
        self.objStreamWindow.sigCountsChanged.connect(self._UpdateStreamButton)
        self._UpdateStreamButton(self.objStreamWindow.nPending, self.objStreamWindow.nActiveMissions)
        return objHeader

    def _BuildMenu(self) -> None:
        """맨 위 메뉴: 자주 안 쓰는 화면은 여기서 눌러서 열어요."""
        objMenuBar = self.menuBar()

        objBroadcast = objMenuBar.addMenu("방송(&B)")
        objBroadcast.addAction("방송 관리 (제목 · 카테고리 · 공지)...", lambda: self._OpenWindow(self.dlgManage))
        objBroadcast.addAction("지금 게임으로 카테고리 맞추기", self.OnSyncSteamGameClicked)
        objBroadcast.addSeparator()
        objBroadcast.addAction("새로고침", self.OnRefreshClicked).setShortcut("F5")
        objBroadcast.addSeparator()
        objBroadcast.addAction("치지직 로그인", self.OnLoginClicked)
        objBroadcast.addAction("로그아웃", self.OnLogoutClicked)

        objView = objMenuBar.addMenu("보기(&V)")
        objView.addAction("방송 상태 (치지직 · 스팀)...", lambda: self._OpenWindow(self.dlgStatus))
        objView.addAction("게임 짝...", lambda: self._OpenWindow(self.dlgGameMap))
        objView.addAction("로그...", lambda: self._OpenWindow(self.dlgLog))
        objView.addSeparator()
        self.actRemote = objView.addAction("치지직 리모컨 (오른쪽)")
        self.actRemote.setCheckable(True)
        self.actRemote.setChecked(bool(self.dictConfig["app"].get("show_remote_panel", True)))
        self.actRemote.toggled.connect(self._SetRemotePanel)
        self.actTools = objView.addAction("후원 목록 · 미션 화면 보이기")
        self.actTools.setCheckable(True)
        self.actTools.setChecked(bool(self.dictConfig["app"].get("show_donation_mission", False)))
        self.actTools.toggled.connect(self._SetToolsVisible)
        objView.addSeparator()
        self.actObs = objView.addAction("OBS 채팅 화면 켜기")
        self.actObs.setCheckable(True)
        self.actObs.setChecked(bool(self.dictConfig["app"].get("obs_overlay", False)))
        self.actObs.toggled.connect(self._SetObsOverlay)
        objView.addAction("OBS 독 주소 복사 (채팅 · 제목 입력 + 방송 상태)", lambda: self._CopyObsUrl(bDock=True))
        objView.addAction("OBS 방송 화면용 채팅 주소 복사 (보기 전용)", lambda: self._CopyObsUrl(bDock=False))
        objView.addAction("OBS 채팅 포트 번호 바꾸기...", self._ChangeObsPort)
        objView.addAction("OBS 영상 후원 알림 주소 설정...", self._SetObsAlertUrl)
        objView.addAction("OBS 리모컨(영상 후원) 주소 복사", self._CopyObsRemoteUrl)
        objView.addAction("업데이트 안내 보기...", self._ShowWhatsNew)

        objSettings = objMenuBar.addMenu("설정(&S)")
        objSettings.addAction("키 · ID · 서버 주소...", self.OnOpenSettingsClicked)
        objSettings.addAction("알림 소리...", self.OnAlarmSettingsClicked)
        objSettings.addAction("색상...", self.OnThemeClicked)
        objSettings.addSeparator()
        objSettings.addAction("이전 설정 가져오기...", self.OnImportConfigClicked)

    def _MakeWindow(self, strTitle: str, objContent: QWidget, nWidth: int, nHeight: int) -> QDialog:
        """메뉴에서 여는 창 하나. (메인 창을 막지 않아서 열어 둔 채로 써도 돼요)"""
        dlgWindow = QDialog(self)
        dlgWindow.setWindowTitle(strTitle)
        dlgWindow.resize(nWidth, nHeight)
        QVBoxLayout(dlgWindow).addWidget(objContent)
        return dlgWindow

    @staticmethod
    def _OpenWindow(dlgWindow: QDialog) -> None:
        dlgWindow.show()
        dlgWindow.raise_()
        dlgWindow.activateWindow()

    @staticmethod
    def _Chip(strText: str) -> QLabel:
        """맨 위 막대의 둥근 색 딱지."""
        lblChip = QLabel(strText)
        lblChip.setObjectName("Chip")
        return lblChip

    @staticmethod
    def _SetChip(lblChip: QLabel, strText: str, strState: str = "") -> None:
        """딱지 글자와 색(live · good · warn · off, 빈칸이면 기본)을 바꿔요."""
        lblChip.setText(strText)
        lblChip.setProperty("state", strState)
        lblChip.style().unpolish(lblChip)  # 색 다시 칠하기
        lblChip.style().polish(lblChip)

    def _BuildStatusColumn(self) -> QWidget:
        """[방송 상태] 창: 치지직 → 지금 하는 게임 → 스팀 (위에서 아래로)."""
        objInner = QWidget()
        objLayout = QVBoxLayout(objInner)
        objLayout.setContentsMargins(0, 0, 0, 0)

        # --- 치지직 상자 ---
        objChzzkBox = QGroupBox("치지직 (CHZZK)")
        objChzzkForm = QFormLayout(objChzzkBox)
        self.lblChzzkChannel = QLabel("-")
        self.lblChzzkStatus = QLabel("-")
        self.lblChzzkStatus.setObjectName("Value")
        self.lblChzzkTitle = QLabel("-")
        self.lblChzzkTitle.setWordWrap(True)
        self.lblChzzkCategory = QLabel("-")
        self.lblChzzkCategory.setWordWrap(True)
        self.lblChzzkViewers = QLabel("-")
        self.lblChzzkViewers.setObjectName("Value")
        objChzzkForm.addRow("채널", self.lblChzzkChannel)
        objChzzkForm.addRow("방송 상태", self.lblChzzkStatus)
        objChzzkForm.addRow("방송 제목", self.lblChzzkTitle)
        objChzzkForm.addRow("카테고리", self.lblChzzkCategory)
        objChzzkForm.addRow("시청자 수", self.lblChzzkViewers)

        # --- 지금 하는 게임 상자 (스팀 + 프로그램 감지를 합친 결과, 카테고리 맞추기에 쓰여요) ---
        objGameBox = QGroupBox("지금 하는 게임")
        objGameForm = QFormLayout(objGameBox)
        self.lblCurrentGame = QLabel("-")
        self.lblCurrentGame.setWordWrap(True)
        self.lblCurrentGame.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        objGameForm.addRow("게임", self.lblCurrentGame)

        # --- 스팀 상자 ---
        objSteamBox = QGroupBox("스팀 (Steam)")
        objSteamForm = QFormLayout(objSteamBox)
        self.lblSteamName = QLabel("-")
        self.lblSteamState = QLabel("-")
        self.lblSteamState.setWordWrap(True)
        self.lblSteamGame = QLabel("-")
        self.lblSteamGame.setWordWrap(True)
        self.lblSteamGame.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        objSteamForm.addRow("닉네임", self.lblSteamName)
        objSteamForm.addRow("접속 상태", self.lblSteamState)
        objSteamForm.addRow("플레이 중", self.lblSteamGame)

        objLayout.addWidget(objChzzkBox)
        objLayout.addWidget(objGameBox)
        objLayout.addWidget(objSteamBox)
        objLayout.addStretch()

        objScroll = QScrollArea()
        objScroll.setWidgetResizable(True)
        objScroll.setWidget(objInner)
        return objScroll

    def _BuildManageTab(self) -> QWidget:
        """방송 관리 칸: 위에서 아래로 [로그인 상태] → [지금 방송 설정] → ①제목 ②카테고리 ③채팅 순서예요."""
        objInner = QWidget()
        objLayout = QVBoxLayout(objInner)
        objLayout.setContentsMargins(0, 0, 0, 0)
        objLayout.setSpacing(10)

        # --- 맨 위: 로그인 상태 막대 (색으로 한눈에!) ---
        self.frmLoginBar = QWidget()
        self.frmLoginBar.setObjectName("LoginBar")
        objLoginRow = QHBoxLayout(self.frmLoginBar)
        objLoginRow.setContentsMargins(12, 8, 12, 8)
        self.lblLoginState = QLabel("-")
        self.lblLoginState.setWordWrap(True)
        self.btnLogin = QPushButton("치지직 로그인")
        self.btnLogin.clicked.connect(self.OnLoginClicked)
        self.btnLogout = QPushButton("로그아웃")
        self.btnLogout.clicked.connect(self.OnLogoutClicked)
        objLoginRow.addWidget(self.lblLoginState, 1)
        objLoginRow.addWidget(self.btnLogin)
        objLoginRow.addWidget(self.btnLogout)
        objLayout.addWidget(self.frmLoginBar)

        # --- 지금 방송 설정 (읽기 전용 요약) ---
        self.grpCurrentSetting = QGroupBox("지금 방송 설정")
        objCurrentForm = QFormLayout(self.grpCurrentSetting)
        self.lblCurTitle = QLabel("-")
        self.lblCurTitle.setWordWrap(True)
        self.lblCurCategory = QLabel("-")
        self.lblCurTags = QLabel("-")
        self.lblCurTags.setWordWrap(True)
        btnReloadSetting = QPushButton("새로고침")
        btnReloadSetting.clicked.connect(self.OnLoadSettingClicked)
        objCurTitleRow = QHBoxLayout()
        objCurTitleRow.addWidget(self.lblCurTitle, 1)
        objCurTitleRow.addWidget(btnReloadSetting)
        objCurrentForm.addRow("제목", objCurTitleRow)
        objCurrentForm.addRow("카테고리", self.lblCurCategory)
        objCurrentForm.addRow("태그", self.lblCurTags)
        objLayout.addWidget(self.grpCurrentSetting)

        # --- ① 방송 제목 ---
        self.grpTitle = QGroupBox("① 방송 제목 바꾸기")
        objTitleLayout = QVBoxLayout(self.grpTitle)
        objTitleLayout.addWidget(self._HelpLabel("다음 방송에도 그대로 쓰여요. 방송 중이면 바로 바뀌어요."))
        self.editTitle = QLineEdit()
        self.editTitle.setPlaceholderText("새 방송 제목")
        self.editTitle.returnPressed.connect(self.OnApplyTitleClicked)
        btnApplyTitle = QPushButton("제목 적용")
        btnApplyTitle.setObjectName("Primary")
        btnApplyTitle.clicked.connect(self.OnApplyTitleClicked)
        objTitleRow = QHBoxLayout()
        objTitleRow.addWidget(self.editTitle, 1)
        objTitleRow.addWidget(btnApplyTitle)
        objTitleLayout.addLayout(objTitleRow)
        objLayout.addWidget(self.grpTitle)

        # --- ② 카테고리 ---
        self.grpCategory = QGroupBox("② 카테고리 바꾸기")
        objCategoryLayout = QVBoxLayout(self.grpCategory)

        # 방법 A: 지금 하는 게임으로 맞추기 (스팀 또는 실행 중인 프로그램)
        objCategoryLayout.addWidget(self._SubTitleLabel("방법 A. 지금 하는 게임으로 맞추기 (추천)"))
        self.lblManageSteamGame = QLabel("지금 게임: 확인 전 (맨 위 [새로고침] 을 눌러 주세요)")
        self.lblManageSteamGame.setWordWrap(True)
        btnSyncGame = QPushButton("지금 게임으로 맞추기")
        btnSyncGame.setObjectName("Primary")
        btnSyncGame.setToolTip("짝이 저장된 게임이면 바로 적용하고, 없으면 검색해서 고르게 해줘요.")
        btnSyncGame.clicked.connect(self.OnSyncSteamGameClicked)
        objSyncRow = QHBoxLayout()
        objSyncRow.addWidget(self.lblManageSteamGame, 1)
        objSyncRow.addWidget(btnSyncGame)
        objCategoryLayout.addLayout(objSyncRow)

        # 짝이 없어서 '고르는 중' 인 게임 표시 + 취소 버튼
        self.frmPending = QWidget()
        self.frmPending.setObjectName("PendingBar")
        objPendingRow = QHBoxLayout(self.frmPending)
        objPendingRow.setContentsMargins(10, 6, 10, 6)
        self.lblPendingMap = QLabel("")
        self.lblPendingMap.setWordWrap(True)
        self.btnCancelPending = QPushButton("취소")
        self.btnCancelPending.clicked.connect(lambda: self._SetPendingMapGame(None))
        objPendingRow.addWidget(self.lblPendingMap, 1)
        objPendingRow.addWidget(self.btnCancelPending)
        objCategoryLayout.addWidget(self.frmPending)

        self.chkAutoSyncCategory = QCheckBox("게임이 바뀌면 자동으로 맞추기")
        self.chkAutoSyncCategory.setToolTip("짝이 없으면 자동으로 찾아요. 맨 위 [자동] 새로고침을 켜 둬야 해요.")
        self.chkAutoSyncCategory.setChecked(bool(self.dictConfig["app"].get("auto_sync_category", False)))
        self.chkAutoSyncCategory.toggled.connect(self.OnAutoSyncToggled)
        objCategoryLayout.addWidget(self.chkAutoSyncCategory)
        self.chkFallbackVarious = QCheckBox("짝을 못 찾으면 '종합 게임' 으로")
        self.chkFallbackVarious.setToolTip("자동 맞추기 때만 써요. 짝으로 저장하지는 않아요.")
        self.chkFallbackVarious.setChecked(bool(self.dictConfig["app"].get("auto_fallback_various", True)))
        self.chkFallbackVarious.toggled.connect(self.OnFallbackVariousToggled)
        objCategoryLayout.addWidget(self.chkFallbackVarious)
        self.chkFolderGames = QCheckBox("목록에 없는 게임도 알아보기")
        self.chkFolderGames.setToolTip("에픽 · 넥슨 · 엑스박스 등 게임 설치 폴더에서 실행된 프로그램도 게임으로 봐요.")
        self.chkFolderGames.setChecked(bool(self.dictConfig["app"].get("auto_detect_folder_games", True)))
        self.chkFolderGames.toggled.connect(self.OnFolderGamesToggled)
        objCategoryLayout.addWidget(self.chkFolderGames)

        # 방법 B: 직접 검색
        objCategoryLayout.addSpacing(6)
        objCategoryLayout.addWidget(self._SubTitleLabel("방법 B. 직접 검색해서 고르기"))
        self.editCategoryQuery = QLineEdit()
        self.editCategoryQuery.setPlaceholderText("카테고리 이름 (예: 나이트레인, talk)")
        self.editCategoryQuery.returnPressed.connect(self.OnSearchCategoryClicked)
        btnSearchCategory = QPushButton("검색")
        btnSearchCategory.clicked.connect(self.OnSearchCategoryClicked)
        objSearchRow = QHBoxLayout()
        objSearchRow.addWidget(self.editCategoryQuery, 1)
        objSearchRow.addWidget(btnSearchCategory)
        objCategoryLayout.addLayout(objSearchRow)

        self.cmbCategory = QComboBox()
        self.cmbCategory.setPlaceholderText("검색하면 여기에 결과가 나와요")
        btnApplyCategory = QPushButton("카테고리 적용")
        btnApplyCategory.setObjectName("Primary")
        btnApplyCategory.clicked.connect(self.OnApplyCategoryClicked)
        objResultRow = QHBoxLayout()
        objResultRow.addWidget(self.cmbCategory, 1)
        objResultRow.addWidget(btnApplyCategory)
        objCategoryLayout.addLayout(objResultRow)
        objLayout.addWidget(self.grpCategory)
        self._SetPendingMapGame(None)

        # --- ③ 채팅 ---
        self.grpChat = QGroupBox("채팅 · 공지")
        objChatLayout = QVBoxLayout(self.grpChat)
        objChatLayout.addWidget(self._HelpLabel("최대 100자. 공지는 채팅창 맨 위에 고정돼요."))
        self.chkAutoDonation = QCheckBox("프로그램을 켜면 후원 받기 자동 시작")
        self.chkAutoDonation.setToolTip("후원 목록 창을 안 열어도 영상 후원이 기록돼요.")
        self.chkAutoDonation.setChecked(bool(self.dictConfig["app"].get("auto_donation", True)))
        self.chkAutoDonation.toggled.connect(self.OnAutoDonationToggled)
        objChatLayout.addWidget(self.chkAutoDonation)
        objChatForm = QFormLayout()
        self.editChat = QLineEdit()
        self.editChat.setMaxLength(100)
        self.editChat.setPlaceholderText("보낼 메시지 (Enter 로 전송)")
        self.editChat.returnPressed.connect(self.OnSendChatClicked)
        btnSendChat = QPushButton("보내기")
        btnSendChat.setObjectName("Primary")
        btnSendChat.clicked.connect(self.OnSendChatClicked)
        objChatRow = QHBoxLayout()
        objChatRow.addWidget(self.editChat, 1)
        objChatRow.addWidget(btnSendChat)
        objChatForm.addRow("메시지", objChatRow)

        self.editNotice = QLineEdit()
        self.editNotice.setMaxLength(100)
        self.editNotice.setPlaceholderText("채팅창 위에 고정할 공지")
        btnNotice = QPushButton("공지 등록")
        btnNotice.clicked.connect(self.OnRegisterNoticeClicked)
        objNoticeRow = QHBoxLayout()
        objNoticeRow.addWidget(self.editNotice, 1)
        objNoticeRow.addWidget(btnNotice)
        objChatForm.addRow("공지", objNoticeRow)
        objChatLayout.addLayout(objChatForm)
        objLayout.addWidget(self.grpChat)
        objLayout.addStretch()

        # 칸이 많아서 창이 작으면 스크롤로 볼 수 있게 해요.
        objScroll = QScrollArea()
        objScroll.setWidgetResizable(True)
        objScroll.setWidget(objInner)
        return objScroll

    @staticmethod
    def _HelpLabel(strText: str) -> QLabel:
        """회색 작은 글씨 설명."""
        lblHelp = QLabel(strText)
        lblHelp.setWordWrap(True)
        lblHelp.setObjectName("Help")  # 색은 gui/theme.py 에서
        return lblHelp

    @staticmethod
    def _SubTitleLabel(strText: str) -> QLabel:
        """그룹 안의 작은 제목."""
        lblTitle = QLabel(strText)
        lblTitle.setWordWrap(True)
        lblTitle.setObjectName("SubTitle")  # 색은 gui/theme.py 에서
        return lblTitle

    def _BuildSettingsDialog(self) -> QDialog:
        """[설정] 창: 키 · ID 와 서버 주소(URL). 닫아도 입력칸은 그대로 남아 있어요."""
        dlgSettings = QDialog(self)
        dlgSettings.setWindowTitle("설정")
        dlgSettings.resize(640, 600)
        objTabs = QTabWidget()
        objTabs.addTab(self._BuildSettingsTab(), "키 · ID")
        objTabs.addTab(self._BuildUrlTab(), "서버 주소 (URL)")
        QVBoxLayout(dlgSettings).addWidget(objTabs)
        return dlgSettings

    def OnOpenSettingsClicked(self) -> None:
        self.dlgSettings.show()
        self.dlgSettings.raise_()
        self.dlgSettings.activateWindow()

    def _ApplyTheme(self, dictColors: Optional[dict] = None) -> None:
        """색을 프로그램 전체에 입혀요. (dictColors 가 없으면 저장된 색)"""
        if dictColors is None:
            dictColors = ThemeColors(self.dictConfig.get("theme"))
        objApp = QApplication.instance()
        # 'Fusion' 모양을 써요. (윈도우 기본 모양은 색을 입히면 화살표 · 체크 표시가 깨져요)
        if objApp.style().name().lower() != "fusion":
            objApp.setStyle("Fusion")
        objApp.setPalette(BuildPalette(dictColors))
        objApp.setStyleSheet(BuildStyleSheet(dictColors))
        # 채팅 칸은 채팅 줄마다 색을 넣어 그려서, 새 색으로 다시 그려 달라고 따로 알려줘요.
        if getattr(self, "objChatWindow", None) is not None:
            self.objChatWindow.SetColors(dictColors["card"], dictColors["text"])

    @staticmethod
    def _DescribeFound(dictInfo: dict) -> str:
        listFound = [strLabel for bFound, strLabel in (
            (dictInfo["bChzzkKeys"], "치지직 Client ID / Secret"), (dictInfo["bChzzkLogin"], "치지직 로그인"),
            (dictInfo["bSteam"], "스팀 API 키"), (dictInfo["bYouTube"], "유튜브 API 키")) if bFound]
        return " · ".join(listFound) if listFound else "(키 · 로그인 정보는 비어 있어요)"

    def _CheckOldConfig(self) -> None:
        """켤 때마다 확인: 설정이 비어 있고 옆 폴더에 이전 버전 설정이 있으면 가져올지 물어봐요.

        - 이미 키 · 로그인이 있으면 아무것도 안 해요. (쓰는 중인 설정은 건드리지 않아요)
        - 시험용 설정(run.bat --test)으로 켰을 때는 묻지 않아요.
        """
        if B_TEST_MODE or not self.dictConfig["app"].get("ask_import_old_config", True):
            return
        if not IsBlankConfig(self.dictConfig):
            return
        listOld = FindOldConfigs()
        if not listOld:
            return
        try:
            dictInfo = DescribeImport(listOld[0])
        except RuntimeError:
            return
        strAnswer = self._AskImportOld(listOld[0], self._DescribeFound(dictInfo), len(dictInfo["listAdded"]))
        if strAnswer == "import":
            self._ImportFromPath(listOld[0], bConfirm=False)
        elif strAnswer == "never":
            self.dictConfig["app"]["ask_import_old_config"] = False
            try:
                SaveConfig(self.dictConfig)
            except OSError as objError:
                self.Log(f"[경고] 설정 저장 실패: {objError}")
            self.Log("[설정] 이전 설정을 다시 묻지 않아요. ([설정] → 이전 설정 가져오기 로 언제든 가져올 수 있어요)")

    def _AskImportOld(self, strPath: str, strFound: str, nAdded: int) -> str:
        """이전 버전 설정을 찾았다고 알리고 물어봐요. 돌려주는 값: "import" / "skip" / "never" """
        objBox = QMessageBox(self)
        objBox.setWindowTitle("이전 설정을 찾았어요")
        objBox.setIcon(QMessageBox.Icon.Question)
        objBox.setText(f"이전 버전의 설정 파일을 찾았어요.\n\n{strPath}\n\n이어받는 것: {strFound} + 프로그램 설정\n"
                       f"새로 생긴 칸 {nAdded}개는 기본값으로 채워요.\n\n지금 설정이 비어 있어서 가져올 수 있어요. 가져올까요?\n"
                       "(가져온 뒤에는 프로그램이 종료돼요. 다시 켜면 적용돼요)")
        btnImport = objBox.addButton("가져오기", QMessageBox.ButtonRole.AcceptRole)
        objBox.addButton("이번엔 건너뛰기", QMessageBox.ButtonRole.RejectRole)
        btnNever = objBox.addButton("다시 묻지 않기", QMessageBox.ButtonRole.DestructiveRole)
        objBox.exec()
        objClicked = objBox.clickedButton()
        return "import" if objClicked is btnImport else "never" if objClicked is btnNever else "skip"

    def OnImportConfigClicked(self) -> None:
        """새 버전으로 옮겼을 때: 이전 폴더의 init.json 을 골라서 키 · 로그인 · 설정을 이어받아요."""
        strPath, _ = QFileDialog.getOpenFileName(
            self, "이전 버전의 설정 파일 고르기 (이전 폴더의 data → init.json)", os.path.dirname(STR_APP_DIR),
            "설정 파일 (*.json);;모든 파일 (*)")
        if not strPath:
            return
        self._ImportFromPath(strPath, bConfirm=True)

    def _ImportFromPath(self, strPath: str, bConfirm: bool) -> None:
        """고른 설정 파일을 가져와요. (bConfirm 이면 가져오기 전에 한 번 더 확인해요)"""
        try:
            dictInfo = DescribeImport(strPath)
        except RuntimeError as objError:
            QMessageBox.warning(self, "가져올 수 없어요", str(objError))
            return
        strFound = self._DescribeFound(dictInfo)
        if bConfirm:
            strQuestion = (f"이 파일의 설정을 지금 설정으로 가져올까요?\n\n{strPath}\n\n"
                           f"이어받는 것: {strFound} + 프로그램 설정\n"
                           f"새로 생긴 칸 {len(dictInfo['listAdded'])}개는 기본값으로 채워요.\n\n"
                           "지금 설정은 .bak 파일로 백업해 두고, 가져온 뒤에는 프로그램이 종료돼요. (다시 켜면 적용돼요)")
            if QMessageBox.question(self, "이전 설정 가져오기", strQuestion) != QMessageBox.StandardButton.Yes:
                return
        try:
            ImportConfig(strPath, STR_CONFIG_PATH)
        except (RuntimeError, OSError) as objError:
            QMessageBox.warning(self, "가져올 수 없어요", str(objError))
            return
        # 메모리의 설정도 같은 내용으로 맞춰요. (안 그러면 종료 전에 뭔가 저장될 때 옛 값으로 덮어써요)
        ReplaceInPlace(self.dictConfig, dictInfo["merged"])
        self.Log(f"[설정] 이전 설정을 가져왔어요: {strFound} (새 칸 {len(dictInfo['listAdded'])}개)")
        QMessageBox.information(self, "가져왔어요",
                                "이전 설정을 가져왔어요.\n프로그램을 종료할게요. run.bat 을 다시 실행해 주세요.")
        QTimer.singleShot(0, self.close)

    def OnThemeClicked(self) -> None:
        """[색상] 창. 고르는 동안 바로 보여주고, 취소하면 원래 색으로 돌아가요."""
        dlgTheme = ThemeDialog(self.dictConfig.get("theme"), fnPreview=self._ApplyTheme, parent=self)
        if dlgTheme.exec() != QDialog.DialogCode.Accepted:
            self._ApplyTheme()
            return
        self.dictConfig["theme"] = dlgTheme.GetTheme()
        try:
            SaveConfig(self.dictConfig)
        except OSError as objError:
            self.Log(f"[경고] 설정 저장 실패: {objError}")
            return
        self.Log(f"색상 저장 완료 ({self.dictConfig['theme']['preset']})")

    def _BuildSettingsTab(self) -> QWidget:
        objTab = QWidget()
        objForm = QFormLayout(objTab)
        dictSteam = self.dictConfig["steam"]
        dictChzzk = self.dictConfig["chzzk"]

        self.editSteamApiKey = QLineEdit(dictSteam.get("api_key", ""))
        self.editSteamApiKey.setEchoMode(QLineEdit.EchoMode.Password)  # 비밀번호처럼 ●●● 로 가려요
        self.editSteamId = QLineEdit(dictSteam.get("steam_id", ""))
        self.editSteamId.setPlaceholderText("숫자 17자리 (7656119...)")
        self.editClientId = QLineEdit(dictChzzk.get("client_id", ""))
        self.editClientSecret = QLineEdit(dictChzzk.get("client_secret", ""))
        self.editClientSecret.setEchoMode(QLineEdit.EchoMode.Password)
        self.editChannelId = QLineEdit(dictChzzk.get("channel_id", ""))
        self.editChannelId.setPlaceholderText("chzzk.naver.com/ 뒤의 32자리 영문+숫자")
        self.editRedirectUri = QLineEdit(dictChzzk.get("redirect_uri", ""))
        self.spinInterval = QSpinBox()
        self.spinInterval.setRange(10, 3600)
        self.spinInterval.setSuffix(" 초")
        self.spinInterval.setValue(int(self.dictConfig["app"].get("refresh_interval_sec", 30)))

        objForm.addRow(QLabel("<b>스팀</b>"))
        objForm.addRow("API 키", self.editSteamApiKey)
        objForm.addRow("SteamID64", self.editSteamId)
        objForm.addRow(QLabel("<b>치지직</b>"))
        objForm.addRow("Client ID", self.editClientId)
        objForm.addRow("Client Secret", self.editClientSecret)
        objForm.addRow("채널 ID", self.editChannelId)
        objForm.addRow("리디렉션 URL", self.editRedirectUri)
        dictYouTube = self.dictConfig["youtube"]
        self.editYouTubeApiKey = QLineEdit(dictYouTube.get("api_key", ""))
        self.editYouTubeApiKey.setEchoMode(QLineEdit.EchoMode.Password)
        self.editYouTubeApiKey.setPlaceholderText("Google Cloud → YouTube Data API v3 → API 키 (없으면 유튜브 채팅 안 씀)")
        self.editYouTubeTarget = QLineEdit(dictYouTube.get("default_target", ""))
        self.editYouTubeTarget.setPlaceholderText("https://www.youtube.com/live/... (또는 @채널이름)")
        self.editYouTubeTarget.setToolTip("@채널이름은 지금 방송을 찾는 데 사용량 100점이 들어서 방송 주소를 추천해요.\n"
                                          "저장한 뒤 채팅 위 [유튜브 연결] 을 누르면 연결돼요.")
        self.spinYouTubeInterval = QSpinBox()
        self.spinYouTubeInterval.setRange(3, 60)
        self.spinYouTubeInterval.setSuffix(" 초")
        self.spinYouTubeInterval.setValue(int(dictYouTube.get("min_interval_sec", 8)))
        self.spinYouTubeInterval.setToolTip("짧을수록 채팅이 빨리 보이지만 하루 사용량(10,000점)을 빨리 써요. 8초면 하루 약 4시간.")
        objForm.addRow(QLabel("<b>유튜브 (채팅 같이 보기)</b>"))
        objForm.addRow("API 키", self.editYouTubeApiKey)
        objForm.addRow("방송 주소", self.editYouTubeTarget)
        objForm.addRow("채팅 가져오는 간격", self.spinYouTubeInterval)
        objForm.addRow(QLabel("<b>앱</b>"))
        objForm.addRow("새로고침 간격", self.spinInterval)

        btnSave = QPushButton("저장")
        btnSave.setObjectName("Primary")
        btnSave.clicked.connect(self.OnSaveSettingsClicked)
        objForm.addRow("", btnSave)
        objForm.addRow(QLabel(f"저장 위치: {STR_CONFIG_PATH}"))
        return objTab

    def _BuildUrlTab(self) -> QWidget:
        """init.json 의 "urls" 칸을 하나씩 입력창으로 만들어 보여줘요."""
        objInner = QWidget()
        objForm = QFormLayout(objInner)

        # 입력창을 나중에 다시 찾을 수 있게 (서비스, 칸이름) → 입력창 사전에 담아둬요.
        self.dictUrlEdits = {}
        for strService, strTitle in (("steam", "스팀"), ("chzzk", "치지직"), ("youtube", "유튜브")):
            objForm.addRow(QLabel(f"<b>{strTitle}</b>"))
            dictUrls = self.dictConfig["urls"][strService]
            for strKey, strLabel in DICT_URL_LABELS[strService].items():
                editUrl = QLineEdit(dictUrls.get(strKey, ""))
                editUrl.setPlaceholderText(DICT_DEFAULT_URLS[strService][strKey])  # 비우면 기본값 사용
                editUrl.setToolTip(f"init.json → urls.{strService}.{strKey}")
                objForm.addRow(strLabel, editUrl)
                self.dictUrlEdits[(strService, strKey)] = editUrl

        objForm.addRow(QLabel("· 경로는 '기본 주소' 뒤에 붙어요. 라이브 상세 경로의 {channelId} 는 채널 ID 로 바뀌어요.\n"
                              "· 칸을 비워두면 프로그램 기본 주소를 사용해요."))

        objButtonRow = QHBoxLayout()
        btnReset = QPushButton("기본값으로 되돌리기")
        btnReset.clicked.connect(self.OnResetUrlsClicked)
        btnSave = QPushButton("URL 저장")
        btnSave.setObjectName("Primary")
        btnSave.clicked.connect(self.OnSaveUrlsClicked)
        objButtonRow.addStretch()
        objButtonRow.addWidget(btnReset)
        objButtonRow.addWidget(btnSave)
        objForm.addRow(objButtonRow)

        # 칸이 많아서 창이 작으면 스크롤로 볼 수 있게 해요.
        objScroll = QScrollArea()
        objScroll.setWidgetResizable(True)
        objScroll.setWidget(objInner)
        return objScroll

    # ===================================================================
    # 도우미 함수
    # ===================================================================

    def Log(self, strMessage: str) -> None:
        strLine = time.strftime("[%H:%M:%S] ") + strMessage
        app_log.Write(strMessage)  # Log 폴더에 날짜별 파일로 남겨요. (7일치)
        self.txtLog.appendPlainText(strLine)
        if hasattr(self, "lblStatusLog"):  # 상태줄은 창을 다 만든 뒤에 생겨요.
            self.lblStatusLog.setText(strLine)

    def RunInBackground(
        self,
        fnTask: Callable,
        fnOnSuccess: Callable[[object], None],
        fnOnFail: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        """일을 일꾼에게 맡기고, 끝나면 fnOnSuccess / fnOnFail 을 불러줘요."""
        objWorker = Worker(fnTask)
        # 일꾼이 일을 마치면 Qt 가 마음대로 지우지 않도록 해요. (우리가 목록에서 직접 정리해요)
        objWorker.setAutoDelete(False)
        self.listActiveWorkers.append(objWorker)

        def _Cleanup():
            if objWorker in self.listActiveWorkers:
                self.listActiveWorkers.remove(objWorker)

        def _OnSuccess(objResult):
            _Cleanup()
            fnOnSuccess(objResult)

        def _OnFail(objError):
            _Cleanup()
            (fnOnFail or self.ShowError)(objError)

        objWorker.objSignals.sigFinished.connect(_OnSuccess)
        objWorker.objSignals.sigFailed.connect(_OnFail)
        self.objThreadPool.start(objWorker)

    def ShowError(self, objError: Exception) -> None:
        if isinstance(objError, ChzzkAuthRequiredError):
            self._UpdateLoginLabel()
            QMessageBox.information(self, "로그인 필요", f"{objError}\n\n맨 위 [치지직 로그인] 을 눌러주세요.")
        else:
            QMessageBox.warning(self, "오류", str(objError))
        self.Log(f"[경고] {objError}")

    def _HasRequiredSettings(self) -> bool:
        # 스팀은 없어도 돼요. (스팀 밖 게임은 실행 중인 프로그램으로 감지해요)
        dictChzzk = self.dictConfig["chzzk"]
        return all([dictChzzk["client_id"], dictChzzk["client_secret"], dictChzzk["channel_id"]])

    def _RebuildClients(self) -> None:
        """설정이 바뀌면 심부름꾼(클라이언트)을 새로 만들어요."""
        dictSteam, dictChzzk = self.dictConfig["steam"], self.dictConfig["chzzk"]

        try:
            self.objSteamClient = SteamApiClient(dictSteam["api_key"], dictUrls=self.dictConfig["urls"]["steam"])
        except SteamApiError:
            self.objSteamClient = None

        # 같은 앱(Client ID/Secret)이면 심부름꾼을 새로 만들지 않고 주소만 바꿔요.
        # 새로 만들면 예전 심부름꾼(예: 채팅창이 쓰는 것)과 '일회용 Refresh Token' 을 나눠 갖게 돼서,
        # 한쪽이 갱신하는 순간 다른 쪽 토큰이 죽고, 그쪽이 갱신에 실패하면 로그인이 풀려요.
        objOld = self.objChzzkClient
        if (objOld is not None and objOld.strClientId == dictChzzk["client_id"].strip()
                and objOld.strClientSecret == dictChzzk["client_secret"].strip()):
            objOld.SetUrls(self.dictConfig["urls"]["chzzk"])
            return

        try:
            objClient = ChzzkApiClient(
                strClientId=dictChzzk["client_id"],
                strClientSecret=dictChzzk["client_secret"],
                objTokenInfo=TokenFromConfig(self.dictConfig),
                dictUrls=self.dictConfig["urls"]["chzzk"],
            )
            # 어떤 심부름꾼이 보낸 소식인지 같이 넘겨요. (지금 쓰는 심부름꾼 것만 저장)
            objClient.fnOnTokenRefreshed = lambda objToken, objOwner=objClient: self._OnTokenRefreshed(objOwner, objToken)
        except ChzzkApiError:
            objClient = None
        self.objChzzkClient = objClient

        # 다른 앱으로 바뀌었으면, 예전 앱으로 된 채팅 연결은 끊어요. (다시 [연결] 하면 새 앱으로 연결돼요)
        if objOld is not None:
            self.objChatHub.Disconnect()

    def _OnTokenRefreshed(self, objOwner: ChzzkApiClient, objTokenInfo) -> None:
        """(일꾼 스레드에서 불림) 새 토큰을 파일에 저장하고, 화면에는 신호로 알려요."""
        if objOwner is not self.objChzzkClient:
            return  # 이미 버려진 예전 심부름꾼의 소식이면 무시 (지금 토큰을 덮어쓰거나 지우면 안 돼요)
        StoreTokenToConfig(self.dictConfig, objTokenInfo)
        self.sigTokenChanged.emit()

    def _UpdateLoginLabel(self) -> None:
        """로그인 상태에 맞춰 색 막대 · 버튼 · 기능 칸을 켜고 꺼요."""
        bHasClient = self.objChzzkClient is not None
        bLoggedIn = bool(bHasClient and self.objChzzkClient.bIsLoggedIn)

        if not bHasClient:
            strState, strText = "none", "<b>치지직 설정 필요</b> — [설정] 메뉴에서 Client ID / Secret 을 먼저 입력해 주세요."
        elif bLoggedIn:
            strState, strText = "on", "<b>치지직 로그인됨</b> — 아래 기능을 모두 쓸 수 있어요."
        else:
            strState, strText = "off", "<b>로그인 필요</b> — 제목 · 카테고리 · 채팅은 [치지직 로그인] 후에 쓸 수 있어요."
        self.lblLoginState.setText(strText)
        self._SetChip(self.lblChipLogin, *{"none": ("치지직 설정 필요", "warn"), "on": ("로그인됨", "good"),
                                          "off": ("로그인 필요", "warn")}[strState])
        self.frmLoginBar.setProperty("state", strState)
        self.frmLoginBar.style().unpolish(self.frmLoginBar)  # 색 다시 칠하기
        self.frmLoginBar.style().polish(self.frmLoginBar)

        self.btnLogin.setVisible(bHasClient and not bLoggedIn)
        self.btnHeaderLogin.setVisible(bHasClient and not bLoggedIn)
        self.btnLogin.setEnabled(True)
        self.btnLogout.setVisible(bLoggedIn)
        for grpBox in (self.grpCurrentSetting, self.grpTitle, self.grpCategory, self.grpChat):
            grpBox.setEnabled(bLoggedIn)

        if not bLoggedIn:
            self.bLiveSettingLoaded = False
            self._ShowLiveSetting(None)
        elif not self.bLiveSettingLoaded:
            self.bLiveSettingLoaded = True
            self.OnLoadSettingClicked()  # 로그인되면 지금 방송 설정을 자동으로 보여줘요.
            # 로그아웃 상태라 못 했던 자동 카테고리 변경을 지금 다시 해봐요.
            self.strLastAutoSyncGameId = None
            self._AutoSyncCategory(self.objCurrentGame)
        self._ApplyAutoDonation()

    def _ApplyAutoDonation(self) -> None:
        """'후원 받기 자동 시작' 이 켜져 있고 로그인돼 있으면 채팅 연결을 붙잡아 둬요. (아니면 놓아요)

        상태가 '바뀔 때만' 붙잡거나 놓아요. 그래서 사용자가 창에서 [연결 끊기] 를 누르면,
        토큰이 갱신돼도 멋대로 다시 연결하지 않아요.
        """
        bLoggedIn = self.objChzzkClient is not None and self.objChzzkClient.bIsLoggedIn
        bWant = self.chkAutoDonation.isChecked() and bLoggedIn
        if bWant and not self.bAutoDonationJoined:
            self.bAutoDonationJoined = True
            self.objChatHub.Join(STR_AUTO_DONATION_USER)
            self.Log("[후원] 후원 받기 자동 시작 — 후원 목록 창을 안 열어도 기록돼요.")
        elif not bWant and self.bAutoDonationJoined:
            self.bAutoDonationJoined = False
            self.objChatHub.Leave(STR_AUTO_DONATION_USER)  # 채팅창 · 후원 목록 창이 열려 있으면 연결은 유지돼요.

    def _OnDonationAlarm(self, objDonation) -> None:
        """후원 · 구독이 오면 알림 소리를 내요. 구독은 후원과 다른 소리고, 각각 꺼 둘 수 있어요."""
        if objDonation.strDonationType == "SUBSCRIPTION":
            if self.objDonationWindow.chkSubSound.isChecked():
                self.objAlarm.Play("subscription")
        elif self.objDonationWindow.chkSound.isChecked():
            self.objAlarm.Play("donation")

    def _SaveAppOption(self, strKey: str, value) -> None:
        self.dictConfig["app"][strKey] = value
        try:
            SaveConfig(self.dictConfig)
        except OSError as objError:
            self.Log(f"[경고] 설정 저장 실패: {objError}")

    def _SetRemotePanel(self, bVisible: bool) -> None:
        """오른쪽 치지직 리모컨 패널을 보이거나 숨겨요. (선택은 저장돼요)"""
        self.bRemoteVisible = bVisible
        if self.actRemote.isChecked() != bVisible:
            self.actRemote.setChecked(bVisible)  # 패널의 [✕] 로 닫았을 때 메뉴 체크도 맞춰요.
            return  # (체크가 바뀌면서 이 함수가 한 번 더 불려요)
        self.objRemotePanel.setVisible(bVisible)
        if bVisible:
            self.objRemotePanel.EnsureLoaded()
        self._SaveAppOption("show_remote_panel", bVisible)

    def _SetToolsVisible(self, bVisible: bool) -> None:
        """후원 목록 · 미션 화면을 보이거나 숨겨요. (숨겨도 후원 받기 · 알림 · 타이머는 계속돼요)"""
        self.objStreamWindow.SetToolsVisible(bVisible)
        self._SaveAppOption("show_donation_mission", bVisible)

    def _PublishObsStatus(self, objLive=None) -> None:
        """OBS 독 상단에 보여줄 방송 상태를 알려요. (방송 중 · 시청자 · 제목 · 카테고리 · 현재 게임)"""
        if objLive is not None:
            self.objLastLive = objLive
        objLive = getattr(self, "objLastLive", None)
        if objLive is None:
            return
        objGame = getattr(self, "objCurrentGame", None)
        objClient = getattr(self, "objChzzkClient", None)
        self.objOverlay.SetStatus({
            "live": bool(objLive.bIsLive), "viewers": int(objLive.nConcurrentUserCount or 0),
            "title": objLive.strLiveTitle or "", "channel": objLive.strChannelName or "",
            "category": objLive.strLiveCategoryValue or objLive.strLiveCategory or "",
            "game": objGame.strGameName if objGame else "",
            "loggedIn": bool(objClient is not None and objClient.bIsLoggedIn),
            "at": datetime.now().strftime("%H:%M:%S")})

    def _OnOverlayTitle(self, strTitle: str) -> None:
        """OBS 독 제목칸에서 온 방송 제목 바꾸기. (결과는 프로그램 로그와 OBS 화면 안내로 알려요)"""
        objClient = getattr(self, "objChzzkClient", None)
        if objClient is None or not objClient.bIsLoggedIn:
            self.objChatWindow._SendOverlay({"type": "system", "text": "치지직 로그인이 필요해요"})
            self.Log("[경고] OBS 제목 바꾸기: 치지직 로그인이 필요해요.")
            return
        self.Log("OBS 제목칸에서 방송 제목 바꾸기 요청")

        def _Done(objSetting):
            self.editTitle.setText(objSetting.strDefaultLiveTitle)
            self.editTitle.setModified(False)
            self._ShowLiveSetting(objSetting)
            self.Log(f"제목 변경: {objSetting.strDefaultLiveTitle}")
            objLast = getattr(self, "objLastLive", None)
            if objLast is not None:
                objLast.strLiveTitle = objSetting.strDefaultLiveTitle
                self.lblHeaderTitle.setText(objSetting.strDefaultLiveTitle or "방송 제목 -")
                self._PublishObsStatus()
            self.objChatWindow._SendOverlay({"type": "system", "text": "방송 제목을 바꿨어요"})

        def _Fail(objError):
            self.Log(f"[경고] OBS 제목 바꾸기 실패: {objError}")
            self.objChatWindow._SendOverlay({"type": "system", "text": f"제목 바꾸기 실패: {objError}"})

        self.RunInBackground(lambda: objClient.UpdateLiveSetting(strDefaultLiveTitle=strTitle), _Done, _Fail)

    def _ObsPort(self) -> int:
        try:
            return int(self.dictConfig["app"].get("obs_overlay_port", N_DEFAULT_PORT))
        except (TypeError, ValueError):
            return N_DEFAULT_PORT

    def _SetObsOverlay(self, bOn: bool, bSave: bool = True) -> None:
        """OBS 채팅 화면(내 컴퓨터 안에서만 열리는 주소)을 켜거나 꺼요."""
        if bOn:
            nWanted = self._ObsPort()
            bOk, strMessage = self.objOverlay.StartWithFallback(nWanted)
            if bOk and self.objOverlay.nPort != nWanted:
                # 원하던 번호를 다른 프로그램이 쓰고 있어서 다음 번호로 열었어요. 앞으로도 같은 주소가 되게 저장해요.
                self.Log(f"[안내] 포트 {nWanted} 는 다른 프로그램이 쓰고 있어서 {self.objOverlay.nPort} 로 열었어요. "
                         "OBS 에는 새 주소를 다시 붙여넣어 주세요. ([보기] → OBS 주소 복사)")
                self.dictConfig["app"]["obs_overlay_port"] = self.objOverlay.nPort
                self._SaveAppOption("obs_overlay_port", self.objOverlay.nPort)
                if bSave:
                    QMessageBox.information(
                        self, "OBS 채팅 화면",
                        f"포트 {nWanted} 를 다른 프로그램이 쓰고 있어서 {self.objOverlay.nPort} 번으로 열었어요.\n"
                        "OBS 에 붙여 둔 주소가 있으면 [보기] → OBS 주소 복사 로 새 주소를 다시 붙여넣어 주세요.")
            if not bOk:
                self.Log(f"[경고] OBS 채팅 화면을 켤 수 없어요: {strMessage}")
                self.actObs.blockSignals(True)
                self.actObs.setChecked(False)
                self.actObs.blockSignals(False)
                QMessageBox.warning(self, "OBS 채팅 화면", f"켤 수 없어요.\n\n{strMessage}")
                return
            self.Log(f"OBS 채팅 화면을 켰어요: {strMessage}  (OBS 브라우저 소스 · 독에 붙여넣으세요)")
        else:
            self.objOverlay.Stop()
            self.Log("OBS 채팅 화면을 껐어요.")
        if bSave:
            self._SaveAppOption("obs_overlay", bOn)

    def _ChangeObsPort(self) -> None:
        """OBS 채팅 화면의 포트 번호를 바꿔요. (다른 프로그램과 겹칠 때)"""
        nNow = self.objOverlay.nPort if self.objOverlay.bIsRunning else self._ObsPort()
        nNew, bOk = QInputDialog.getInt(
            self, "OBS 채팅 포트 번호",
            "OBS 채팅 주소의 포트 번호예요. (1024~65535)\n다른 프로그램과 겹치면 다른 번호로 바꾸세요.\n"
            "바꾸면 OBS 에 붙인 주소도 새로 붙여넣어야 해요.", nNow, 1024, 65535)
        if not bOk or nNew == nNow:
            return
        bWasOn = self.objOverlay.bIsRunning
        if bWasOn:
            self.objOverlay.Stop()
        self.dictConfig["app"]["obs_overlay_port"] = nNew
        self._SaveAppOption("obs_overlay_port", nNew)
        self.Log(f"OBS 채팅 포트를 {nNew} 로 바꿨어요.")
        if bWasOn:
            self._SetObsOverlay(True, bSave=False)

    def _CopyObsUrl(self, bDock: bool = False) -> None:
        """OBS 주소 복사. bDock=True 면 독용(/dock: 방송 상태 + 제목 · 채팅 입력칸), 아니면 방송 화면용(/chat: 보기 전용)."""
        if not self.objOverlay.bIsRunning:
            QMessageBox.information(self, "OBS 주소", "먼저 [보기] → OBS 채팅 화면 켜기 를 체크해 주세요.")
            return
        strUrl = self.objOverlay.DockUrl() if bDock else self.objOverlay.Url()
        QApplication.clipboard().setText(strUrl)
        if bDock:
            strGuide = ("OBS 메뉴 [독] → 사용자 지정 브라우저 독 → 이름 정하고 주소 붙여넣기\n\n"
                        "패널에 이렇게 나와요:\n"
                        "· 맨 위: 방송 상태 (방송 중 · 시청자 · 카테고리 · 제목 · 게임)\n"
                        "· 가운데: 채팅\n"
                        "· 아래: 제목 입력칸 + 채팅 입력칸\n"
                        "(치지직 로그인이 되어 있어야 제목 · 채팅을 보낼 수 있어요. 스트리머만 보는 화면이에요)")
        else:
            strGuide = ("OBS 소스 [+] → 브라우저 → 주소 붙여넣기 (방송 화면에 채팅이 나가요, 보기 전용)\n\n"
                        "옵션 예: 주소 뒤에 ?theme=light&size=24&lines=20  (자세한 건 README)")
        QMessageBox.information(self, "OBS 주소", f"주소를 복사했어요:\n{strUrl}\n\n{strGuide}")

    def _SetObsAlertUrl(self) -> None:
        """치지직 스튜디오의 '알림 주소'를 넣어 두면 OBS 채팅 화면 위쪽에 영상 후원 알림 화면이 같이 나와요."""
        strNow = self.objOverlay.strAlertUrl
        strText, bOk = QInputDialog.getText(
            self, "OBS 영상 후원 알림 주소",
            "치지직 스튜디오의 '알림 주소'(OBS 브라우저 소스에 넣는 방송용 주소)를 붙여넣어 주세요.\n"
            "· 같은 OBS 채팅 화면 위쪽에 영상 후원 알림이 같이 나와요.\n"
            "· 이 주소에는 내 채널 비밀 값이 들어 있어요. 남에게 보여주지 마세요.\n"
            "· 지우려면 비우고 [확인]. 네이버(https) 주소만 받아요.",
            QLineEdit.EchoMode.Password, strNow)
        if not bOk:
            return
        strText = strText.strip()
        if strText and not IsAllowedAlertUrl(strText):
            QMessageBox.warning(self, "OBS 영상 후원 알림 주소",
                                "이 주소는 쓸 수 없어요. 네이버(https://...naver.com/...) 주소만 받아요.")
            return
        self.objOverlay.strAlertUrl = strText
        self._SaveAppOption("obs_alert_url", strText)
        self.Log("OBS 영상 후원 알림 주소를 " + ("저장했어요. (OBS 채팅 화면을 새로고침하면 보여요)" if strText else "지웠어요."))

    def _CopyObsRemoteUrl(self) -> None:
        """영상 후원 재생 · 건너뛰기를 하는 치지직 리모컨 주소를 복사해요. (OBS 독에 붙여서 쓰기)"""
        strUrl = RemoteControlUrl(self.dictConfig["chzzk"].get("channel_id", ""))
        QApplication.clipboard().setText(strUrl)
        QMessageBox.information(
            self, "OBS 리모컨 주소",
            f"주소를 복사했어요:\n{strUrl}\n\n"
            "OBS [독] → 사용자 지정 브라우저 독 → 이름 정하고 주소 붙여넣기\n"
            "처음 한 번 네이버 로그인을 하면 OBS 안에 로그인이 저장돼요.\n"
            "영상 후원 재생 · 건너뛰기는 이 화면에서 직접 눌러요.\n"
            "(영상 자체는 치지직이 주는 방송용 알림 주소를 OBS 브라우저 소스로 쓰는 거예요)")

    def _OnFirstShown(self) -> None:
        """창이 뜬 다음: 새 버전 안내 → 이전 설정 가져오기 확인."""
        if self.actObs.isChecked():
            self._SetObsOverlay(True, bSave=False)  # 지난번에 켜 두었으면 다시 켜요.
        self._CheckWhatsNew()
        self._CheckOldConfig()

    def _ShowWhatsNew(self) -> None:
        objBox = QMessageBox(self)
        objBox.setWindowTitle("업데이트 안내")
        objBox.setTextFormat(Qt.TextFormat.RichText)
        objBox.setText(whats_new.BuildHtml())
        objBox.exec()

    def _CheckWhatsNew(self) -> None:
        """새 버전으로 처음 켰을 때 바뀐 점을 한 번만 보여줘요. (시험용 설정으로 켰을 때는 건너뛰어요)"""
        if B_TEST_MODE or self.dictConfig["app"].get("last_seen_version", "") == whats_new.STR_VERSION:
            return
        self._ShowWhatsNew()
        self._SaveAppOption("last_seen_version", whats_new.STR_VERSION)

    def OnAlarmSettingsClicked(self) -> None:
        """[설정] → 알림 소리...: 후원 · 구독 소리의 크기 · 음 높이"""
        if self.dlgAlarm is None:
            self.dlgAlarm = AlarmSettingsDialog(self.objAlarm.GetStyle, self._ApplyAlarmStyle, self._PreviewAlarm, self)
        self.dlgAlarm.Reload()
        self._OpenWindow(self.dlgAlarm)

    def _ApplyAlarmStyle(self, strKind: str, nVolume: int, strPitch: str, bSave: bool) -> None:
        self.objAlarm.SetStyle(strKind, nVolume, strPitch)
        self.dictConfig["app"][f"{strKind}_sound_volume"] = nVolume
        self.dictConfig["app"][f"{strKind}_sound_pitch"] = strPitch
        if bSave:
            try:
                SaveConfig(self.dictConfig)
            except OSError as objError:
                self.Log(f"[경고] 설정 저장 실패: {objError}")

    def _PreviewAlarm(self, strKind: str) -> None:
        """설정을 바꾼 직후 들려줘요. (바로 이어서 바꿀 수 있게 간격 제한은 풀어요)"""
        self.objAlarm.dictLastPlayedAt.pop(strKind, None)
        self.objAlarm.Play(strKind)

    def OnAlarmToggled(self, strKey: str, strName: str, bChecked: bool) -> None:
        """후원 소리 / 구독 소리 켜고 끄기를 저장해요."""
        self.dictConfig["app"][strKey] = bChecked
        try:
            SaveConfig(self.dictConfig)
        except OSError as objError:
            self.Log(f"[경고] 설정 저장 실패: {objError}")
        self.Log(f"[{strName}] 알림 소리 {'켜짐' if bChecked else '꺼짐'}")

    def OnAutoDonationToggled(self, bChecked: bool) -> None:
        self.dictConfig["app"]["auto_donation"] = bChecked
        try:
            SaveConfig(self.dictConfig)
        except OSError as objError:
            self.Log(f"[경고] 설정 저장 실패: {objError}")
        self._ApplyAutoDonation()
        if not bChecked:
            self.Log("[후원] 후원 받기 자동 시작 꺼짐 — 채팅창이나 후원 목록 창을 열었을 때만 받아요.")

    def _ShowLiveSetting(self, objSetting) -> None:
        """'지금 방송 설정' 칸을 채워요. (None 이면 비워요)"""
        if objSetting is None:
            for lblItem in (self.lblCurTitle, self.lblCurCategory, self.lblCurTags):
                lblItem.setText("-")
            return
        self.lblCurTitle.setText(objSetting.strDefaultLiveTitle or "-")
        if objSetting.strCategoryId:
            self.lblCurCategory.setText(f"{objSetting.strCategoryValue or objSetting.strCategoryId}  [{objSetting.strCategoryType}]")
        else:
            self.lblCurCategory.setText("없음")
        self.lblCurTags.setText(", ".join(objSetting.listTags) or "없음")
        # 사용자가 제목 칸을 고치는 중이 아니면, 지금 제목으로 채워둬요. (조금만 고쳐서 적용하기 편하게)
        if not self.editTitle.isModified():
            self.editTitle.setText(objSetting.strDefaultLiveTitle)

    def _RequireChzzk(self) -> Optional[ChzzkApiClient]:
        if self.objChzzkClient is None:
            QMessageBox.information(self, "설정 필요", "[설정] 메뉴에서 치지직 Client ID / Secret 을 먼저 입력해 주세요.")
        return self.objChzzkClient

    # ===================================================================
    # 상태 새로고침 동작
    # ===================================================================

    def OnRefreshClicked(self) -> None:
        if self.bRefreshing:
            return  # 이전 새로고침이 아직 안 끝났으면 건너뛰어요.
        self.bRefreshing = True
        self.btnRefresh.setEnabled(False)

        objSteamClient = self.objSteamClient
        objChzzkClient = self.objChzzkClient
        bFolderGames = self.chkFolderGames.isChecked()
        strSteamId = self.dictConfig["steam"]["steam_id"]
        strChannelId = self.dictConfig["chzzk"]["channel_id"]

        def _FetchAll():
            """스팀과 치지직을 따로따로 조회해서, 한쪽 실패가 다른 쪽을 막지 않게 해요."""
            dictResult = {}
            try:
                # 스팀 키가 없으면 스팀은 건너뛰어요. (None = 스팀 안 씀)
                dictResult["objSteam"] = objSteamClient.GetPlayerStatus(strSteamId) if objSteamClient else None
            except SteamApiError as objError:
                dictResult["objSteam"] = objError
            try:
                dictResult["setExes"] = ListRunningExeNames()
            except OSError:
                dictResult["setExes"] = set()
            try:
                dictResult["listFolderGames"] = ListFolderGames() if bFolderGames else []
            except OSError:
                dictResult["listFolderGames"] = []
            try:
                if objChzzkClient is None:
                    raise ChzzkApiError("치지직 Client ID / Secret 이 설정되지 않았어요.")
                dictResult["objChzzk"] = objChzzkClient.GetLiveDetail(strChannelId)
            except ChzzkApiError as objError:
                dictResult["objChzzk"] = objError
            return dictResult

        def _Done(dictResult):
            self.bRefreshing = False
            self.btnRefresh.setEnabled(True)
            self._ShowSteam(dictResult["objSteam"])
            self.setLastRunningExes = dictResult["setExes"]
            self.listLastFolderGames = dictResult["listFolderGames"]
            self._UpdateCurrentGame()
            self._ShowChzzk(dictResult["objChzzk"])
            self.lblLastUpdated.setText(time.strftime("마지막 갱신 %H:%M:%S"))

        def _Fail(objError):
            self.bRefreshing = False
            self.btnRefresh.setEnabled(True)
            self.Log(f"[경고] 새로고침 실패: {objError}")

        self.RunInBackground(_FetchAll, _Done, _Fail)

    def _UpdateCurrentGame(self, bAutoSync: bool = True) -> None:
        """마지막 스팀 상태 + 실행 중인 프로그램으로 '지금 하는 게임' 을 다시 정하고, 화면과 자동 변경에 반영해요."""
        self.objCurrentGame = PickCurrentGame(self.objLastSteamStatus, self.setLastRunningExes,
                                              [objEntry.strSteamGameId for objEntry in self.objGameMap.ListEntries()],
                                              self.listLastFolderGames if self.chkFolderGames.isChecked() else [])
        objGame = self.objCurrentGame
        self._SetChip(self.lblChipGame, f"게임: {objGame.strGameName}" if objGame else "게임 없음")
        self._PublishObsStatus()
        if objGame is None:
            self.lblCurrentGame.setText("없음 (스팀 게임도, 짝이 있거나 잘 알려진 게임 프로그램도 안 보여요)")
        else:
            objEntry = self.objGameMap.Get(objGame.strGameId)
            strMapped = (objEntry.strCategoryValue or objEntry.strCategoryId) if objEntry else "없음"
            self.lblCurrentGame.setText(f"{objGame.strGameName}  [{objGame.strSourceName}: {KeyToDisplay(objGame.strGameId)}]"
                                        f"\n→ 치지직 짝: {strMapped}")
        self._UpdateManageSteamGame(objGame)
        if bAutoSync:
            self._AutoSyncCategory(objGame)

    def _UpdateManageSteamGame(self, objGame: Optional[DetectedGame]) -> None:
        """방송 관리 칸의 '지금 게임' 글자를 고쳐요."""
        if objGame is None:
            self.lblManageSteamGame.setText("지금 게임: 없음 (게임을 켜고 맨 위 [새로고침] 을 눌러 주세요)")
            return
        objEntry = self.objGameMap.Get(objGame.strGameId)
        strMapped = (f"<b>{objEntry.strCategoryValue or objEntry.strCategoryId}</b>" if objEntry
                     else "<span style='color:#b45309'>짝 없음 → 누르면 검색해서 골라요</span>")
        self.lblManageSteamGame.setText(f"지금 게임: <b>{objGame.strGameName}</b> ({objGame.strSourceName})"
                                        f"<br>→ 치지직 짝: {strMapped}")

    def _ShowSteam(self, objResult) -> None:
        """스팀 상자를 채워요. (카테고리 맞추기는 _UpdateCurrentGame 이 해요)"""
        if objResult is None:  # 스팀 키를 안 넣었으면 스팀은 안 써요.
            self.objLastSteamStatus = None
            self.lblSteamName.setText("-")
            self.lblSteamState.setText("스팀 API 키 없음 — 실행 중인 프로그램 감지만 써요")
            self.lblSteamGame.setText("-")
            return
        if isinstance(objResult, Exception):
            self.lblSteamState.setText(f"[경고] {objResult}")
            self.Log(f"[스팀] [경고] {objResult}")
            # 예전 게임 정보로 '지금 게임으로 맞추기' 를 하지 않도록 지워요.
            self.objLastSteamStatus = None
            return
        self.objLastSteamStatus = objResult
        self.lblSteamName.setText(objResult.strPersonaName)
        self.lblSteamState.setText(objResult.strPersonaState)
        if objResult.bIsPlaying:
            self.lblSteamGame.setText(f"{objResult.strGameName}  (ID: {objResult.strGameId})")
        elif not objResult.bIsProfilePublic:
            self.lblSteamGame.setText("프로필 비공개 (게임 정보 확인 불가)")
        else:
            self.lblSteamGame.setText("게임 안 하는 중")
        self.Log("[스팀] " + objResult.ToDisplayText())

    def _ShowChzzk(self, objResult) -> None:
        if isinstance(objResult, Exception):
            self.lblChzzkStatus.setText(f"[경고] {objResult}")
            self._SetChip(self.lblChipLive, "치지직 확인 실패", "warn")
            self.Log(f"[치지직] [경고] {objResult}")
            return
        objLive: ChzzkLiveStatus = objResult
        self._SetChip(self.lblChipLive, "● 방송 중" if objLive.bIsLive else "방송 꺼짐", "live" if objLive.bIsLive else "off")
        self._SetChip(self.lblChipViewers, f"시청자 {objLive.nConcurrentUserCount:,}명" if objLive.bIsLive else "시청자 -")
        self.lblHeaderTitle.setText(objLive.strLiveTitle or "방송 제목 -")
        strCategory = objLive.strLiveCategoryValue or objLive.strLiveCategory
        self.lblHeaderCategory.setText(f"카테고리: {strCategory}" if strCategory else "")
        self.lblChzzkChannel.setText(objLive.strChannelName)
        self.lblChzzkStatus.setText("방송 중" if objLive.bIsLive else "방송 꺼짐")
        self.lblChzzkTitle.setText(objLive.strLiveTitle or "-")
        self.lblChzzkCategory.setText(objLive.strLiveCategoryValue or objLive.strLiveCategory or "-")
        self.lblChzzkViewers.setText(f"{objLive.nConcurrentUserCount:,} 명" if objLive.bIsLive else "-")
        self.Log(f"[치지직] {'방송 중' if objLive.bIsLive else '방송 꺼짐'} / 출처: {objLive.strSource}")
        self._PublishObsStatus(objLive)

    def OnAutoRefreshToggled(self, bChecked: bool) -> None:
        self._SaveAppOption("auto_refresh", bChecked)
        if bChecked:
            nIntervalSec = int(self.dictConfig["app"]["refresh_interval_sec"])
            self.objRefreshTimer.start(nIntervalSec * 1000)
            self.Log(f"자동 새로고침 켜짐 ({nIntervalSec}초마다)")
        else:
            self.objRefreshTimer.stop()
            self.Log("자동 새로고침 꺼짐")

    # ===================================================================
    # 방송 관리 동작
    # ===================================================================

    def OnLoginClicked(self) -> None:
        objClient = self._RequireChzzk()
        if objClient is None:
            return
        self.btnLogin.setEnabled(False)
        self.Log("브라우저에서 치지직 로그인 후 [동의] 를 눌러주세요... (최대 3분 대기)")
        strRedirectUri = self.dictConfig["chzzk"]["redirect_uri"]

        def _Done(_objToken):
            self._UpdateLoginLabel()
            self.Log("치지직 계정 연동 완료")

        def _Fail(objError):
            self._UpdateLoginLabel()
            self.ShowError(objError)

        self.RunInBackground(lambda: LoginWithBrowser(objClient, strRedirectUri), _Done, _Fail)

    def OnLogoutClicked(self) -> None:
        objClient = self._RequireChzzk()
        if objClient is None:
            return

        def _Done(_):
            self._UpdateLoginLabel()
            self.Log("로그아웃 완료")

        def _Fail(objError):
            # 서버에 폐기 요청이 실패해도, 내 컴퓨터의 토큰은 이미 지워졌어요.
            self._UpdateLoginLabel()
            self.Log(f"로그아웃 (서버 폐기 요청 실패: {objError})")

        self.RunInBackground(objClient.RevokeToken, _Done, _Fail)

    def OnLoadSettingClicked(self) -> None:
        objClient = self.objChzzkClient
        if objClient is None or not objClient.bIsLoggedIn:
            return

        def _Done(objSetting):
            self._ShowLiveSetting(objSetting)
            self.Log(f"방송 설정 불러옴: 제목='{objSetting.strDefaultLiveTitle}', "
                     f"카테고리='{objSetting.strCategoryValue or '-'}'")

        def _Fail(objError):
            self.bLiveSettingLoaded = False
            self.ShowError(objError)

        self.RunInBackground(objClient.GetLiveSetting, _Done, _Fail)

    def OnApplyTitleClicked(self) -> None:
        objClient = self._RequireChzzk()
        strTitle = self.editTitle.text().strip()
        if objClient is None:
            return
        if not strTitle:
            QMessageBox.information(self, "안내", "방송 제목을 입력해 주세요.")
            return

        def _Done(objSetting):
            self.editTitle.setModified(False)
            self._ShowLiveSetting(objSetting)
            self.Log(f"제목 변경: {objSetting.strDefaultLiveTitle}")

        self.RunInBackground(lambda: objClient.UpdateLiveSetting(strDefaultLiveTitle=strTitle), _Done)

    def OnSearchCategoryClicked(self) -> None:
        objClient = self._RequireChzzk()
        strQuery = self.editCategoryQuery.text().strip()
        if objClient is None or not strQuery:
            return

        def _Done(listCategories):
            self.cmbCategory.clear()
            for objCategory in listCategories:
                # 화면엔 이름을, 속에는 상자 전체를 숨겨서 넣어둬요.
                self.cmbCategory.addItem(f"{objCategory.strCategoryValue}  [{objCategory.strCategoryType}]", objCategory)
            self.Log(f"카테고리 검색 '{strQuery}': {len(listCategories)}개")
            if not listCategories and self.objPendingMapGame is not None:
                self.Log("[안내] 결과가 없어요. 치지직에서 쓰는 한글 이름으로 다시 검색해 보세요. (예: 엘든 링)")

        self.RunInBackground(lambda: objClient.SearchCategory(strQuery), _Done)

    def OnApplyCategoryClicked(self) -> None:
        objClient = self._RequireChzzk()
        objCategory = self.cmbCategory.currentData()
        if objClient is None or objCategory is None:
            QMessageBox.information(self, "안내", "먼저 카테고리를 검색해서 하나 골라주세요.")
            return
        objPendingGame = self.objPendingMapGame

        def _Done(objSetting):
            self._ShowLiveSetting(objSetting)
            self.Log(f"카테고리 변경: {objSetting.strCategoryValue or objCategory.strCategoryValue}")
            if objPendingGame is not None and IsFallbackCategory(objCategory.strCategoryId):
                # '종합 게임' 은 짝으로 저장하지 않아요. (나중에 치지직에 카테고리가 생기면 그걸 쓰게)
                self.Log(f"[안내] '종합 게임' 은 짝으로 저장하지 않아요: {objPendingGame.strGameName}")
                self._SetPendingMapGame(None)
                return
            # '지금 게임으로 맞추기' 중이었다면 → 이 선택을 짝으로 기억해요. (다음부터는 자동!)
            if objPendingGame is not None:
                self._SaveGameMap(objPendingGame, objCategory.strCategoryType,
                                  objCategory.strCategoryId, objCategory.strCategoryValue)
                self._SetPendingMapGame(None)

        self.RunInBackground(
            lambda: objClient.UpdateLiveSetting(
                strCategoryType=objCategory.strCategoryType, strCategoryId=objCategory.strCategoryId
            ),
            _Done,
        )

    def OnSyncSteamGameClicked(self) -> None:
        """지금 하는 게임(스팀 또는 실행 중인 프로그램)에 맞춰 치지직 카테고리를 바꿔요.

        - 짝이 저장된 게임 → 바로 적용
        - 짝이 없는 게임   → 자동으로 찾아봐요. (스팀 한국어 이름 · 한국어 이름 목록)
                             확실하면 짝으로 저장하고 적용, 아니면 후보를 보여주고 고르게 해요.
        """
        objSteam = self.objCurrentGame
        if objSteam is None:
            QMessageBox.information(self, "안내", "지금 하는 게임이 확인되지 않았어요. 맨 위 [새로고침] 을 눌러 보세요.\n"
                                    "(목록에 없는 프로그램이면 [보기] → [게임 짝] → '실행 중인 프로그램에서' 로 짝을 만들어 주세요)")
            return

        objEntry = self.objGameMap.Get(objSteam.strGameId)
        if objEntry is not None:
            self._ApplyMappedCategory(objEntry, objSteam.strGameName)
            return

        # 짝이 없어요 → 자동으로 찾아보고, 못 찾으면 고르는 모드로!
        self._AutoFindAndApply(objSteam, bQuiet=False)

    def _AutoFindAndApply(self, objGame: DetectedGame, bQuiet: bool) -> None:
        """짝이 없는 게임의 치지직 카테고리를 자동으로 찾아요.

        - 확실한 짝(이름이 똑같음) → 짝으로 저장하고 적용 (다음부터는 바로)
        - 못 찾음 + bQuiet(자동 맞추기) → '종합 게임' 설정이 켜져 있으면 종합 게임으로 적용 (저장은 안 함)
        - 못 찾음 + 버튼으로 누름        → 후보 + '종합 게임' 을 목록에 채워서 고르게 해요.
        """
        objClient = self.objChzzkClient if bQuiet else self._RequireChzzk()
        if objClient is None:
            return
        self.Log(f"[짝 찾기] {objGame.strGameName} 의 치지직 카테고리를 찾는 중...")

        def _Done(objResult):
            if objResult.objBest is not None:
                objBest = objResult.objBest
                self._SaveGameMap(objGame, objBest.strCategoryType, objBest.strCategoryId, objBest.strCategoryValue)
                self.Log(f"[짝 찾기] 자동으로 찾았어요: {objGame.strGameName} → {objBest.strCategoryValue} "
                         f"(검색어 '{objResult.strMatchedQuery}')")
                objEntry = self.objGameMap.Get(objGame.strGameId)
                if objEntry is not None:
                    self._ApplyMappedCategory(objEntry, objGame.strGameName, bQuiet=bQuiet)
                return

            strTried = ", ".join(f"'{strQuery}'" for strQuery in objResult.listQueries) or "-"
            if bQuiet:
                if self.chkFallbackVarious.isChecked():
                    strType, strId, strValue = TUPLE_FALLBACK_CATEGORY
                    self.Log(f"[짝 찾기] {objGame.strGameName} 은(는) 치지직 카테고리를 못 찾아서 '{strValue}' 으로 바꿔요. "
                             f"(찾아본 말: {strTried})")
                    self._ApplyMappedCategory(GameMapEntry(objGame.strGameId, strType, strId, strValue),
                                              objGame.strGameName, bQuiet=True)
                else:
                    self.Log(f"[짝 찾기] {objGame.strGameName} 은(는) 짝을 못 찾아서 자동 변경을 건너뛰어요. "
                             "[방송 관리] → '지금 게임으로 맞추기' 로 골라 주세요.")
                return

            # 버튼으로 눌렀을 때 → 후보를 보여주고 고르게 해요.
            self._SetPendingMapGame(objGame)
            self.editCategoryQuery.setText(objResult.listQueries[0] if objResult.listQueries else objGame.strGameName)
            self.cmbCategory.clear()
            for objCategory in objResult.listCandidates:
                self.cmbCategory.addItem(f"{objCategory.strCategoryValue}  [{objCategory.strCategoryType}]", objCategory)
            objFallback = FallbackCategory()
            self.cmbCategory.addItem(f"{objFallback.strCategoryValue}  [{objFallback.strCategoryType}]  — 치지직에 없는 게임", objFallback)
            if not objResult.listCandidates:
                self.cmbCategory.setCurrentIndex(self.cmbCategory.count() - 1)  # 후보가 없으면 종합 게임을 골라 둬요.
            self.Log(f"[짝 찾기] 확실한 짝을 못 찾았어요 (찾아본 말: {strTried}). 후보 {len(objResult.listCandidates)}개 — "
                     "맞는 걸 골라 [카테고리 적용] 을 누르세요. 치지직에 없는 게임이면 '종합 게임' 을 고르세요.")

        def _Fail(objError):
            self.Log(f"[짝 찾기] 실패: {objError}")
            if bQuiet:
                self.strLastAutoSyncGameId = None  # 다음 새로고침 때 다시 시도

        self.RunInBackground(lambda: FindCategoryForGame(objClient, objGame.strGameId, objGame.strGameName), _Done, _Fail)

    # ===================================================================
    # 게임 짝 (스팀 gameid / 프로그램 exe ↔ 치지직 카테고리)
    # ===================================================================

    def _SetPendingMapGame(self, objSteam: Optional[DetectedGame]) -> None:
        self.objPendingMapGame = objSteam
        self.frmPending.setVisible(objSteam is not None)
        if objSteam is None:
            self.lblPendingMap.setText("")
        else:
            self.lblPendingMap.setText(
                f"짝 저장 대기: <b>{objSteam.strGameName}</b> ({objSteam.strSourceName}: {KeyToDisplay(objSteam.strGameId)})<br>"
                "검색 결과에서 맞는 카테고리를 골라 [카테고리 적용] 을 누르면 짝으로 저장돼요. "
                "결과가 없으면 한글 이름으로 다시 검색해 보세요."
            )

    def _SaveGameMap(self, objSteam: DetectedGame, strCategoryType: str,
                     strCategoryId: str, strCategoryValue: str) -> None:
        try:
            self.objGameMap.Set(GameMapEntry(
                strSteamGameId=objSteam.strGameId,
                strCategoryType=strCategoryType,
                strCategoryId=strCategoryId,
                strCategoryValue=strCategoryValue,
                strMemo=objSteam.strGameName,
            ))
        except (OSError, ValueError) as objError:
            self.ShowError(objError)
            return
        self._ReloadGameMapTable()
        self.Log(f"짝 저장: {objSteam.strGameName} ↔ {strCategoryValue} (data/game_map.txt)")

    def _ApplyMappedCategory(self, objEntry: GameMapEntry, strGameName: str, bQuiet: bool = False) -> None:
        """짝 목록에 적힌 카테고리를 치지직에 적용해요."""
        objClient = self.objChzzkClient if bQuiet else self._RequireChzzk()
        if objClient is None:
            return
        strShowName = objEntry.strCategoryValue or objEntry.strCategoryId

        def _Fail(objError):
            if bQuiet:
                self.strLastAutoSyncGameId = None  # 실패했으니 다음 새로고침 때 다시 시도해요.
                self.Log(f"[경고] 자동 카테고리 변경 실패 ({strGameName}): {objError}")
            else:
                self.ShowError(objError)

        self.RunInBackground(
            lambda: objClient.UpdateLiveSetting(strCategoryType=objEntry.strCategoryType,
                                                strCategoryId=objEntry.strCategoryId),
            lambda objSetting: (self._ShowLiveSetting(objSetting),
                                self.Log(f"카테고리 변경: {strGameName} → {strShowName}")),
            _Fail,
        )

    def _AutoSyncCategory(self, objSteam: Optional[DetectedGame]) -> None:
        """(새로고침 때마다 불림) 게임이 바뀌었고 짝이 있으면 카테고리를 자동으로 바꿔요."""
        if not self.chkAutoSyncCategory.isChecked():
            return
        if objSteam is None:
            self.strLastAutoSyncGameId = None  # 게임을 끄면 초기화 → 다시 켜면 또 맞춰줘요.
            return
        if objSteam.strGameId == self.strLastAutoSyncGameId:
            return  # 이미 처리한 게임
        self.strLastAutoSyncGameId = objSteam.strGameId

        if self.objChzzkClient is None or not self.objChzzkClient.bIsLoggedIn:
            self.Log("[안내] 자동 카테고리 변경은 치지직 로그인이 필요해요. 맨 위 [치지직 로그인] 을 눌러 주세요.")
            return
        objEntry = self.objGameMap.Get(objSteam.strGameId)
        if objEntry is None:
            self._AutoFindAndApply(objSteam, bQuiet=True)  # 짝이 없으면 자동으로 찾아봐요.
            return
        self._ApplyMappedCategory(objEntry, objSteam.strGameName, bQuiet=True)

    def OnFolderGamesToggled(self, bChecked: bool) -> None:
        self.dictConfig["app"]["auto_detect_folder_games"] = bChecked
        try:
            SaveConfig(self.dictConfig)
        except OSError as objError:
            self.Log(f"[경고] 설정 저장 실패: {objError}")
        if not bChecked:
            self.listLastFolderGames = []
            self._UpdateCurrentGame(bAutoSync=False)

    def OnFallbackVariousToggled(self, bChecked: bool) -> None:
        self.dictConfig["app"]["auto_fallback_various"] = bChecked
        try:
            SaveConfig(self.dictConfig)
        except OSError as objError:
            self.Log(f"[경고] 설정 저장 실패: {objError}")

    def OnAutoSyncToggled(self, bChecked: bool) -> None:
        self.dictConfig["app"]["auto_sync_category"] = bChecked
        try:
            SaveConfig(self.dictConfig)
        except OSError as objError:
            self.Log(f"[경고] 설정 저장 실패: {objError}")
        self.strLastAutoSyncGameId = None
        self.Log("자동 카테고리 변경 " + ("켜짐" if bChecked else "꺼짐"))
        if bChecked:
            self._AutoSyncCategory(self.objCurrentGame)

    def _BuildGameMapTab(self) -> QWidget:
        objTab = QWidget()
        objLayout = QVBoxLayout(objTab)
        objLayout.setContentsMargins(0, 0, 0, 0)
        objLayout.addWidget(self._HelpLabel(
            "게임 ↔ 치지직 카테고리 짝 목록 (data/game_map.txt). "
            "스팀 게임은 gameid, 스팀 밖 게임(롤 · 발로란트 등)은 프로그램 이름(exe)으로 짝을 지어요."
        ))

        self.tblGameMap = QTableWidget(0, 4)
        self.tblGameMap.setHorizontalHeaderLabels(["gameid / exe", "게임 (메모)", "치지직 카테고리", "카테고리 ID"])
        self.tblGameMap.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tblGameMap.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tblGameMap.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tblGameMap.verticalHeader().setVisible(False)
        # 줄을 누르면 아래 '추가 / 수정' 칸에 그 짝이 채워져요.
        self.tblGameMap.itemSelectionChanged.connect(self.OnGameMapRowSelected)
        objLayout.addWidget(self.tblGameMap)

        objButtonRow = QHBoxLayout()
        btnDelete = QPushButton("선택한 짝 삭제")
        btnDelete.clicked.connect(self.OnDeleteGameMapClicked)
        btnOpen = QPushButton("파일 열기 (메모장)")
        btnOpen.clicked.connect(self.OnOpenGameMapFileClicked)
        btnReload = QPushButton("다시 읽기")
        btnReload.clicked.connect(self.OnReloadGameMapClicked)
        objButtonRow.addWidget(btnDelete)
        objButtonRow.addStretch()
        objButtonRow.addWidget(btnOpen)
        objButtonRow.addWidget(btnReload)
        objLayout.addLayout(objButtonRow)

        # --- 짝 추가 / 수정 ---
        objEditBox = QGroupBox("짝 추가 / 수정  (목록에서 줄을 누르면 수정)")
        objEditForm = QFormLayout(objEditBox)

        self.editMapGameId = QLineEdit()
        self.editMapGameId.setPlaceholderText("스팀 gameid (예: 2622380) 또는 exe 이름")
        self.editMapGameId.setToolTip("예: 2622380 또는 VALORANT-Win64-Shipping.exe")
        btnLoadCurrentGame = QPushButton("지금 하는 게임")
        btnLoadCurrentGame.clicked.connect(self.OnLoadCurrentGameForMapClicked)
        btnPickProgram = QPushButton("실행 중인 프로그램에서")
        btnPickProgram.setToolTip("스팀 밖 게임용: 지금 창이 떠 있는 프로그램 목록에서 게임을 골라요.")
        btnPickProgram.clicked.connect(self.OnPickProgramForMapClicked)
        objGameIdRow = QHBoxLayout()
        objGameIdRow.addWidget(QLabel("불러오기:"))
        objGameIdRow.addWidget(btnLoadCurrentGame)
        objGameIdRow.addWidget(btnPickProgram)
        objGameIdRow.addStretch()
        objEditForm.addRow("gameid / exe", self.editMapGameId)
        objEditForm.addRow("", objGameIdRow)

        self.editMapMemo = QLineEdit()
        self.editMapMemo.setPlaceholderText("게임 이름 (메모용, 비워도 됨)")
        objEditForm.addRow("게임 이름", self.editMapMemo)

        self.editMapCategoryQuery = QLineEdit()
        self.editMapCategoryQuery.setPlaceholderText("치지직 카테고리 이름 (예: 나이트레인)")
        self.editMapCategoryQuery.returnPressed.connect(self.OnSearchMapCategoryClicked)
        btnSearchMapCategory = QPushButton("검색")
        btnSearchMapCategory.clicked.connect(self.OnSearchMapCategoryClicked)
        objQueryRow = QHBoxLayout()
        objQueryRow.addWidget(self.editMapCategoryQuery)
        objQueryRow.addWidget(btnSearchMapCategory)
        objEditForm.addRow("카테고리 검색", objQueryRow)

        self.cmbMapCategory = QComboBox()
        objEditForm.addRow("치지직 카테고리", self.cmbMapCategory)

        objSaveRow = QHBoxLayout()
        btnClearMapForm = QPushButton("입력 지우기")
        btnClearMapForm.clicked.connect(self.OnClearMapFormClicked)
        btnSaveMap = QPushButton("짝 저장")
        btnSaveMap.setObjectName("Primary")
        btnSaveMap.clicked.connect(self.OnSaveMapEntryClicked)
        objSaveRow.addStretch()
        objSaveRow.addWidget(btnClearMapForm)
        objSaveRow.addWidget(btnSaveMap)
        objEditForm.addRow(objSaveRow)
        objLayout.addWidget(objEditBox)

        self._ReloadGameMapTable()
        return objTab

    def OnGameMapRowSelected(self) -> None:
        """목록에서 고른 짝을 '추가 / 수정' 칸에 채워요."""
        nRow = self.tblGameMap.currentRow()
        if nRow < 0 or self.tblGameMap.item(nRow, 0) is None:
            return
        objEntry = self.objGameMap.Get(self.tblGameMap.item(nRow, 0).data(Qt.ItemDataRole.UserRole))
        if objEntry is None:
            return
        self.editMapGameId.setText(KeyToDisplay(objEntry.strSteamGameId))
        self.editMapMemo.setText(objEntry.strMemo)
        # 지금 저장된 카테고리를 선택칸에 넣어둬요. (검색 안 하고 메모만 고쳐 저장해도 되게)
        self.cmbMapCategory.clear()
        self._AddMapCategoryItem(ChzzkCategory(
            strCategoryType=objEntry.strCategoryType,
            strCategoryId=objEntry.strCategoryId,
            strCategoryValue=objEntry.strCategoryValue,
        ), "  (현재 저장된 값)")

    def _AddMapCategoryItem(self, objCategory: ChzzkCategory, strSuffix: str = "") -> None:
        strName = objCategory.strCategoryValue or objCategory.strCategoryId
        self.cmbMapCategory.addItem(f"{strName}  [{objCategory.strCategoryType}]{strSuffix}", objCategory)

    def OnLoadCurrentGameForMapClicked(self) -> None:
        objSteam = self.objCurrentGame
        if objSteam is None:
            QMessageBox.information(self, "안내", "지금 하는 게임이 확인되지 않았어요. 맨 위 [새로고침] 을 눌러 보세요.\n"
                                    "(스팀 밖 게임이면 '실행 중인 프로그램에서 고르기' 를 눌러 보세요)")
            return
        self.editMapGameId.setText(KeyToDisplay(objSteam.strGameId))
        self.editMapMemo.setText(objSteam.strGameName)
        objEntry = self.objGameMap.Get(objSteam.strGameId)
        if objEntry is not None:
            self.Log(f"[안내] {objSteam.strGameName} 은(는) 이미 짝이 있어요. 저장하면 새 카테고리로 바뀌어요.")
        if not self.editMapCategoryQuery.text().strip():
            self.editMapCategoryQuery.setText(objSteam.strGameName)

    def OnPickProgramForMapClicked(self) -> None:
        """창이 떠 있는 프로그램 목록을 보여주고, 고른 프로그램을 짝 입력칸에 채워요. (스팀 밖 게임용)"""
        try:
            listPrograms = ListWindowedPrograms()
        except OSError as objError:
            self.ShowError(objError)
            return
        if not listPrograms:
            QMessageBox.information(self, "안내", "창이 떠 있는 프로그램을 찾지 못했어요. 게임을 먼저 켜 주세요.")
            return
        listItems = []
        for strExe, strTitle in listPrograms:
            strKnown = DICT_KNOWN_GAMES.get(strExe.lower())
            listItems.append(f"{strExe}  —  {strKnown or strTitle}" + ("  ★" if strKnown else ""))
        strPicked, bOk = QInputDialog.getItem(self, "실행 중인 프로그램", "게임 프로그램을 고르세요. (★ = 잘 알려진 게임)",
                                              listItems, 0, False)
        if not bOk:
            return
        strExe, strTitle = listPrograms[listItems.index(strPicked)]
        strName = DICT_KNOWN_GAMES.get(strExe.lower(), strTitle)
        self.editMapGameId.setText(strExe)
        self.editMapMemo.setText(strName)
        if not self.editMapCategoryQuery.text().strip():
            self.editMapCategoryQuery.setText(strName)
        if self.objGameMap.Get(KeyFromInput(strExe)) is not None:
            self.Log(f"[안내] {strExe} 은(는) 이미 짝이 있어요. 저장하면 새 카테고리로 바뀌어요.")

    def OnSearchMapCategoryClicked(self) -> None:
        objClient = self._RequireChzzk()
        strQuery = self.editMapCategoryQuery.text().strip()
        if objClient is None or not strQuery:
            return

        def _Done(listCategories):
            self.cmbMapCategory.clear()
            for objCategory in listCategories:
                self._AddMapCategoryItem(objCategory)
            self.Log(f"카테고리 검색 '{strQuery}': {len(listCategories)}개")
            if not listCategories:
                self.Log("[안내] 결과가 없어요. 치지직에서 쓰는 한글 이름으로 다시 검색해 보세요. (예: 나이트레인)")

        self.RunInBackground(lambda: objClient.SearchCategory(strQuery), _Done)

    def OnClearMapFormClicked(self) -> None:
        self.tblGameMap.clearSelection()
        self.editMapGameId.clear()
        self.editMapMemo.clear()
        self.editMapCategoryQuery.clear()
        self.cmbMapCategory.clear()

    def OnSaveMapEntryClicked(self) -> None:
        """입력한 짝을 game_map.txt 에 추가하거나 고쳐요."""
        strGameId = KeyFromInput(self.editMapGameId.text())
        objCategory = self.cmbMapCategory.currentData()
        if strGameId is None:
            QMessageBox.warning(self, "확인", "스팀 gameid(숫자) 또는 프로그램 이름(.exe 로 끝남)을 입력해 주세요.\n"
                                "([보기] → [방송 상태] '지금 하는 게임' 의 [ ] 안 글자)")
            return
        if objCategory is None:
            QMessageBox.warning(self, "확인", "치지직 카테고리를 검색해서 하나 골라 주세요.")
            return

        # 이미 있는 짝을 다른 카테고리로 바꾸는 거면 한 번 물어봐요.
        objOld = self.objGameMap.Get(strGameId)
        if objOld is not None and objOld.strCategoryId != objCategory.strCategoryId:
            strQuestion = (f"{KeyToDisplay(strGameId)} 는 이미 '{objOld.strCategoryValue or objOld.strCategoryId}' 와 짝이에요.\n"
                           f"'{objCategory.strCategoryValue or objCategory.strCategoryId}' 로 바꿀까요?")
            if QMessageBox.question(self, "확인", strQuestion) != QMessageBox.StandardButton.Yes:
                return

        strMemo = self.editMapMemo.text().strip().replace("#", "")
        try:
            self.objGameMap.Set(GameMapEntry(
                strSteamGameId=strGameId,
                strCategoryType=objCategory.strCategoryType,
                strCategoryId=objCategory.strCategoryId,
                strCategoryValue=objCategory.strCategoryValue,
                strMemo=strMemo,
            ))
        except (OSError, ValueError) as objError:
            self.ShowError(objError)
            return

        self._ReloadGameMapTable()
        self.strLastAutoSyncGameId = None  # 짝이 바뀌었으니 자동 변경을 다시 확인하게 해요.
        self.Log(f"짝 {'수정' if objOld else '추가'}: {strMemo or KeyToDisplay(strGameId)} ↔ "
                 f"{objCategory.strCategoryValue or objCategory.strCategoryId}")
        self._UpdateCurrentGame()  # 새 짝으로 '지금 게임' 을 다시 정하고, 자동 변경도 다시 확인해요.

    def _ReloadGameMapTable(self) -> None:
        listEntries = self.objGameMap.ListEntries()
        self.tblGameMap.setRowCount(len(listEntries))
        for nRow, objEntry in enumerate(listEntries):
            strKeyText = KeyToDisplay(objEntry.strSteamGameId)
            if strKeyText != objEntry.strSteamGameId:
                strKeyText += "  (프로그램)"
            listCells = [strKeyText, objEntry.strMemo,
                         f"{objEntry.strCategoryValue} [{objEntry.strCategoryType}]", objEntry.strCategoryId]
            for nCol, strText in enumerate(listCells):
                self.tblGameMap.setItem(nRow, nCol, QTableWidgetItem(strText))
            # 화면 글자와 별개로 진짜 열쇠(exe:이름.exe)를 숨겨 둬요. (고르기 · 삭제에 써요)
            self.tblGameMap.item(nRow, 0).setData(Qt.ItemDataRole.UserRole, objEntry.strSteamGameId)
        # 짝이 바뀌었으니 '지금 게임' 표시도 새로 고쳐요. (자동 변경은 부르는 쪽에서 정해요)
        if hasattr(self, "lblManageSteamGame"):
            self._UpdateCurrentGame(bAutoSync=False)

    def OnDeleteGameMapClicked(self) -> None:
        nRow = self.tblGameMap.currentRow()
        if nRow < 0:
            return
        strGameId = self.tblGameMap.item(nRow, 0).data(Qt.ItemDataRole.UserRole)
        strName = self.tblGameMap.item(nRow, 1).text() or KeyToDisplay(strGameId)
        if QMessageBox.question(self, "확인", f"'{strName}' 짝을 삭제할까요?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.objGameMap.Remove(strGameId)
        except OSError as objError:
            self.ShowError(objError)
            return
        self._ReloadGameMapTable()
        self.strLastAutoSyncGameId = None
        self.Log(f"짝 삭제: {strName}")

    def OnOpenGameMapFileClicked(self) -> None:
        """윈도우 기본 프로그램(보통 메모장)으로 game_map.txt 를 열어요."""
        try:
            os.startfile(self.objGameMap.strPath)
        except OSError as objError:
            self.ShowError(objError)
            return
        self.Log("파일을 고쳐서 저장한 뒤 [다시 읽기] 를 눌러주세요.")

    def OnReloadGameMapClicked(self) -> None:
        listWarnings = self.objGameMap.Load()
        self._ReloadGameMapTable()
        self.strLastAutoSyncGameId = None
        for strWarning in listWarnings:
            self.Log(f"[경고] {strWarning}")
        self.Log(f"짝 목록 다시 읽음: {len(self.objGameMap.ListEntries())}개")

    def OnSendChatClicked(self) -> None:
        objClient = self._RequireChzzk()
        strMessage = self.editChat.text().strip()
        if objClient is None or not strMessage:
            return

        def _Done(strMessageId):
            self.editChat.clear()
            self.Log(f"채팅 전송: {strMessage} (id={strMessageId})")

        self.RunInBackground(lambda: objClient.SendChatMessage(strMessage), _Done)

    def OnRegisterNoticeClicked(self) -> None:
        objClient = self._RequireChzzk()
        strMessage = self.editNotice.text().strip()
        if objClient is None or not strMessage:
            return
        self.RunInBackground(
            lambda: objClient.RegisterChatNotice(strMessage=strMessage),
            lambda _: self.Log(f"공지 등록: {strMessage}"),
        )

    # ===================================================================
    # 설정 저장
    # ===================================================================

    def OnSaveSettingsClicked(self) -> None:
        strSteamId = self.editSteamId.text().strip()
        if strSteamId and not (strSteamId.isdigit() and len(strSteamId) == 17):
            QMessageBox.warning(self, "확인", "SteamID64 는 숫자 17자리여야 해요.")
            return

        dictSteam, dictChzzk = self.dictConfig["steam"], self.dictConfig["chzzk"]
        bClientChanged = (
            dictChzzk["client_id"] != self.editClientId.text().strip()
            or dictChzzk["client_secret"] != self.editClientSecret.text().strip()
        )

        dictSteam["api_key"] = self.editSteamApiKey.text().strip()
        dictSteam["steam_id"] = strSteamId
        dictChzzk["client_id"] = self.editClientId.text().strip()
        dictChzzk["client_secret"] = self.editClientSecret.text().strip()
        dictChzzk["channel_id"] = self.editChannelId.text().strip()
        dictChzzk["redirect_uri"] = self.editRedirectUri.text().strip()
        self.dictConfig["app"]["refresh_interval_sec"] = self.spinInterval.value()
        self.dictConfig["youtube"]["api_key"] = self.editYouTubeApiKey.text().strip()
        self.dictConfig["youtube"]["min_interval_sec"] = self.spinYouTubeInterval.value()
        self.dictConfig["youtube"]["default_target"] = self.editYouTubeTarget.text().strip()

        # 다른 앱(Client)으로 바꿨다면, 예전 앱으로 받은 토큰은 쓸 수 없으니 지워요.
        if bClientChanged:
            dictChzzk["access_token"] = dictChzzk["refresh_token"] = ""
            dictChzzk["token_expire_at"] = 0

        try:
            SaveConfig(self.dictConfig)
        except OSError as objError:
            QMessageBox.warning(self, "저장 실패", str(objError))
            return

        self._RebuildClients()
        self._UpdateLoginLabel()
        if self.chkAutoRefresh.isChecked():
            self.objRefreshTimer.start(self.spinInterval.value() * 1000)
        self.Log("설정 저장 완료")
        if self.bRemoteVisible:
            self.objRemotePanel.EnsureLoaded()  # 채널 ID 를 새로 넣었거나 바꿨다면 리모컨을 새로 불러와요.
        if self._HasRequiredSettings():
            self.OnRefreshClicked()

    def OnResetUrlsClicked(self) -> None:
        """입력창을 기본 주소로 채워요. (아직 저장은 안 돼요 → 'URL 저장' 을 눌러야 해요)"""
        for (strService, strKey), editUrl in self.dictUrlEdits.items():
            editUrl.setText(DICT_DEFAULT_URLS[strService][strKey])
        self.Log("URL 입력칸을 기본값으로 채웠어요. 'URL 저장' 을 눌러야 init.json 에 반영돼요.")

    def OnSaveUrlsClicked(self) -> None:
        """입력한 URL 들을 검사한 뒤 init.json 의 "urls" 칸에 저장해요."""
        dictNewUrls = {"steam": {}, "chzzk": {}, "youtube": {}}
        for (strService, strKey), editUrl in self.dictUrlEdits.items():
            # 비워둔 칸은 기본값으로 저장해요.
            strValue = editUrl.text().strip() or DICT_DEFAULT_URLS[strService][strKey]
            strLabel = DICT_URL_LABELS[strService][strKey]
            if strKey in SET_FULL_URL_KEYS and not strValue.startswith(("http://", "https://")):
                QMessageBox.warning(self, "확인", f"[{strLabel}] 는 http:// 또는 https:// 로 시작해야 해요.")
                return
            if strKey not in SET_FULL_URL_KEYS and not strValue.startswith("/"):
                QMessageBox.warning(self, "확인", f"[{strLabel}] 경로는 / 로 시작해야 해요.")
                return
            dictNewUrls[strService][strKey] = strValue

        if "{channelId}" not in dictNewUrls["chzzk"]["live_detail"]:
            QMessageBox.warning(self, "확인", "라이브 상세 경로에는 {channelId} 가 꼭 들어가야 해요.")
            return

        self.dictConfig["urls"] = dictNewUrls
        try:
            SaveConfig(self.dictConfig)
        except OSError as objError:
            QMessageBox.warning(self, "저장 실패", str(objError))
            return

        # 화면에도 실제 저장된 값을 보여줘요. (빈 칸 → 기본값)
        for (strService, strKey), editUrl in self.dictUrlEdits.items():
            editUrl.setText(dictNewUrls[strService][strKey])

        self._RebuildClients()  # 새 주소로 심부름꾼을 다시 만들어요.
        self._UpdateLoginLabel()
        self.Log(f"URL 저장 완료 → {STR_CONFIG_PATH}")

    # ===================================================================
    # 실시간 채팅창
    # ===================================================================
    def OnOpenChatWindowClicked(self) -> None:
        """방송 도우미(채팅 + 후원 · 미션)를 보여줘요. 메인 화면 가운데에 있어서 메인 창을 앞으로 가져와요."""
        self.objStreamWindow.ShowTab()

    def OnOpenDonationWindowClicked(self) -> None:
        """방송 도우미 창을 [후원 목록] 탭으로 열어요. (열면 채팅 연결도 같이 켜져요)"""
        self.objStreamWindow.ShowTab(N_TAB_DONATION)

    def OnOpenMissionWindowClicked(self) -> None:
        """방송 도우미 창을 [미션] 탭으로 열어요."""
        self.objStreamWindow.ShowTab(N_TAB_MISSION)

    def _UpdateStreamButton(self, nPending: int, nMissions: int) -> None:
        """창 제목에 후원 대기 · 미션 수를 보여줘요. (작업 표시줄에서도 보여요)"""
        listParts = ([f"대기 {nPending}"] if nPending else []) + ([f"미션 {nMissions}"] if nMissions else [])
        self.setWindowTitle(STR_APP_TITLE + (f" ({' · '.join(listParts)})" if listParts else ""))

    def closeEvent(self, objEvent) -> None:  # noqa: N802 (Qt 가 정한 이름)
        """메인 창을 닫으면 방송 도우미 창도 닫고 연결도 끊어요."""
        self.objMissionWindow.Shutdown()
        self.objYouTubeHub.Disconnect()
        self.objStreamWindow.close()
        self.objChatHub.Disconnect()
        self.objRemotePanel.Shutdown()
        self.objOverlay.Stop()
        app_log.Write("=== 프로그램 종료 ===")
        super().closeEvent(objEvent)


def RunGui() -> int:
    """창을 띄우고, 사용자가 창을 닫을 때까지 기다려요."""
    app_log.InstallExceptionHook()  # 처리되지 않은 오류도 로그 파일에 남겨요.
    objApp = QApplication(sys.argv)
    objWindow = MainWindow()
    objWindow.show()
    return objApp.exec()
