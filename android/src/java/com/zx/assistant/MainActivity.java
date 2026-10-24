package com.zx.assistant;

import android.Manifest;
import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PrintWriter;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.util.HashMap;
import java.util.Map;

/**
 * 转写助手 Android 壳
 *
 * 把 mobile/ 里的网页放进 APK 的 assets，用本机回环 HTTP 服务提供。
 * 走 127.0.0.1 而不是 file:// 的原因：浏览器只在安全上下文里允许录音，
 * 而 http://127.0.0.1 被视作安全上下文，getUserMedia / MediaRecorder 才能用。
 */
public class MainActivity extends Activity {

    private WebView web;
    private ServerSocket server;
    private int port;
    private ValueCallback<Uri[]> fileCallback;
    private static final int REQ_FILE = 1001;
    private static final int REQ_AUDIO = 1002;

    private static final Map<String, String> MIME = new HashMap<>();
    static {
        MIME.put("html", "text/html; charset=utf-8");
        MIME.put("js", "application/javascript; charset=utf-8");
        MIME.put("css", "text/css; charset=utf-8");
        MIME.put("json", "application/json; charset=utf-8");
        MIME.put("webmanifest", "application/manifest+json; charset=utf-8");
        MIME.put("png", "image/png");
        MIME.put("jpg", "image/jpeg");
        MIME.put("svg", "image/svg+xml");
        MIME.put("ico", "image/x-icon");
        MIME.put("txt", "text/plain; charset=utf-8");
    }

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        applySystemBars();

        try {
            server = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"));
            port = server.getLocalPort();
            startServerThread();
        } catch (IOException e) {
            Toast.makeText(this, "本地服务启动失败: " + e.getMessage(), Toast.LENGTH_LONG).show();
            finish();
            return;
        }

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        web.setWebViewClient(new WebViewClient());

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        try {
                            request.grant(request.getResources());
                        } catch (Exception ignored) {
                        }
                    }
                });
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb,
                                             FileChooserParams params) {
                if (fileCallback != null) {
                    fileCallback.onReceiveValue(null);
                }
                fileCallback = cb;
                Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*");
                try {
                    startActivityForResult(Intent.createChooser(intent, "选择音视频文件"), REQ_FILE);
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });

        setContentView(web);
        web.addJavascriptInterface(new Bridge(), "ZXAndroid");
        ensureMicPermission();
        web.loadUrl("http://127.0.0.1:" + port + "/index.html");
    }

    /** 暴露给网页的原生能力：WebView 里 <a download> 不生效，改由原生写文件 */
    class Bridge {
        @JavascriptInterface
        public boolean saveText(final String fileName, final String content) {
            try {
                OutputStream os = null;
                if (Build.VERSION.SDK_INT >= 29) {
                    ContentValues cv = new ContentValues();
                    cv.put(MediaStore.MediaColumns.DISPLAY_NAME, fileName);
                    cv.put(MediaStore.MediaColumns.MIME_TYPE, "text/plain");
                    cv.put(MediaStore.MediaColumns.RELATIVE_PATH,
                            Environment.DIRECTORY_DOWNLOADS);
                    Uri uri = getContentResolver()
                            .insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
                    if (uri != null) os = getContentResolver().openOutputStream(uri);
                }
                if (os == null) {
                    File dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
                    if (dir != null) {
                        if (!dir.exists()) dir.mkdirs();
                        os = new FileOutputStream(new File(dir, fileName));
                    }
                }
                if (os == null) return false;
                os.write(content.getBytes("UTF-8"));
                os.close();
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        Toast.makeText(MainActivity.this,
                                "已保存到「下载」：" + fileName, Toast.LENGTH_LONG).show();
                    }
                });
                return true;
            } catch (Exception e) {
                return false;
            }
        }
    }

    /** 深色模式下列状态栏与导航栏跟随页面底色, 避免出现亮色横条 */
    private void applySystemBars() {
        boolean dark = (getResources().getConfiguration().uiMode
                & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
        int bg = dark ? Color.parseColor("#000000") : Color.parseColor("#f5f5f7");
        getWindow().setStatusBarColor(bg);
        getWindow().setNavigationBarColor(bg);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            View decor = getWindow().getDecorView();
            int flags = decor.getSystemUiVisibility();
            if (dark) {
                flags &= ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            } else {
                flags |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            }
            decor.setSystemUiVisibility(flags);
        }
    }

    private void ensureMicPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                    != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_AUDIO);
            }
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        super.onRequestPermissionsResult(code, perms, results);
        if (code == REQ_AUDIO && results.length > 0
                && results[0] != PackageManager.PERMISSION_GRANTED) {
            Toast.makeText(this, "没有麦克风权限，录音功能不可用（仍可选择文件）",
                    Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        if (req == REQ_FILE) {
            if (fileCallback == null) return;
            Uri[] uris = null;
            if (result == RESULT_OK && data != null && data.getData() != null) {
                uris = new Uri[]{data.getData()};
            }
            fileCallback.onReceiveValue(uris);
            fileCallback = null;
        } else {
            super.onActivityResult(req, result, data);
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        try {
            if (web != null) web.destroy();
            if (server != null) server.close();
        } catch (Exception ignored) {
        }
        super.onDestroy();
    }

    // ---------------- 本地静态文件服务 ----------------

    private void startServerThread() {
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                while (!server.isClosed()) {
                    try {
                        final Socket sock = server.accept();
                        new Thread(new Runnable() {
                            @Override
                            public void run() {
                                handle(sock);
                            }
                        }).start();
                    } catch (IOException e) {
                        break;
                    }
                }
            }
        });
        t.setDaemon(true);
        t.start();
    }

    private void handle(Socket sock) {
        try (Socket s = sock) {
            InputStream in = s.getInputStream();
            ByteArrayOutputStream head = new ByteArrayOutputStream();
            int b;
            while ((b = in.read()) != -1) {
                head.write(b);
                if (head.size() >= 4 && head.toByteArray()[head.size() - 1] == '\n'
                        && head.toByteArray()[head.size() - 3] == '\r'
                        && head.toByteArray()[head.size() - 2] == '\n') {
                    break;
                }
                if (head.size() > 8192) break;
            }
            String reqLine = new String(head.toByteArray(), "UTF-8").split("\r\n")[0];
            String[] parts = reqLine.split(" ");
            String path = parts.length > 1 ? parts[1] : "/";
            int q = path.indexOf('?');
            if (q >= 0) path = path.substring(0, q);
            if (path.equals("/") || path.isEmpty()) path = "/index.html";
            path = URLDecoder.decode(path, "UTF-8");
            if (path.contains("..")) {
                writeResponse(s.getOutputStream(), 403, "text/plain", "forbidden".getBytes("UTF-8"));
                return;
            }

            byte[] body = readAsset("web" + path);
            if (body == null) {
                writeResponse(s.getOutputStream(), 404, "text/plain", "not found".getBytes("UTF-8"));
                return;
            }
            String ext = path.contains(".") ? path.substring(path.lastIndexOf('.') + 1).toLowerCase() : "";
            String mime = MIME.getOrDefault(ext, "application/octet-stream");
            writeResponse(s.getOutputStream(), 200, mime, body);
        } catch (Exception ignored) {
        }
    }

    private byte[] readAsset(String name) {
        try (InputStream is = getAssets().open(name)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = is.read(buf)) > 0) out.write(buf, 0, n);
            return out.toByteArray();
        } catch (IOException e) {
            return null;
        }
    }

    private void writeResponse(OutputStream out, int code, String mime, byte[] body)
            throws IOException {
        PrintWriter w = new PrintWriter(out, false);
        w.print("HTTP/1.1 " + code + " " + (code == 200 ? "OK" : "Error") + "\r\n");
        w.print("Content-Type: " + mime + "\r\n");
        w.print("Content-Length: " + body.length + "\r\n");
        w.print("Cache-Control: no-store\r\n");
        w.print("Connection: close\r\n\r\n");
        w.flush();
        out.write(body);
        out.flush();
    }
}
