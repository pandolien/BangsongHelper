# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 설정 파일 — build_exe.bat 이 이걸로 exe 를 만들어요.
# 결과: dist\BangsongHelper\BangsongHelper.exe (+ _internal 폴더, data 폴더)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # 실시간 채팅(Socket.IO 2.x)이 쓰는 웹소켓 라이브러리 — 코드 안에서 늦게 불러와서 직접 알려줘요.
    hiddenimports=['websocket', 'engineio.client', 'socketio.client'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc', 'test'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BangsongHelper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX 압축은 백신 오진이 잦아서 안 써요.
    console=False,      # 창 프로그램 (검은 콘솔 창 없음). 오류는 data\error.log 에 남아요.
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BangsongHelper',
)
