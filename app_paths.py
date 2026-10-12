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

# 설정 파일을 고르는 방법 (기본은 data/init.json)
#     run.bat --test              → data/init_test.json   (시험용 계정 · 키로 켜 볼 때)
#     run.bat --config 이름.json   → data/이름.json         (--config=이름.json 도 돼요)
#     환경 변수 BANGSONG_CONFIG=이름.json 도 같아요.
# 시험용 설정을 쓰면 후원 · 미션 기록 같은 파일도 따로 써요. (진짜 기록에 시험 기록이 섞이지 않게)
STR_CONFIG_ENV = "BANGSONG_CONFIG"
STR_DEFAULT_CONFIG_NAME = "init.json"
STR_TEST_CONFIG_NAME = "init_test.json"


def ConsumeConfigOption(listArgv: list) -> None:
    """실행 인자에서 설정 파일 고르는 옵션을 찾아 환경 변수로 넘기고, 인자 목록에서는 지워요.

    지워야 뒤의 명령어 해석(argparse)이나 창 프로그램이 모르는 옵션이라고 하지 않아요.
    """
    nIndex = 1
    while nIndex < len(listArgv):
        strArg = listArgv[nIndex]
        if strArg == "--test":
            os.environ[STR_CONFIG_ENV] = STR_TEST_CONFIG_NAME
            del listArgv[nIndex]
        elif strArg == "--config":
            if nIndex + 1 < len(listArgv):
                os.environ[STR_CONFIG_ENV] = listArgv[nIndex + 1]
                del listArgv[nIndex:nIndex + 2]
            else:
                del listArgv[nIndex]  # 이름이 없으면 무시해요.
        elif strArg.startswith("--config="):
            os.environ[STR_CONFIG_ENV] = strArg[len("--config="):]
            del listArgv[nIndex]
        else:
            nIndex += 1


def ConfigFileName() -> str:
    """지금 쓸 설정 파일 이름. (data 폴더 안의 파일 이름만 받아요. 폴더 경로는 버려요)"""
    strName = os.path.basename((os.environ.get(STR_CONFIG_ENV) or "").strip())
    if not strName:
        return STR_DEFAULT_CONFIG_NAME
    return strName if strName.lower().endswith(".json") else strName + ".json"


ConsumeConfigOption(sys.argv)
STR_CONFIG_NAME = ConfigFileName()
B_TEST_MODE = STR_CONFIG_NAME.lower() != STR_DEFAULT_CONFIG_NAME

# PyInstaller 로 만든 exe 면 sys.frozen 이 True 예요.
B_FROZEN = bool(getattr(sys, "frozen", False))

STR_APP_DIR = os.path.dirname(os.path.abspath(sys.executable if B_FROZEN else __file__))
STR_DATA_DIR = os.path.join(STR_APP_DIR, "data")


def DataPath(strFileName: str) -> str:
    """data 폴더 안의 파일 경로. 예) DataPath("init.json")"""
    return os.path.join(STR_DATA_DIR, strFileName)


def RecordPath(strFileName: str) -> str:
    """후원 · 미션 기록처럼 '설정(계정)마다 따로 둬야 하는' 파일 경로.

    기본 설정이면 DataPath 와 같아요.  init_test.json 이면 이름 뒤에 _test 가 붙어요.
        donations.json → donations_test.json,   mission_timer.txt → mission_timer_test.txt
    """
    if not B_TEST_MODE:
        return DataPath(strFileName)
    strStem = STR_CONFIG_NAME[:-len(".json")]
    strTag = strStem[len("init_"):] if strStem.lower().startswith("init_") else strStem
    strBase, strExt = os.path.splitext(strFileName)
    return DataPath(f"{strBase}_{strTag}{strExt}")
