#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VegToon Image Batch — bulk ChatGPT image generation, in your browser.

Double-click this file. It opens a web page where you paste prompts (one per
line), pick an output folder, and press Generate. Images are produced by
ChatGPT and billed to your ChatGPT subscription -- no API key, no API bill.

Requires: Python 3.9+ only. Everything else it installs by itself.

How it works
------------
Sign-in reuses the official Codex CLI browser login (`codex login`). This app
never sees or asks for your password; it only reads the token file that login
writes (~/.codex/auth.json), exactly as the codex-imagegen-cli project does.
Images come from ChatGPT's own hosted image tool.

Protocol reference: github.com/jdmnk/codex-imagegen-cli (Apache-2.0)
"""

import base64
import collections
import http.server
import json
import os
import platform
import random
import re
import shutil
import socket
import string
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from datetime import datetime, timezone
from pathlib import Path

APP_NAME = "VegToon Image Batch"
APP_VERSION = "1.2.0"

# --- Update + diagnostics channel ------------------------------------------
# The upload key is write-only on purpose: it can post a report, it cannot read
# anything back. Reading needs a separate admin key that never leaves my side.
UPDATE_MANIFEST = "https://danielarnold6136.github.io/veg-toon-studio/tools/latest.json"
RELAY_URL = "https://vegtoon-relay.fleet-fefsba.workers.dev"
RELAY_UPLOAD_KEY = "__RELAY_UPLOAD_KEY__"

# --- Codex protocol constants (must match the official CLI) -----------------
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_REFRESH_URL = "https://auth.openai.com/oauth/token"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_MODEL = "gpt-5.5"
CODEX_ORIGINATOR = "codex_cli_rs"
CODEX_RELEASES_API = "https://api.github.com/repos/openai/codex/releases/latest"

SIZES = ("auto", "1024x1024", "1536x1024", "1024x1536")
QUALITIES = ("auto", "low", "medium", "high")
BACKGROUNDS = ("auto", "opaque", "transparent")

MAX_RETRIES = 4
INPUT_IMAGE_RATE_DELAYS = (65.0, 130.0, 260.0, 300.0)

HOME = Path.home()
APP_DIR = HOME / ".vegtoon-batch"
BIN_DIR = APP_DIR / "bin"
SETTINGS_FILE = APP_DIR / "settings.json"

SESSION_TOKEN = "".join(random.choices(string.ascii_letters + string.digits, k=24))


# ============================================================================
# Small helpers
# ============================================================================

CONSOLE = collections.deque(maxlen=160)


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    CONSOLE.append(line)
    print(line, flush=True)


def redact(text) -> str:
    """Strip the user's home path out of anything we send off the machine."""
    try:
        return str(text).replace(str(HOME), "~")
    except Exception:
        return str(text)


def codex_home() -> Path:
    env = os.environ.get("CODEX_HOME")
    return Path(env).expanduser() if env else HOME / ".codex"


def auth_file() -> Path:
    return codex_home() / "auth.json"


def load_settings() -> dict:
    defaults = {
        "out_dir": str(HOME / "Pictures" / "VegToon"),
        "size": "1024x1536",
        "quality": "high",
        "background": "auto",
        "count": 1,
        "prefix": "img",
        "report": True,
        "install_id": "",
    }
    try:
        if SETTINGS_FILE.exists():
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                defaults.update({k: v for k, v in saved.items() if k in defaults})
    except Exception:
        pass
    if not defaults["install_id"]:
        defaults["install_id"] = "pc-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        save_settings({"install_id": defaults["install_id"]})
    return defaults


def save_settings(data: dict):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        current = load_settings()
        current.update({k: v for k, v in data.items() if k in current})
        SETTINGS_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except Exception as exc:
        log(f"could not save settings: {exc}")


# ============================================================================
# Update channel + diagnostics relay
#
# What leaves this machine, and nothing else: app/Python/OS version, whether
# sign-in worked (true/false only), the plan name, the batch settings, each
# prompt's status + error + timing, and the console lines you can see in the
# black window. Built as an allow-list below, so a token can never fall in by
# accident. Turn it off with the tick-box in the app.
# ============================================================================

UPDATE = {"checked": 0.0, "latest": "", "url": "", "notes": "", "error": ""}


def _relay_post(path: str, data: bytes, content_type: str):
    # A User-Agent is required: Cloudflare rejects urllib's default with error 1010.
    req = urllib.request.Request(
        f"{RELAY_URL}/{path.lstrip('/')}", data=data, method="POST",
        headers={"x-key": RELAY_UPLOAD_KEY, "Content-Type": content_type,
                 "User-Agent": f"{APP_NAME}/{APP_VERSION}"},
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_report(note: str = "") -> dict:
    settings = load_settings()
    auth = load_auth()
    snap = BATCH.snapshot()
    items = []
    for i, it in enumerate(snap["items"]):
        items.append({
            "n": i + 1,
            "status": it.get("status"),
            "error": redact(it.get("error") or "")[:400],
            "seconds": it.get("seconds"),
            "prompt_head": (it.get("prompt") or "")[:160],
        })
    counts = collections.Counter(it.get("status") for it in snap["items"])
    return {
        "app": APP_VERSION,
        "note": note,
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "install_id": settings.get("install_id"),
        "python": sys.version.split()[0],
        "os": platform.platform(),
        "machine": platform.machine(),
        "codex_found": bool(find_codex()),
        "codex_version": codex_version_string(),
        "signed_in": bool(auth and access_token(auth)),
        "plan": account_plan(auth) if auth else None,
        "settings": {
            "size": settings.get("size"), "quality": settings.get("quality"),
            "background": settings.get("background"), "count": settings.get("count"),
            "out_dir": redact(settings.get("out_dir")),
        },
        "totals": {
            "queued": len(snap["items"]), "done": counts.get("done", 0),
            "failed": counts.get("failed", 0), "stopped": counts.get("stopped", 0),
            "elapsed": snap.get("elapsed"),
        },
        "message": redact(snap.get("message")),
        "items": items,
        "console": [redact(line) for line in list(CONSOLE)],
    }


def send_report(note: str = "", force: bool = False) -> str:
    if not force and not load_settings().get("report", True):
        return "Reporting is switched off."
    try:
        body = json.dumps(build_report(note)).encode("utf-8")
        out = _relay_post(f"r/{load_settings().get('install_id')}", body, "application/json")
        log(f"report sent ({len(body)} bytes)")
        return f"Report sent. {out.get('key', '')}"
    except Exception as exc:
        log(f"report failed: {exc}")
        return f"Could not send the report: {exc}"


def send_samples(limit: int = 3) -> str:
    """Upload the most recent generated images so they can be looked at."""
    snap = BATCH.snapshot()
    paths = [it["file"] for it in snap["items"] if it.get("status") == "done" and it.get("file")]
    if not paths:
        return "No images from this run yet."
    sent = 0
    for path in paths[-limit:]:
        try:
            raw = Path(path).read_bytes()
            if len(raw) > 20 * 1024 * 1024:
                continue
            _relay_post(f"i/{Path(path).name}", raw, "image/png")
            sent += 1
        except Exception as exc:
            log(f"sample upload failed for {Path(path).name}: {exc}")
    send_report(note=f"sample upload ({sent} images)", force=True)
    return f"Sent {sent} image{'s' if sent != 1 else ''}." if sent else "Could not send the images."


def check_update(force: bool = False) -> dict:
    if not force and time.time() - UPDATE["checked"] < 900:
        return UPDATE
    UPDATE["checked"] = time.time()
    UPDATE["error"] = ""
    try:
        req = urllib.request.Request(UPDATE_MANIFEST, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        UPDATE["latest"] = str(data.get("version") or "")
        UPDATE["url"] = str(data.get("url") or "")
        UPDATE["notes"] = str(data.get("notes") or "")
    except Exception as exc:
        UPDATE["error"] = str(exc)
        log(f"update check failed: {exc}")
    return UPDATE


def version_tuple(text: str):
    try:
        return tuple(int(p) for p in text.split(".")[:3])
    except Exception:
        return (0, 0, 0)


def apply_update() -> str:
    info = check_update(force=True)
    if not info["latest"] or version_tuple(info["latest"]) <= version_tuple(APP_VERSION):
        return "Already on the newest version."
    if not info["url"]:
        return "The update did not list a download link."
    try:
        req = urllib.request.Request(info["url"], headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=120) as resp:
            new_source = resp.read()
    except Exception as exc:
        return f"Could not download the update: {exc}"

    text = new_source.decode("utf-8", errors="replace")
    if "VegToon Image Batch" not in text or "def main(" not in text:
        return "The downloaded file did not look like this app. Nothing was changed."
    try:
        compile(text, "update", "exec")
    except SyntaxError as exc:
        return f"The downloaded update is damaged, so it was not installed ({exc})."

    me = Path(__file__).resolve()
    try:
        shutil.copy2(me, me.with_suffix(".py.backup"))
        me.write_bytes(new_source)
    except Exception as exc:
        return f"Could not replace the app file: {exc}"
    log(f"updated {APP_VERSION} -> {info['latest']}")
    return f"Updated to v{info['latest']}. Close the black window and double-click the file again."


def safe_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.")
    return cleaned[:60] or "img"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ============================================================================
# Codex CLI discovery / installation
# ============================================================================

def find_codex():
    """Return a path to a usable codex binary, or None."""
    found = shutil.which("codex")
    if found:
        return found
    local = BIN_DIR / ("codex.exe" if os.name == "nt" else "codex")
    if local.exists():
        return str(local)
    return None


def codex_asset_name():
    """Pick the right release asset for this machine, preferring stdlib-openable formats."""
    machine = platform.machine().lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if os.name == "nt":
        return f"codex-{arch}-pc-windows-msvc.exe.zip", "zip"
    if sys.platform == "darwin":
        return f"codex-{arch}-apple-darwin.tar.gz", "tar"
    return f"codex-{arch}-unknown-linux-musl.tar.gz", "tar"


def install_codex(progress_cb):
    """Download the official Codex binary. Returns its path."""
    want, kind = codex_asset_name()
    progress_cb(f"Looking up the latest Codex release ({want}) ...")
    req = urllib.request.Request(CODEX_RELEASES_API, headers={"User-Agent": APP_NAME})
    with urllib.request.urlopen(req, timeout=60) as resp:
        release = json.loads(resp.read().decode("utf-8"))

    asset = next((a for a in release.get("assets", []) if a.get("name") == want), None)
    if asset is None:
        raise RuntimeError(
            f"Could not find '{want}' in Codex release {release.get('tag_name')}. "
            "Install the Codex app yourself from github.com/openai/codex/releases, "
            "then reopen this page."
        )

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    archive = BIN_DIR / want
    total = int(asset.get("size") or 0)
    progress_cb(f"Downloading Codex ({total / 1e6:.0f} MB). This happens once.")

    req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": APP_NAME})
    done = 0
    last_pct = -5
    with urllib.request.urlopen(req, timeout=120) as resp, open(archive, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                pct = int(done * 100 / total)
                if pct >= last_pct + 5:
                    last_pct = pct
                    progress_cb(f"Downloading Codex ... {pct}%")

    progress_cb("Unpacking ...")
    target = BIN_DIR / ("codex.exe" if os.name == "nt" else "codex")
    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            member = next((n for n in zf.namelist() if n.lower().endswith(".exe")), None)
            if member is None:
                raise RuntimeError("Codex zip did not contain an .exe")
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            member = next(
                (m for m in tf.getmembers()
                 if m.isfile() and Path(m.name).name.startswith("codex")),
                None,
            )
            if member is None:
                raise RuntimeError("Codex archive did not contain a codex binary")
            extracted = tf.extractfile(member)
            with open(target, "wb") as dst:
                shutil.copyfileobj(extracted, dst)

    try:
        archive.unlink()
    except Exception:
        pass
    if os.name != "nt":
        target.chmod(0o755)
    progress_cb("Codex installed.")
    return str(target)


# ============================================================================
# Auth: read + refresh the token that `codex login` writes
# ============================================================================

def _b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def jwt_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        out = json.loads(_b64url(parts[1]).decode("utf-8"))
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def load_auth():
    path = auth_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def access_token(auth: dict):
    tokens = auth.get("tokens")
    if isinstance(tokens, dict):
        tok = tokens.get("access_token")
        if isinstance(tok, str) and tok:
            return tok
    return None


def id_token_claims(auth: dict) -> dict:
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        return {}
    idt = tokens.get("id_token")
    if isinstance(idt, dict):
        return idt
    if isinstance(idt, str):
        payload = jwt_payload(idt)
        auth_claim = payload.get("https://api.openai.com/auth")
        merged = dict(payload)
        if isinstance(auth_claim, dict):
            merged.update(auth_claim)
        return merged
    return {}


def account_id(auth: dict):
    tokens = auth.get("tokens")
    if isinstance(tokens, dict):
        acc = tokens.get("account_id")
        if isinstance(acc, str) and acc:
            return acc
    acc = id_token_claims(auth).get("chatgpt_account_id")
    return acc if isinstance(acc, str) and acc else None


def account_email(auth: dict):
    claims = id_token_claims(auth)
    for key in ("email", "preferred_username"):
        val = claims.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def account_plan(auth: dict):
    plan = id_token_claims(auth).get("chatgpt_plan_type")
    return plan if isinstance(plan, str) and plan else None


def token_expiring(token: str, leeway=60) -> bool:
    exp = jwt_payload(token).get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return exp <= datetime.now(timezone.utc).timestamp() + leeway


def refresh_auth(auth: dict):
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        raise RuntimeError("Not signed in. Press Sign in with ChatGPT.")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RuntimeError("Sign-in has expired. Press Sign in with ChatGPT again.")

    body = json.dumps({
        "client_id": CODEX_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode("utf-8")
    req = urllib.request.Request(
        CODEX_REFRESH_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        refreshed = json.loads(resp.read().decode("utf-8"))

    for key in ("access_token", "refresh_token"):
        val = refreshed.get(key)
        if isinstance(val, str) and val:
            tokens[key] = val
    idt = refreshed.get("id_token")
    if isinstance(idt, str) and idt:
        payload = jwt_payload(idt)
        claim = payload.get("https://api.openai.com/auth")
        merged = dict(payload)
        if isinstance(claim, dict):
            merged.update(claim)
        tokens["id_token"] = merged
    auth["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path = auth_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(auth, indent=2) + "\n", encoding="utf-8")
    return auth


def ready_auth():
    auth = load_auth()
    if auth is None or not access_token(auth):
        raise RuntimeError("Not signed in yet. Press Sign in with ChatGPT.")
    if token_expiring(access_token(auth)):
        auth = refresh_auth(auth)
    return auth


def codex_version_string():
    binary = find_codex()
    if binary:
        try:
            out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=20)
            match = re.search(r"(\d+\.\d+\.\d+)", (out.stdout or "") + (out.stderr or ""))
            if match:
                return match.group(1)
        except Exception:
            pass
    return "0.0.0"


def auth_headers(auth: dict) -> dict:
    ver = codex_version_string()
    system, release, machine = platform.system(), platform.release(), platform.machine()
    headers = {
        "Authorization": f"Bearer {access_token(auth)}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "originator": CODEX_ORIGINATOR,
        "User-Agent": f"{CODEX_ORIGINATOR}/{ver} ({system} {release}; {machine}) {APP_NAME}/{APP_VERSION}",
        "version": ver,
    }
    acc = account_id(auth)
    if acc:
        headers["ChatGPT-Account-ID"] = acc
    if id_token_claims(auth).get("chatgpt_account_is_fedramp"):
        headers["X-OpenAI-Fedramp"] = "true"
    return headers


# ============================================================================
# Image generation
# ============================================================================

class RateLimited(Exception):
    def __init__(self, message, delay):
        super().__init__(message)
        self.delay = delay


def build_payload(prompt: str, size: str, quality: str, background: str, cache_key: str) -> dict:
    return {
        "model": CODEX_MODEL,
        "instructions": (
            "Use the available image generation tool to generate exactly one PNG image "
            "for the user request. Do not use any other tool."
        ),
        "input": [{
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": prompt}],
        }],
        "tools": [{
            "type": "image_generation",
            "output_format": "png",
            "size": size,
            "quality": quality,
            "background": background,
        }],
        "tool_choice": {"type": "image_generation"},
        "parallel_tool_calls": False,
        "reasoning": None,
        "store": False,
        "stream": True,
        "include": [],
        "prompt_cache_key": cache_key,
        "client_metadata": {"x-codex-installation-id": "vegtoon-image-batch"},
    }


def parse_sse_block(block: str):
    data_lines = []
    for raw in block.splitlines():
        if raw.startswith("data:"):
            data_lines.append(raw.split(":", 1)[1].lstrip())
    return "\n".join(data_lines) if data_lines else None


def retry_delay_for(error_obj: dict, attempt: int):
    """Mirror the reference CLI's backoff policy. None => do not retry."""
    if not isinstance(error_obj, dict) or error_obj.get("code") != "rate_limit_exceeded":
        return None
    message = error_obj.get("message") or ""
    if "input-images per min" in message:
        used = re.search(r"Used\s+(\d+(?:\.\d+)?)", message)
        limit = re.search(r"Limit\s+(\d+(?:\.\d+)?)", message)
        if used and limit and float(used.group(1)) >= float(limit.group(1)):
            return INPUT_IMAGE_RATE_DELAYS[min(attempt, len(INPUT_IMAGE_RATE_DELAYS) - 1)]
    parsed = None
    match = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*(ms|s)", message, re.IGNORECASE)
    if match:
        parsed = float(match.group(1))
        if match.group(2).lower() == "ms":
            parsed /= 1000.0
    backoff = min(2.0 ** attempt, 16.0)
    return backoff if parsed is None else max(parsed, backoff)


def stream_one_image(headers: dict, payload: dict, timeout: float, cancel: threading.Event) -> str:
    """POST to the Codex responses endpoint, return base64 PNG. Raises on failure."""
    url = f"{CODEX_BASE_URL}/responses"
    req_headers = dict(headers)
    req_headers["Accept"] = "text/event-stream"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=req_headers, method="POST",
    )
    last_error = None
    last_status = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            pending = ""
            while True:
                if cancel.is_set():
                    raise RuntimeError("Stopped.")
                chunk = resp.read(4096)
                if not chunk:
                    break
                pending += chunk.decode("utf-8", errors="replace")
                while "\n\n" in pending:
                    block, pending = pending.split("\n\n", 1)
                    data = parse_sse_block(block)
                    if not data:
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get("type") in ("response.failed", "response.incomplete"):
                        resp_obj = event.get("response")
                        if isinstance(resp_obj, dict):
                            last_error = resp_obj.get("error")
                    item = event.get("item")
                    if isinstance(item, dict) and item.get("type") == "image_generation_call":
                        last_status = item.get("status")
                        result = item.get("result")
                        if isinstance(result, str) and result:
                            return result
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise urllib.error.HTTPError(exc.url, exc.code, raw[:500], exc.headers, None)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network problem: {exc.reason}")

    if last_error:
        message = last_error.get("message") or "Image generation failed."
        if last_error.get("code") == "rate_limit_exceeded":
            raise RateLimited(message, retry_delay_for(last_error, 0))
        raise RuntimeError(message)
    if last_status:
        raise RuntimeError(f"Finished without an image (status: {last_status}).")
    raise RuntimeError("Finished without an image.")


def demo_png(index: int) -> str:
    """A tiny valid PNG, used by Test run so the whole pipeline can be checked offline."""
    import struct
    import zlib
    w = h = 64
    shade = (index * 37) % 200 + 40
    rows = b"".join(
        b"\x00" + bytes([shade, (shade * 2) % 256, 200] * w) for _ in range(h)
    )

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return base64.b64encode(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    ).decode("ascii")


# ============================================================================
# Job state
# ============================================================================

class Batch:
    def __init__(self):
        self.lock = threading.Lock()
        self.items = []
        self.running = False
        self.cancel = threading.Event()
        self.message = ""
        self.out_dir = ""
        self.started_at = None

    def snapshot(self):
        with self.lock:
            return {
                "running": self.running,
                "message": self.message,
                "out_dir": self.out_dir,
                "items": [dict(i) for i in self.items],
                "elapsed": round(time.time() - self.started_at, 1) if self.started_at else 0,
            }

    def set_message(self, text):
        with self.lock:
            self.message = text

    def update(self, index, **fields):
        with self.lock:
            self.items[index].update(fields)


BATCH = Batch()
SETUP = {"busy": False, "message": "", "error": "", "auth_url": ""}
SETUP_LOCK = threading.Lock()


def setup_msg(text, error=""):
    with SETUP_LOCK:
        SETUP["message"] = text
        if error:
            SETUP["error"] = error
    log(text if not error else f"{text} :: {error}")


def run_batch(prompts, opts):
    """Worker thread: generate every prompt, one at a time."""
    out_dir = Path(opts["out_dir"]).expanduser()
    demo = bool(opts.get("demo"))
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        BATCH.set_message(f"Cannot use that folder: {exc}")
        with BATCH.lock:
            BATCH.running = False
        return

    auth = headers = None
    if not demo:
        try:
            auth = ready_auth()
            headers = auth_headers(auth)
        except Exception as exc:
            BATCH.set_message(str(exc))
            with BATCH.lock:
                BATCH.running = False
            return

    per_prompt = max(1, int(opts.get("count", 1)))
    prefix = safe_name(opts.get("prefix") or "img")
    total = len(BATCH.items)
    completed = 0

    for idx, item in enumerate(list(BATCH.items)):
        if BATCH.cancel.is_set():
            BATCH.update(idx, status="stopped")
            continue
        prompt = prompts[item["prompt_index"]]
        BATCH.update(idx, status="running", started=time.time())
        BATCH.set_message(f"Generating {idx + 1} of {total} ...")
        t0 = time.time()

        attempt = 0
        while True:
            try:
                if demo:
                    time.sleep(0.35)
                    encoded = demo_png(idx)
                else:
                    payload = build_payload(
                        prompt, opts["size"], opts["quality"], opts["background"],
                        f"vegtoon-batch-{idx}",
                    )
                    encoded = stream_one_image(headers, payload, 600.0, BATCH.cancel)
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and not demo and attempt == 0:
                    try:
                        auth = refresh_auth(load_auth())
                        headers = auth_headers(auth)
                        attempt += 1
                        continue
                    except Exception as inner:
                        BATCH.update(idx, status="failed", error=f"Sign-in expired: {inner}")
                        break
                BATCH.update(idx, status="failed", error=f"HTTP {exc.code}: {exc.reason}")
                break
            except RateLimited as exc:
                delay = exc.delay
                if delay is None or attempt >= MAX_RETRIES:
                    BATCH.update(idx, status="failed", error=str(exc))
                    break
                attempt += 1
                BATCH.update(idx, status="waiting",
                             error=f"Rate limited — retrying in {delay:.0f}s ({attempt}/{MAX_RETRIES})")
                BATCH.set_message(f"Rate limited. Waiting {delay:.0f}s before retry {attempt}.")
                waited = 0.0
                while waited < delay and not BATCH.cancel.is_set():
                    time.sleep(0.5)
                    waited += 0.5
                if BATCH.cancel.is_set():
                    BATCH.update(idx, status="stopped")
                    break
                BATCH.update(idx, status="running", error="")
                continue
            except Exception as exc:
                BATCH.update(idx, status="failed", error=str(exc)[:300])
                break

        with BATCH.lock:
            status_now = BATCH.items[idx]["status"]
        if status_now in ("failed", "stopped"):
            continue

        name = f"{prefix}-{item['prompt_index'] + 1:03d}"
        if per_prompt > 1:
            name += f"-{item['copy_index'] + 1}"
        target = out_dir / f"{name}.png"
        n = 2
        while target.exists():
            target = out_dir / f"{name}-{n}.png"
            n += 1
        try:
            target.write_bytes(base64.b64decode(encoded))
        except Exception as exc:
            BATCH.update(idx, status="failed", error=f"Could not save file: {exc}")
            continue

        completed += 1
        BATCH.update(idx, status="done", file=str(target), name=target.name,
                     seconds=round(time.time() - t0, 1), error="")

    with BATCH.lock:
        BATCH.running = False
        if BATCH.cancel.is_set():
            BATCH.message = f"Stopped. {completed} of {total} saved to {out_dir}"
        else:
            failed = sum(1 for i in BATCH.items if i["status"] == "failed")
            BATCH.message = (
                f"Finished. {completed} of {total} saved to {out_dir}"
                + (f" — {failed} failed." if failed else ".")
            )
    log(BATCH.message)
    if not demo:
        threading.Thread(target=send_report, args=("run finished",), daemon=True).start()


# ============================================================================
# Folder picker (separate process so tkinter never fights the web server)
# ============================================================================

PICKER_CODE = (
    "import tkinter as tk\n"
    "from tkinter import filedialog\n"
    "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
    "p = filedialog.askdirectory(title='Choose the output folder')\n"
    "print(p or '')\n"
)


def pick_folder(initial):
    try:
        out = subprocess.run(
            [sys.executable, "-c", PICKER_CODE],
            capture_output=True, text=True, timeout=300,
        )
        chosen = (out.stdout or "").strip().splitlines()
        return chosen[-1].strip() if chosen and chosen[-1].strip() else None
    except Exception as exc:
        log(f"folder picker unavailable: {exc}")
        return None


def open_folder(path):
    try:
        p = str(Path(path).expanduser())
        if os.name == "nt":
            os.startfile(p)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
        return True
    except Exception as exc:
        log(f"could not open folder: {exc}")
        return False


# ============================================================================
# Sign-in
# ============================================================================

CODEX_AUTH_URL = "https://auth.openai.com/oauth/authorize"
CALLBACK_PORT = 1455
CALLBACK_PATH = "/auth/callback"
OAUTH_SCOPE = ("openid profile email offline_access "
               "api.connectors.read api.connectors.invoke")


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(os.urandom(64)).decode("ascii").rstrip("=")
    import hashlib
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    return verifier, challenge


def _exchange_code(code: str, verifier: str) -> dict:
    """Swap the one-time code for tokens. Tries JSON, falls back to form encoding."""
    fields = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}",
        "client_id": CODEX_CLIENT_ID,
        "code_verifier": verifier,
    }
    last = None
    for body, ctype in (
        (json.dumps(fields).encode("utf-8"), "application/json"),
        (urllib.parse.urlencode(fields).encode("utf-8"), "application/x-www-form-urlencoded"),
    ):
        try:
            req = urllib.request.Request(
                CODEX_REFRESH_URL, data=body, method="POST",
                headers={"Content-Type": ctype, "Accept": "application/json",
                         "User-Agent": f"{CODEX_ORIGINATOR}/{APP_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"
        except Exception as exc:
            last = str(exc)
    raise RuntimeError(f"Could not complete sign-in: {last}")


def _write_auth(tokens: dict):
    id_raw = tokens.get("id_token")
    claims = {}
    if isinstance(id_raw, str) and id_raw:
        payload = jwt_payload(id_raw)
        extra = payload.get("https://api.openai.com/auth")
        claims = dict(payload)
        if isinstance(extra, dict):
            claims.update(extra)
    blob = {
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": claims or id_raw,
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "account_id": claims.get("chatgpt_account_id"),
        },
        "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    path = auth_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")
    return blob


def builtin_login():
    """Sign in without Codex: PKCE + the same local callback the Codex CLI uses."""
    verifier, challenge = _pkce_pair()
    state = base64.urlsafe_b64encode(os.urandom(24)).decode("ascii").rstrip("=")
    params = {
        "response_type": "code",
        "client_id": CODEX_CLIENT_ID,
        "redirect_uri": f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}",
        "scope": OAUTH_SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "state": state,
        "originator": CODEX_ORIGINATOR,
    }
    url = f"{CODEX_AUTH_URL}?{urllib.parse.urlencode(params)}"
    result = {"code": None, "error": None}
    done = threading.Event()

    class CB(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if not parsed.path.startswith(CALLBACK_PATH):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            q = urllib.parse.parse_qs(parsed.query)
            if q.get("state", [None])[0] != state:
                result["error"] = "Sign-in came back with the wrong state. Try again."
            elif q.get("error"):
                result["error"] = q["error"][0]
            else:
                result["code"] = q.get("code", [None])[0]
                if not result["code"]:
                    result["error"] = "Sign-in came back without a code."
            page = (b"<html><body style='font-family:system-ui;background:#0d1117;color:#e8edf4;"
                    b"text-align:center;padding-top:80px'><h2>"
                    + (b"Signed in. You can close this tab and go back to the app."
                       if result["code"] else b"Sign-in failed. Go back to the app and try again.")
                    + b"</h2></body></html>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            done.set()

    try:
        cb = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), CB)
    except OSError as exc:
        raise RuntimeError(
            f"Port {CALLBACK_PORT} is busy ({exc}). Close any Codex window and try again."
        )

    threading.Thread(target=cb.serve_forever, daemon=True).start()
    with SETUP_LOCK:
        SETUP["auth_url"] = url
    setup_msg("Your browser should open the ChatGPT sign-in page. "
              "If it doesn't, use the blue link below.")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    ok = done.wait(timeout=600)
    try:
        cb.shutdown()
    except Exception:
        pass
    with SETUP_LOCK:
        SETUP["auth_url"] = ""

    if not ok:
        raise RuntimeError("Sign-in timed out after 10 minutes.")
    if result["error"]:
        raise RuntimeError(result["error"])

    setup_msg("Finishing sign-in ...")
    tokens = _exchange_code(result["code"], verifier)
    if not tokens.get("access_token"):
        raise RuntimeError("Sign-in did not return an access token.")
    _write_auth(tokens)
    setup_msg("Signed in.")


def do_login():
    """Built-in sign-in first; the Codex CLI only as a fallback."""
    with SETUP_LOCK:
        if SETUP["busy"]:
            return
        SETUP["busy"] = True
        SETUP["error"] = ""
    try:
        builtin_login()
    except Exception as exc:
        log(f"built-in sign-in failed: {exc}")
        setup_msg("Built-in sign-in did not work — trying the Codex method.", "")
        try:
            codex_login()
        except Exception as inner:
            setup_msg("Sign-in failed.", f"{exc} / {inner}")
    finally:
        with SETUP_LOCK:
            SETUP["busy"] = False


def codex_login():
    """Fallback: install Codex if needed, then run `codex login` and wait for the token."""
    binary = find_codex()
    if not binary:
        setup_msg("Fetching the official Codex sign-in tool (one time only).")
        binary = install_codex(lambda m: setup_msg(m))

    setup_msg("Starting the Codex sign-in ...")
    before = auth_file().stat().st_mtime if auth_file().exists() else 0

    # stdin MUST be a real handle. Double-clicked on Windows the inherited one can be
    # invalid, and Codex then fails with "runner: no pipe-in provided".
    creation = 0
    if os.name == "nt":
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        [binary, "login"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=dict(os.environ), creationflags=creation,
    )

    def drain():
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                log(f"codex: {line}")
                found = re.search(r"(https://auth\.openai\.com/\S+)", line)
                if found:
                    with SETUP_LOCK:
                        SETUP["auth_url"] = found.group(1)
                    setup_msg("Use the blue sign-in link below.")
                    try:
                        webbrowser.open(found.group(1))
                    except Exception:
                        pass
        except Exception:
            pass

    threading.Thread(target=drain, daemon=True).start()

    deadline = time.time() + 600
    while time.time() < deadline:
        if auth_file().exists() and auth_file().stat().st_mtime > before:
            auth = load_auth()
            if auth and access_token(auth):
                with SETUP_LOCK:
                    SETUP["auth_url"] = ""
                setup_msg("Signed in.")
                try:
                    proc.terminate()
                except Exception:
                    pass
                return
        time.sleep(1)
    try:
        proc.terminate()
    except Exception:
        pass
    raise RuntimeError("Codex sign-in timed out after 10 minutes.")


# ============================================================================
# Web UI
# ============================================================================

PAGE = r"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__APP__</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#127814;</text></svg>">
<style>
:root{--bg:#0d1117;--panel:#161c27;--panel2:#1b222e;--line:#26303f;--line2:#33415a;
--ink:#e8edf4;--muted:#9aa7b8;--faint:#6b7888;--marigold:#ffae3b;--leaf:#5bd07a;--chili:#ff5a5a;--sky:#5ab0ff;
--mono:ui-monospace,'Cascadia Code',Consolas,monospace;--sans:'Segoe UI',system-ui,-apple-system,Roboto,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1100px 520px at 82% -12%,#16202e 0,var(--bg) 55%) fixed,var(--bg);
color:var(--ink);font-family:var(--sans);line-height:1.6;font-size:15px}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
header{border-bottom:1px solid var(--line);padding:20px 0 16px;background:linear-gradient(180deg,rgba(255,174,59,.06),transparent)}
h1{margin:6px 0 2px;font-size:26px;letter-spacing:-.02em}
.kicker{font-size:11.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--marigold)}
.who{color:var(--muted);font-size:13.5px;margin-top:4px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:16px 0}
label{display:block;font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--faint);font-weight:700;margin-bottom:5px}
textarea,input,select{width:100%;background:#0a0e14;border:1px solid var(--line2);color:var(--ink);
border-radius:9px;padding:10px 12px;font-family:var(--sans);font-size:14px;outline:none}
textarea{min-height:230px;font-family:var(--mono);font-size:12.5px;line-height:1.65;resize:vertical}
textarea:focus,input:focus,select:focus{border-color:var(--marigold)}
.row{display:grid;gap:12px;margin-top:14px}
.r4{grid-template-columns:repeat(4,1fr)}.r3{grid-template-columns:2fr 1fr 1fr}
@media(max-width:760px){.r4,.r3{grid-template-columns:1fr 1fr}}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--marigold);color:#1a1206;
font-weight:800;border:1px solid transparent;border-radius:999px;padding:11px 22px;font-size:14.5px;cursor:pointer;font-family:var(--sans)}
.btn:hover{filter:brightness(1.08)}
.btn:disabled{opacity:.45;cursor:not-allowed;filter:none}
.btn.ghost{background:transparent;color:var(--ink);border-color:var(--line2)}
.btn.ghost:hover{border-color:var(--marigold);background:var(--panel2);filter:none}
.btn.danger{background:var(--chili);color:#2a0c0c}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:16px}
.note{background:rgba(255,174,59,.07);border:1px solid rgba(255,174,59,.25);border-radius:12px;
padding:13px 15px;color:#f0e4cf;font-size:13.5px}
.note.bad{background:rgba(255,90,90,.08);border-color:rgba(255,90,90,.3);color:#f6dada}
.note.good{background:rgba(91,208,122,.08);border-color:rgba(91,208,122,.32);color:#dff0e4}
.status{font-size:13.5px;color:var(--muted);margin-top:10px;min-height:20px}
.prog{height:7px;background:#0a0e14;border:1px solid var(--line);border-radius:99px;overflow:hidden;margin-top:12px}
.prog i{display:block;height:100%;background:linear-gradient(90deg,var(--marigold),var(--leaf));width:0;transition:width .3s}
.jobs{margin-top:14px;display:grid;gap:7px;max-height:420px;overflow-y:auto}
.job{display:grid;grid-template-columns:34px 1fr auto;gap:11px;align-items:center;
background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:13px}
.job .n{font-family:var(--mono);color:var(--faint);font-size:11.5px}
.job .p{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.job .s{font-size:11px;font-weight:700;padding:2px 9px;border-radius:99px;border:1px solid var(--line2);color:var(--muted);white-space:nowrap}
.job.done{border-color:rgba(91,208,122,.35)} .job.done .s{color:var(--leaf);border-color:rgba(91,208,122,.4)}
.job.running .s{color:var(--marigold);border-color:rgba(255,174,59,.45)}
.job.waiting .s{color:var(--sky);border-color:rgba(90,176,255,.45)}
.job.failed{border-color:rgba(255,90,90,.35)} .job.failed .s{color:var(--chili);border-color:rgba(255,90,90,.4)}
.job .err{grid-column:2/4;color:var(--chili);font-size:11.5px}
.hint{color:var(--faint);font-size:12.5px;margin-top:7px}
.chk{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px;cursor:pointer}
.chk input{width:auto}
footer{color:var(--faint);font-size:12px;padding:22px 0 34px}
.hide{display:none}
</style></head><body>
<header><div class="wrap">
<div class="kicker">&#127814; Bulk image generation &middot; runs on your ChatGPT plan</div>
<h1>__APP__</h1>
<div class="who" id="who">Checking sign-in ...</div>
</div></header>
<div class="wrap">

<div class="note good hide" id="updBanner" style="margin:16px 0"></div>

<div class="card" id="authCard">
  <div class="note" id="authNote">Checking ...</div>
  <div class="bar">
    <button class="btn" id="loginBtn">Sign in with ChatGPT</button>
    <button class="btn ghost" id="recheckBtn">Re-check</button>
  </div>
  <div class="status" id="authStatus"></div>
  <div id="authLinkWrap" class="hide" style="margin-top:12px">
    <a class="btn" id="authLink" target="_blank" rel="noopener">Open the ChatGPT sign-in page</a>
    <div class="hint">If nothing opened by itself, click the button above. You can also copy this
      address into any browser <b>on this PC</b>:</div>
    <div class="hint" style="word-break:break-all;color:var(--sky)" id="authUrlText"></div>
  </div>
</div>

<div class="card">
  <label for="prompts">Prompts &mdash; one per line (or separate longer ones with a line containing only <b>---</b>)</label>
  <textarea id="prompts" placeholder="A photoreal 3D render of ...&#10;Another prompt on the next line ..."></textarea>
  <div class="hint" id="countHint">0 prompts</div>

  <div class="row r3">
    <div><label for="outdir">Output folder</label><input id="outdir" spellcheck="false"></div>
    <div><label for="prefix">File name prefix</label><input id="prefix" spellcheck="false"></div>
    <div style="display:flex;align-items:flex-end;gap:8px">
      <button class="btn ghost" id="browseBtn" style="flex:1">Browse</button>
      <button class="btn ghost" id="openBtn" title="Open the folder">Open</button>
    </div>
  </div>

  <div class="row r4">
    <div><label for="size">Shape</label><select id="size">
      <option value="1024x1536">Portrait 2:3 &mdash; for 9:16 shorts</option>
      <option value="1536x1024">Landscape 3:2</option>
      <option value="1024x1024">Square 1:1</option>
      <option value="auto">Auto</option>
    </select></div>
    <div><label for="quality">Quality</label><select id="quality">
      <option value="high">High</option><option value="medium">Medium</option>
      <option value="low">Low</option><option value="auto">Auto</option>
    </select></div>
    <div><label for="background">Background</label><select id="background">
      <option value="auto">Auto</option><option value="opaque">Opaque</option>
      <option value="transparent">Transparent</option>
    </select></div>
    <div><label for="count">Images per prompt</label><input id="count" type="number" min="1" max="8" value="1"></div>
  </div>

  <div class="bar">
    <button class="btn" id="goBtn">Generate</button>
    <button class="btn danger hide" id="stopBtn">Stop</button>
    <label class="chk"><input type="checkbox" id="demo"> Test run (no ChatGPT, writes placeholder images)</label>
  </div>
  <div class="prog"><i id="progBar"></i></div>
  <div class="status" id="status">Ready.</div>
  <div class="jobs" id="jobs"></div>
</div>

<div class="card" id="helpCard">
  <label>If something goes wrong</label>
  <div class="bar" style="margin-top:2px">
    <button class="btn ghost" id="reportBtn">Send a report to Claude</button>
    <button class="btn ghost" id="samplesBtn">Send 3 sample images</button>
    <button class="btn ghost" id="updBtn">Check for an update</button>
  </div>
  <div class="status" id="helpStatus"></div>
  <label class="chk" style="margin-top:10px"><input type="checkbox" id="reporting" checked>
    Send a report automatically after each real run</label>
  <div class="hint">A report contains: app / Windows / Python version, whether sign-in worked, your batch settings, each prompt's status, error and timing, and the lines you can see in the black window. It never contains your password, your sign-in token, or your files.</div>
</div>

<footer><span id="verLine">__APP__ v__VER__</span> &middot; images are generated by ChatGPT and count against your ChatGPT plan's limits &middot; close this tab and the black window to quit</footer>
</div>
<script>
const T = "__TOKEN__";
const $ = s => document.querySelector(s);
const api = (path, body) => fetch(path + (path.includes('?') ? '&' : '?') + 't=' + T, body ? {
  method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
} : {}).then(r => r.json());

function splitPrompts(raw){
  const text = (raw || '').replace(/\r/g, '');
  const parts = /^---$/m.test(text) ? text.split(/^---$/m) : text.split('\n');
  return parts.map(p => p.trim()).filter(Boolean);
}
function refreshCount(){
  const n = splitPrompts($('#prompts').value).length;
  const per = Math.max(1, parseInt($('#count').value) || 1);
  $('#countHint').textContent = n + (n === 1 ? ' prompt' : ' prompts')
    + (per > 1 ? ' × ' + per + ' = ' + (n * per) + ' images' : '');
}
$('#prompts').addEventListener('input', refreshCount);
$('#count').addEventListener('input', refreshCount);

let authed = false;
function renderAuth(s){
  authed = s.authed;
  const note = $('#authNote');
  if (s.authed){
    $('#authCard').classList.add('hide');
    $('#who').textContent = 'Signed in' + (s.email ? ' as ' + s.email : '')
      + (s.plan ? ' · ' + s.plan + ' plan' : '');
  } else {
    $('#authCard').classList.remove('hide');
    $('#who').textContent = 'Not signed in';
    note.className = 'note';
    note.innerHTML = 'Press <b>Sign in with ChatGPT</b>. Your browser opens the normal ChatGPT '
      + 'sign-in page and comes straight back. Nothing to download, and this app never sees '
      + 'your password &mdash; it only keeps the sign-in token ChatGPT hands back.';
  }
  if (s.setup_error){
    const n = $('#authNote'); n.className = 'note bad'; n.textContent = s.setup_error;
    $('#authCard').classList.remove('hide');
  }
  $('#authStatus').textContent = s.setup_message || '';
  const wrap = $('#authLinkWrap');
  if (s.auth_url){
    wrap.classList.remove('hide');
    $('#authLink').href = s.auth_url;
    $('#authUrlText').textContent = s.auth_url;
    $('#authCard').classList.remove('hide');
  } else { wrap.classList.add('hide'); }
  $('#loginBtn').disabled = !!s.setup_busy;
  $('#loginBtn').textContent = s.setup_busy ? 'Working ...' : 'Sign in with ChatGPT';
}

function renderBatch(b){
  const running = b.running;
  $('#goBtn').classList.toggle('hide', running);
  $('#stopBtn').classList.toggle('hide', !running);
  const total = b.items.length;
  const done = b.items.filter(i => i.status === 'done').length;
  $('#progBar').style.width = total ? (done * 100 / total) + '%' : '0';
  if (b.message) $('#status').textContent = b.message;
  const box = $('#jobs');
  box.innerHTML = '';
  b.items.forEach((it, i) => {
    const el = document.createElement('div');
    el.className = 'job ' + it.status;
    const label = {queued:'queued', running:'generating', waiting:'waiting',
                   done:'saved', failed:'failed', stopped:'stopped'}[it.status] || it.status;
    el.innerHTML = '<div class="n">' + (i + 1) + '</div>'
      + '<div class="p" title="' + esc(it.prompt) + '">'
      + (it.status === 'done' && it.name ? '<b>' + esc(it.name) + '</b> — ' : '')
      + esc(it.prompt.slice(0, 110)) + '</div>'
      + '<div class="s">' + label + (it.seconds ? ' ' + it.seconds + 's' : '') + '</div>'
      + (it.error ? '<div class="err">' + esc(it.error) + '</div>' : '');
    box.appendChild(el);
  });
}
function esc(s){ return (s || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

async function poll(){
  try {
    const s = await api('/api/status');
    renderAuth(s);
    renderBatch(s.batch);
    if (s.settings && !$('#outdir').value){
      $('#outdir').value = s.settings.out_dir;
      $('#prefix').value = s.settings.prefix;
      $('#size').value = s.settings.size;
      $('#quality').value = s.settings.quality;
      $('#background').value = s.settings.background;
      $('#count').value = s.settings.count;
      $('#reporting').checked = s.settings.report !== false;
      refreshCount();
    }
    if (s.version) $('#verLine').textContent = '__APP__ v' + s.version;
    renderUpdate(s.update, s.version);
  } catch (e) {
    $('#status').textContent = 'Lost contact with the app. Is the black window still open?';
  }
}
setInterval(poll, 1200); poll();

function renderUpdate(u, cur){
  const box = $('#updBanner');
  if (!u || !u.newer){ box.classList.add('hide'); return; }
  box.classList.remove('hide');
  box.innerHTML = '<b>Version ' + esc(u.latest) + ' is ready</b> (you have ' + esc(cur || '') + ').'
    + (u.notes ? ' ' + esc(u.notes) : '')
    + ' <button class="btn" id="doUpd" style="margin-left:10px;padding:6px 16px">Update now</button>';
  $('#doUpd').onclick = async () => {
    $('#doUpd').disabled = true; $('#doUpd').textContent = 'Updating ...';
    const r = await api('/api/update-apply', {});
    box.className = 'note good'; box.textContent = r.message || 'Done.';
  };
}

async function help(path, btn, label, body){
  const b = $(btn); const old = b.textContent;
  b.disabled = true; b.textContent = label;
  const r = await api(path, body || {});
  b.disabled = false; b.textContent = old;
  $('#helpStatus').textContent = r.message || r.error || 'Done.';
}
$('#reportBtn').onclick = () => help('/api/report', '#reportBtn', 'Sending ...');
$('#samplesBtn').onclick = () => help('/api/samples', '#samplesBtn', 'Uploading ...');
$('#updBtn').onclick = async () => {
  const b = $('#updBtn'); b.disabled = true; b.textContent = 'Checking ...';
  const r = await api('/api/update-check', {});
  b.disabled = false; b.textContent = 'Check for an update';
  $('#helpStatus').textContent = r.error ? ('Could not check: ' + r.error)
    : (r.newer ? ('Version ' + r.latest + ' is available.') : 'You are on the newest version.');
  poll();
};
$('#reporting').onchange = () => api('/api/reporting', {on: $('#reporting').checked});

$('#loginBtn').onclick = async () => { $('#loginBtn').disabled = true; await api('/api/login', {}); poll(); };
$('#recheckBtn').onclick = poll;
$('#browseBtn').onclick = async () => {
  $('#browseBtn').disabled = true; $('#browseBtn').textContent = 'Choosing ...';
  const r = await api('/api/pick', {current: $('#outdir').value});
  $('#browseBtn').disabled = false; $('#browseBtn').textContent = 'Browse';
  if (r.path) $('#outdir').value = r.path;
  else if (r.error) $('#status').textContent = r.error;
};
$('#openBtn').onclick = () => api('/api/open', {path: $('#outdir').value});
$('#stopBtn').onclick = () => api('/api/stop', {});
$('#goBtn').onclick = async () => {
  const prompts = splitPrompts($('#prompts').value);
  if (!prompts.length){ $('#status').textContent = 'Put at least one prompt in the box.'; return; }
  if (!$('#outdir').value.trim()){ $('#status').textContent = 'Choose an output folder.'; return; }
  if (!authed && !$('#demo').checked){ $('#status').textContent = 'Sign in first.'; return; }
  $('#goBtn').disabled = true;
  const r = await api('/api/start', {
    prompts, out_dir: $('#outdir').value.trim(), prefix: $('#prefix').value.trim() || 'img',
    size: $('#size').value, quality: $('#quality').value, background: $('#background').value,
    count: Math.max(1, parseInt($('#count').value) || 1), demo: $('#demo').checked
  });
  $('#goBtn').disabled = false;
  if (r.error) $('#status').textContent = r.error;
  poll();
};
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj))

    def _authorized(self):
        query = urllib.parse.urlparse(self.path).query
        return urllib.parse.parse_qs(query).get("t", [None])[0] == SESSION_TOKEN

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            page = (PAGE.replace("__APP__", APP_NAME)
                        .replace("__VER__", APP_VERSION)
                        .replace("__TOKEN__", SESSION_TOKEN))
            self._send(200, page, "text/html; charset=utf-8")
            return
        if path == "/api/status":
            if not self._authorized():
                self._json({"error": "bad token"}, 403)
                return
            auth = load_auth()
            token = access_token(auth) if auth else None
            with SETUP_LOCK:
                setup = dict(SETUP)
            self._json({
                "authed": bool(token),
                "email": account_email(auth) if auth else None,
                "plan": account_plan(auth) if auth else None,
                "codex": bool(find_codex()),
                "setup_busy": setup["busy"],
                "setup_message": setup["message"],
                "setup_error": setup["error"],
                "auth_url": setup.get("auth_url", ""),
                "settings": load_settings(),
                "batch": BATCH.snapshot(),
                "version": APP_VERSION,
                "update": {
                    "latest": UPDATE["latest"],
                    "notes": UPDATE["notes"],
                    "newer": bool(UPDATE["latest"])
                             and version_tuple(UPDATE["latest"]) > version_tuple(APP_VERSION),
                },
            })
            return
        self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._authorized():
            self._json({"error": "bad token"}, 403)
            return
        body = self._body()

        if path == "/api/login":
            threading.Thread(target=do_login, daemon=True).start()
            self._json({"ok": True})
            return

        if path == "/api/pick":
            chosen = pick_folder(body.get("current"))
            if chosen:
                self._json({"path": chosen})
            else:
                self._json({"path": None,
                            "error": "Folder chooser did not open. Type the folder path instead."})
            return

        if path == "/api/open":
            self._json({"ok": open_folder(body.get("path") or str(HOME))})
            return

        if path == "/api/report":
            self._json({"message": send_report(note=body.get("note") or "sent by hand", force=True)})
            return

        if path == "/api/samples":
            self._json({"message": send_samples()})
            return

        if path == "/api/update-check":
            info = check_update(force=True)
            newer = bool(info["latest"]) and version_tuple(info["latest"]) > version_tuple(APP_VERSION)
            self._json({"latest": info["latest"], "notes": info["notes"],
                        "error": info["error"], "newer": newer})
            return

        if path == "/api/update-apply":
            self._json({"message": apply_update()})
            return

        if path == "/api/reporting":
            save_settings({"report": bool(body.get("on"))})
            self._json({"ok": True})
            return

        if path == "/api/stop":
            BATCH.cancel.set()
            BATCH.set_message("Stopping after the current image ...")
            self._json({"ok": True})
            return

        if path == "/api/start":
            with BATCH.lock:
                if BATCH.running:
                    self._json({"error": "A batch is already running."})
                    return
            prompts = [p for p in (body.get("prompts") or []) if isinstance(p, str) and p.strip()]
            if not prompts:
                self._json({"error": "No prompts."})
                return
            opts = {
                "out_dir": body.get("out_dir") or str(HOME),
                "prefix": body.get("prefix") or "img",
                "size": body.get("size") if body.get("size") in SIZES else "1024x1536",
                "quality": body.get("quality") if body.get("quality") in QUALITIES else "high",
                "background": body.get("background") if body.get("background") in BACKGROUNDS else "auto",
                "count": max(1, min(8, int(body.get("count") or 1))),
                "demo": bool(body.get("demo")),
            }
            try:
                Path(opts["out_dir"]).expanduser().mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                self._json({"error": f"Cannot use that output folder: {exc}"})
                return
            save_settings(opts)
            items = []
            for pi, prompt in enumerate(prompts):
                for ci in range(opts["count"]):
                    items.append({
                        "prompt_index": pi, "copy_index": ci,
                        "prompt": prompt, "status": "queued",
                        "error": "", "name": "", "file": "", "seconds": 0,
                    })
            with BATCH.lock:
                BATCH.items = items
                BATCH.running = True
                BATCH.cancel = threading.Event()
                BATCH.message = "Starting ..."
                BATCH.out_dir = opts["out_dir"]
                BATCH.started_at = time.time()
            threading.Thread(target=run_batch, args=(prompts, opts), daemon=True).start()
            self._json({"ok": True, "queued": len(items)})
            return

        self._json({"error": "unknown endpoint"}, 404)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    if sys.version_info < (3, 9):
        print("This needs Python 3.9 or newer. Install it from python.org and try again.", flush=True)
        input("Press Enter to close ...")
        return

    APP_DIR.mkdir(parents=True, exist_ok=True)
    port = free_port()
    url = f"http://127.0.0.1:{port}/?t={SESSION_TOKEN}"
    server = Server(("127.0.0.1", port), Handler)

    print("=" * 66, flush=True)
    print(f"  {APP_NAME} v{APP_VERSION}")
    print("=" * 66, flush=True)
    print("  Your browser should open by itself. If it doesn't, paste this in:")
    print(f"  {url}")
    print()
    print("  Keep this window open while you work. Close it to quit.")
    print("=" * 66, flush=True)
    print()

    threading.Thread(target=lambda: (time.sleep(0.6), webbrowser.open(url)), daemon=True).start()
    threading.Thread(target=lambda: check_update(force=True), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nClosing.")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
