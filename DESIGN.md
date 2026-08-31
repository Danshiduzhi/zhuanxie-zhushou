# 转写助手 设计文档 v1.0

> 桌面软件（Windows + macOS），在客户电脑上运行，不依赖服务器。
> 优先级：**识别准确 > 使用简单 > 节省费用**。
> 每视频三件套输出：`文字记录.docx` + `总结提炼.docx` + `音频.mp3`，同命名前缀、同文件夹。

## 1. 技术栈

| 层 | 选型 | 理由 |
|----|------|------|
| 窗口 | pywebview（原生窗口内嵌网页） | 网页级美观 + 真软件观感，无浏览器依赖 |
| 后端 | Python 3.12 + Flask | 简单、好维护，复用现有 pipeline.py |
| 前端 | 原生 HTML/CSS/JS（无构建工具） | 开发者可轻松改 UI |
| 转写 | faster-whisper（CTranslate2） | 本地运行，零 token，多平台 |
| 说话人区分 | pyannote.audio 3.1 | 开源最强，商用免费（见许可说明） |
| Word | python-docx | 已用熟 |
| 音视频 | ffmpeg（随包分发） | 提取音频/导出 mp3 |
| 打包 | PyInstaller + GitHub Actions | Windows 本地打，macOS 用 CI 双架构打 |

## 2. 识别准确率（核心，token 不设限）

**第 1 层 本地转写**
- 默认 large-v3（最强中文识别）；档位：large-v3 / distil-large-v3 / medium / small
- 首次启动硬件自检（GPU/内存/CPU）自动推荐档位，设置页可改
- 支持用户自定义**热词表**（人名/术语），转写时通过 initial_prompt + hotwords 注入，显著降低专有名词错字

**第 2 层 AI 校对（LLM，可开关）**
- 转写稿送入 LLM 一次：修正同音错字、补标点、理顺断句、统一人名术语
- 同时输出"语义疑问点"（指代不明/疑似听错/术语不确定）
- 约 0.1~0.3 元/小时视频（DeepSeek）

**第 3 层 说话人区分**
- pyannote 3.1 本地跑，与转写片段按时间重叠分配说话人标签 `[A]`、`[B]`
- 会议/访谈场景可读性大幅提升；弱机自动提示关闭
- 需开发者配置一次 HuggingFace token（见 §7）

**存疑双来源汇总**：ASR 低置信度 + LLM 疑问点 → 文档末尾"存疑与待确认"清单，界面可点击试听对应音频段。

## 3. 输出（每视频一个文件夹）

```
04_文档/2026-08-22_15-30_产品评审会/
├ 2026-08-22_15-30_产品评审会_文字记录.docx   ← 说话人标签 + 时间戳 + 存疑标注
├ 2026-08-22_15-30_产品评审会_总结提炼.docx   ← 摘要/要点/详解/行动项/存疑问题
└ 2026-08-22_15-30_产品评审会_音频.mp3        ← 从原视频直接导出的 mp3（原音质，约10MB/小时）
```

## 4. 软件结构

```
app.py               入口：启动 Flask + pywebview 窗口
backend/
  server.py          Flask API（任务/设置/进度/试听）
  tasks.py           任务队列 + 状态持久化（data/tasks.json，断点续跑）
  pipeline.py        编排：extract → transcribe → diarize → proofread → docgen
  engine.py          转写引擎（档位选择/热词/进度回调）
  diarize.py         pyannote 封装（说话人映射）
  proofread.py       LLM 校对（DeepSeek/OpenAI 兼容）
  docgen.py          Word 生成（三件套）
  naming.py          命名规范（日期_时间_内容）
frontend/
  index.html / style.css / app.js   单页界面
config.json          设置（API Key/模型/热词/命名/输出目录）
data/tasks.json      任务历史
```

## 5. 界面（三页 + 深浅主题）

- **任务页**：拖拽批量导入 → 卡片式队列（状态/进度条/说话人开关）→ 完成显示三件套 + 一键打开文件夹 + 存疑清单（点击试听）
- **设置页**：API 提供商（DeepSeek 默认/OpenAI 兼容）、Key、模型档位、热词表、命名规则、输出目录、说话人区分开关
- **历史页**：已完成任务列表，可重新打开结果、重跑

## 6. 打包与分发

- **Windows**：PyInstaller 单文件夹 exe（内置 ffmpeg），双击即用
- **macOS**：GitHub Actions matrix 分别构建 **arm64（Apple Silicon）+ x86_64（Intel）** 两个版本（universal2 依赖不兼容风险高，故分两包）；未签名应用首次需"右键 → 打开"
- 模型首次下载走 hf-mirror（国内可用），带进度条 + 断点续传
- 后续版本更新：同一 CI 自动出三个安装包

## 7. 需要开发者准备（开工前）

1. **HuggingFace 账号**：接受 `pyannote/speaker-diarization-3.1` 和 `pyannote/segmentation-3.0` 两个模型授权（免费），提供 Access Token 填入设置。⚠️ 商用前请核对模型卡条款（部分版本要求署名）；若需完全无限制商用，备用方案为 SpeechBrain / NeMo（Apache 2.0）
2. **GitHub 账号**：用于 macOS 版 CI 构建（免费额度足够）；没有的话需借一台 Mac 本地构建
3. **DeepSeek API Key**：AI 校对 + 总结（可选，无 Key 时软件照常出记录和音频）
4. **1~2 个真实视频**：验证准确率和校对效果

## 8. 开发计划（会话 = 半天）

| 会话 | 内容 |
|------|------|
| S1 | 转写引擎升级：档位选择 + 硬件自检 + 热词（改造现有 pipeline.py） |
| S2 | AI 校对 + 存疑升级（用真实视频调优提示词） |
| S3 | 说话人区分：pyannote 集成 + 说话人→转写段映射 |
| S4 | 后端：Flask API + 任务队列 + 配置 + 历史续跑 |
| S5 | 前端界面：任务页/设置页/历史页/主题/试听 |
| S6 | 三件套输出 + 字幕导出 .srt + 完成通知 |
| S7 | Windows 打包 + macOS CI 构建 + 使用说明 |

**估算：7~9 个会话（约 3.5~4.5 天），开发消耗约 80~130 万 token**（大头是调试和界面迭代；AI 校对提示词会先用真实视频调准再固化，减少返工）。

## 9. 费用（客户运行时，每 1 小时视频）

| 环节 | 费用 |
|------|------|
| 转写 + 说话人区分 | 免费（本地） |
| AI 校对（可关） | 约 0.1~0.3 元 |
| 总结（可关） | 约 0.05 元 |
