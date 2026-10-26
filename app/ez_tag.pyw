"""EZ Tag - start here.  (Double-click, or run:  pythonw ez_tag.pyw [folder or songs])"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _report(exc_text):
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        log_dir = os.path.join(base, "EZ Tag")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "error-log.txt"), "a", encoding="utf-8") as fh:
            fh.write(exc_text + "\n")
    except OSError:
        pass
    try:
        import tkinter.messagebox as mb
        mb.showerror("EZ Tag", "Something went wrong:\n\n" + exc_text[-1500:])
    except Exception:
        pass


def _hook(exc_type, exc, tb):
    _report("".join(traceback.format_exception(exc_type, exc, tb)))


if __name__ == "__main__":
    sys.excepthook = _hook
    try:
        import tkinter
        tkinter.Tk.report_callback_exception = lambda self, et, ev, tb: _hook(et, ev, tb)
        from eztag.gui import main
        main()
    except Exception:
        _report(traceback.format_exc())
