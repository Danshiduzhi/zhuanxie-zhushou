# 发布指南（GitHub Actions 自动构建 Windows + Mac）

## 第一次发布（约 5 分钟）

### 1. 创建 GitHub 仓库
1. 打开 https://github.com/new （已登录 danshiduzhi）
2. Repository name 填：`zhuanxie-zhushou`
3. 选 **Public** 或 **Private** 都行（Private 每月有免费构建额度，够用）
4. 不要勾选任何初始化选项（README/.gitignore 都不要，项目里已有）
5. 点 **Create repository**

### 2. 推送代码（在本项目文件夹里打开 Git Bash）
```bash
cd "F:/deepseek YUJIAN/转写z.code"
git init
git add .
git commit -m "转写助手 v1.0"
git branch -M main
git remote add origin https://github.com/danshiduzhi/zhuanxie-zhushou.git
git push -u origin main
```
- push 时会**自动弹出浏览器让你登录 GitHub**，登录一次即可（Windows 凭据管理器会记住）
- 推送成功后，GitHub 页面 **Actions** 标签里会自动开始构建（或点 "Run workflow" 手动触发）

### 3. 下载安装包
构建完成后（约 10 分钟），每个任务运行页底部 **Artifacts** 里有三个包：
- `转写助手-windows` → Windows 版
- `转写助手-macos-apple-silicon` → Mac M 系列
- `转写助手-macos-intel` → Mac Intel

下载解压即用（模型文件不在包里，首次运行会自动下载；或在本地把 `models/` 文件夹复制进包内目录可免下载）。

## 以后更新
改完代码 → `git add . && git commit -m "说明" && git push` → Actions 自动出三个新包。

## 注意事项
- `config.json`（含你的 DeepSeek Key）、视频、模型都已加入 `.gitignore`，**不会**上传
- macOS 版首次打开需右键 → 打开（未签名应用）
