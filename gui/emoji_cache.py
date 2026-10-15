"""
치지직 이모티콘 그림 (채팅창에서만 보여주고 저장하지 않아요)
===========================================================

- 그림은 메모리에만 두고, 파일로는 저장하지 않아요. 프로그램을 끄면 사라져요.
- 허용된 네이버 이미지 주소(https + *.pstatic.net / *.naver.net / *.naver.com)에서만 받아요.
  (채팅에서 온 주소를 그대로 믿지 않아요)
- 한 장은 N_MAX_BYTES 이하, 보관은 N_MAX_IMAGES 장까지만. 넘치면 그냥 [이름] 글자로 보여줘요.
- 받는 동안(또는 실패하면)은 [이름] 글자로 보여요. 받고 나면 그다음 채팅부터 그림으로 나와요.
"""

import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Set

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from gui.bg_task import BackgroundTask, RunTask

N_MAX_BYTES = 300 * 1024
N_MAX_IMAGES = 300
N_MAX_FAILED = 500
N_HEIGHT = 22          # 채팅 글자 옆에 보일 그림 높이(px)
N_TIMEOUT_SEC = 5
TUPLE_ALLOWED_SUFFIXES = (".pstatic.net", ".naver.net", ".naver.com")


def IsAllowedImageUrl(strUrl: str) -> bool:
    try:
        objParsed = urllib.parse.urlparse(strUrl or "")
    except ValueError:
        return False
    strHost = (objParsed.hostname or "").lower().rstrip(".")
    return objParsed.scheme == "https" and any(strHost.endswith(strSuffix) for strSuffix in TUPLE_ALLOWED_SUFFIXES)


def _Download(strUrl: str) -> bytes:
    objRequest = urllib.request.Request(strUrl, headers={"User-Agent": "BangsongHelper"})
    with urllib.request.urlopen(objRequest, timeout=N_TIMEOUT_SEC) as objResponse:
        if not IsAllowedImageUrl(objResponse.geturl()):  # 다른 주소로 넘겨졌으면 거절
            raise ValueError("허용되지 않은 주소")
        baData = objResponse.read(N_MAX_BYTES + 1)
    if len(baData) > N_MAX_BYTES:
        raise ValueError("그림이 너무 커요")
    return baData


class EmojiCache:
    """주소 → 그림(QImage). fnOnReady(주소, 그림) 은 화면 스레드에서 불려요."""

    def __init__(self, fnOnReady: Callable[[str, QImage], None]):
        self.fnOnReady = fnOnReady
        self.dictImages: Dict[str, QImage] = {}
        self.setPending: Set[str] = set()
        self.setFailed: Set[str] = set()
        self.listWorkers: List[BackgroundTask] = []

    def Get(self, strUrl: str) -> Optional[QImage]:
        """있으면 그림, 없으면 None (그리고 받아오기를 시작해요)."""
        objImage = self.dictImages.get(strUrl)
        if objImage is not None:
            return objImage
        if (strUrl in self.setPending or strUrl in self.setFailed or not IsAllowedImageUrl(strUrl)
                or len(self.dictImages) >= N_MAX_IMAGES):
            return None
        self.setPending.add(strUrl)
        RunTask(self.listWorkers, lambda: _Download(strUrl), lambda objResult: self._Done(strUrl, objResult))
        return None

    def _Done(self, strUrl: str, objResult) -> None:
        self.setPending.discard(strUrl)
        objImage = QImage()
        if isinstance(objResult, (bytes, bytearray)) and objImage.loadFromData(objResult) and not objImage.isNull():
            if objImage.height() > N_HEIGHT:
                objImage = objImage.scaledToHeight(N_HEIGHT, Qt.TransformationMode.SmoothTransformation)
            self.dictImages[strUrl] = objImage
            self.fnOnReady(strUrl, objImage)
        elif len(self.setFailed) < N_MAX_FAILED:
            self.setFailed.add(strUrl)  # 실패한 주소는 다시 시도하지 않아요.
