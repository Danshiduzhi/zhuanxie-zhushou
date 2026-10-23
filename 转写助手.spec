# -*- mode: python ; coding: utf-8 -*-
"""转写助手 打包配置

onedir 模式: 主程序 + _internal 依赖 + 随包资源
- 前端页面通过 --add-data 打包
- ctranslate2 / faster_whisper 的 dll 与数据文件必须显式收集
- 不再打包 torch/pyannote (说话人区分已移除), 安装包体积大幅下降
"""
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_all

datas = [('frontend', 'frontend')]
binaries = []
hiddenimports = ['flask', 'psutil']
datas += collect_data_files('faster_whisper')
binaries += collect_dynamic_libs('nvidia.cublas')
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pyannote', 'torch', 'torchaudio', 'lightning', 'speechbrain',
              'torchcodec', 'scipy', 'matplotlib', 'pandas', 'notebook',
              'IPython', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='转写助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # 含 CUDA 动态库, 压缩易破坏 DLL, 关闭
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='转写助手',
)
