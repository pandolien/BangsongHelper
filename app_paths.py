"""
프로그램 폴더 · data 폴더 위치
==============================

설정(init.json), 게임 짝(game_map.txt), 후원 · 미션 기록은 모두 'data' 폴더에 저장해요.

- 파이썬으로 실행할 때(run.bat): 이 파일이 있는 폴더 = 프로그램 폴더
- exe 로 실행할 때(BangsongHelper.exe): exe 가 있는 폴더 = 프로그램 폴더
  (exe 안의 파일들은 실행할 때마다 바뀌는 임시 폴더에 풀려서, 거기에 저장하면 끄는 순간 사라져요!)
"""

import os
import sys

# PyInstaller 로 만든 exe 면 sys.frozen 이 True 예요.
B_FROZEN = bool(getattr(sys, "frozen", False))

STR_APP_DIR = os.path.dirname(os.path.abspath(sys.executable if B_FROZEN else __file__))
STR_DATA_DIR = os.path.join(STR_APP_DIR, "data")


def DataPath(strFileName: str) -> str:
    """data 폴더 안의 파일 경로. 예) DataPath("init.json")"""
    return os.path.join(STR_DATA_DIR, strFileName)
