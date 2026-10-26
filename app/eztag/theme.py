"""Colors, fonts and the friendly colorful widgets used everywhere in EZ Tag."""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

BG = "#f4f1ff"          # soft lavender window background
PANEL = "#ffffff"
INK = "#212529"
MUTED = "#6c757d"
LINE = "#e3dcff"
HEADER = "#5f3dc4"
HEADER_2 = "#7950f2"
SELECT = "#d0bfff"
KEEP = "#9c8fd1"

COLORS = {
    "blue": "#1c7ed6", "teal": "#0ca678", "green": "#2f9e44", "orange": "#f76707",
    "purple": "#7048e8", "pink": "#d6336c", "yellow": "#f59f00", "red": "#e03131",
    "cyan": "#1098ad", "indigo": "#4263eb", "gray": "#868e96", "grape": "#ae3ec9",
    "lime": "#66a80f", "brown": "#a0522d",
}

IS_WIN = sys.platform.startswith("win")
FAMILY = "Segoe UI" if IS_WIN else "DejaVu Sans"
EMOJI = "Segoe UI Emoji" if IS_WIN else FAMILY

_scale = [1.0]


def set_text_scale(large: bool):
    _scale[0] = 1.18 if large else 1.0


def font(size=10, weight="normal", family=None):
    return (family or FAMILY, int(round(size * _scale[0])), weight)


def lighten(hex_color: str, amount: float = 0.18) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (int(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def darken(hex_color: str, amount: float = 0.18) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (int(c * (1 - amount)) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


class BigButton(tk.Frame):
    """A big, rounded-looking, colorful button: icon on top, words below."""

    def __init__(self, master, text, icon="", color="blue", command=None, width=92,
                 height=70, tip=None, small=False):
        c = COLORS.get(color, color)
        super().__init__(master, bg=c, cursor="hand2", width=width, height=height,
                         highlightthickness=0, bd=0)
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.color = c
        self.command = command
        self.enabled = True
        inner = tk.Frame(self, bg=c)
        inner.place(relx=0.5, rely=0.5, anchor="center")
        self.parts = [self, inner]
        if icon:
            li = tk.Label(inner, text=icon, bg=c, fg="white",
                          font=font(12 if small else 17, family=EMOJI))
            li.pack()
            self.parts.append(li)
        lt = tk.Label(inner, text=text, bg=c, fg="white", font=font(8 if small else 9, "bold"),
                      justify="center", wraplength=width - 6)
        lt.pack()
        self.parts.append(lt)
        for p in self.parts:
            p.bind("<Enter>", self._enter)
            p.bind("<Leave>", self._leave)
            p.bind("<ButtonRelease-1>", self._click)
        if tip:
            Tooltip(self, tip)

    def _paint(self, c):
        for p in self.parts:
            p.configure(bg=c)

    def _enter(self, _e=None):
        if self.enabled:
            self._paint(lighten(self.color))

    def _leave(self, _e=None):
        self._paint(self.color if self.enabled else "#ced4da")

    def _click(self, e):
        if not self.enabled:
            return
        w = e.widget
        x, y = w.winfo_pointerxy()
        if self.winfo_containing(x, y) not in self.parts:
            return
        self._paint(darken(self.color))
        self.after(110, self._leave)
        if self.command:
            self.after(10, self.command)

    def set_enabled(self, on: bool):
        self.enabled = on
        self._leave()


class PillButton(tk.Label):
    """Smaller colorful one-line button."""

    def __init__(self, master, text, color="blue", command=None, padx=14, pady=6, fsize=10):
        c = COLORS.get(color, color)
        super().__init__(master, text=text, bg=c, fg="white", cursor="hand2",
                         font=font(fsize, "bold"), padx=padx, pady=pady)
        self.color = c
        self.command = command
        self.bind("<Enter>", lambda e: self.configure(bg=lighten(self.color)))
        self.bind("<Leave>", lambda e: self.configure(bg=self.color))
        self.bind("<ButtonRelease-1>", self._click)

    def _click(self, e):
        x, y = self.winfo_pointerxy()
        if self.winfo_containing(x, y) is not self:
            return
        self.configure(bg=darken(self.color))
        self.after(100, lambda: self.configure(bg=self.color))
        if self.command:
            self.after(10, self.command)


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.tip, self.job = widget, text, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        for child in widget.winfo_children():
            child.bind("<Enter>", self._schedule, add="+")
            child.bind("<Leave>", self._hide, add="+")
            for g in child.winfo_children():
                g.bind("<Enter>", self._schedule, add="+")
                g.bind("<Leave>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self.job = self.widget.after(600, self._show)

    def _cancel(self):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None

    def _show(self):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#fff9db", fg=INK, font=font(9),
                 relief="solid", bd=1, padx=8, pady=4, justify="left").pack()

    def _hide(self, _e=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


def setup_styles(root):
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure(".", font=font(10), background=BG)
    st.configure("Treeview", rowheight=int(26 * _scale[0]), font=font(10), background=PANEL,
                 fieldbackground=PANEL, bordercolor=LINE, borderwidth=0)
    st.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", INK)])
    st.configure("Treeview.Heading", font=font(10, "bold"), background=HEADER_2,
                 foreground="white", relief="flat", padding=(6, 6))
    st.map("Treeview.Heading", background=[("active", HEADER)])
    st.configure("TCombobox", padding=4, arrowsize=14)
    st.configure("TEntry", padding=4)
    st.configure("TCheckbutton", background=PANEL, font=font(10))
    st.configure("TRadiobutton", background=PANEL, font=font(10))
    st.configure("Card.TCheckbutton", background=PANEL)
    st.configure("Vertical.TScrollbar", background=LINE, troughcolor=BG, arrowsize=14)
    st.configure("Horizontal.TScrollbar", background=LINE, troughcolor=BG, arrowsize=14)
    st.configure("TNotebook", background=BG)
    st.configure("TNotebook.Tab", font=font(10, "bold"), padding=(12, 6))
    st.configure("Horizontal.TProgressbar", background=COLORS["teal"], troughcolor=LINE)
    root.option_add("*TCombobox*Listbox.font", font(10))
    root.option_add("*Menu.font", font(10))


class Dialog(tk.Toplevel):
    """Base for all pop-up windows: colored title band, white body, button row."""

    def __init__(self, master, title, icon="", color="purple", width=720, height=None):
        super().__init__(master)
        self.withdraw()
        self.title(f"EZ Tag - {title}")
        self.configure(bg=PANEL)
        self.transient(master.winfo_toplevel())
        self.resizable(True, True)
        c = COLORS.get(color, color)
        band = tk.Frame(self, bg=c)
        band.pack(fill="x")
        tk.Label(band, text=(icon + "  " if icon else "") + title, bg=c, fg="white",
                 font=font(15, "bold"), padx=18, pady=12).pack(side="left")
        self.buttons = tk.Frame(self, bg=PANEL, padx=18, pady=12)
        self.buttons.pack(fill="x", side="bottom")
        tk.Frame(self, bg=LINE, height=1).pack(fill="x", side="bottom")
        self.body = tk.Frame(self, bg=PANEL, padx=18, pady=12)
        self.body.pack(fill="both", expand=True)
        self.result = None
        self.bind("<Escape>", lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._size = (width, height)

    def add_button(self, text, color, command, side="right"):
        b = PillButton(self.buttons, text, color, command)
        b.pack(side=side, padx=(8, 0) if side == "right" else (0, 8))
        return b

    def show(self):
        self.update_idletasks()
        w, h = self._size
        h = h or max(self.winfo_reqheight(), 200)
        m = self.master.winfo_toplevel()
        x = m.winfo_rootx() + max(0, (m.winfo_width() - w) // 2)
        y = m.winfo_rooty() + max(0, (m.winfo_height() - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.deiconify()
        self.grab_set()
        self.focus_set()
        self.wait_window()
        return self.result

    def close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def label(master, text, size=10, bold=False, color=INK, bg=PANEL, **kw):
    return tk.Label(master, text=text, font=font(size, "bold" if bold else "normal"),
                    fg=color, bg=bg, **kw)


def entry(master, var=None, width=40, **kw):
    e = tk.Entry(master, textvariable=var, width=width, font=font(11), relief="flat",
                 bg="#f8f9fa", highlightthickness=2, highlightbackground=LINE,
                 highlightcolor=COLORS["purple"], **kw)
    return e
