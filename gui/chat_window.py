"""
실시간 채팅창 (PySide6)
========================

방송 채팅을 실시간으로 보여주고, 바로 채팅을 보낼 수 있는 '따로 뜨는 창' 이에요.
게임 옆에 띄워 두기 좋게 [항상 위] 옵션도 있어요.

시청자 관리
    닉네임을 누르거나 채팅 줄을 우클릭하면 메뉴가 떠요.
    임시 제한 / 임시 제한 풀기 / 이 메시지 가리기 / 활동 제한 / 닉네임 복사
    (개발자 센터 권한: 활동제한 쓰기 · 활동제한 조회 · 채팅 메시지 쓰기)

구조
    ChzzkChatSession (뒤쪽 스레드에서 채팅을 듣는 전화기)
        ↓ 채팅이 오면
    ChatHub (공유기: 뒤쪽 스레드 → 화면 스레드로 안전하게 넘겨주고, 후원 목록 창과 연결을 나눠 써요)
        ↓
    ChatWindow (화면에 한 줄씩 그리기)
"""

import html
import re
import urllib.parse
import zlib
from collections import OrderedDict, deque
from typing import Callable, Optional

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
# (PySide6 를 먼저 부르면 socketio 가 쓰는 six 라이브러리와 충돌해서 프로그램이 꺼져요)
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox,
    QTextBrowser, QToolTip, QVBoxLayout, QWidget,
)

from chzzk import (
    RE_EMOJI_PLACEHOLDER, ChzzkChatMessage, ChzzkDonationMessage,
)
from gui.bg_task import RunTask
from gui.chat_hub import ChatHub
from gui.emoji_cache import EmojiCache, IsAllowedImageUrl, N_HEIGHT as N_EMOJI_HEIGHT
from gui.restrict_dialog import ExplainRestrictError, RestrictDialog
from gui.viewer_info_dialog import ViewerInfoDialog
from moderation_history import ModerationHistory
from youtube import N_DAILY_QUOTA, YouTubeChatMessage

N_MAX_CHAT_LINES = 500  # 이보다 많아지면 오래된 줄부터 지워요 (메모리 아끼기)
N_MAX_KEPT_MESSAGES = 1000  # 닉네임 메뉴(제한 · 가리기)에 쓰려고 기억해 두는 최근 채팅 수
N_MAX_CHATS_PER_USER = 300  # '시청자 정보' 창에 보여주려고 시청자마다 기억해 두는 최근 채팅 수
N_MAX_REMEMBERED_USERS = 3000  # 이보다 많은 시청자가 쌓이면 오래 말이 없던 시청자부터 잊어요.
STR_MSG_LINK_PREFIX = "msg:"  # 채팅 줄 링크 모양: msg:번호

# 채팅 줄은 색 자리표시를 넣어 기억해 두고, 화면에 넣을 때 지금 색으로 바꿔요.
# (색상 설정을 바꾸면 이미 보이는 채팅도 새 색으로 다시 그릴 수 있게)
STR_TEXT_COLOR_TOKEN = "@@TEXT@@"                  # 채팅 글자색
RE_NICK_COLOR_TOKEN = re.compile(r"@@NICK(#[0-9a-fA-F]{6})@@")  # 닉네임 색 (어두운 배경이면 밝게)
RE_EMOJI_TOKEN = re.compile(r"@@EMO\|([^|@]*)\|([^|@]*)@@")   # 이모티콘 자리표시 (주소 · 이름은 %인코딩)
STR_ROW_BG_TOKENS = ("@@ROWBG0@@", "@@ROWBG1@@")    # 채팅 줄 배경 (한 줄씩 번갈아 아주 연하게)
STR_DONATION_TEXT = "#1f2937"                      # 노란 후원 줄 안의 글자는 배경이 늘 밝아서 진하게 고정

# 닉네임 색깔표 (흰 바탕에서 잘 읽히는 색들). 같은 사람은 항상 같은 색이 나와요.
LIST_NICK_COLORS = [
    "#d9480f", "#c2255c", "#9c36b5", "#6741d9", "#3b5bdb", "#1971c2",
    "#0c8599", "#099268", "#2f9e44", "#66a80f", "#e67700", "#a61e4d",
]

# 역할별 작은 딱지 색
DICT_ROLE_COLORS = {
    "streamer": "#e03131",
    "streaming_channel_manager": "#1971c2",
    "streaming_chat_manager": "#0c8599",
}

# 연결 상태별 표시
DICT_STATUS_VIEW = {
    "connecting": ("#e67700", "연결 중..."),
    "connected": ("#2f9e44", "연결됨"),
    "reconnecting": ("#e67700", "다시 연결 대기"),
    "stopped": ("#868e96", "연결 안 됨"),
    "error": ("#e03131", "오류"),
}


class ChatWindow(QWidget):
    """실시간 채팅창.

    objHub      : 실시간 채팅 연결 공유기 (후원 목록 창과 같은 연결을 써요)
    fnLog       : 메인 창 로그에 남길 함수 (없어도 됨)
    """

    sigOverlaySend = Signal(str)  # OBS 독 입력칸에서 온 채팅 (다른 스레드에서 와도 화면 스레드에서 처리돼요)

    def __init__(self, objHub: ChatHub,
                 fnLog: Optional[Callable[[str], None]] = None, objParent: Optional[QWidget] = None,
                 objYouTubeHub=None, fnGetYouTubeTarget: Optional[Callable[[], str]] = None):
        super().__init__(objParent, Qt.WindowType.Window)
        self.setWindowTitle("치지직 채팅")
        self.resize(420, 640)

        self.objHub = objHub
        self.bManageHub = True  # 따로 뜨는 창이면 열려 있는 동안 채팅 연결을 붙잡아요. (방송 도우미 창 안에선 False)
        self.fnGetClient = objHub.fnGetClient
        self.fnLog = fnLog or (lambda strMessage: None)
        self.listSendWorkers = []
        # 화면에 그린 채팅을 번호로 기억해 둬요. (닉네임을 누르면 그 채팅으로 제한 · 가리기를 해요)
        self.dictMessages: "OrderedDict[int, ChzzkChatMessage]" = OrderedDict()
        self.nNextMessageKey = 0
        self.objRestrictDialog: Optional[RestrictDialog] = None

        self._BuildUi()
        self._OnStatus(self.objHub.strLastState, "")
        self.objHub.sigChat.connect(self._AppendChat)
        self.objHub.sigDonation.connect(self._AppendDonation)
        self.objHub.sigSubscriptionState.connect(self._OnSubscriptionState)
        self.objHub.sigStatus.connect(self._OnStatus)

        # 유튜브 채팅 (있으면): [YT] 로 섞어서 보여줘요. 슈퍼챗은 노란 줄로.
        self.objYouTubeHub = objYouTubeHub
        # 유튜브 방송 주소는 [설정] 에서 넣어요. 연결할 때마다 지금 저장된 주소를 읽어요.
        self.fnGetYouTubeTarget = fnGetYouTubeTarget or (lambda: "")
        self.wgtYouTubeRow.setVisible(objYouTubeHub is not None)
        if objYouTubeHub is not None:
            objYouTubeHub.sigChat.connect(self._AppendYouTubeChat)
            objYouTubeHub.sigDonation.connect(self._AppendDonation)
            objYouTubeHub.sigStatus.connect(self._OnYouTubeStatus)
            objYouTubeHub.sigQuota.connect(lambda nUsed: self._OnYouTubeStatus(objYouTubeHub.strLastState, ""))
            self._OnYouTubeStatus(objYouTubeHub.strLastState, "")

    # ===================================================================
    # 화면 만들기
    # ===================================================================
    def _BuildUi(self) -> None:
        objLayout = QVBoxLayout(self)
        objLayout.setContentsMargins(8, 8, 8, 8)

        # --- 위쪽: 상태 + 연결 버튼 ---
        objTopRow = QHBoxLayout()
        self.lblStatus = QLabel()
        self.lblStatus.setToolTip("")
        self.btnConnect = QPushButton("연결")
        self.btnConnect.clicked.connect(self.OnConnectClicked)
        objTopRow.addWidget(self.lblStatus, 1)
        objTopRow.addWidget(self.btnConnect)
        objLayout.addLayout(objTopRow)

        # 오류일 때 자세한 설명
        self.lblStatusDetail = QLabel("")
        self.lblStatusDetail.setWordWrap(True)
        self.lblStatusDetail.setStyleSheet("color: #6b7280;")
        self.lblStatusDetail.hide()
        objLayout.addWidget(self.lblStatusDetail)

        # --- 유튜브 채팅 줄 (유튜브 공식 API): [YT] 상태 · 오늘 사용량 + 연결 버튼. 주소는 [설정] 에서 ---
        self.wgtYouTubeRow = QWidget()
        objYouTubeRow = QHBoxLayout(self.wgtYouTubeRow)
        objYouTubeRow.setContentsMargins(0, 0, 0, 0)
        lblYouTubeTag = QLabel("<span style='background:#ff0000; color:#ffffff'>&nbsp;YT&nbsp;</span>")
        self.lblYouTubeStatus = QLabel("")
        self.lblYouTubeStatus.setWordWrap(True)
        self.lblYouTubeStatus.setStyleSheet("color: #6b7280;")
        self.btnYouTube = QPushButton("유튜브 연결")
        self.btnYouTube.setToolTip("[설정] 에 저장한 유튜브 방송 주소로 연결해요.")
        self.btnYouTube.clicked.connect(self.OnYouTubeConnectClicked)
        objYouTubeRow.addWidget(lblYouTubeTag)
        objYouTubeRow.addWidget(self.lblYouTubeStatus, 1)
        objYouTubeRow.addWidget(self.btnYouTube)
        objLayout.addWidget(self.wgtYouTubeRow)
        self.wgtYouTubeRow.hide()

        # --- 옵션 줄 ---
        objOptionRow = QHBoxLayout()
        self.chkOnTop = QCheckBox("항상 위")
        self.chkOnTop.toggled.connect(self.OnOnTopToggled)
        self.chkAutoScroll = QCheckBox("자동 스크롤")
        self.chkAutoScroll.setChecked(True)
        self.chkShowTime = QCheckBox("시간")
        self.chkShowTime.setChecked(True)
        self.spinFontSize = QSpinBox()
        self.spinFontSize.setRange(8, 28)
        self.spinFontSize.setValue(11)
        self.spinFontSize.setPrefix("글자 ")
        self.spinFontSize.valueChanged.connect(self.OnFontSizeChanged)
        btnClear = QPushButton("지우기")
        btnClear.clicked.connect(self.OnClearClicked)
        self.btnCopy = QPushButton("복사")
        self.btnCopy.setToolTip("채팅창에서 드래그해서 고른 글자를 복사해요.\n고른 게 없으면 지금 보이는 채팅 전체를 복사해요.")
        self.btnCopy.clicked.connect(self.OnCopyClicked)
        btnRestrictList = QPushButton("제한 목록")
        btnRestrictList.setToolTip("활동 제한한 시청자를 보고 풀어줘요.")
        btnRestrictList.clicked.connect(self.OnRestrictListClicked)
        objOptionRow.addWidget(self.chkOnTop)
        objOptionRow.addWidget(self.chkAutoScroll)
        objOptionRow.addWidget(self.chkShowTime)
        objOptionRow.addStretch()
        objOptionRow.addWidget(self.spinFontSize)
        objOptionRow.addWidget(btnRestrictList)
        objOptionRow.addWidget(self.btnCopy)
        objOptionRow.addWidget(btnClear)
        objLayout.addLayout(objOptionRow)

        # --- 채팅 보이는 곳 ---
        self.txtChat = QTextBrowser()
        self.txtChat.setOpenLinks(False)
        # 채팅 한 줄(표)이 문서 안에서 '문단 4개' 라서, 줄 수 × 4 + 여유로 잡아야 N_MAX_CHAT_LINES 줄이 남아요.
        self.txtChat.document().setMaximumBlockCount(N_MAX_CHAT_LINES * 4 + 8)
        self.txtChat.setObjectName("Chat")  # 배경 · 글자색은 gui/theme.py 에서
        self.setEmojiReady: set = set()  # 문서에 올려 둔 이모티콘 그림 주소
        self.objEmojiCache = EmojiCache(self._OnEmojiReady, self.fnLog)  # 메모리에만 보관 (파일로 저장 안 함)
        self.bRedrawPending = False
        self.dequeChatHtml = deque(maxlen=N_MAX_CHAT_LINES)  # 다시 그리기용 채팅 줄 (색 자리표시 그대로)
        self.dictUserChats: "OrderedDict[str, deque]" = OrderedDict()  # 시청자(채널 ID) → 그 시청자의 최근 채팅
        self.objHistory = ModerationHistory()  # 이 프로그램으로 한 제한 기록 (파일에 저장돼요)
        self.objViewerInfo = None
        self.strTextColor = "#1f2937"
        self.strBackgroundColor = "#ffffff"
        self.bDarkBackground = False
        self.nRowTick = 0  # 채팅 줄 배경을 번갈아 칠하려고 세는 숫자
        self.fnOverlay: Callable[[dict], None] = lambda dictEvent: None  # OBS 채팅 화면으로 보내는 곳 (메인 창이 연결)
        self.sigOverlaySend.connect(self.SendFromOverlay)
        self.txtChat.setToolTip("닉네임을 누르거나 채팅을 우클릭하면 임시 제한 · 가리기 메뉴가 떠요.")
        # 닉네임(링크)을 누르면 → 시청자 메뉴
        self.txtChat.anchorClicked.connect(self._OnChatLinkClicked)
        # 채팅 줄을 우클릭하면 → 시청자 메뉴 (빈 곳이면 기본 메뉴)
        self.txtChat.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.txtChat.customContextMenuRequested.connect(self._OnChatContextMenu)
        objLayout.addWidget(self.txtChat, 1)
        self.OnFontSizeChanged(self.spinFontSize.value())

        # --- 아래쪽: 채팅 보내기 ---
        objSendRow = QHBoxLayout()
        self.editMessage = QLineEdit()
        self.editMessage.setMaxLength(100)
        self.editMessage.setPlaceholderText("채팅 입력 후 Enter")
        self.editMessage.returnPressed.connect(self.OnSendClicked)
        self.editMessage.textChanged.connect(
            lambda strText: self.lblCount.setText(f"{len(strText)}/100"))
        self.lblCount = QLabel("0/100")
        self.lblCount.setStyleSheet("color: #6b7280;")
        self.btnSend = QPushButton("보내기")
        self.btnSend.clicked.connect(self.OnSendClicked)
        objSendRow.addWidget(self.editMessage, 1)
        objSendRow.addWidget(self.lblCount)
        objSendRow.addWidget(self.btnSend)
        objLayout.addLayout(objSendRow)

    # ===================================================================
    # 연결 / 끊기
    # ===================================================================
    def OnConnectClicked(self) -> None:
        if self.objHub.bIsRunning:
            self.objHub.Disconnect()
        else:
            self.objHub.Connect()

    def Connect(self) -> None:
        """이 창이 연결을 쓰기 시작해요. (연결이 없으면 공유기가 연결해요)"""
        if self.bManageHub:
            self.objHub.Join(self)

    def closeEvent(self, objEvent) -> None:  # noqa: N802 (Qt 가 정한 이름)
        """창을 닫으면 연결에서 빠져요. 다른 창도 닫혀 있으면 연결이 끊겨요. (보이지 않는 연결이 남지 않게)"""
        if self.bManageHub:
            self.objHub.Leave(self)
        super().closeEvent(objEvent)

    def _OnStatus(self, strState: str, strMessage: str) -> None:
        strColor, strText = DICT_STATUS_VIEW.get(strState, ("#868e96", strState))
        self.lblStatus.setText(f"<span style='color:{strColor}; font-size:14px'>●</span> <b>{strText}</b>")
        bRunning = strState in ("connecting", "connected", "reconnecting")
        self.btnConnect.setText("연결 끊기" if bRunning else "연결")

        # 오류/재연결 설명은 아래 줄에 보여주고, 메인 창 로그에도 남겨요.
        bShowDetail = strState in ("error", "reconnecting") and bool(strMessage)
        self.lblStatusDetail.setText(strMessage)
        self.lblStatusDetail.setVisible(bShowDetail)
        if strState == "error":
            self.lblStatusDetail.setStyleSheet("color: #e03131;")
        else:
            self.lblStatusDetail.setStyleSheet("color: #6b7280;")
        if strMessage:
            self.fnLog(f"[채팅] {strMessage}")
        if strState == "connected" and strMessage:
            self._AppendSystem(strMessage)

    # ===================================================================
    # 화면에 한 줄씩 그리기
    # ===================================================================
    def _TimeHtml(self, objTime) -> str:
        if not self.chkShowTime.isChecked():
            return ""
        return f"<span style='color:#9ca3af; font-size:9pt'>{objTime.strftime('%H:%M')}</span>&nbsp; "

    def _OnEmojiReady(self, strUrl: str, objImage) -> None:
        """이모티콘 그림을 다 받았어요 → 채팅창 문서에 올려 둬요. (이후 채팅부터 그림으로 나와요)"""
        self.txtChat.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(strUrl), objImage)
        self.setEmojiReady.add(strUrl)
        if not self.bRedrawPending:  # 이미 보이는 채팅의 [이름] 도 그림으로 바꿔요. (여러 장이 한꺼번에 오면 한 번만)
            self.bRedrawPending = True
            QTimer.singleShot(300, self._Redraw)

    def _ReloadEmojiResources(self) -> None:
        """채팅창을 비우면(clear) 문서에 올려 둔 그림도 같이 지워져서, 받아 둔 이모티콘 그림을 다시 올려 둬요."""
        for strUrl, objImage in self.objEmojiCache.dictImages.items():
            self.txtChat.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(strUrl), objImage)

    def _Redraw(self) -> None:
        """저장해 둔 채팅 줄을 지금 상태(색 · 이모티콘 그림)로 처음부터 다시 그려요. 스크롤 위치는 지켜요."""
        self.bRedrawPending = False
        objScrollBar = self.txtChat.verticalScrollBar()
        bAtBottom = objScrollBar.value() >= objScrollBar.maximum() - 4
        nValue = objScrollBar.value()
        self.txtChat.clear()
        self._ReloadEmojiResources()
        for strHtml in self.dequeChatHtml:
            self.txtChat.append(self._RenderHtml(strHtml))
        if bAtBottom:
            self.txtChat.moveCursor(QTextCursor.MoveOperation.End)
        else:
            objScrollBar.setValue(nValue)

    def _ContentHtml(self, strContent: str, dictEmojis: Optional[dict] = None) -> str:
        """글자를 안전하게 바꾸고(HTML 특수문자 처리), 이모티콘은 그림으로(아직 못 받았으면 회색 [이름] 으로) 보여줘요."""
        dictEmojis = dictEmojis or {}
        listParts = []
        nLast = 0
        for objMatch in RE_EMOJI_PLACEHOLDER.finditer(strContent):
            listParts.append(html.escape(strContent[nLast:objMatch.start()]))
            strName = objMatch.group(1)
            strUrl = dictEmojis.get(strName)
            if isinstance(strUrl, str):
                self.objEmojiCache.Get(strUrl)  # 아직 없으면 받아 오기 시작 (허용 안 된 주소는 로그에 도메인만 남겨요)
            if isinstance(strUrl, str) and IsAllowedImageUrl(strUrl):
                # 그림은 화면에 넣는 순간에 정해요 (_RenderHtml). 늦게 받아도 이미 쓴 줄이 나중에 그림으로 바뀌어요.
                listParts.append(f"@@EMO|{urllib.parse.quote(strUrl, safe='')}|{urllib.parse.quote(strName, safe='')}@@")
            else:
                listParts.append(f"<span style='color:#9ca3af'>[{html.escape(strName)}]</span>")
            nLast = objMatch.end()
        listParts.append(html.escape(strContent[nLast:]))
        return "".join(listParts)

    @staticmethod
    def _OverlayParts(strContent: str, dictEmojis: Optional[dict]) -> list:
        """OBS 화면용 내용: [["t", 글자], ["e", 그림 주소, 이름], ...] (허용된 주소의 그림만 그림으로)"""
        dictEmojis = dictEmojis or {}
        strContent = strContent or ""
        listParts = []
        nLast = 0
        for objMatch in RE_EMOJI_PLACEHOLDER.finditer(strContent):
            if objMatch.start() > nLast:
                listParts.append(["t", strContent[nLast:objMatch.start()]])
            strUrl = dictEmojis.get(objMatch.group(1))
            if isinstance(strUrl, str) and IsAllowedImageUrl(strUrl):
                listParts.append(["e", strUrl, objMatch.group(1)])
            else:
                listParts.append(["t", f"[{objMatch.group(1)}]"])
            nLast = objMatch.end()
        if nLast < len(strContent):
            listParts.append(["t", strContent[nLast:]])
        return listParts

    def _SendOverlay(self, dictEvent: dict) -> None:
        try:
            self.fnOverlay(dictEvent)
        except Exception:  # OBS 화면에 문제가 있어도 채팅창은 계속 돼요.
            pass

    def _OverlayNickColor(self, strKey: str) -> str:
        """OBS 화면은 어두운 바탕 위에 올라가는 일이 많아서 닉네임 색을 밝게 보내요."""
        return QColor(self._NickColor(strKey)).lighter(150).name()

    def _Row(self, strInner: str, strBarColor: str) -> str:
        """채팅 한 줄: 왼쪽에 색 띠(닉네임 색) + 연한 바탕을 번갈아 칠한 칸. 줄 사이가 또렷하게 보여요."""
        self.nRowTick += 1
        strBg = STR_ROW_BG_TOKENS[self.nRowTick % 2]
        return (f"<table width='100%' cellspacing='0' cellpadding='0' style='background:{strBg}'><tr>"
                f"<td width='4' bgcolor='{strBarColor}'></td>"
                f"<td style='padding:5px 8px 5px 8px'>{strInner}</td></tr></table>")

    @staticmethod
    def _NickColor(strKey: str) -> str:
        return LIST_NICK_COLORS[zlib.crc32(strKey.encode("utf-8")) % len(LIST_NICK_COLORS)]

    def _AppendChat(self, objMessage: ChzzkChatMessage) -> None:
        strRole = ""
        if objMessage.strRoleName:
            strRoleColor = DICT_ROLE_COLORS.get(objMessage.strUserRole, "#495057")
            strRole = (f"<span style='background:{strRoleColor}; color:#ffffff'>&nbsp;{objMessage.strRoleName}&nbsp;</span> ")
        strNickColor = self._NickColor(objMessage.strSenderChannelId or objMessage.strNickname)
        # 닉네임과 내용을 링크로 감싸요 → 누르거나 우클릭하면 이 채팅으로 시청자 메뉴가 떠요.
        strLink = f"{STR_MSG_LINK_PREFIX}{self._RememberMessage(objMessage)}"
        strInner = (f"{self._TimeHtml(objMessage.dtTime)}{strRole}"
                    f"<a href='{strLink}' style='text-decoration:none'>"
                    f"<b style='color:@@NICK{strNickColor}@@'>{html.escape(objMessage.strNickname)}</b></a>"
                    f"<br><a href='{strLink}' style='text-decoration:none'><span style='color:{STR_TEXT_COLOR_TOKEN}'>"
                    f"{self._ContentHtml(objMessage.strContent, objMessage.dictEmojis)}</span></a>")
        self._AppendHtml(self._Row(strInner, f"@@NICK{strNickColor}@@"))
        self._SendOverlay({
            "type": "chat", "time": objMessage.dtTime.strftime("%H:%M"), "nick": objMessage.strNickname,
            "color": self._OverlayNickColor(objMessage.strSenderChannelId or objMessage.strNickname),
            "role": objMessage.strRoleName or "",
            "roleColor": DICT_ROLE_COLORS.get(objMessage.strUserRole, "#495057"),
            "parts": self._OverlayParts(objMessage.strContent, objMessage.dictEmojis)})

    def _RememberUserChat(self, objMessage: ChzzkChatMessage) -> None:
        """시청자별 채팅을 모아 둬요. ('시청자 정보' 창용. 프로그램을 끄면 사라져요)"""
        strId = objMessage.strSenderChannelId
        if not strId:
            return
        dequeUser = self.dictUserChats.pop(strId, None)
        if dequeUser is None:
            dequeUser = deque(maxlen=N_MAX_CHATS_PER_USER)
        dequeUser.append((objMessage.dtTime, objMessage.strPlainContent))
        self.dictUserChats[strId] = dequeUser  # 맨 뒤 = 가장 최근에 말한 시청자
        while len(self.dictUserChats) > N_MAX_REMEMBERED_USERS:
            self.dictUserChats.popitem(last=False)

    def ShowViewerInfo(self, objMessage: ChzzkChatMessage) -> None:
        """이 시청자의 정보 창을 열어요. (받은 채팅 · 이 프로그램으로 한 제한 · 치지직에서 확인한 상태)"""
        strId = objMessage.strSenderChannelId
        dlgInfo = ViewerInfoDialog(
            objMessage.strNickname, strId, objMessage.strRoleName,
            list(self.dictUserChats.get(strId, [])), self.objHistory.ListFor(strId), self.fnGetClient, self)
        dlgInfo.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlgInfo.setWindowFlag(Qt.WindowType.Window, True)
        dlgInfo.show()
        self.objViewerInfo = dlgInfo  # (시험 · 확인용으로 마지막 창을 붙잡아 둬요)

    def _RememberMessage(self, objMessage: ChzzkChatMessage) -> int:
        nKey = self.nNextMessageKey
        self.nNextMessageKey += 1
        self.dictMessages[nKey] = objMessage
        self._RememberUserChat(objMessage)
        while len(self.dictMessages) > N_MAX_KEPT_MESSAGES:
            self.dictMessages.popitem(last=False)  # 오래된 것부터 잊어요.
        return nKey

    # ===================================================================
    # 유튜브 채팅
    # ===================================================================
    def OnYouTubeConnectClicked(self) -> None:
        if self.objYouTubeHub is None:
            return
        if self.objYouTubeHub.bIsRunning:
            self.objYouTubeHub.Disconnect()
            return
        self.objYouTubeHub.Connect(self.fnGetYouTubeTarget().strip())

    def _OnYouTubeStatus(self, strState: str, strMessage: str) -> None:
        dictView = {"connecting": ("#e67700", "연결 중..."), "connected": ("#2f9e44", "연결됨"),
                    "reconnecting": ("#e67700", "다시 시도 대기"), "stopped": ("#868e96", "연결 안 됨"), "error": ("#e03131", "오류")}
        strColor, strText = dictView.get(strState, ("#868e96", strState))
        # 오류로 끊기면 바로 '연결 안 됨' 이 와요 → 왜 끊겼는지(마지막 오류)를 계속 보여줘요.
        if strState == "error" and strMessage:
            self.strYouTubeLastError = strMessage
        elif strState in ("connecting", "connected"):
            self.strYouTubeLastError = ""
        strDetail = strMessage if strState in ("error", "reconnecting") and strMessage else             (getattr(self, "strYouTubeLastError", "") if strState in ("stopped", "error") else "")
        nUsed = self.objYouTubeHub.nQuotaUsed if self.objYouTubeHub is not None else 0
        strQuota = f" · 오늘 사용량 약 {nUsed:,} / {N_DAILY_QUOTA:,}"
        self.lblYouTubeStatus.setText(f"<span style='color:{strColor}'>● {strText}</span>{strQuota}"
                                      + (f"<br><span style='color:#e03131'>{html.escape(strDetail)}</span>" if strDetail else ""))
        bRunning = strState in ("connecting", "connected", "reconnecting")
        self.btnYouTube.setText("유튜브 끊기" if bRunning else "유튜브 연결")
        if strMessage:
            self.fnLog(f"[유튜브] {strMessage}")
        if strState == "connected" and strMessage:
            self._AppendSystem(strMessage)

    def _AppendYouTubeChat(self, objMessage: YouTubeChatMessage) -> None:
        strRole = ""
        if objMessage.strRoleName:
            strRoleColor = {"주인": "#e03131", "모더": "#1971c2", "멤버": "#2f9e44"}.get(objMessage.strRoleName, "#495057")
            strRole = f"<span style='background:{strRoleColor}; color:#ffffff'>&nbsp;{objMessage.strRoleName}&nbsp;</span> "
        strNickColor = self._NickColor("yt:" + (objMessage.strAuthorChannelId or objMessage.strNickname))
        strInner = (f"{self._TimeHtml(objMessage.dtTime)}"
                    f"<span style='background:#ff0000; color:#ffffff'>&nbsp;YT&nbsp;</span> {strRole}"
                    f"<b style='color:@@NICK{strNickColor}@@'>{html.escape(objMessage.strNickname)}</b>"
                    f"<br><span style='color:{STR_TEXT_COLOR_TOKEN}'>{html.escape(objMessage.strText)}</span>")
        self._AppendHtml(self._Row(strInner, "#ff0000"))
        self._SendOverlay({
            "type": "youtube", "time": objMessage.dtTime.strftime("%H:%M"), "nick": objMessage.strNickname,
            "color": self._OverlayNickColor("yt:" + (objMessage.strAuthorChannelId or objMessage.strNickname)),
            "role": objMessage.strRoleName or "", "roleColor": "#495057",
            "parts": [["t", objMessage.strText or ""]]})

    def _AppendDonation(self, objDonation: ChzzkDonationMessage) -> None:
        strKind = {"VIDEO": "영상 후원", "MISSION": "미션 후원", "YOUTUBE": "[YT] 슈퍼챗",
                   "SUBSCRIPTION": "구독"}.get(objDonation.strDonationType, "후원")
        strText = self._ContentHtml(objDonation.strText, objDonation.dictEmojis) if objDonation.strText else ""
        strHtml = (f"<table width='100%' cellspacing='0' cellpadding='0' style='background:#fff3bf'><tr>"
                   f"<td width='6' bgcolor='#f08c00'></td>"
                   f"<td style='padding:7px 10px 7px 10px; color:{STR_DONATION_TEXT}'>"
                   f"{self._TimeHtml(objDonation.dtTime)}"
                   f"<b style='color:#d9480f; font-size:12pt'>{strKind}"
                   f"{'' if objDonation.strDonationType == 'SUBSCRIPTION' else ' ' + self._AmountText(objDonation)}</b> "
                   f"<b style='color:{STR_DONATION_TEXT}'>{html.escape(objDonation.strNickname)}</b>"
                   f"{'<br>' + strText if strText else ''}</td></tr></table>")
        self._AppendHtml(strHtml)
        self._SendOverlay({
            "type": "donation", "kind": strKind, "nick": objDonation.strNickname,
            "amount": "" if objDonation.strDonationType == "SUBSCRIPTION" else self._AmountText(objDonation),
            "parts": self._OverlayParts(objDonation.strText or "", objDonation.dictEmojis)})
        strLogText = (objDonation.strText or "").replace("\n", " ")
        strLogAmount = "" if objDonation.strDonationType == "SUBSCRIPTION" else self._AmountText(objDonation) + " "
        self.fnLog(f"[{'구독' if objDonation.strDonationType == 'SUBSCRIPTION' else '후원'}] {strKind} {strLogAmount}"
                   f"{objDonation.strNickname}" + (f" — {strLogText[:80]}" if strLogText else ""))

    def _OnSubscriptionState(self, objOk, strReason: str) -> None:
        """구독 알림 신청이 거절됐으면 한 번 알려요. (채팅 · 후원은 그대로 와요)"""
        if objOk is False:
            self._AppendSystem(f"구독 알림을 받을 수 없어요: {strReason}")
            self.fnLog(f"[구독] 구독 알림을 받을 수 없어요: {strReason}")

    @staticmethod
    def _AmountText(objDonation: ChzzkDonationMessage) -> str:
        """금액 글자: 원화면 '10,000원', 유튜브 외화 슈퍼챗이면 '$5.00' 처럼 원래 금액"""
        strRawAmount = (objDonation.dictRaw or {}).get("amount", "")
        if objDonation.nPayAmount == 0 and strRawAmount:
            return strRawAmount
        return f"{objDonation.nPayAmount:,}원"

    def _AppendSystem(self, strMessage: str) -> None:
        self._AppendHtml(f"<div align='center' style='color:#9ca3af; font-size:9pt; margin:4px 0'>"
                         f"— {html.escape(strMessage)} —</div>")

    def _EmojiHtml(self, objMatch) -> str:
        strUrl = urllib.parse.unquote(objMatch.group(1))
        strName = urllib.parse.unquote(objMatch.group(2))
        if strUrl in self.setEmojiReady:
            return (f"<img src='{html.escape(strUrl, quote=True)}' height='{N_EMOJI_HEIGHT}' "
                    f"alt='{html.escape(strName, quote=True)}'>")
        return f"<span style='color:#9ca3af'>[{html.escape(strName)}]</span>"

    def _RenderHtml(self, strHtml: str) -> str:
        """색 자리표시 → 지금 색. 어두운 배경이면 닉네임 색을 밝게 해서 잘 보이게 해요."""
        strHtml = RE_EMOJI_TOKEN.sub(self._EmojiHtml, strHtml)
        strHtml = strHtml.replace(STR_TEXT_COLOR_TOKEN, self.strTextColor)
        strTint = QColor(self.strBackgroundColor)
        strTintMix = QColor(self.strTextColor)
        for nIndex, strToken in enumerate(STR_ROW_BG_TOKENS):  # 바탕에 글자색을 아주 조금(0 / 6%) 섞어요.
            nRatio = 0.06 * nIndex
            strHtml = strHtml.replace(strToken, QColor(
                round(strTint.red() * (1 - nRatio) + strTintMix.red() * nRatio),
                round(strTint.green() * (1 - nRatio) + strTintMix.green() * nRatio),
                round(strTint.blue() * (1 - nRatio) + strTintMix.blue() * nRatio)).name())
        if self.bDarkBackground:
            return RE_NICK_COLOR_TOKEN.sub(lambda objMatch: QColor(objMatch.group(1)).lighter(150).name(), strHtml)
        return RE_NICK_COLOR_TOKEN.sub(lambda objMatch: objMatch.group(1), strHtml)

    def SetColors(self, strBackground: str, strText: str) -> None:
        """색상 설정이 바뀌면 불려요. 이미 보이는 채팅도 새 색으로 다시 그려요."""
        self.strTextColor = strText
        self.strBackgroundColor = strBackground
        objBackground = QColor(strBackground)
        self.bDarkBackground = (0.299 * objBackground.red() + 0.587 * objBackground.green()
                                + 0.114 * objBackground.blue()) < 128
        self._Redraw()

    def OnClearClicked(self) -> None:
        self.dequeChatHtml.clear()
        self.txtChat.clear()
        self._ReloadEmojiResources()

    def _AppendHtml(self, strHtml: str) -> None:
        objScrollBar = self.txtChat.verticalScrollBar()
        # 사용자가 위로 올려서 예전 채팅을 보는 중이면, 아래로 끌어내리지 않아요.
        bAtBottom = objScrollBar.value() >= objScrollBar.maximum() - 4
        self.dequeChatHtml.append(strHtml)
        self.txtChat.append(self._RenderHtml(strHtml))
        if self.chkAutoScroll.isChecked() and bAtBottom:
            self.txtChat.moveCursor(QTextCursor.MoveOperation.End)
            objScrollBar.setValue(objScrollBar.maximum())

    # ===================================================================
    # 옵션
    # ===================================================================
    def OnOnTopToggled(self, bChecked: bool) -> None:
        # 방송 도우미 창 안에 들어가 있으면 그 창 전체를 '항상 위' 로 해요.
        objWindow = self.window()
        objWindow.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bChecked)
        objWindow.show()  # 창 옵션을 바꾸면 다시 보여줘야 적용돼요.

    def OnFontSizeChanged(self, nSize: int) -> None:
        objFont = QFont(self.txtChat.font())
        objFont.setPointSize(nSize)
        self.txtChat.setFont(objFont)

    # ===================================================================
    # 채팅 보내기
    # ===================================================================
    def SendFromOverlay(self, strMessage: str) -> None:
        """OBS 독 입력칸에서 온 채팅을 보내요. (결과는 채팅창 · OBS 화면에 안내로 나와요)"""
        strMessage = (strMessage or "").strip()
        if not strMessage:
            return
        objClient = self.fnGetClient()
        if objClient is None or not objClient.bIsLoggedIn:
            self._SendOverlay({"type": "system", "text": "치지직 로그인이 필요해요"})
            self._OnStatus("error", "치지직 로그인이 필요해요.")
            return
        self.fnLog(f"[채팅] OBS 입력칸에서 보냄: {strMessage[:100]}")

        def _Done(objResult):
            if isinstance(objResult, Exception):
                self._AppendHtml(f"<span style='color:#e03131'>보내기 실패: {html.escape(str(objResult))}</span>")
                self._SendOverlay({"type": "system", "text": f"보내기 실패: {objResult}"})
                return
            if not self.objHub.bIsRunning:
                self._AppendSystem(f"보냄: {strMessage}  (채팅창이 연결돼 있지 않아 목록엔 안 보여요)")

        RunTask(self.listSendWorkers, lambda: objClient.SendChatMessage(strMessage), _Done)

    def OnSendClicked(self) -> None:
        strMessage = self.editMessage.text().strip()
        if not strMessage:
            return
        objClient = self.fnGetClient()
        if objClient is None or not objClient.bIsLoggedIn:
            self._OnStatus("error", "치지직 로그인이 필요해요.")
            return

        self.btnSend.setEnabled(False)

        def _Done(objResult):
            self.btnSend.setEnabled(True)
            if isinstance(objResult, Exception):
                self._AppendHtml(f"<span style='color:#e03131'>보내기 실패: {html.escape(str(objResult))}</span>")
                return
            # 보낸 채팅은 연결돼 있으면 채팅 목록으로 다시 들어오니까 여기서 따로 그리지 않아요.
            self.editMessage.clear()
            if not self.objHub.bIsRunning:
                self._AppendSystem(f"보냄: {strMessage}  (채팅창이 연결돼 있지 않아 목록엔 안 보여요)")

        RunTask(self.listSendWorkers, lambda: objClient.SendChatMessage(strMessage), _Done)

    # ===================================================================
    # 시청자 관리 (임시 제한 · 활동 제한 · 메시지 가리기)
    # ===================================================================
    def _MessageFromLink(self, strLink: str) -> Optional[ChzzkChatMessage]:
        if not strLink.startswith(STR_MSG_LINK_PREFIX):
            return None
        try:
            return self.dictMessages.get(int(strLink[len(STR_MSG_LINK_PREFIX):]))
        except ValueError:
            return None

    def _OnChatLinkClicked(self, objUrl: QUrl) -> None:
        objMessage = self._MessageFromLink(objUrl.toString())
        if objMessage is not None:
            self._ShowUserMenu(objMessage, QCursor.pos())

    def _OnChatContextMenu(self, objPos: QPoint) -> None:
        objMessage = self._MessageFromLink(self.txtChat.anchorAt(objPos))
        if objMessage is not None:
            self._ShowUserMenu(objMessage, self.txtChat.viewport().mapToGlobal(objPos))
        else:  # 채팅 줄이 아닌 곳 → 복사 같은 기본 메뉴
            self.txtChat.createStandardContextMenu().exec(self.txtChat.viewport().mapToGlobal(objPos))

    def _ShowUserMenu(self, objMessage: ChzzkChatMessage, objGlobalPos: QPoint) -> None:
        strNick = objMessage.strNickname
        objMenu = QMenu(self)
        objTitle = objMenu.addAction(f"{strNick}" + (f"  ({objMessage.strRoleName})" if objMessage.strRoleName else ""))
        objTitle.setEnabled(False)
        objMenu.addAction("이 시청자 정보 보기...").triggered.connect(lambda: self.ShowViewerInfo(objMessage))
        objMenu.addSeparator()

        if objMessage.strUserRole == "streamer":
            objMenu.addAction("스트리머 본인이에요").setEnabled(False)
        else:
            bHasChatChannel = bool(objMessage.strChatChannelId)
            actTemp = objMenu.addAction("임시 제한 (30초부터, 할수록 길어져요)")
            actTempRelease = objMenu.addAction("임시 제한 풀기")
            objMenu.addSeparator()
            actBlind = objMenu.addAction("이 메시지 가리기")
            objMenu.addSeparator()
            actRestrict = objMenu.addAction("활동 제한 (풀 때까지)...")
            for actItem in (actTemp, actTempRelease, actBlind):
                actItem.setEnabled(bHasChatChannel)  # 채팅 채널 ID 가 없으면 못 해요.
            actTemp.triggered.connect(lambda: self._RunModeration(
                lambda objClient: objClient.TemporaryRestrict(objMessage.strSenderChannelId, objMessage.strChatChannelId),
                f"{strNick} 님을 임시 제한했어요", (objMessage, "임시 제한", "")))
            actTempRelease.triggered.connect(lambda: self._RunModeration(
                lambda objClient: objClient.ReleaseTemporaryRestrict(objMessage.strSenderChannelId, objMessage.strChatChannelId),
                f"{strNick} 님의 임시 제한을 풀었어요", (objMessage, "임시 제한 풀기", "")))
            actBlind.triggered.connect(lambda: self._RunModeration(
                lambda objClient: objClient.BlindChatMessage(objMessage.strChatChannelId, objMessage.nMessageTime,
                                                             objMessage.strSenderChannelId),
                f"{strNick} 님의 메시지를 가렸어요", (objMessage, "메시지 가리기", objMessage.strPlainContent)))
            actRestrict.triggered.connect(lambda: self._ConfirmRestrict(objMessage))

        objMenu.addSeparator()
        strContent = objMessage.strPlainContent
        objMenu.addAction("채팅 내용 복사").triggered.connect(lambda: self._CopyText(strContent, objGlobalPos))
        objMenu.addAction("닉네임 + 채팅 복사").triggered.connect(
            lambda: self._CopyText(f"{strNick}: {strContent}", objGlobalPos))
        objMenu.addAction("닉네임 복사").triggered.connect(lambda: self._CopyText(strNick, objGlobalPos))
        objMenu.exec(objGlobalPos)

    def _CopyText(self, strText: str, objGlobalPos: Optional[QPoint] = None, strDone: str = "복사했어요") -> None:
        """클립보드에 복사하고, 마우스 옆에 잠깐 알려줘요."""
        QApplication.clipboard().setText(strText)
        QToolTip.showText(objGlobalPos or QCursor.pos(), strDone, self)

    def OnCopyClicked(self) -> None:
        """[복사]: 채팅창에서 드래그해서 고른 글자가 있으면 그것만, 없으면 지금 보이는 채팅 전체를 복사해요."""
        objCursor = self.txtChat.textCursor()
        bSelected = objCursor.hasSelection()
        strText = objCursor.selectedText() if bSelected else self.txtChat.toPlainText()
        # 줄바꿈 글자(문단 구분 U+2029)와 글자 사이 빈칸(&nbsp;)을 보통 글자로 바꿔요.
        strText = strText.replace("\u2029", "\n").replace("\u2028", "\n").replace("\xa0", " ").replace("\ufffc", "[이모티콘]")
        # 표(채팅 줄 모양)를 통째로 고르면 Qt 가 칸 경계를 알리는 보이지 않는 표시(U+FDD0~FDEF)를 섞어 넣어서 빼요.
        strText = "".join(ch for ch in strText if not "\ufdd0" <= ch <= "\ufdef")
        # \ucc44\ud305 \uc904 \ubaa8\uc591(\ud45c) \ub54c\ubb38\uc5d0 \uc0dd\uae30\ub294 \ube48 \uc904\uc740 \ube7c\uace0, \uc904 \uc55e \u00b7 \ub4a4 \ube48\uce78\ub3c4 \uc815\ub9ac\ud574\uc694.
        strText = "\n".join(strLine.strip() for strLine in strText.splitlines() if strLine.strip())
        if not strText:
            QToolTip.showText(QCursor.pos(), "복사할 채팅이 없어요", self)
            return
        nLines = len(strText.splitlines())
        self._CopyText(strText, strDone=f"{'고른 글자' if bSelected else '채팅 전체'} {nLines}줄을 복사했어요")

    def _ConfirmRestrict(self, objMessage: ChzzkChatMessage) -> None:
        strNick = objMessage.strNickname
        strQuestion = (f"{strNick} 님을 활동 제한할까요?\n\n"
                       "풀어줄 때까지 채팅을 못 해요. ([제한 목록] 에서 풀 수 있어요)")
        if QMessageBox.question(self, "활동 제한", strQuestion) != QMessageBox.StandardButton.Yes:
            return
        self._RunModeration(lambda objClient: objClient.AddRestriction(objMessage.strSenderChannelId),
                            f"{strNick} 님을 활동 제한했어요", (objMessage, "활동 제한", ""))

    def _RunModeration(self, fnAction: Callable, strDoneText: str, tupleRecord: Optional[tuple] = None) -> None:
        """제한 · 가리기 요청을 뒤에서 보내고, 결과를 채팅창과 메인 로그에 남겨요.

        tupleRecord: (채팅, 한 일 이름, 내용) — 성공하면 '이 프로그램으로 한 제한 기록' 에 남겨요.
        """
        objClient = self.fnGetClient()
        if objClient is None or not objClient.bIsLoggedIn:
            self._OnStatus("error", "치지직 로그인이 필요해요.")
            return

        def _Done(objResult):
            if isinstance(objResult, Exception):
                strError = ExplainRestrictError(objResult)
                self._AppendHtml(f"<span style='color:#e03131'>실패: {html.escape(strError)}</span>")
                self.fnLog(f"[제한] 실패: {strError}")
                return
            self._AppendSystem(strDoneText)
            self.fnLog(f"[제한] {strDoneText}")
            if tupleRecord:
                objTarget, strAction, strDetail = tupleRecord
                self.objHistory.Add(objTarget.strSenderChannelId, objTarget.strNickname, strAction, strDetail)

        RunTask(self.listSendWorkers, lambda: fnAction(objClient), _Done)

    def OnRestrictListClicked(self) -> None:
        if self.objRestrictDialog is None:
            self.objRestrictDialog = RestrictDialog(
                self.fnGetClient, fnLog=self.fnLog, objParent=self,
                fnRecord=lambda strChannelId, strNickname, strAction: self.objHistory.Add(strChannelId, strNickname, strAction))
        else:
            self.objRestrictDialog.Reload()
        self.objRestrictDialog.show()
        self.objRestrictDialog.raise_()
        self.objRestrictDialog.activateWindow()

    # 테스트/미리보기용: 시간 없이 바로 여러 줄 넣기
    def DebugAppend(self, objMessage) -> None:
        if isinstance(objMessage, ChzzkDonationMessage):
            self._AppendDonation(objMessage)
        else:
            self._AppendChat(objMessage)

