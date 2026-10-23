#!/usr/bin/env bash
# 转写助手 Android APK 构建（不依赖 Gradle / Android Studio）
# 说明: aapt2 在 Windows 下无法处理含中文的路径, 因此先把工程复制到纯英文暂存目录再构建
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_SDK:-/f/android-toolchain/sdk}"
JDK="${JAVA_HOME_DIR:-/f/android-toolchain/jdk}"
BT="$SDK/build-tools/34.0.0"
AJ="$SDK/platforms/android-34/android.jar"
STAGE="F:/zx-android-build"
OUT="$STAGE/build"
DIST="$ROOT/../dist"

export PATH="$JDK/bin:$PATH"

[ -f "$BT/aapt2.exe" ] || { echo "缺少 build-tools/34.0.0"; exit 1; }
[ -f "$AJ" ] || { echo "缺少 platforms/android-34"; exit 1; }

echo "[0/6] 准备暂存目录"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -r "$ROOT/src" "$STAGE/src"
rm -rf "$STAGE/src/assets/web"
cp -r "$ROOT/../mobile" "$STAGE/src/assets/web"
rm -f "$STAGE/src/assets/web/README.md"

mkdir -p "$OUT/compiled" "$OUT/gen" "$OUT/classes" "$OUT/dex"

echo "[1/6] 编译资源"
"$BT/aapt2.exe" compile --dir "$STAGE/src/res" -o "$OUT/compiled/res.zip"

echo "[2/6] 链接 APK"
"$BT/aapt2.exe" link \
  -o "$OUT/app-unsigned.apk" \
  -I "$AJ" \
  --manifest "$STAGE/src/AndroidManifest.xml" \
  -A "$STAGE/src/assets" \
  --java "$OUT/gen" \
  --min-sdk-version 24 \
  --target-sdk-version 34 \
  --version-code 2 --version-name 2.0 \
  "$OUT/compiled/res.zip"

echo "[3/6] 编译 Java"
find "$STAGE/src/java" "$OUT/gen" -name "*.java" > "$OUT/sources.txt"
javac -source 1.8 -target 1.8 -encoding UTF-8 -bootclasspath "$AJ" \
      -d "$OUT/classes" @"$OUT/sources.txt"

echo "[4/6] 生成 dex"
find "$OUT/classes" -name "*.class" > "$OUT/classes.txt"
"$BT/d8.bat" --lib "$AJ" --min-api 24 --output "$OUT/dex" @"$OUT/classes.txt"

echo "[5/6] 打包并对齐"
python - "$OUT" <<'PY'
import sys, zipfile, shutil, os
out = sys.argv[1]
src = os.path.join(out, "app-unsigned.apk")
dst = os.path.join(out, "app-withdex.apk")
shutil.copy(src, dst)
with zipfile.ZipFile(dst, "a", zipfile.ZIP_DEFLATED) as z:
    z.write(os.path.join(out, "dex", "classes.dex"), "classes.dex")
print("  已加入 classes.dex")
PY
"$BT/zipalign.exe" -f 4 "$OUT/app-withdex.apk" "$OUT/app-aligned.apk"

echo "[6/6] 签名"
KS="$ROOT/debug.keystore"
if [ ! -f "$KS" ]; then
  keytool -genkeypair -v -keystore "$KS" -alias zx -keyalg RSA -keysize 2048 \
    -validity 10000 -storepass android -keypass android \
    -dname "CN=ZhuanXie Assistant, OU=Dev, O=Personal, L=Beijing, C=CN" >/dev/null 2>&1
  echo "  已生成 debug.keystore"
fi
mkdir -p "$DIST"
TMPAPK="$STAGE/zx.apk"
"$BT/apksigner.bat" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out "$TMPAPK" "$OUT/app-aligned.apk"
cp "$TMPAPK" "$DIST/转写助手_Android_v2.0.apk"

echo "--- 校验 ---"
"$BT/apksigner.bat" verify --print-certs "$TMPAPK" | head -3
ls -lh "$DIST/转写助手_Android_v2.0.apk"
echo "完成"
