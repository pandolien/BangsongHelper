"""
update.bat 이 쓰는 작은 도우미 (표준 라이브러리만 써요)

    python update_helper.py merge-game-map <내 예전 파일> <새로 받은 파일>

게임 짝 목록(data/game_map.txt)을 업데이트할 때, 내가 직접 만들거나 자동으로 저장된 짝을 잃지 않게 합쳐요.
- 새로 받은 파일을 바탕으로 해요. (새 게임 짝이 들어와요)
- 내 파일에만 있는 짝은 그대로 덧붙여요.
- 같은 게임 번호(열쇠)가 양쪽에 있으면 내 것을 써요. (내가 정한 게 우선이에요)
"""

import os
import sys


def _Key(strLine: str):
    """'열쇠 = ...' 줄이면 소문자 열쇠, 주석 · 빈 줄이면 None"""
    strBody = strLine.split("#", 1)[0]
    if "=" not in strBody:
        return None
    return strBody.split("=", 1)[0].strip().lower() or None


def MergeGameMap(strMinePath: str, strNewPath: str) -> None:
    with open(strMinePath, "r", encoding="utf-8-sig") as objFile:
        listMine = objFile.read().splitlines()
    with open(strNewPath, "r", encoding="utf-8-sig", newline="") as objFile:
        strNewRaw = objFile.read()
    strNewline = "\r\n" if "\r\n" in strNewRaw else "\n"
    listNew = strNewRaw.splitlines()

    dictMine = {}
    for strLine in listMine:
        strKey = _Key(strLine)
        if strKey:
            dictMine[strKey] = strLine

    listOut, setUsed = [], set()
    for strLine in listNew:
        strKey = _Key(strLine)
        if strKey and strKey in dictMine:
            listOut.append(dictMine[strKey])   # 같은 열쇠는 내 것
            setUsed.add(strKey)
        else:
            listOut.append(strLine)
    listExtra = [strLine for strKey, strLine in dictMine.items() if strKey not in setUsed]
    if listExtra:
        listOut.append("")
        listOut.append("# --- 내가 추가한 짝 (업데이트해도 남아요) ---")
        listOut.extend(listExtra)

    strTmp = strNewPath + ".tmp"
    with open(strTmp, "w", encoding="utf-8", newline="") as objFile:
        objFile.write(strNewline.join(listOut) + strNewline)
    os.replace(strTmp, strNewPath)


def main(listArgs) -> int:
    if len(listArgs) == 4 and listArgs[1] == "merge-game-map":
        try:
            MergeGameMap(listArgs[2], listArgs[3])
        except (OSError, UnicodeError) as objError:
            print(f"[update] game_map merge failed: {objError}")
            return 1
        return 0
    print("usage: update_helper.py merge-game-map <mine> <new>")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
