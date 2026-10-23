# 手机端（PWA）说明

## 这是什么

一个纯前端网页应用，装到手机主屏后跟 App 一样用：

- 录音 / 选择音视频 → 直接调用**你自己的**语音识别 API → 得到文字
- 可选接 DeepSeek 做「智能校对 + 总结」
- 不需要服务器、不需要自建后端，Key 只存在手机本地

iOS（Safari）、Android（Chrome）、macOS 都能装。

## 怎么装到手机

PWA 需要 HTTPS 或 localhost。三种办法：

### 方案 A：GitHub Pages（推荐，免费）

1. 在 GitHub 新建仓库（例如 `zhuanxie-mobile`）
2. 把本文件夹 `mobile/` 里的文件推到仓库根目录
3. 仓库 Settings → Pages → Source 选 `main` 分支根目录 → 保存
4. 等 1 分钟，得到 `https://<用户名>.github.io/zhuanxie-mobile/`

手机打开这个网址：

- **iPhone**：Safari → 分享按钮 → 「添加到主屏幕」
- **Android**：Chrome → ⋮ → 「安装应用」/「添加到主屏幕」

### 方案 B：本机临时调试

```bash
cd mobile
python -m http.server 8900
```

手机连同一 WiFi，浏览器打开 `http://电脑IP:8900`。
（http 下不能装 PWA，只能当网页用；录音功能需要 https 或 localhost）

### 方案 C：打成 APK / iOS App

- Android：用 Capacitor 包一层 WebView（Windows 上装 JDK + Android SDK 即可编 APK）
- iOS：必须 macOS + Xcode，或 GitHub Actions 的 macOS runner + Apple 开发者账号（$99/年）

## 配置

左上角齿轮 → 填语音识别服务：

| 服务商 | 接口地址 | 模型 |
|---|---|---|
| 硅基流动 | `https://api.siliconflow.cn/v1` | `FunAudioLLM/SenseVoiceSmall` |
| OpenAI | `https://api.openai.com/v1` | `whisper-1` |
| 自定义 | 任何 OpenAI 兼容的 `/audio/transcriptions` 接口 | 按服务商填 |

AI 整理（可选）：填 DeepSeek 的 Key，模型 `deepseek-chat`。

> Key 保存在浏览器 localStorage，不会发往除你指定 API 以外的任何地方。

## 与电脑版的关系

| | 电脑版 | 手机版 |
|---|---|---|
| 识别 | 本地 large-v3，免费、离线、最准 | 云端 API，按量计费 |
| 输出 | Word / 字幕 / 音频 四件套 | 纯文本（可复制、保存、分享） |
| 适合 | 长视频、批量、隐私内容 | 随手录音、采访速记、外出场景 |

电脑版能力（本地模型、Word 生成）在手机浏览器里跑不动，所以手机端走 API 路线。

## 已知限制

- iOS Safari 录音需授予麦克风权限；页面必须 https
- 长录音（>30 分钟）上传耗流量，建议在 WiFi 下用
- PWA 无法「打开文件位置」，保存后去「文件」App（iOS）或「下载」目录（Android）查看
