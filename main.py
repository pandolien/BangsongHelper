"""
프로그램 시작점
================

    python main.py              → 창(GUI) 프로그램 실행
    python main.py status       → 창 없이 터미널(CLI)로 실행 (명령 목록: python main.py --help)
"""

import sys


def _RedirectOutputForExe() -> None:
    """창 모드 exe 는 콘솔이 없어서 sys.stdout / stderr 가 None 이에요.
    그대로 두면 오류를 출력하려다 또 오류가 나서 꺼질 수 있어요 → data/error.log 에 남겨요.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    import os
    from app_paths import STR_DATA_DIR
    try:
        os.makedirs(STR_DATA_DIR, exist_ok=True)
        objLog = open(os.path.join(STR_DATA_DIR, "error.log"), "a", encoding="utf-8", buffering=1)
    except OSError:
        objLog = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = sys.stdout or objLog
    sys.stderr = sys.stderr or objLog


def main() -> int:
    # 설정 파일 옵션(--test 등)을 먼저 꺼내요. (이걸 안 하면 아래에서 '명령어가 붙어 있다' 고 CLI 로 들어가요)
    import app_paths  # noqa: F401  (불러오는 순간 sys.argv 에서 옵션을 지워요)
    _RedirectOutputForExe()
    # 뒤에 명령어가 붙어 있으면 CLI, 아무것도 없으면 GUI 로 실행해요.
    if len(sys.argv) > 1:
        from main_cli import main as RunCli
        return RunCli()

    from gui import RunGui
    return RunGui()


if __name__ == "__main__":
    sys.exit(main())
