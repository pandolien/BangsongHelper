"""
치지직 로그인(계정 연동) 도우미
================================

왜 필요한가요?
    방송 제목을 바꾸거나 채팅을 보내려면 '방송하는 본인' 의 허락이 필요해요.
    허락받는 순서는 이래요:

    1) 브라우저로 치지직 '권한 허락 페이지' 를 열어요.
    2) 사용자가 [동의] 버튼을 누르면, 치지직이 우리가 정해둔 주소
       (예: http://localhost:8080/callback) 로 '임시 쿠폰(code)' 을 보내줘요.
    3) 이 파일이 내 컴퓨터에 아주 작은 '우편함(웹 서버)' 을 잠깐 열어두고 그 쿠폰을 받아요.
    4) 받은 쿠폰을 치지직에 내밀면 '본인 출입증(Access Token)' 으로 바꿔줘요.

주의: 치지직 개발자 센터의 "로그인 리디렉션 URL" 에 똑같은 주소를 등록해 둬야 해요!
"""

import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .chzzk_api import ChzzkApiClient, ChzzkApiError, ChzzkTokenInfo

STR_DEFAULT_REDIRECT_URI = "http://localhost:8080/callback"
F_DEFAULT_LOGIN_TIMEOUT_SEC = 180.0

STR_SUCCESS_HTML = (
    "<html><head><meta charset='utf-8'></head><body style='font-family:sans-serif;text-align:center;padding-top:60px'>"
    "<h2>치지직 계정 연동 완료!</h2><p>이 창은 닫아도 괜찮아요.</p></body></html>"
)
STR_FAIL_HTML = (
    "<html><head><meta charset='utf-8'></head><body style='font-family:sans-serif;text-align:center;padding-top:60px'>"
    "<h2>연동 실패</h2><p>{strReason}</p></body></html>"
)


class _CallbackHandler(BaseHTTPRequestHandler):
    """우편함에 편지(브라우저 요청)가 도착하면 실행되는 '우체부' 예요."""

    # 서버 쪽에서 채워 넣어주는 값들 (클래스 변수로 공유)
    strExpectedPath = "/callback"
    dictResult: dict = {}
    objDoneEvent: threading.Event = threading.Event()

    def do_GET(self):  # noqa: N802 (http.server 가 정한 이름이라 바꿀 수 없어요)
        objUrl = urlparse(self.path)
        if objUrl.path != self.strExpectedPath:
            self.send_response(404)
            self.end_headers()
            return

        dictQuery = parse_qs(objUrl.query)
        strCode = (dictQuery.get("code") or [""])[0]
        strState = (dictQuery.get("state") or [""])[0]

        if strCode:
            self.dictResult["strCode"] = strCode
            self.dictResult["strState"] = strState
            strHtml = STR_SUCCESS_HTML
        else:
            strHtml = STR_FAIL_HTML.format(strReason="code 값이 오지 않았어요. 동의를 취소했나요?")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(strHtml.encode("utf-8"))
        self.objDoneEvent.set()  # "편지 받았어요!" 하고 알리기

    def log_message(self, strFormat, *args):  # noqa: N802
        """서버가 콘솔에 지저분한 기록을 남기지 않도록 조용히 시켜요."""
        return


def LoginWithBrowser(
    objClient: ChzzkApiClient,
    strRedirectUri: str = STR_DEFAULT_REDIRECT_URI,
    fTimeoutSec: float = F_DEFAULT_LOGIN_TIMEOUT_SEC,
    bOpenBrowser: bool = True,
) -> ChzzkTokenInfo:
    """브라우저 로그인 → 쿠폰 받기 → 출입증 교환 까지 한 번에 해줘요.

    성공하면 objClient 안에도 토큰이 저장되고, ChzzkTokenInfo 를 돌려줘요.
    """

    objRedirect = urlparse(strRedirectUri)
    if objRedirect.hostname not in ("localhost", "127.0.0.1"):
        raise ChzzkApiError("자동 로그인은 localhost 리디렉션 주소에서만 쓸 수 있어요.")
    nPort = objRedirect.port or 80

    # state = '이 응답이 진짜 내가 보낸 요청에 대한 답장인지' 확인하는 비밀 암호표예요. (CSRF 방지)
    strState = secrets.token_urlsafe(16)

    # 우체부에게 정보 전달 (매 로그인마다 새로 초기화)
    _CallbackHandler.strExpectedPath = objRedirect.path or "/"
    _CallbackHandler.dictResult = {}
    _CallbackHandler.objDoneEvent = threading.Event()

    try:
        objServer = HTTPServer((objRedirect.hostname, nPort), _CallbackHandler)
    except OSError as objError:
        raise ChzzkApiError(f"{nPort}번 포트를 열 수 없어요. 다른 프로그램이 쓰고 있나요? ({objError})") from objError

    objThread = threading.Thread(target=objServer.serve_forever, daemon=True)
    objThread.start()

    try:
        strAuthorizeUrl = objClient.BuildAuthorizeUrl(strRedirectUri, strState)
        if bOpenBrowser:
            webbrowser.open(strAuthorizeUrl)
        else:
            print(f"아래 주소를 브라우저에서 열어 주세요:\n{strAuthorizeUrl}")

        # 사용자가 동의할 때까지 기다려요 (최대 fTimeoutSec 초)
        if not _CallbackHandler.objDoneEvent.wait(fTimeoutSec):
            raise ChzzkApiError(f"{int(fTimeoutSec)}초 안에 로그인이 끝나지 않았어요.")
    finally:
        objServer.shutdown()
        objServer.server_close()

    dictResult = _CallbackHandler.dictResult
    strCode: Optional[str] = dictResult.get("strCode")
    if not strCode:
        raise ChzzkApiError("로그인이 취소되었거나 code 를 받지 못했어요.")
    if dictResult.get("strState") != strState:
        raise ChzzkApiError("state 값이 달라요! 보안을 위해 로그인을 중단했어요.")

    return objClient.IssueToken(strCode, strState)
