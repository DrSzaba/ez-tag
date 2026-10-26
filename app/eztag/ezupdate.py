"""
EZ apps - automatic updates from GitHub.

Shared by EZ Video Maker and EZ Password Manager (one copy in each app).

How it works
  * Every release on GitHub carries a setup zip (e.g. EZ-Video-Maker-Setup.zip).
  * .../releases/latest/download/<zip> redirects to .../releases/download/<tag>/<zip>,
    so one request tells us the newest version AND proves the file is really there.
  * A newer version is downloaded in the background. The app then offers
    "Restart & update now"; if you don't click it, the update installs by itself
    when you close the app.
  * The setup runs quietly (/S). With /UPDATE it opens the app again afterwards.

Only the Python standard library is used. Nothing here touches your files or
settings - the setup only replaces the program files.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

IS_WIN = sys.platform.startswith("win")
USER_AGENT = "EZ-Apps-Updater/1.0"
CHECK_EVERY_HOURS = 6


def _base():
    # test hook: point at a pretend GitHub
    return os.environ.get("EZ_UPDATE_BASE", "https://github.com").rstrip("/")


def version_tuple(v):
    nums = re.findall(r"\d+", str(v or ""))[:4]
    t = tuple(int(n) for n in nums)
    return t + (0,) * (3 - len(t)) if len(t) < 3 else t


def is_newer(latest, current):
    return bool(latest) and version_tuple(latest) > version_tuple(current)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Updater:
    """One app's updater. All network work happens on background threads."""

    def __init__(self, app_name, version, repo, zip_name, data_dir):
        self.app_name = app_name
        self.version = version
        self.repo = repo                  # "DrSzaba/ez-video-maker"
        self.zip_name = zip_name          # "EZ-Video-Maker-Setup.zip"
        self.data_dir = data_dir
        self.latest = None                # newest version on GitHub (after a check)
        self.ready_setup = None           # path of a downloaded setup waiting to run
        self.ready_version = None
        self.error = None
        self.busy = False
        self._restart = False
        self._lock = threading.Lock()

    # ---------------- finding the newest version ----------------
    def zip_url(self):
        return f"{_base()}/{self.repo}/releases/latest/download/{self.zip_name}"

    def find_latest(self, timeout=20):
        """Newest released version that actually has its setup zip attached.
        Returns (version, direct download url) or (None, None)."""
        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(self.zip_url(), method="HEAD",
                                     headers={"User-Agent": USER_AGENT})
        try:
            resp = opener.open(req, timeout=timeout)
            loc = resp.geturl()
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                loc = e.headers.get("Location", "")
            elif e.code == 404:
                return None, None         # newest release has no setup zip attached
            else:
                raise
        m = re.search(r"/releases/download/([^/]+)/", loc or "")
        if not m:
            return None, None
        tag = urllib.request.unquote(m.group(1))
        ver = ".".join(str(n) for n in version_tuple(tag))
        if not re.search(r"\d", tag):
            return None, None
        if loc.startswith("/"):
            loc = _base() + loc
        return ver, loc

    def _stamp(self):
        return os.path.join(self.data_dir, "update-check.txt")

    def due(self):
        try:
            with open(self._stamp(), encoding="utf-8") as fh:
                last = float(fh.read().strip() or 0)
            return time.time() - last > CHECK_EVERY_HOURS * 3600
        except Exception:
            return True

    def _mark(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(self._stamp(), "w", encoding="utf-8") as fh:
                fh.write(str(time.time()))
        except Exception:
            pass

    # ---------------- downloading ----------------
    def _download(self, url, version, progress=None):
        folder = os.path.join(tempfile.gettempdir(),
                              re.sub(r"\W+", "-", self.app_name) + "-update-" + version)
        os.makedirs(folder, exist_ok=True)
        zpath = os.path.join(folder, self.zip_name)
        part = zpath + ".part"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp, open(part, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            last = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if progress and total and time.time() - last > 0.3:
                    progress(got * 100.0 / total)
                    last = time.time()
        if total and os.path.getsize(part) != total:
            raise IOError("the download was incomplete")
        os.replace(part, zpath)
        with zipfile.ZipFile(zpath) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".exe")]
            pick = [n for n in names if "setup" in os.path.basename(n).lower()] or names
            if not pick:
                raise IOError("the update file has no setup program in it")
            name = pick[0]
            target = os.path.join(folder, os.path.basename(name))
            with z.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        if progress:
            progress(100.0)
        return target

    # ---------------- the whole check ----------------
    def check(self, download=True, progress=None):
        """Find the newest version and (if newer) download it.
        Returns one of: 'newer-ready', 'up-to-date', 'no-release', 'error'."""
        with self._lock:
            if self.busy:
                return "busy"
            self.busy = True
        try:
            self.error = None
            ver, url = self.find_latest()
            self._mark()
            self.latest = ver
            if not ver:
                return "no-release"
            if not is_newer(ver, self.version):
                return "up-to-date"
            if not download:
                return "newer"
            if self.ready_setup and self.ready_version == ver and os.path.isfile(self.ready_setup):
                return "newer-ready"
            self.ready_setup = self._download(url, ver, progress)
            self.ready_version = ver
            return "newer-ready"
        except Exception as e:
            self.error = friendly(e)
            return "error"
        finally:
            self.busy = False

    def check_in_background(self, on_done, download=True, progress=None):
        def run():
            result = self.check(download=download, progress=progress)
            on_done(result)
        threading.Thread(target=run, daemon=True).start()

    # ---------------- installing ----------------
    def request_restart(self):
        self._restart = True

    def run_pending_setup(self):
        """Call when the app is closing. Starts the quiet setup if an update was
        downloaded. Returns True if a setup was started."""
        if not self.ready_setup or not os.path.isfile(self.ready_setup):
            return False
        args = [self.ready_setup, "/S"] + (["/UPDATE"] if self._restart else [])
        if not IS_WIN:
            return False                  # tests: nothing to run on Linux
        flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(args, close_fds=True, creationflags=flags,
                         cwd=os.path.dirname(self.ready_setup))
        return True


def friendly(e):
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return "the newest release doesn't have its setup file yet"
        return f"GitHub answered with error {e.code}"
    if isinstance(e, urllib.error.URLError):
        return "can't reach GitHub - check your internet"
    if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
        return "GitHub took too long to answer"
    return str(e) or e.__class__.__name__


# ====================================================================
# Ready-made pieces for tkinter apps
# ====================================================================

def attach_to_tk(root, updater, bar_parent, colors, font, on_close_chain=None):
    """Start the automatic check and show a bar when an update is ready.
    colors: dict with keys bg, fg, button, button_fg.  Returns the bar frame.
    on_close_chain: the app's own close function (called first)."""
    import tkinter as tk

    bar = tk.Frame(bar_parent, bg=colors["bg"])
    msg = tk.Label(bar, text="", bg=colors["bg"], fg=colors["fg"], font=(font, 11, "bold"))
    msg.pack(side="left", padx=(16, 10), pady=7)
    btn = tk.Button(bar, text="Restart & update now", bg=colors["button"], fg=colors["button_fg"],
                    activebackground=colors["button"], activeforeground=colors["button_fg"],
                    relief="flat", font=(font, 10, "bold"), cursor="hand2", padx=14, pady=3)
    btn.pack(side="left", pady=6)
    later = tk.Label(bar, text="(or it updates by itself when you close the app)", bg=colors["bg"],
                     fg=colors["fg"], font=(font, 9, "italic"))
    later.pack(side="left", padx=10)
    state = {"shown": False}

    def show_ready():
        if state["shown"]:
            return
        state["shown"] = True
        msg.config(text=f"⬆  Version {updater.ready_version} of {updater.app_name} is ready.")
        btn.config(command=restart_now)
        others = [w for w in bar_parent.pack_slaves() if w is not bar]
        if others:
            bar.pack(side="top", fill="x", before=others[0])
        else:
            bar.pack(side="top", fill="x")

    def restart_now():
        updater.request_restart()
        close()

    def close():
        if on_close_chain is not None:
            on_close_chain()      # the app may ask "save first?" and destroys the window
        else:
            root.destroy()

    # tkinter must only be touched from the main thread: the background check just
    # sets updater.ready_setup, and this poll (on the main thread) shows the bar
    def poll():
        try:
            if updater.ready_setup and not state["shown"]:
                show_ready()
            root.after(500, poll)
        except Exception:
            pass

    if updater.due():
        root.after(2500, lambda: updater.check_in_background(lambda result: None))
    root.after(500, poll)
    updater._show_ready = show_ready
    return bar


def open_about(root, updater, colors, font, extra_lines=()):
    """'About & updates' window: shows the version and an Update button."""
    import tkinter as tk

    win = tk.Toplevel(root)
    win.title(f"About {updater.app_name}")
    win.configure(bg="white")
    win.resizable(False, False)
    win.transient(root)
    tk.Label(win, text=updater.app_name, bg="white", fg=colors["title"],
             font=(font, 18, "bold")).pack(padx=40, pady=(22, 2))
    ver = tk.Label(win, text=f"You have version {updater.version}", bg="white",
                   fg=colors["text"], font=(font, 13))
    ver.pack()
    for line in extra_lines:
        tk.Label(win, text=line, bg="white", fg=colors["muted"], font=(font, 10)).pack()
    status = tk.Label(win, text="", bg="white", fg=colors["muted"], font=(font, 11),
                      wraplength=420, justify="center")
    status.pack(padx=30, pady=(14, 6))
    row = tk.Frame(win, bg="white")
    row.pack(pady=(4, 20))
    go = tk.Button(row, text="⟳  Check for updates", bg=colors["button"], fg="white",
                   activebackground=colors["button"], activeforeground="white", relief="flat",
                   font=(font, 11, "bold"), cursor="hand2", padx=16, pady=6)
    go.pack(side="left", padx=6)
    tk.Button(row, text="Close", command=win.destroy, bg="white", fg=colors["title"], relief="solid",
              bd=1, font=(font, 10, "bold"), cursor="hand2", padx=14, pady=5).pack(side="left", padx=6)

    def say(text, color=None):
        try:
            status.config(text=text, fg=color or colors["muted"])
        except Exception:
            pass

    import queue
    q = queue.Queue()

    def progress(p):
        q.put(("progress", p))

    def done(result):
        q.put(("done", result))

    def pump():
        try:
            while True:
                kind, val = q.get_nowait()
                if kind == "progress":
                    say(f"Downloading the new version...  {val:.0f}%")
                else:
                    show_result(val)
        except queue.Empty:
            pass
        try:
            win.after(200, pump)
        except Exception:
            pass

    def show_result(result):
        def ui():
            go.config(state="normal")
            if result == "newer-ready":
                say(f"Version {updater.ready_version} is downloaded and ready.", colors["good"])
                go.config(text="Restart & update now", command=lambda: (win.destroy(), restart()))
                show = getattr(updater, "_show_ready", None)
                if show:
                    show()
            elif result == "up-to-date":
                say(f"✔  You have the newest version ({updater.version}).", colors["good"])
            elif result == "no-release":
                say("No downloadable release was found on GitHub yet.")
            elif result == "busy":
                say("Already checking - one moment...")
            else:
                say(f"Couldn't check for updates: {updater.error}", colors["bad"])
        try:
            ui()
        except Exception:
            pass

    def restart():
        updater.request_restart()
        closer = getattr(updater, "close_app", None)
        if closer:
            closer()
        else:
            root.destroy()

    def start():
        if updater.ready_setup:
            show_result("newer-ready")
            return
        go.config(state="disabled")
        say("Checking GitHub for a newer version...")
        updater.check_in_background(done, progress=progress)

    go.config(command=start)
    win.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - win.winfo_width()) // 2
    y = root.winfo_rooty() + (root.winfo_height() - win.winfo_height()) // 3
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    pump()
    start()
    return win
