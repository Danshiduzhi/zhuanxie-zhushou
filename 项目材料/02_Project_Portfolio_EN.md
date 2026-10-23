# Transcription Assistant — Independent Software Project

**Role:** Solo developer — product definition, full implementation, testing, release
**Timeline:** August – October 2026 (~2 months, part-time)
**Stack:** Python 3.12, Flask, faster-whisper / CTranslate2, python-docx, ffmpeg, PyInstaller, Inno Setup, vanilla JavaScript, PWA
**Codebase:** 4,261 lines across 19 files
**Status:** Windows installer released; mobile PWA live; software copyright filed in China

---

## The Problem

I work with a lot of recorded material — online lectures, interviews, meeting recordings. Every existing option had a problem:

- **Web transcription services** charge by the minute, and uploading private content to a third party is a privacy risk.
- **Built-in transcription in editing apps** locks you into one ecosystem and exports rigid formats.
- **Open-source Whisper** is excellent but requires Python, dependencies, and command-line fluency — unusable for anyone outside engineering.

My goal: a tool a non-technical person can double-click, that runs fully offline, costs nothing, and outputs documents ready to hand to a client.

Three product principles, in priority order: **accuracy > ease of use > cost**.

---

## What I Built

### Desktop application (Windows)

Drop in a video, get back a ready-to-deliver document set.

- **Fully offline transcription** — Whisper large-v3 (2.9 GB) bundled with the app. No network required after install.
- **Hardware-aware model selection** — detects GPU, RAM, and core count, then picks the best model tier automatically. Weak machines get a smaller model rather than failing.
- **Custom vocabulary** — user-supplied names and technical terms are injected into the recognizer, substantially reducing errors on proper nouns.
- **AI proofreading** — chunked LLM pass correcting homophone errors, restoring punctuation, and normalizing terminology. Optional.
- **Automatic summarization** — abstract, key points, detailed breakdown, action items.
- **Uncertainty flagging** — low-confidence segments are marked `[uncertain]`, listed at the end of the document, and can be clicked to replay the exact audio moment for human review.
- **Standardized output** — per video: transcript `.docx`, summary `.docx`, audio `.mp3`, subtitles `.srt`.
- **Task queue** — batch import, resumable after crash, retry on failure, cancel mid-run.
- **Privacy switch** — optionally delete source video and audio once transcription finishes, keeping only documents.

### Mobile (PWA)

Phones cannot run a 2.9 GB model, so I took a different route: record or pick a file, send it directly to the user's own speech-to-text API, get text back. Works on iOS and Android; add to home screen and it behaves like a native app.

---

## Architecture

```
┌─────────────────────────────────────┐
│ Frontend — vanilla HTML/CSS/JS       │
│ tasks · history · settings · support │
└──────────────┬──────────────────────┘
               │ local HTTP with one-time token
┌──────────────▼──────────────────────┐
│ Flask service layer                  │
│ tasks · settings · upload · preview  │
├─────────────────────────────────────┤
│ Scheduler — single-thread queue      │
│ persisted state · resume · cancel    │
├─────────────────────────────────────┤
│ Capability layer                     │
│ engine.py     audio extraction, ASR  │
│ proofread.py  chunked correction     │
│ docgen.py     Word / SRT generation  │
│ config.py     settings + key crypto  │
│ paths.py      app dir vs data dir    │
└─────────────────────────────────────┘
```

**Key technical decisions**

| Layer | Choice | Reasoning |
|---|---|---|
| Window | pywebview + WebView2 | Web-quality UI inside a real native window, no browser dependency |
| Backend | Python + Flask | Richest ecosystem for the speech pipeline |
| ASR | faster-whisper (CTranslate2) | ~4× faster than reference Whisper; viable on CPU |
| Documents | python-docx | Precise control over Word styles, page numbers, tables |
| Packaging | PyInstaller + Inno Setup | Zero-configuration installer for end users |
| Mobile | Vanilla JS + PWA | One codebase for iOS and Android, no app-store review |

---

## Hard Problems I Solved

These mattered more than the feature list.

### 1. The LLM silently swallowed half of a long transcript

**Symptom:** a 47-minute interview, sent for AI proofreading, came back visibly shorter — the second half had vanished.

**Cause:** the model's output has a hard token ceiling (~8k). Worse, it "helpfully" merged adjacent sentences, breaking line correspondence.

**Fix:** *chunked proofreading* — split at 4,000-character boundaries — plus *timestamp-anchored merging*. Each line is matched by its `[MM:SS]` anchor; any line missing from the corrected output falls back to the original. Result: not a single line lost, and a failed chunk degrades to raw text instead of aborting the job.

### 2. CUDA libraries would not survive packaging

**Symptom:** worked in development, failed immediately after PyInstaller packaging — `cublas64_12.dll` not found.

**Cause:** NVIDIA runtime libraries live outside Python's default search path and must be registered *before* CTranslate2 is imported.

**Fix:** at import time, scan `nvidia/*/bin`, register each directory with both `os.add_dll_directory()` and `PATH`, handling both the source layout and PyInstaller's unpacked layout.

### 3. User data inflated the program directory to 9 GB

**Symptom:** first release grew to 9 GB, and installing under `C:\Program Files` crashed immediately from write-permission errors.

**Cause:** I had conflated "application directory" with "data directory."

**Fix:** split into a read-only application directory (frontend, models, ffmpeg) and a writable data directory under `%LOCALAPPDATA%`. Added a compatibility migration so existing users' data is left in place rather than disappearing.

### 4. API keys sat in plaintext on disk

**Problem:** send the installed folder to a friend, and your LLM API key goes with it.

**Fix:** encrypt secrets with Windows DPAPI, scoped to the current user account. On another machine the blob simply fails to decrypt; the app treats it as "not configured" instead of crashing.

### 5. Summarization exceeded the context window

**Problem:** a three-hour recording produces a transcript far larger than any model's context.

**Fix:** two-stage map-reduce — extract key points per segment, then merge into a structured summary. Short transcripts take a direct path so no extra call is wasted.

### 6. Cancelling a running task did nothing

**Problem:** the UI had a cancel button that had no effect once a job started, because the queue only checked the cancel flag when picking up work.

**Fix:** pushed cancellation checks into the progress callback and the ffmpeg subprocess wait loop, killing the child process on cancel.

---

## Results

| Metric | Value |
|---|---|
| Real-world validation | 47-minute interview processed end to end |
| Output completeness | 4 artifacts per video (2 Word docs + audio + subtitles) |
| Installer | 3.3 GB including the offline model; no admin rights required |
| Dependencies for users | None — no Python, no ffmpeg, no runtime installs |
| Software copyright | Filed with China Copyright Protection Center, application no. 2026R11L3085396 |

---

## What I Learned

- **Product trade-offs are harder than technical work.** I built and then removed a speaker-diarization feature. It worked technically, but required shipping 3 GB of PyTorch dependencies and behaved inconsistently on real recordings. Removing it cut the installer from 7 GB to 3.3 GB — a better product, not a smaller one.
- **"It runs" and "it ships" are separated by packaging, logging, error recovery, and data migration.** Writing features was a third of the work.
- **Design for failure early.** I added stage-level caching only after a 47-minute job failed at the final step and had to re-transcribe everything from scratch.
- **Never assume your data format is stable.** Adding chronological sorting exposed that old task records stored timestamps as strings while new ones used floats — the API returned 500 on a mixed list. A migration layer fixed it.

---

## Roadmap

- Additional cloud speech providers beyond the current Silicon Flow / OpenAI / OpenAI-compatible support
- Live transcription (text appears while recording)
- macOS build (requires a macOS build environment)

---

*Repository: https://github.com/Danshiduzhi/zhuanxie-zhushou*
