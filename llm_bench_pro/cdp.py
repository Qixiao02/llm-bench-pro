#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cdp.py — 纯标准库 Chrome DevTools Protocol 客户端
- 查找本机 Chrome / Edge / Chromium, 以无头模式启动 (独立临时用户目录, 记录所属进程, 遗留进程可回收)
- 最小 WebSocket 客户端 (RFC 6455: 握手 / 掩码帧 / 扩展长度 / 分片 / ping)
- CDP 会话: 同步命令 + 事件缓冲
- PNG 解码 (8-bit RGB/RGBA 非隔行, 即 Chrome 截图格式) 与像素统计, 供白屏/动画/交互判定
"""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zlib


# ---------------------------------------------------------------- 浏览器定位与启动

def find_browser():
    """优先 $LLM_BENCH_BROWSER, 其次常见安装路径与 PATH。找不到返回 None。"""
    env = os.environ.get("LLM_BENCH_BROWSER")
    if env and os.path.isfile(env):
        return env
    cands = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if base:
                cands += [os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                          os.path.join(base, "Chromium", "Application", "chrome.exe"),
                          os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    for c in cands:
        if os.path.isfile(c):
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


PROFILE_PREFIX = "llmbench-chrome-"
_OWNER_FILE = "llmbench-owner.json"


def _pid_alive(pid):
    """进程是否仍在运行。Windows 上 os.kill(pid, 0) 会直接结束目标进程, 必须用 OpenProcess 查询。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # 拒绝访问: 进程存在(例如以管理员身份运行)
        try:
            code = wintypes.DWORD()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_port(profile):
    try:
        with open(os.path.join(profile, "DevToolsActivePort")) as f:
            return int(f.readline().strip())
    except (OSError, ValueError):
        return None


def close_via_devtools(port, timeout=3):
    """通过 DevTools 让浏览器自行退出。对"启动进程已退出、实际浏览器是它重启出来的另一个进程"同样有效。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=timeout) as r:
            ws_url = json.loads(r.read()).get("webSocketDebuggerUrl")
        if not ws_url:
            return False
        ws = WebSocket(ws_url, timeout=timeout)
        try:
            ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
            try:
                ws.recv()
            except Exception:
                pass
        finally:
            ws.close()
        return True
    except Exception:
        return False


def _remove_profile(path, tries=20):
    for _ in range(tries):  # Windows 上进程退出后文件句柄释放有延迟
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        time.sleep(0.3)
    return False


def reap_orphans(log=None):
    """关闭本工具遗留在后台的浏览器: 临时目录里记录的所属进程已经退出, 浏览器却还在运行。
    只处理带归属记录的目录; 没有记录的旧目录可能正被其他仍在运行的服务使用, 不自动处理。返回处理的目录数。"""
    base = tempfile.gettempdir()
    try:
        names = [n for n in os.listdir(base) if n.startswith(PROFILE_PREFIX)]
    except OSError:
        return 0
    n = 0
    for name in names:
        d = os.path.join(base, name)
        try:
            with open(os.path.join(d, _OWNER_FILE), encoding="utf-8") as f:
                owner = json.load(f)
        except (OSError, ValueError):
            continue
        if _pid_alive(owner.get("pid")):
            continue
        port = _read_port(d)
        if port:
            close_via_devtools(port)
        _remove_profile(d, tries=10)
        n += 1
        if log:
            log("  已关闭遗留的后台浏览器(所属进程 %s 已退出): %s" % (owner.get("pid"), name))
    return n


class Browser:
    """一个无头浏览器进程; 通过 /json 端点开关标签页。线程安全地为每个作品开独立标签。"""

    def __init__(self, path=None, timeout=30):
        self.path = path or find_browser()
        if not self.path:
            raise RuntimeError("未找到 Chrome/Edge/Chromium (可设 LLM_BENCH_BROWSER 指定路径)")
        self.profile = tempfile.mkdtemp(prefix=PROFILE_PREFIX)
        self.proc, self.port, self._log = None, None, None
        self.relaunched = False
        try:
            with open(os.path.join(self.profile, _OWNER_FILE), "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "created": time.time()}, f)
        except OSError:
            pass
        args = [self.path, "--headless=new", "--remote-debugging-port=0", "--remote-allow-origins=*",
                "--user-data-dir=" + self.profile, "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--disable-background-networking", "--disable-sync",
                "--disable-component-update", "--mute-audio", "--hide-scrollbars",
                "--autoplay-policy=no-user-gesture-required",
                "--use-angle=swiftshader", "--enable-unsafe-swiftshader",  # 无 GPU 环境下 WebGL 软件渲染
                "--disable-renderer-backgrounding", "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows", "--window-size=1280,800", "about:blank"]
        if sys.platform.startswith("win"):
            # 服务以管理员身份运行时, Chrome 默认会以普通权限重启自身, 启动进程随即退出。
            # 旧代码因此判定"启动失败": 所有作品降级成源码检查, 重启出的浏览器也一直留在后台。
            args.insert(1, "--do-not-de-elevate")
        flags = 0x08000000 if sys.platform.startswith("win") else 0  # CREATE_NO_WINDOW
        try:
            self._log = open(os.path.join(self.profile, "chrome-launch.log"), "wb")
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=self._log, creationflags=flags)
        except OSError as e:
            self.close()
            raise RuntimeError("无法启动浏览器 %s: %s" % (self.path, e))
        t0 = time.time()
        exited = None
        while True:
            self.port = _read_port(self.profile)
            if self.port:
                break
            now = time.time()
            if exited is None and self.proc.poll() is not None:
                exited = now  # 启动进程已退出: 可能是浏览器重启了自身, 再等一会儿看新进程是否就绪
            if (exited is not None and now - exited > 8) or now - t0 > timeout:
                reason = self._failure_reason(exited is not None, now - t0)
                self.close()
                raise RuntimeError(reason)
            time.sleep(0.1)
        self.relaunched = self.proc.poll() is not None  # 实际浏览器是启动进程重启出来的
        try:
            self.version = self._http("GET", "/json/version").get("Browser", "")
        except Exception as e:
            self.close()
            raise RuntimeError("浏览器已启动但无法连接调试端口 %s: %s" % (self.port, e))

    def _failure_reason(self, exited, waited):
        tail = ""
        try:
            self._log.flush()
            with open(self._log.name, "rb") as f:
                tail = f.read()[-800:].decode("utf-8", "replace").strip()
        except Exception:
            pass
        if exited:
            msg = "浏览器启动后立即退出（退出码 %s）" % self.proc.returncode
        else:
            msg = "浏览器 %d 秒内没有准备好" % waited
        msg += "：%s" % self.path
        lines = [x for x in tail.splitlines() if x.strip()]
        if lines:
            msg += "。浏览器输出：" + " / ".join(lines[-3:])[:300]
        return msg

    def _http(self, method, path):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method)
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read()
        try:
            return json.loads(body)
        except ValueError:
            return {}

    def new_page(self):
        info = self._http("PUT", "/json/new?about:blank")
        return Page(self, info["id"], info["webSocketDebuggerUrl"])

    def close_target(self, target_id):
        try:
            self._http("GET", "/json/close/" + target_id)
        except Exception:
            pass

    def close(self):
        try:
            if self.port:
                close_via_devtools(self.port)  # 先让浏览器自行退出: 覆盖重启后换了进程的情况
            if self.proc is not None and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        finally:
            if self._log is not None:
                try:
                    self._log.close()
                except Exception:
                    pass
            _remove_profile(self.profile)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------- WebSocket

class WebSocket:
    def __init__(self, url, timeout=15):
        u = urllib.parse.urlsplit(url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + ("?" + u.query if u.query else "")
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n") % (path, u.hostname, u.port or 80, key)
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket 握手失败")
            resp += chunk
        head, self._buf = resp.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError("WebSocket 握手被拒: %r" % head[:120])
        self._send_lock = threading.Lock()

    def send(self, text):
        data = text.encode("utf-8")
        n = len(data)
        if n < 126:
            header = struct.pack("!BB", 0x81, 0x80 | n)
        elif n < 65536:
            header = struct.pack("!BBH", 0x81, 0x80 | 126, n)
        else:
            header = struct.pack("!BBQ", 0x81, 0x80 | 127, n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data)) if n < 4096 else _xor_mask(data, mask)
        with self._send_lock:
            self.sock.sendall(header + mask + masked)

    def _read_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self._buf)))
            if not chunk:
                raise ConnectionError("WebSocket 连接关闭")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv(self):
        """返回一条完整文本消息 (拼接分片; 自动回应 ping)。"""
        parts = []
        while True:
            b1, b2 = self._read_exact(2)
            fin, op, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read_exact(8))[0]
            if b2 & 0x80:
                mask = self._read_exact(4)
                payload = _xor_mask(self._read_exact(n), mask)
            else:
                payload = self._read_exact(n)
            if op == 0x8:
                raise ConnectionError("WebSocket 被对端关闭")
            if op == 0x9:
                with self._send_lock:
                    self.sock.sendall(struct.pack("!BB", 0x8A, 0x80 | len(payload)) + b"\0\0\0\0" + payload)
                continue
            if op in (0x1, 0x2, 0x0):
                parts.append(payload)
                if fin:
                    return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def _xor_mask(data, mask):
    n = len(data)
    m = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "little") ^ int.from_bytes(m, "little")).to_bytes(n, "little")


# ---------------------------------------------------------------- CDP 页面会话

class CDPError(RuntimeError):
    pass


class Page:
    def __init__(self, browser, target_id, ws_url):
        self.browser, self.target_id = browser, target_id
        self.ws = WebSocket(ws_url)
        self._id = 0
        self._lock = threading.Lock()
        self._results = {}
        self._cond = threading.Condition()
        self.events = []  # (monotonic_t, method, params)
        self._alive = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        try:
            while self._alive:
                msg = json.loads(self.ws.recv())
                with self._cond:
                    if "id" in msg:
                        self._results[msg["id"]] = msg
                    else:
                        self.events.append((time.monotonic(), msg.get("method"), msg.get("params") or {}))
                    self._cond.notify_all()
        except Exception:
            with self._cond:
                self._alive = False
                self._cond.notify_all()

    def send(self, method, params=None, timeout=15):
        with self._lock:
            self._id += 1
            mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        with self._cond:
            while mid not in self._results:
                left = deadline - time.monotonic()
                if left <= 0 or not self._alive:
                    raise CDPError("%s 超时或连接断开(页面可能卡死)" % method)
                self._cond.wait(left)
            msg = self._results.pop(mid)
        if "error" in msg:
            raise CDPError("%s: %s" % (method, msg["error"].get("message")))
        return msg.get("result") or {}

    def wait_event(self, method, timeout=15, since=0.0):
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                for t, m, p in self.events:
                    if m == method and t >= since:
                        return p
                left = deadline - time.monotonic()
                if left <= 0 or not self._alive:
                    return None
                self._cond.wait(left)

    def evaluate(self, expr, timeout=10):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True}, timeout)
        if r.get("exceptionDetails"):
            raise CDPError("evaluate 异常: %s" % r["exceptionDetails"].get("text"))
        return (r.get("result") or {}).get("value")

    def screenshot(self, fmt="png", scale=1.0, quality=70, width=1280, height=800):
        params = {"format": fmt, "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": scale},
                  "captureBeyondViewport": False}
        if fmt == "jpeg":
            params["quality"] = quality
        return base64.b64decode(self.send("Page.captureScreenshot", params, timeout=20)["data"])

    def close(self):
        self._alive = False
        self.ws.close()
        self.browser.close_target(self.target_id)


# ---------------------------------------------------------------- PNG 解码与像素统计

def decode_png(data):
    """返回 (width, height, channels, bytes)。仅支持 8-bit 灰度/RGB/RGBA、非隔行。"""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("非 PNG")
    pos, idat, w = 8, [], None
    while pos < len(data):
        n, typ = struct.unpack("!I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + n]
        if typ == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack("!IIBBBBB", chunk)
            if depth != 8 or interlace or ctype not in (0, 2, 6):
                raise ValueError("不支持的 PNG 格式")
            ch = {0: 1, 2: 3, 6: 4}[ctype]
        elif typ == b"IDAT":
            idat.append(chunk)
        elif typ == b"IEND":
            break
        pos += 12 + n
    raw = zlib.decompress(b"".join(idat))
    stride = w * ch
    out = bytearray(h * stride)
    prev = bytearray(stride)
    for y in range(h):
        base = y * (stride + 1)
        f = raw[base]
        line = bytearray(raw[base + 1:base + 1 + stride])
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif f == 2:
            line = bytearray((a + b) & 0xFF for a, b in zip(line, prev))
        elif f == 3:
            for i in range(stride):
                left = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, ch, bytes(out)


def image_stats(png):
    """非白屏判定用: 亮度标准差、近似主色占比、颜色种类数(量化后)。"""
    w, h, ch, px = decode_png(png)
    n = w * h
    lum = [0] * n
    hist = {}
    for i in range(n):
        o = i * ch
        r, g, b = (px[o], px[o + 1], px[o + 2]) if ch >= 3 else (px[o],) * 3
        lum[i] = (r * 299 + g * 587 + b * 114) // 1000
        q = (r >> 4, g >> 4, b >> 4)
        hist[q] = hist.get(q, 0) + 1
    mean = sum(lum) / n
    std = (sum((x - mean) ** 2 for x in lum) / n) ** 0.5
    return {"w": w, "h": h, "lum_mean": round(mean, 1), "lum_std": round(std, 2),
            "dominant_ratio": round(max(hist.values()) / n, 4), "colors": len(hist)}


def image_diff(png_a, png_b, threshold=24):
    """两帧变化像素占比 (任一通道差 > threshold)。尺寸不同返回 1.0。"""
    wa, ha, ca, a = decode_png(png_a)
    wb, hb, cb, b = decode_png(png_b)
    if (wa, ha, ca) != (wb, hb, cb):
        return 1.0
    changed = 0
    step = ca
    for o in range(0, len(a), step):
        if abs(a[o] - b[o]) > threshold or abs(a[o + 1] - b[o + 1]) > threshold or abs(a[o + 2] - b[o + 2]) > threshold:
            changed += 1
    return round(changed / (wa * ha), 5)


def reap_all_legacy(log=print):
    """手动回收: 关闭所有 llmbench-chrome-* 目录对应的后台浏览器(包括旧版本遗留、没有归属记录的)。
    只应在没有评测正在运行时使用。返回处理的目录数。"""
    base = tempfile.gettempdir()
    n = 0
    for name in sorted(os.listdir(base)):
        if not name.startswith(PROFILE_PREFIX):
            continue
        d = os.path.join(base, name)
        port = _read_port(d)
        closed = close_via_devtools(port) if port else False
        removed = _remove_profile(d, tries=10)
        n += 1
        log("%s  浏览器%s  目录%s" % (name, "已关闭" if closed else "未在运行", "已删除" if removed else "删除失败(可能仍被占用)"))
    return n


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="后台浏览器维护")
    ap.add_argument("--reap", action="store_true", help="回收所属进程已退出的后台浏览器")
    ap.add_argument("--reap-all", action="store_true", help="关闭全部 llmbench 后台浏览器(含旧版本遗留), 确认没有评测在运行时使用")
    args = ap.parse_args(argv)
    if args.reap_all:
        print("共处理 %d 个" % reap_all_legacy())
    elif args.reap:
        print("共处理 %d 个" % reap_orphans(print))
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
