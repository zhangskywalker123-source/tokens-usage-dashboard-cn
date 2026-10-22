# -*- mode: python ; coding: utf-8 -*-
# Tokens 用量看板 - 原生窗口版（tkinter，无浏览器/无 HTML）

a = Analysis(
    ['native_dashboard.py'],
    pathex=[],
    binaries=[],
    datas=[('bundle/runtime.zip', 'runtime.zip')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'test', 'unittest', 'unittest.test', 'pydoc', 'doctest', 'lib2to3',
        'idlelib', 'turtledemo', 'tkinter.test', 'sqlite3.test', 'distutils',
        'setuptools', 'pip', 'pkg_resources', 'ensurepip', 'venv',
        'pdb', 'profile', 'cProfile', 'tabnanny', 'this', 'antigravity',
        'py_compile', 'compileall', 'symtable', 'tracemalloc',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Tokens用量统计中文看板',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
