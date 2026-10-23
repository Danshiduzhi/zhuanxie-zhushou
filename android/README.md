# 转写助手 · Android 版

把 `mobile/` 那套网页装进 APK 的原生壳。不依赖 Gradle / Android Studio，纯命令行构建。

## 产物

`dist/转写助手_Android_v2.0.apk`（约 250 KB）

- 包名 `com.zx.assistant`，minSdk 24（Android 7.0+），targetSdk 34
- 网页资源打进 `assets/web/`，运行时由 App 内建的本地 HTTP 服务提供

## 为什么用本地 HTTP 而不是 file://

浏览器只在**安全上下文**里允许录音（`getUserMedia` / `MediaRecorder`）。
`file://` 不算安全上下文，`http://127.0.0.1` 算。
所以 App 启动时在回环地址起一个极简静态服务，WebView 加载 `http://127.0.0.1:<随机端口>/index.html`。

## 原生能力

| 能力 | 实现 |
|---|---|
| 麦克风 | `onPermissionRequest` 直接授权 + 运行时申请 `RECORD_AUDIO` |
| 选择文件 | `onShowFileChooser` 调系统文件选择器 |
| 保存文本 | JS 桥 `ZXAndroid.saveText()` 写入「下载」目录（WebView 不支持 `<a download>`） |
| 返回键 | WebView 可回退则回退，否则退出 |

## 构建

```bash
# 依赖：JDK 17 + Android SDK（build-tools;34.0.0, platforms;android-34）
bash android/build_apk.sh
```

默认到 `F:\android-toolchain\sdk` 找 SDK，可用环境变量覆盖：

```bash
ANDROID_SDK=/path/to/sdk JAVA_HOME_DIR=/path/to/jdk bash android/build_apk.sh
```

脚本流程：`aapt2 compile` → `aapt2 link` → `javac` → `d8` → 打包 dex → `zipalign` → `apksigner`。

> 注意：aapt2 在 Windows 下无法处理含中文的路径，脚本会先把工程复制到 `F:/zx-android-build` 再构建。

## 签名

首次构建自动生成 `android/debug.keystore`（口令 `android`）。
这是**调试签名**，自己用没问题；要发给别人或上架，换成自己的正式密钥：

```bash
keytool -genkeypair -keystore release.keystore -alias zx -keyalg RSA -keysize 2048 -validity 10000
```

然后改 `build_apk.sh` 里 apksigner 的 `--ks`。

## 与 PWA 的关系

同一套网页，两种分发：

| | APK | PWA |
|---|---|---|
| 安装 | 传 APK 双击安装 | 浏览器「添加到主屏幕」 |
| 录音 | 原生权限，稳定 | iOS 需 https |
| 保存文件 | 直接写「下载」 | 走浏览器下载 |
| 更新 | 重新发 APK | 自动 |

iOS 没有对应安装包——苹果要求 macOS + Xcode 编译，网页版加到主屏即可。

## 已知限制

- 语音识别仍然调用云端 API（手机跑不动本地大模型），需在设置里填 Key
- 首次打开需要允许麦克风权限，否则只能选文件
- 录音格式由 WebView 决定（`audio/webm` 或 `audio/mp4`），主流识别接口都支持
