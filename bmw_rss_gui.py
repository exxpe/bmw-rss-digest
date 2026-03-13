#!/usr/bin/env python3
"""
BMW RSS Digest — GUI
Run: python3 bmw_rss_gui.py  or double-click run_rss_gui.command
"""

import sys
import threading
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

sys.path.insert(0, str(Path(__file__).parent))
import bmw_rss_digest as engine


# ── Logging handler that writes to a ScrolledText widget ─────────────────────

class TextHandler(logging.Handler):
    LEVEL_TAGS = {
        logging.ERROR:   "error",
        logging.WARNING: "warning",
        logging.INFO:    "info",
        logging.DEBUG:   "debug",
    }

    def __init__(self, widget: scrolledtext.ScrolledText):
        super().__init__()
        self.widget = widget

    def emit(self, record):
        msg = self.format(record) + "\n"
        tag = self.LEVEL_TAGS.get(record.levelno, "")
        self.widget.after(0, self._append, msg, tag)

    def _append(self, msg: str, tag: str):
        self.widget.configure(state="normal")
        self.widget.insert("end", msg, tag)
        self.widget.see("end")
        self.widget.configure(state="disabled")


# ── Main application ──────────────────────────────────────────────────────────

class BMWDigestApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("BMW RSS Digest")
        self.geometry("940x760")
        self.minsize(720, 580)
        self.resizable(True, True)

        # Engine logging — file handler only; GUI adds its own text handler
        engine.setup_logging(add_stream_handler=False)

        self._running = False
        self.config: dict = {}
        self._last_digest_path: str = ""

        self._build_ui()
        self._attach_log_handler()
        self._load_config()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Top notebook (tabs)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=False, padx=8, pady=(8, 4))

        self._build_feeds_tab()
        self._build_keywords_tab()
        self._build_settings_tab()

        # ── Run section ───────────────────────────────────────────────────────
        run_frame = ttk.LabelFrame(self, text="Run")
        run_frame.pack(fill="x", padx=8, pady=4)

        ttk.Label(run_frame, text="From:").grid(row=0, column=0, padx=(10, 2), pady=8)
        self.date_from = ttk.Entry(run_frame, width=12)
        self.date_from.grid(row=0, column=1, padx=2)

        ttk.Label(run_frame, text="To:").grid(row=0, column=2, padx=(12, 2))
        self.date_to = ttk.Entry(run_frame, width=12)
        self.date_to.grid(row=0, column=3, padx=2)

        self.run_btn = ttk.Button(
            run_frame, text="▶  Run Digest", command=self._run_digest
        )
        self.run_btn.grid(row=0, column=4, padx=(16, 8))

        ttk.Button(
            run_frame, text="Open output folder", command=self._open_output_folder
        ).grid(row=0, column=5, padx=4)

        self.obsidian_btn = ttk.Button(
            run_frame, text="Open in Obsidian", command=self._open_in_obsidian,
            state="disabled"
        )
        self.obsidian_btn.grid(row=0, column=6, padx=4)

        run_frame.columnconfigure(6, weight=1)

        # Stats bar
        self.stats_var = tk.StringVar(value="—")
        stats_label = ttk.Label(
            run_frame, textvariable=self.stats_var, anchor="w"
        )
        stats_label.grid(row=1, column=0, columnspan=7, sticky="ew", padx=10, pady=(0, 8))

        # ── Log area ──────────────────────────────────────────────────────────
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=14,
            state="disabled",
            font=("Menlo", 11),
            wrap="word",
            background="#1e1e1e",
            foreground="#d4d4d4",
            insertbackground="#d4d4d4",
            relief="flat",
        )
        self.log_text.pack(fill="both", expand=True, padx=4, pady=(4, 0))

        self.log_text.tag_configure("error",   foreground="#f38ba8")
        self.log_text.tag_configure("warning", foreground="#f9e2af")
        self.log_text.tag_configure("info",    foreground="#a6e3a1")
        self.log_text.tag_configure("debug",   foreground="#6c7086")

        ttk.Button(
            log_frame, text="Clear log", command=self._clear_log
        ).pack(anchor="e", padx=4, pady=(2, 4))

    def _build_feeds_tab(self):
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="  Feeds  ")

        # Listbox
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")

        self.feeds_list = tk.Listbox(
            list_frame,
            yscrollcommand=sb.set,
            height=8,
            selectmode="single",
            font=("Helvetica", 12),
            activestyle="dotbox",
        )
        self.feeds_list.pack(fill="both", expand=True)
        sb.config(command=self.feeds_list.yview)

        # Add feed section
        add_frame = ttk.LabelFrame(frame, text="Add feed", padding=8)
        add_frame.pack(fill="x", pady=(8, 0))

        ttk.Label(add_frame, text="URL:").grid(row=0, column=0, sticky="w", pady=3)
        self.feed_url_entry = ttk.Entry(add_frame)
        self.feed_url_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=3)

        ttk.Label(add_frame, text="Name:").grid(row=1, column=0, sticky="w", pady=3)
        self.feed_name_entry = ttk.Entry(add_frame)
        self.feed_name_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=3)
        self.feed_name_entry.bind("<Return>", lambda e: self._add_feed())

        btn_row = ttk.Frame(add_frame)
        btn_row.grid(row=2, column=0, columnspan=2, pady=(6, 0))
        ttk.Button(btn_row, text="Add",             command=self._add_feed).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Remove selected", command=self._remove_feed).pack(side="left", padx=4)

        add_frame.columnconfigure(1, weight=1)

    def _build_keywords_tab(self):
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="  Keywords  ")

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")

        self.kw_list = tk.Listbox(
            list_frame,
            yscrollcommand=sb.set,
            height=10,
            selectmode="extended",
            font=("Helvetica", 12),
            activestyle="dotbox",
        )
        self.kw_list.pack(fill="both", expand=True)
        sb.config(command=self.kw_list.yview)

        add_frame = ttk.LabelFrame(frame, text="Add / Remove keyword", padding=8)
        add_frame.pack(fill="x", pady=(8, 0))

        ttk.Label(add_frame, text="Keyword:").pack(side="left", padx=(0, 8))
        self.kw_entry = ttk.Entry(add_frame)
        self.kw_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.kw_entry.bind("<Return>", lambda e: self._add_keyword())

        ttk.Button(add_frame, text="Add",             command=self._add_keyword).pack(side="left", padx=4)
        ttk.Button(add_frame, text="Remove selected", command=self._remove_keyword).pack(side="left", padx=4)

    def _build_settings_tab(self):
        frame = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(frame, text="  Settings  ")

        ttk.Label(frame, text="Output directory:").grid(row=0, column=0, sticky="w", pady=8)
        self.output_dir_entry = ttk.Entry(frame, width=42)
        self.output_dir_entry.grid(row=0, column=1, padx=8)
        ttk.Button(frame, text="Browse…", command=self._browse_output).grid(row=0, column=2)

        ttk.Label(frame, text="Max age (days):").grid(row=1, column=0, sticky="w", pady=8)
        self.max_age_var = tk.StringVar()
        ttk.Spinbox(frame, from_=1, to=365, textvariable=self.max_age_var, width=6).grid(
            row=1, column=1, sticky="w", padx=8
        )

        ttk.Button(frame, text="Save settings", command=self._save_settings).grid(
            row=2, column=0, columnspan=3, pady=(16, 0), sticky="w"
        )

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self):
        try:
            self.config = engine.load_config()
        except Exception as e:
            messagebox.showerror("Config error", str(e))
            self.config = {
                "feeds": [], "keywords": [],
                "output_dir": "~/bmw_rss_digests", "max_age_days": 7,
            }

        self._refresh_feeds_list()
        self._refresh_keywords_list()

        self.output_dir_entry.delete(0, "end")
        self.output_dir_entry.insert(0, self.config.get("output_dir", "~/bmw_rss_digests"))

        max_age = self.config.get("max_age_days", 7)
        self.max_age_var.set(str(max_age))

        # Prefill date range from config
        self.date_from.delete(0, "end")
        self.date_from.insert(0, (datetime.now() - timedelta(days=max_age)).strftime("%Y-%m-%d"))
        self.date_to.delete(0, "end")
        self.date_to.insert(0, datetime.now().strftime("%Y-%m-%d"))

    def _refresh_feeds_list(self):
        self.feeds_list.delete(0, "end")
        for f in self.config.get("feeds", []):
            self.feeds_list.insert("end", f["name"])

    def _refresh_keywords_list(self):
        self.kw_list.delete(0, "end")
        for kw in self.config.get("keywords", []):
            self.kw_list.insert("end", kw)

    # ── Feed actions ──────────────────────────────────────────────────────────

    def _add_feed(self):
        url  = self.feed_url_entry.get().strip()
        name = self.feed_name_entry.get().strip()
        if not url or not name:
            messagebox.showwarning("Missing data", "Please enter both URL and name.")
            return
        engine.cmd_add_feed(self.config, url, name)
        self._refresh_feeds_list()
        self.feed_url_entry.delete(0, "end")
        self.feed_name_entry.delete(0, "end")

    def _remove_feed(self):
        sel = self.feeds_list.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Select a feed to remove.")
            return
        idx  = sel[0]
        feed = self.config["feeds"][idx]
        if messagebox.askyesno("Remove feed", f"Remove '{feed['name']}'?"):
            self.config["feeds"].pop(idx)
            engine.save_config(self.config)
            self._refresh_feeds_list()

    # ── Keyword actions ───────────────────────────────────────────────────────

    def _add_keyword(self):
        word = self.kw_entry.get().strip()
        if not word:
            return
        engine.cmd_add_keyword(self.config, word)
        self._refresh_keywords_list()
        self.kw_entry.delete(0, "end")

    def _remove_keyword(self):
        sel = self.kw_list.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Select keyword(s) to remove.")
            return
        for idx in reversed(sel):
            word = self.config["keywords"][idx]
            engine.cmd_remove_keyword(self.config, word)
        self._refresh_keywords_list()

    # ── Settings actions ──────────────────────────────────────────────────────

    def _browse_output(self):
        d = filedialog.askdirectory(title="Select output directory")
        if d:
            self.output_dir_entry.delete(0, "end")
            self.output_dir_entry.insert(0, d)

    def _save_settings(self):
        self.config["output_dir"] = self.output_dir_entry.get().strip()
        try:
            self.config["max_age_days"] = int(self.max_age_var.get())
        except ValueError:
            messagebox.showerror("Invalid value", "Max age must be a number.")
            return
        engine.save_config(self.config)
        messagebox.showinfo("Saved", "Settings saved.")

    def _open_in_obsidian(self):
        if not self._last_digest_path:
            return
        import subprocess
        result = subprocess.run(
            ["open", "-a", "Obsidian", self._last_digest_path],
            capture_output=True
        )
        if result.returncode != 0:
            messagebox.showwarning(
                "Obsidian not found",
                "Obsidian не установлен или не найден в /Applications.\n"
                "Скачай с obsidian.md и установи."
            )

    def _open_output_folder(self):
        import subprocess
        path = Path(self.config.get("output_dir", "~/bmw_rss_digests")).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(path)])

    # ── Run digest ────────────────────────────────────────────────────────────

    def _parse_date_entry(self, entry: ttk.Entry, label: str):
        val = entry.get().strip()
        if not val:
            return None
        try:
            return datetime.strptime(val, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            messagebox.showerror("Invalid date", f"{label} must be YYYY-MM-DD")
            return False  # signals a parse error

    def _run_digest(self):
        if self._running:
            return

        from_date = self._parse_date_entry(self.date_from, "From date")
        if from_date is False:
            return
        to_date = self._parse_date_entry(self.date_to, "To date")
        if to_date is False:
            return

        self._running = True
        self.run_btn.configure(state="disabled", text="⏳ Running…")
        self.stats_var.set("Running — please wait…")

        # Reload config so any edits in tabs are picked up
        self.config = engine.load_config()

        def worker():
            try:
                stats = engine.run_digest(
                    self.config, from_date=from_date, to_date=to_date
                )
                self.after(0, self._on_done, stats)
            except Exception as exc:
                engine.logger.error(f"Digest failed: {exc}")
                self.after(0, self._on_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, stats: dict):
        self._running = False
        self.run_btn.configure(state="normal", text="▶  Run Digest")

        m  = stats["matched"]
        t  = stats["total"]
        fc = stats["feeds_count"]
        ts = stats["timestamp"]

        # Per-feed breakdown for the stats bar
        hit_feeds = sum(
            1 for v in stats["feed_stats"].values()
            if v.get("matched", 0) > 0
        )
        errors = sum(
            1 for v in stats["feed_stats"].values()
            if v.get("error")
        )

        parts = [f"✅  {m} matched / {t} total  |  {hit_feeds}/{fc} feeds had hits  |  {ts}"]
        if errors:
            parts.append(f"  ⚠️ {errors} feed error(s)")
        self.stats_var.set("".join(parts))

        self._last_digest_path = str(stats["path"])
        self.obsidian_btn.configure(state="normal")

    def _on_error(self, msg: str):
        self._running = False
        self.run_btn.configure(state="normal", text="▶  Run Digest")
        self.stats_var.set(f"❌  Error — {msg[:80]}")
        messagebox.showerror("Digest failed", msg)

    # ── Log ───────────────────────────────────────────────────────────────────

    def _attach_log_handler(self):
        handler = TextHandler(self.log_text)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-5s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        engine.logger.addHandler(handler)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = BMWDigestApp()
    app.mainloop()


if __name__ == "__main__":
    main()
