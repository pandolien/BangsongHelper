"""
치지직 리모컨 패널 (메인 화면 오른쪽)
=====================================

치지직 스튜디오의 리모컨 화면(studio.chzzk.naver.com/채널ID/remotecontrol)을 프로그램 안에 띄워요.

- 이건 공식 API 가 아니라 '웹 화면을 그대로 보여주는 것' 이에요. 화면 안의 버튼은 사람이 눌러요.
  (프로그램이 그 화면을 대신 조작하지는 않아요)
- 네이버 로그인이 필요해요. 한 번 로그인하면 로그인 정보(쿠키)가 저장돼서 다음부터는 자동으로 로그인돼요.
  로그인 정보는 프로그램 폴더가 아니라 내 계정의 AppData 에 저장해요.
  → 프로그램 폴더를 압축해서 보내거나 깃허브에 올려도 로그인 정보는 같이 가지 않아요.
  (아이디 · 비밀번호는 저장하지 않아요)
- 안전하게: 네이버(*.naver.com) 주소만 이 안에서 열고, 다른 주소로 가는 링크는 기본 브라우저로 보내요.
  파일 내려받기 · 카메라 · 마이크 · 위치 같은 요청은 모두 거절해요.
- 웹 화면은 처음 보일 때 만들어요. (안 쓰면 메모리를 안 써요)
"""

import os
import re
import webbrowser
from typing import Callable, Optional

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import QUrl, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedLayout, QVBoxLayout, QWidget

try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    B_WEBENGINE = True
except ImportError:  # 웹 화면 부품이 없는 환경이어도 프로그램은 켜져요.
    B_WEBENGINE = False

RE_CHANNEL_ID = re.compile(r"^[0-9a-f]{32}$")
STR_REMOTE_URL = "https://studio.chzzk.naver.com/{channelId}/remotecontrol"
STR_PROFILE_NAME = "BangsongHelper"


def RemoteUrl(strChannelId: str) -> str:
    """채널 ID 로 리모컨 주소를 만들어요. 채널 ID 가 형식에 안 맞으면 ""  (설정이 변조돼도 이상한 주소가 안 만들어져요)"""
    strChannelId = (strChannelId or "").strip().lower()
    return STR_REMOTE_URL.format(channelId=strChannelId) if RE_CHANNEL_ID.match(strChannelId) else ""


def IsAllowedHost(strHost: str) -> bool:
    """naver.com 과 그 아래 주소(studio.chzzk.naver.com, nid.naver.com ...)만 허용해요.
    'naver.com.evil.com' 이나 'evilnaver.com' 같은 비슷한 주소는 허용하지 않아요."""
    strHost = (strHost or "").lower().rstrip(".")
    return strHost == "naver.com" or strHost.endswith(".naver.com")


def ProfileDir() -> str:
    """로그인 정보를 저장할 폴더. 프로그램 폴더 밖(내 계정의 AppData)이에요."""
    strBase = os.environ.get("BANGSONG_WEB_PROFILE_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BangsongHelper")
    return os.path.join(strBase, "web_profile")


if B_WEBENGINE:
    class _NaverPage(QWebEnginePage):
        """네이버 주소만 이 창 안에서 열어요."""

        def __init__(self, objProfile, objParent=None, fnOpenInside: Optional[Callable[[QUrl], None]] = None):
            super().__init__(objProfile, objParent)
            self.fnOpenInside = fnOpenInside
            if hasattr(self, "permissionRequested"):          # Qt 6.8 이상
                self.permissionRequested.connect(lambda objPermission: objPermission.deny())
            elif hasattr(self, "featurePermissionRequested"):  # 그 이전
                self.featurePermissionRequested.connect(
                    lambda objUrl, nFeature: self.setFeaturePermission(
                        objUrl, nFeature, QWebEnginePage.PermissionPolicy.PermissionDeniedByUser))

        def acceptNavigationRequest(self, objUrl, nType, bIsMainFrame):  # noqa: N802 (Qt 가 정한 이름)
            if not bIsMainFrame:
                return True  # 화면 안의 그림 · 스크립트 · 내장 화면은 페이지가 알아서 불러요.
            if objUrl.scheme() == "https" and IsAllowedHost(objUrl.host()):
                return True
            if nType == QWebEnginePage.NavigationType.NavigationTypeLinkClicked and objUrl.scheme() in ("http", "https"):
                webbrowser.open(objUrl.toString())  # 다른 사이트는 기본 브라우저로 열어요.
            return False

        def createWindow(self, nType):  # noqa: N802 (Qt 가 정한 이름)
            """새 창으로 열라는 링크: 새 창을 만들지 않고, 네이버면 이 창에서 / 아니면 기본 브라우저로 열어요."""
            objProxy = _PopupProxy(self.profile(), self)
            objProxy.fnDecide = self._DecidePopup
            return objProxy

        def _DecidePopup(self, objUrl: QUrl) -> None:
            if objUrl.scheme() == "https" and IsAllowedHost(objUrl.host()):
                if self.fnOpenInside:
                    self.fnOpenInside(objUrl)
            elif objUrl.scheme() in ("http", "https"):
                webbrowser.open(objUrl.toString())

    class _PopupProxy(QWebEnginePage):
        """새 창 요청이 어디로 가는지만 알아내서 넘겨주는 껍데기."""
        fnDecide: Optional[Callable[[QUrl], None]] = None

        def acceptNavigationRequest(self, objUrl, nType, bIsMainFrame):  # noqa: N802
            if self.fnDecide:
                self.fnDecide(objUrl)
            return False


class RemotePanel(QWidget):
    sigHideRequested = Signal()  # 패널 위쪽 [✕] 를 눌렀어요.

    def __init__(self, fnGetChannelId: Callable[[], str], objParent: Optional[QWidget] = None):
        super().__init__(objParent)
        self.fnGetChannelId = fnGetChannelId
        self.objView = None
        self.objProfile = None
        self.objPage = None
        self.strLoadedUrl = ""

        objLayout = QVBoxLayout(self)
        objLayout.setContentsMargins(4, 0, 0, 0)

        # --- 위쪽 줄 ---
        objTop = QHBoxLayout()
        lblTitle = QLabel("치지직 리모컨")
        lblTitle.setObjectName("ColumnTitle")
        objTop.addWidget(lblTitle, 1)
        for strText, strTip, fnClick in (
                ("새로고침", "화면을 다시 불러와요.", self.Reload),
                ("브라우저", "기본 브라우저로 열어요.", self.OpenInBrowser),
                ("로그아웃", "이 패널에 저장된 네이버 로그인 정보를 지워요.", self.ClearLogin),
                ("✕", "패널을 숨겨요. ([보기] 메뉴에서 다시 켤 수 있어요)", self.sigHideRequested.emit)):
            btnItem = QPushButton(strText)
            btnItem.setToolTip(strTip)
            btnItem.clicked.connect(lambda _=False, fn=fnClick: fn())
            objTop.addWidget(btnItem)
            if strText == "✕":
                btnItem.setFixedWidth(34)
        objLayout.addLayout(objTop)

        # --- 아래: 안내 글 / 웹 화면 (둘 중 하나만 보여요) ---
        self.lblMessage = QLabel()
        self.lblMessage.setWordWrap(True)
        self.lblMessage.setObjectName("Help")
        self.lblMessage.setMargin(12)
        self.wgtStack = QWidget()
        self.objStack = QStackedLayout(self.wgtStack)
        self.objStack.addWidget(self.lblMessage)
        objLayout.addWidget(self.wgtStack, 1)

    # -------------------------------------------------------------------
    def CurrentUrl(self) -> str:
        return RemoteUrl(self.fnGetChannelId())

    def _ShowMessage(self, strText: str) -> None:
        self.lblMessage.setText(strText)
        self.objStack.setCurrentWidget(self.lblMessage)

    def _EnsureView(self) -> bool:
        """웹 화면을 처음 쓸 때 만들어요. 못 만들면 False."""
        if self.objView is not None:
            return True
        if not B_WEBENGINE:
            return False
        try:
            strDir = ProfileDir()
            os.makedirs(strDir, exist_ok=True)
            self.objProfile = QWebEngineProfile(STR_PROFILE_NAME, self)
            self.objProfile.setPersistentStoragePath(strDir)
            self.objProfile.setCachePath(os.path.join(strDir, "cache"))
            self.objProfile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
            self.objProfile.downloadRequested.connect(lambda objDownload: objDownload.cancel())  # 내려받기 거절
            self.objPage = _NaverPage(self.objProfile, self, fnOpenInside=lambda objUrl: self.objView.load(objUrl))
            objSettings = self.objPage.settings()
            objSettings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
            objSettings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
            self.objView = QWebEngineView(self)
            self.objView.setPage(self.objPage)
            self.objStack.addWidget(self.objView)
            return True
        except Exception:  # 웹 화면이 안 만들어져도 프로그램은 계속 돼요.
            self.objView = None
            return False

    def EnsureLoaded(self) -> None:
        """보이게 되면 불러요. 채널 ID 가 바뀌었으면 새 주소로 다시 불러요."""
        strUrl = self.CurrentUrl()
        if not (self.fnGetChannelId() or "").strip():
            self._ShowMessage("[설정] → 키 · ID · 서버 주소 에서 <b>채널 ID</b> 를 넣고 저장하면 여기에 리모컨이 나와요.")
            return
        if not strUrl:
            self._ShowMessage("채널 ID 형식이 맞지 않아요. (영문 소문자 · 숫자 32자리)<br>[설정] 에서 다시 확인해 주세요.")
            return
        if not self._EnsureView():
            self._ShowMessage("이 환경에서는 웹 화면을 띄울 수 없어요.<br>위의 <b>[브라우저]</b> 로 열어 주세요.")
            return
        self.objStack.setCurrentWidget(self.objView)
        if strUrl != self.strLoadedUrl:
            self.strLoadedUrl = strUrl
            self.objView.load(QUrl(strUrl))

    def Reload(self) -> None:
        strUrl = self.CurrentUrl()
        if strUrl and self.objView is not None:
            self.strLoadedUrl = strUrl
            self.objView.load(QUrl(strUrl))
        else:
            self.EnsureLoaded()

    def OpenInBrowser(self) -> None:
        strUrl = self.CurrentUrl()
        if strUrl:
            webbrowser.open(strUrl)
        else:
            self.EnsureLoaded()  # 안내 글을 보여줘요.

    def ClearLogin(self) -> None:
        """이 패널에 저장된 로그인 정보(쿠키 · 캐시)를 지워요."""
        if self.objProfile is not None:
            self.objProfile.cookieStore().deleteAllCookies()
            self.objProfile.clearHttpCache()
        self.strLoadedUrl = ""  # 다음에 다시 불러오게
        if self.objView is not None and self.CurrentUrl():
            self.Reload()

    def Shutdown(self) -> None:
        """창을 닫을 때: 웹 화면 → 페이지 → 프로필 순서로 정리해요. (순서가 틀리면 종료할 때 경고가 나요)"""
        if self.objView is not None:
            self.objView.setPage(None)
            self.objView.deleteLater()
            self.objView = None
        if self.objPage is not None:
            self.objPage.deleteLater()
            self.objPage = None
        if self.objProfile is not None:
            self.objProfile.deleteLater()
            self.objProfile = None
