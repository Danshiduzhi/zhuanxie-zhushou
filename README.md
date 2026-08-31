# 转写助手

把视频/音频转成 **Word 三件套** 的桌面软件（Windows / macOS）：`文字记录.docx` + `总结提炼.docx` + `音频.mp3`，每视频一个文件夹，命名统一为 `日期_时间_内容`。

## 两种使用方式

**① 软件（推荐给客户）**
```
dist/转写助手/ 转写助手.exe      ← 双击即用, 无需安装任何东西
```
首次使用会自动下载转写模型（约 3GB，国内镜像，带进度；之后离线可用）。

**② 命令行（开发/批处理）**
```bash
python pipeline.py all           # 处理 01_视频/ 下所有视频
python pipeline.py md2docx x.md  # 总结 Markdown -> Word
```

## 开发模式启动

```bash
python app.py                    # 打开软件窗口 (pywebview)
python app.py --no-window        # 只启动本地服务 http://127.0.0.1:8765
```

## 功能与设置（软件设置页）

| 项 | 说明 |
|----|------|
| API Key | DeepSeek 默认（OpenAI 兼容接口）。配置后启用 AI 校对 + 总结提炼 |
| 模型档位 | auto=按电脑性能自动选（有独显→large-v3 极致准确；强CPU→large-v3；弱机→distil/medium/small） |
| 热词表 | 人名/术语每行一个，显著降低专有名词错字 |
| 说话人区分 | 需 HuggingFace Token（[S3 待实现]），标出 [A] [B] |
| 存疑标注 | 置信度低/语义不明处自动标 [存疑]，文末汇总，界面可点击试听 |

## 输出结构

```
04_文档/2026-08-22_15-30_产品评审会/
├ 2026-08-22_15-30_产品评审会_文字记录.docx   ← 时间戳+说话人+存疑标注
├ 2026-08-22_15-30_产品评审会_总结提炼.docx   ← 摘要/要点/详解/行动项/存疑问题
├ 2026-08-22_15-30_产品评审会_音频.mp3        ← 原音质导出
└ 2026-08-22_15-30_产品评审会.srt             ← 字幕(可导入播放器)
```

## 打包发布

```bash
python -m PyInstaller --noconfirm --onedir --windowed --name "转写助手" \
  --add-data "frontend;frontend" --collect-all ctranslate2 app.py
# 再把 ffmpeg.exe 复制到 dist/转写助手/
```

macOS 版：待配置 GitHub Actions 后自动构建（[S7b 押后]）。

## 费用（每 1 小时视频）

| 环节 | 费用 |
|------|------|
| 转写 + 说话人区分 | 免费（本地） |
| AI 校对（可关） | 约 0.1~0.3 元 |
| 总结提炼（可关） | 约 0.05 元 |
