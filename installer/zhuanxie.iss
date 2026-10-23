; 转写助手 Windows 安装包脚本 (Inno Setup 7)
; 编译: tools\build_installer.bat  或  ISCC.exe installer\zhuanxie.iss
;
; 是否把离线模型打进安装包:
;   ISCC.exe installer\zhuanxie.iss                 -> 完整版(含模型, 约 3.3 GB)
;   ISCC.exe installer\zhuanxie_slim.iss    -> 精简版(约 1.1 GB, 首次转写时联网下载模型)

; 1 = 打包离线模型(完整版)  0 = 不打包(精简版)
; 精简版请用 installer\zhuanxie_slim.iss, ISCC 的 /D 传进来是字符串, 无法直接当整数用
#ifndef WithModels
  #define WithModels 1
#endif

#define MyAppName "转写助手"
#define MyAppVersion "2.0"
#define MyAppPublisher "旦史独支"
#define MyAppExeName "转写助手.exe"
#define AppId "{{5F3B9C21-7E4A-4C8B-9D16-2A8E6F0B7C34}"
#define DistDir "..\dist\转写助手"

#if WithModels
  #define SetupSuffix ""
#else
  #define SetupSuffix "_精简版"
#endif

[Setup]
AppId={#AppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\ZhuanXieZhuShou
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 装到用户目录, 不需要管理员权限
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=转写助手_Setup_{#MyAppVersion}{#SetupSuffix}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
; 卸载时保留用户数据(视频/文档在 %LOCALAPPDATA%\转写助手, 不随程序删除)
SetupLogging=yes

[Languages]
Name: "chs"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: checkedonce

[Components]
Name: "core"; Description: "转写助手主程序"; Types: full compact custom; Flags: fixed
#if WithModels
Name: "models"; Description: "离线识别模型 large-v3（约 2.9 GB，装完即可断网使用；不装则首次转写时联网下载）"; Types: full
#endif

[Files]
; 主程序 + 依赖 + 前端 + ffmpeg
Source: "{#DistDir}\*"; DestDir: "{app}"; Excludes: "models\*, *.pyc, __pycache__, 01_视频\*, 02_音频\*, 03_转写\*, 04_文档\*, data\*, logs\*, config.json, app.url, portable.flag"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: core
; 识别模型(可选组件)
#if WithModels
Source: "{#DistDir}\models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist; Components: models
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 只清理程序目录内的缓存, 用户工作目录在 %LOCALAPPDATA%\转写助手, 不删
Type: filesandordirs; Name: "{app}\__pycache__"
