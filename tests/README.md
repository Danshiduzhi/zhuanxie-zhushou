# 测试

## 跑法

```bash
python tests/test_core.py                      # 纯逻辑, 不需要模型/网络
python tests/test_e2e.py 音频.wav [长音频.m4a]  # 起服务跑完整流程
```

`test_e2e.py` 会自建临时数据目录、启动服务、提交任务、校验产物与进度、再测取消，
结束后清理。默认读取 `testdata/speech.wav`。

## 准备测试音频

```powershell
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SetOutputToWaveFile("testdata\speech.wav")
$s.Speak("This is a test of the transcription assistant pipeline.")
$s.Dispose()
```

长音频用于验证"运行中取消"，随便一段 10 分钟以上的录音即可。

## 覆盖点

- `clean_label` 文件标签清洗
- 配置加密落盘与历史明文兼容
- 任务时间字段迁移、OOM 判定
- 校对时间戳对齐（不丢行）
- 分块/切分
- 显存分档与批量大小选择
- 字幕时间格式
- 端到端：产物齐全、进度单调不倒退、运行中可取消
