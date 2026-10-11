"""
뒤에서 일하는 '일꾼' (채팅창 · 제한 목록 창이 같이 써요)
=========================================================

인터넷 요청은 몇 초씩 걸릴 수 있어서, 화면 스레드에서 하면 창이 멈춰요.
그래서 일꾼에게 맡기고, 끝나면 신호로 결과(또는 에러)를 받아요.
"""

from typing import Callable, List

# [중요] socketio 는 반드시 PySide6 보다 "먼저" 불러와야 해요.
import socketio  # noqa: F401  (순서 맞추기용)
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _BackgroundTaskSignals(QObject):
    sigDone = Signal(object)


class BackgroundTask(QRunnable):
    """fnTask 를 뒤에서 실행하고, 결과(실패하면 에러 객체)를 sigDone 으로 알려요."""

    def __init__(self, fnTask: Callable):
        super().__init__()
        self.fnTask = fnTask
        self.objSignals = _BackgroundTaskSignals()
        self.setAutoDelete(False)

    def run(self):
        try:
            objResult = self.fnTask()
        except Exception as objError:
            objResult = objError
        try:
            self.objSignals.sigDone.emit(objResult)
        except RuntimeError:  # 창이 이미 닫혔으면 무시
            pass


def RunTask(listHolder: List[BackgroundTask], fnTask: Callable, fnDone: Callable[[object], None]) -> None:
    """일꾼에게 맡겨요. fnDone(결과 또는 에러) 는 화면 스레드에서 불려요.
    listHolder: 일하는 도중 일꾼이 사라지지 않게 붙잡아 두는 목록 (창마다 하나)
    """
    objTask = BackgroundTask(fnTask)
    listHolder.append(objTask)

    def _Done(objResult):
        if objTask in listHolder:
            listHolder.remove(objTask)
        fnDone(objResult)

    objTask.objSignals.sigDone.connect(_Done)
    QThreadPool.globalInstance().start(objTask)
