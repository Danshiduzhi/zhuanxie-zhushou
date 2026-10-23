@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0.."

echo [1/4] PyInstaller 打包...
python -m PyInstaller --noconfirm 转写助手.spec
if errorlevel 1 goto :fail

echo [2/4] 复制 ffmpeg...
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo    未找到 ffmpeg，跳过（运行时会用系统 PATH 里的）
) else (
    for /f "delims=" %%i in ('where ffmpeg') do (
        copy /Y "%%i" "dist\转写助手\ffmpeg.exe" >nul
        goto :copied
    )
    :copied
    echo    ffmpeg 已复制
)

echo [3/4] 准备模型目录...
if exist "models\large-v3\model.bin" (
    if not exist "dist\转写助手\models" mkdir "dist\转写助手\models"
    robocopy "models" "dist\转写助手\models" /E /NFL /NDL /NJH /NJS /NC /NS >nul
    echo    模型已复制
) else (
    echo    本地没有 models\large-v3，安装包将不含离线模型
)

echo [4/4] 生成安装包...
set "ISCC=C:\Program Files\Inno Setup 7\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
if not exist "%ISCC%" (
    echo    未找到 Inno Setup 7，请先安装 https://jrsoftware.org/isdl.php
    goto :fail
)
"%ISCC%" "installer\zhuanxie.iss"
if errorlevel 1 goto :fail

echo.
echo 完成: dist\转写助手_Setup_2.0.exe
exit /b 0

:fail
echo.
echo 构建失败，请检查上面的输出。
exit /b 1
