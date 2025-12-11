"""
Snapchat Memories Downloader - Modern GUI
A sleek, dark-themed interface for downloading Snapchat memories
"""

import asyncio
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk
import exif
import httpx
from pydantic import BaseModel, Field, field_validator


# ============== Data Models ==============

class Memory(BaseModel):
    date: datetime = Field(alias="Date")
    download_link: str = Field(alias="Download Link")
    location: str = Field(default="", alias="Location")
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v):
        if isinstance(v, str):
            return datetime.strptime(v, "%Y-%m-%d %H:%M:%S UTC")
        return v

    def model_post_init(self, __context):
        if self.location and not self.latitude:
            if match := re.search(r"([-\d.]+),\s*([-\d.]+)", self.location):
                self.latitude = float(match.group(1))
                self.longitude = float(match.group(2))

    @property
    def filename(self) -> str:
        return self.date.strftime("%Y-%m-%d_%H-%M-%S")


class DownloadStats(BaseModel):
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    total: int = 0
    mb: float = 0
    current_file: str = ""


# ============== Download Logic ==============

def load_memories(json_path: Path) -> list[Memory]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Memory(**item) for item in data["Saved Media"]]


async def get_cdn_url(download_link: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            download_link,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.text.strip()


def add_exif_data(image_path: Path, memory: Memory):
    try:
        with open(image_path, "rb") as f:
            img = exif.Image(f)

        dt_str = memory.date.strftime("%Y:%m:%d %H:%M:%S")
        img.datetime_original = dt_str
        img.datetime_digitized = dt_str
        img.datetime = dt_str

        if memory.latitude is not None and memory.longitude is not None:
            def decimal_to_dms(decimal):
                degrees = int(abs(decimal))
                minutes_decimal = (abs(decimal) - degrees) * 60
                minutes = int(minutes_decimal)
                seconds = (minutes_decimal - minutes) * 60
                return (degrees, minutes, seconds)

            lat_dms = decimal_to_dms(memory.latitude)
            lon_dms = decimal_to_dms(memory.longitude)

            img.gps_latitude = lat_dms
            img.gps_latitude_ref = "N" if memory.latitude >= 0 else "S"
            img.gps_longitude = lon_dms
            img.gps_longitude_ref = "E" if memory.longitude >= 0 else "W"

        with open(image_path, "wb") as f:
            f.write(img.get_file())
    except Exception:
        pass


async def download_memory(
    memory: Memory,
    output_dir: Path,
    add_exif: bool,
    semaphore: asyncio.Semaphore,
) -> tuple[bool, int, str, int | None]:
    async with semaphore:
        try:
            cdn_url = await get_cdn_url(memory.download_link)
            ext = Path(cdn_url.split("?")[0]).suffix or ".jpg"
            filename = f"{memory.filename}{ext}"
            output_path = output_dir / filename
            
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(cdn_url)
                response.raise_for_status()
                output_path.write_bytes(response.content)
                timestamp = memory.date.timestamp()
                os.utime(output_path, (timestamp, timestamp))

                if add_exif and ext == ".jpg":
                    add_exif_data(output_path, memory)

                return True, len(response.content), filename, response.status_code
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code if e.response else None
            return False, 0, str(e), status_code
        except Exception as e:
            return False, 0, str(e), None


# ============== Theme & Styling ==============

# Snapchat-inspired yellow with dark theme
COLORS = {
    "bg_dark": "#0D0D0D",
    "bg_card": "#1A1A1A",
    "bg_hover": "#252525",
    "accent": "#FFFC00",  # Snapchat yellow
    "accent_hover": "#E6E300",
    "text_primary": "#FFFFFF",
    "text_secondary": "#888888",
    "text_muted": "#555555",
    "success": "#00D26A",
    "error": "#FF4757",
    "border": "#333333",
}


class ModernButton(ctk.CTkButton):
    """Custom styled button with Snapchat-inspired design"""
    
    def __init__(self, master, text, command=None, variant="primary", **kwargs):
        if variant == "primary":
            super().__init__(
                master,
                text=text,
                command=command,
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                text_color="#000000",
                font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                corner_radius=25,
                height=45,
                **kwargs
            )
        else:
            super().__init__(
                master,
                text=text,
                command=command,
                fg_color="transparent",
                hover_color=COLORS["bg_hover"],
                text_color=COLORS["text_primary"],
                border_color=COLORS["border"],
                border_width=2,
                font=ctk.CTkFont(family="Segoe UI", size=14),
                corner_radius=25,
                height=45,
                **kwargs
            )


class FileSelector(ctk.CTkFrame):
    """File/folder selector component"""
    
    def __init__(self, master, label: str, is_folder: bool = False, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.is_folder = is_folder
        self.path_var = ctk.StringVar()
        
        # Label
        self.label = ctk.CTkLabel(
            self,
            text=label,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
            anchor="w"
        )
        self.label.pack(fill="x", pady=(0, 8))
        
        # Input frame
        input_frame = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=12)
        input_frame.pack(fill="x")
        
        self.entry = ctk.CTkEntry(
            input_frame,
            textvariable=self.path_var,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color="transparent",
            border_width=0,
            text_color=COLORS["text_primary"],
            placeholder_text="Click to select...",
            placeholder_text_color=COLORS["text_muted"],
            height=45
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(15, 5))
        
        self.browse_btn = ctk.CTkButton(
            input_frame,
            text="Browse",
            width=80,
            height=45,
            corner_radius=10,
            fg_color="transparent",
            hover_color=COLORS["bg_hover"],
            font=ctk.CTkFont(size=18),
            command=self._browse
        )
        self.browse_btn.pack(side="right", padx=5, pady=5)
    
    def _browse(self):
        if self.is_folder:
            path = filedialog.askdirectory()
        else:
            path = filedialog.askopenfilename(
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )
        if path:
            self.path_var.set(path)
    
    def get(self) -> str:
        return self.path_var.get()
    
    def set(self, value: str):
        self.path_var.set(value)


class StatsCard(ctk.CTkFrame):
    """Statistics display card"""
    
    def __init__(self, master, title: str, value: str = "0", icon: str = "📊", **kwargs):
        super().__init__(master, fg_color=COLORS["bg_card"], corner_radius=16, **kwargs)
        
        self.grid_columnconfigure(0, weight=1)
        
        # Icon
        icon_label = ctk.CTkLabel(
            self,
            text=icon,
            font=ctk.CTkFont(size=24)
        )
        icon_label.grid(row=0, column=0, pady=(15, 5))
        
        # Value
        self.value_label = ctk.CTkLabel(
            self,
            text=value,
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        self.value_label.grid(row=1, column=0, pady=(0, 5))
        
        # Title
        title_label = ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"]
        )
        title_label.grid(row=2, column=0, pady=(0, 15))
    
    def set_value(self, value: str):
        self.value_label.configure(text=value)


class ProgressSection(ctk.CTkFrame):
    """Progress display section"""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        
        # Current file label
        self.file_label = ctk.CTkLabel(
            self,
            text="Ready to download",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLORS["text_secondary"],
            anchor="w"
        )
        self.file_label.pack(fill="x", pady=(0, 10))
        
        # Progress bar
        self.progress = ctk.CTkProgressBar(
            self,
            height=8,
            corner_radius=4,
            fg_color=COLORS["bg_card"],
            progress_color=COLORS["accent"]
        )
        self.progress.pack(fill="x")
        self.progress.set(0)
        
        # Percentage label
        self.percent_label = ctk.CTkLabel(
            self,
            text="0%",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["accent"]
        )
        self.percent_label.pack(pady=(10, 0))
    
    def update_progress(self, value: float, current_file: str = ""):
        self.progress.set(value)
        self.percent_label.configure(text=f"{int(value * 100)}%")
        if current_file:
            self.file_label.configure(text=f"⬇️  {current_file}")
    
    def set_complete(self):
        self.progress.set(1)
        self.percent_label.configure(text="100%")
        self.file_label.configure(text="✅ Download complete!")
    
    def reset(self):
        self.progress.set(0)
        self.percent_label.configure(text="0%")
        self.file_label.configure(text="Ready to download")


# ============== Main Application ==============

class SnapchatDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Window setup
        self.title("Snapchat Memories Downloader")
        width, height = 1100, 900
        screen_width = self.winfo_screenwidth()
        x = max((screen_width - width) // 2, 0)
        self.geometry(f"{width}x{height}+{x}+0")  # snap to top of the screen
        self.configure(fg_color=COLORS["bg_dark"])
        self.resizable(True, True)
        
        # State
        self.is_downloading = False
        self.memories: list[Memory] = []
        self.year_vars: dict[int, ctk.BooleanVar] = {}
        self.selected_years_cache: set[int] | None = None
        self.auto_concurrency_var = ctk.BooleanVar(value=True)
        
        # Build UI
        self._create_widgets()
    
    def _create_widgets(self):
        # Main container with padding
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=30, pady=30)
        container.grid_columnconfigure(0, weight=3)
        container.grid_columnconfigure(1, weight=2)
        container.grid_rowconfigure(0, weight=1)
        
        # Left content column (scrollable content + pinned buttons)
        left = ctk.CTkFrame(container, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        left.grid_rowconfigure(0, weight=1)
        left.grid_rowconfigure(1, minsize=120)
        left.grid_columnconfigure(0, weight=1)
        left_scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        left_scroll.grid(row=0, column=0, sticky="nsew")
        left_footer = ctk.CTkFrame(left, fg_color="transparent")
        left_footer.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        
        # Right console column
        right = ctk.CTkFrame(container, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)
        
        # Build left column sections
        self._create_header(left_scroll)
        self._create_file_section(left_scroll)
        self._create_options_section(left_scroll)
        self._create_year_filter_section(left_scroll)
        self._create_progress_section(left_scroll)
        self._create_stats_section(left_scroll)
        self._create_action_buttons(left_footer)
        
        # Build console on the right
        self._create_console_panel(right)
    
    def _create_header(self, parent):
        header_frame = ctk.CTkFrame(parent, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 30))
        
        # Ghost icon (Snapchat-style)
        icon_label = ctk.CTkLabel(
            header_frame,
            text="👻",
            font=ctk.CTkFont(size=48)
        )
        icon_label.pack()
        
        # Title
        title_label = ctk.CTkLabel(
            header_frame,
            text="Memories Downloader",
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        title_label.pack(pady=(10, 5))
        
        # Subtitle
        subtitle_label = ctk.CTkLabel(
            header_frame,
            text="Download your Snapchat memories",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color=COLORS["text_secondary"]
        )
        subtitle_label.pack()
    
    def _create_file_section(self, parent):
        file_frame = ctk.CTkFrame(parent, fg_color="transparent")
        file_frame.pack(fill="x", pady=(0, 20))
        
        # JSON file selector
        self.json_selector = FileSelector(
            file_frame,
            label="📄 JSON file (memories_history.json)",
            is_folder=False
        )
        self.json_selector.pack(fill="x", pady=(0, 15))
        
        # Output folder selector
        self.output_selector = FileSelector(
            file_frame,
            label="📂 Output folder",
            is_folder=True
        )
        self.output_selector.pack(fill="x")
        self.output_selector.set("./downloads")
    
    def _create_options_section(self, parent):
        options_frame = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=16)
        options_frame.pack(fill="x", pady=(0, 20))
        
        options_inner = ctk.CTkFrame(options_frame, fg_color="transparent")
        options_inner.pack(fill="x", padx=20, pady=20)
        
        # Title
        options_title = ctk.CTkLabel(
            options_inner,
            text="⚙️  Options",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"],
            anchor="w"
        )
        options_title.pack(fill="x", pady=(0, 15))
        
        # Options grid
        options_grid = ctk.CTkFrame(options_inner, fg_color="transparent")
        options_grid.pack(fill="x")
        options_grid.grid_columnconfigure((0, 1), weight=1)
        
        # EXIF checkbox
        self.exif_var = ctk.BooleanVar(value=True)
        self.exif_check = ctk.CTkCheckBox(
            options_grid,
            text="Add EXIF metadata",
            variable=self.exif_var,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            checkmark_color="#000000",
            border_color=COLORS["border"]
        )
        self.exif_check.grid(row=0, column=0, sticky="w", pady=5)
        
        # Skip existing checkbox
        self.skip_var = ctk.BooleanVar(value=True)
        self.skip_check = ctk.CTkCheckBox(
            options_grid,
            text="Skip existing files",
            variable=self.skip_var,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            checkmark_color="#000000",
            border_color=COLORS["border"]
        )
        self.skip_check.grid(row=0, column=1, sticky="w", pady=5)
        
        # Auto concurrency checkbox
        self.auto_concurrency_check = ctk.CTkCheckBox(
            options_grid,
            text="Auto-tune concurrency",
            variable=self.auto_concurrency_var,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            checkmark_color="#000000",
            border_color=COLORS["border"]
        )
        self.auto_concurrency_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))
        
        # Concurrent downloads slider
        slider_frame = ctk.CTkFrame(options_inner, fg_color="transparent")
        slider_frame.pack(fill="x", pady=(15, 0))
        
        slider_label = ctk.CTkLabel(
            slider_frame,
            text="Concurrent downloads:",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLORS["text_secondary"]
        )
        slider_label.pack(side="left")
        
        self.concurrent_value = ctk.CTkLabel(
            slider_frame,
            text="40",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLORS["accent"],
            width=30
        )
        self.concurrent_value.pack(side="right")
        
        self.concurrent_slider = ctk.CTkSlider(
            slider_frame,
            from_=1,
            to=100,
            number_of_steps=99,
            fg_color=COLORS["bg_dark"],
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            command=self._on_slider_change
        )
        self.concurrent_slider.pack(side="right", padx=(15, 10), fill="x", expand=True)
        self.concurrent_slider.set(40)
    
    def _create_year_filter_section(self, parent):
        section = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=16)
        section.pack(fill="x", pady=(0, 20))
        
        inner = ctk.CTkFrame(section, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=20)
        
        header = ctk.CTkLabel(
            inner,
            text="📆  Years to download",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"],
            anchor="w"
        )
        header.pack(fill="x")
        
        subtitle = ctk.CTkLabel(
            inner,
            text="Load years from your JSON, then pick the ones you want.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
            anchor="w"
        )
        subtitle.pack(fill="x", pady=(4, 10))
        
        controls = ctk.CTkFrame(inner, fg_color="transparent")
        controls.pack(fill="x", pady=(0, 10))
        
        load_btn = ModernButton(
            controls,
            text="Refresh years from JSON",
            command=self._load_years_from_json,
            variant="secondary"
        )
        load_btn.pack(side="left", padx=(0, 10))
        
        self.select_all_years_btn = ModernButton(
            controls,
            text="Select all",
            command=self._select_all_years,
            variant="secondary"
        )
        self.select_all_years_btn.pack(side="left")
        
        self.year_list = ctk.CTkScrollableFrame(
            inner,
            fg_color=COLORS["bg_dark"],
            corner_radius=12,
            height=140
        )
        self.year_list.pack(fill="both", expand=True)
        
        placeholder = ctk.CTkLabel(
            self.year_list,
            text="Load your JSON to see available years",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"]
        )
        placeholder.pack(pady=10)
    
    def _on_slider_change(self, value):
        self.concurrent_value.configure(text=str(int(value)))
    
    def _clear_year_list(self):
        for child in self.year_list.winfo_children():
            child.destroy()
    
    def _populate_years(self, years: list[int], select_all: bool = True):
        self._clear_year_list()
        self.year_vars.clear()
        if not years:
            ctk.CTkLabel(
                self.year_list,
                text="No years found in JSON",
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=COLORS["text_secondary"]
            ).pack(pady=10)
            return
        
        for year in years:
            var = ctk.BooleanVar(value=select_all)
            chk = ctk.CTkCheckBox(
                self.year_list,
                text=str(year),
                variable=var,
                font=ctk.CTkFont(family="Segoe UI", size=13),
                text_color=COLORS["text_primary"],
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                checkmark_color="#000000",
                border_color=COLORS["border"]
            )
            chk.pack(anchor="w", pady=2, padx=6)
            self.year_vars[year] = var
    
    def _select_all_years(self):
        for var in self.year_vars.values():
            var.set(True)
    
    def _get_selected_years(self) -> set[int] | None:
        if not self.year_vars:
            return None
        chosen = {year for year, var in self.year_vars.items() if var.get()}
        return chosen or None
    
    def _load_years_from_json(self):
        json_path = self.json_selector.get()
        if not json_path or not Path(json_path).exists():
            messagebox.showerror("Error", "Please select a valid JSON file first.")
            return
        
        try:
            memories = load_memories(Path(json_path))
            years = sorted({m.date.year for m in memories})
        except Exception as e:
            messagebox.showerror("Error", f"Could not read years from JSON:\n{e}")
            return
        
        self._populate_years(years, select_all=True)
        self._log(f"Loaded years from JSON: {', '.join(map(str, years))}")
    
    def _create_progress_section(self, parent):
        self.progress_section = ProgressSection(parent)
        self.progress_section.pack(fill="x", pady=(0, 20))
    
    def _create_stats_section(self, parent):
        stats_frame = ctk.CTkFrame(parent, fg_color="transparent")
        stats_frame.pack(fill="x", pady=(0, 20))
        stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        
        self.stats_total = StatsCard(stats_frame, "Total", "0", "📊")
        self.stats_total.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        
        self.stats_downloaded = StatsCard(stats_frame, "Downloaded", "0", "✅")
        self.stats_downloaded.grid(row=0, column=1, padx=8, sticky="nsew")
        
        self.stats_skipped = StatsCard(stats_frame, "Skipped", "0", "⏭️")
        self.stats_skipped.grid(row=0, column=2, padx=8, sticky="nsew")
        
        self.stats_failed = StatsCard(stats_frame, "Failed", "0", "❌")
        self.stats_failed.grid(row=0, column=3, padx=(8, 0), sticky="nsew")
    
    def _create_action_buttons(self, parent):
        button_frame = ctk.CTkFrame(parent, fg_color="transparent")
        button_frame.pack(fill="x", pady=(10, 0))
        
        self.download_btn = ModernButton(
            button_frame,
            text="⬇️  Start download",
            command=self._start_download,
            variant="primary"
        )
        self.download_btn.pack(fill="x", pady=(0, 10))
        
        self.cancel_btn = ModernButton(
            button_frame,
            text="Cancel",
            command=self._cancel_download,
            variant="secondary"
        )
        self.cancel_btn.pack(fill="x")
        self.cancel_btn.configure(state="disabled")
    
    def _create_console_panel(self, parent):
        panel = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=16)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_rowconfigure(3, weight=1)
        panel.grid_columnconfigure(0, weight=1)
        
        header = ctk.CTkLabel(
            panel,
            text="Live console",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        header.grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))
        
        subheader = ctk.CTkLabel(
            panel,
            text="See progress, auto-tuned concurrency, and any warnings.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"]
        )
        subheader.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))
        
        progress_wrap = ctk.CTkFrame(panel, fg_color="transparent")
        progress_wrap.grid(row=2, column=0, sticky="ew", padx=16)
        progress_wrap.grid_columnconfigure(0, weight=1)
        
        self.console_file_label = ctk.CTkLabel(
            progress_wrap,
            text="Waiting to start...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
            anchor="w"
        )
        self.console_file_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        
        self.console_progress = ctk.CTkProgressBar(
            progress_wrap,
            height=10,
            corner_radius=6,
            fg_color=COLORS["bg_dark"],
            progress_color=COLORS["accent"]
        )
        self.console_progress.grid(row=1, column=0, sticky="ew")
        self.console_progress.set(0)
        
        self.console_text = ctk.CTkTextbox(
            panel,
            fg_color=COLORS["bg_dark"],
            text_color=COLORS["text_primary"],
            corner_radius=12,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word"
        )
        self.console_text.grid(row=3, column=0, sticky="nsew", padx=16, pady=(12, 16))
        self.console_text.insert("end", "Console ready.\n")
        self.console_text.configure(state="disabled")
    
    def _append_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console_text.configure(state="normal")
        self.console_text.insert("end", f"[{timestamp}] {message}\n")
        self.console_text.see("end")
        self.console_text.configure(state="disabled")
    
    def _log(self, message: str):
        self.after(0, lambda: self._append_log(message))
    
    def _update_console_progress(self, progress: float, current_file: str):
        self.console_progress.set(progress)
        if current_file:
            self.console_file_label.configure(text=current_file)
        else:
            self.console_file_label.configure(text="")
    
    def _update_progress_ui(self, progress: float, current_file: str):
        self.after(0, lambda p=progress, f=current_file: self.progress_section.update_progress(p, f))
        self.after(0, lambda p=progress, f=current_file: self._update_console_progress(p, f"⬇️ {current_file}" if current_file else ""))
    
    def _validate_inputs(self) -> bool:
        json_path = self.json_selector.get()
        output_path = self.output_selector.get()
        
        if not json_path:
            messagebox.showerror("Error", "Please select a JSON file.")
            return False
        
        if not Path(json_path).exists():
            messagebox.showerror("Error", "The JSON file does not exist.")
            return False
        
        if not output_path:
            messagebox.showerror("Error", "Please select an output folder.")
            return False
        
        return True
    
    def _start_download(self):
        if not self._validate_inputs():
            return
        
        self.selected_years_cache = self._get_selected_years()
        self.is_downloading = True
        self.download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self._log("Starting download...")
        
        # Reset stats
        self.progress_section.reset()
        self.console_progress.set(0)
        self.console_file_label.configure(text="Preparing downloads...")
        self.stats_total.set_value("0")
        self.stats_downloaded.set_value("0")
        self.stats_skipped.set_value("0")
        self.stats_failed.set_value("0")
        
        # Start download in background thread
        thread = threading.Thread(target=self._run_download)
        thread.daemon = True
        thread.start()
    
    def _run_download(self):
        asyncio.run(self._download_async())
    
    async def _download_async(self):
        json_path = Path(self.json_selector.get())
        output_dir = Path(self.output_selector.get())
        max_concurrent = int(self.concurrent_slider.get())
        add_exif = self.exif_var.get()
        skip_existing = self.skip_var.get()
        auto_tune = self.auto_concurrency_var.get()
        selected_years = self.selected_years_cache
        
        try:
            memories = load_memories(json_path)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", f"Could not load JSON:\n{e}"))
            self.after(0, self._download_complete)
            return
        
        years_available = sorted({m.date.year for m in memories})
        if not self.year_vars:
            self.after(0, lambda yrs=years_available: self._populate_years(yrs, select_all=True))
        elif set(self.year_vars.keys()) != set(years_available):
            previous_selection = {y for y, var in self.year_vars.items() if var.get()}
            def update_years():
                self._populate_years(years_available, select_all=False)
                for y in years_available:
                    if y in previous_selection:
                        self.year_vars[y].set(True)
            self.after(0, update_years)
        
        if selected_years:
            memories = [m for m in memories if m.date.year in selected_years]
            self._log(f"Filtering to years: {', '.join(map(str, sorted(selected_years)))}")
        
        if not memories:
            self.after(0, lambda: messagebox.showinfo("Info", "No snaps match the selected years."))
            self.after(0, self._download_complete)
            return
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        stats = DownloadStats(total=len(memories))
        
        # Filter existing files
        to_download = []
        for memory in memories:
            jpg_path = output_dir / f"{memory.filename}.jpg"
            mp4_path = output_dir / f"{memory.filename}.mp4"
            if skip_existing and (jpg_path.exists() or mp4_path.exists()):
                stats.skipped += 1
            else:
                to_download.append(memory)
        
        # Update stats
        self.after(0, lambda: self.stats_total.set_value(str(stats.total)))
        self.after(0, lambda: self.stats_skipped.set_value(str(stats.skipped)))
        self._log(f"Queued {len(to_download)} files ({stats.skipped} skipped).")
        
        if not to_download:
            self.after(0, lambda: messagebox.showinfo("Info", "All files are already downloaded!"))
            self.after(0, self._download_complete)
            return
        
        completed = 0
        total_to_download = len(to_download)
        current_concurrency = max(1, min(max_concurrent, total_to_download))
        min_concurrency = 1
        
        async def process_memory(memory: Memory, semaphore: asyncio.Semaphore):
            nonlocal completed
            if not self.is_downloading:
                return False, None
            
            success, bytes_downloaded, result, status_code = await download_memory(
                memory, output_dir, add_exif, semaphore
            )
            
            completed += 1
            
            if success:
                stats.downloaded += 1
                stats.mb += bytes_downloaded / 1024 / 1024
                current_file = result
            else:
                stats.failed += 1
                current_file = f"Error: {result[:30]}..."
                if status_code == 429:
                    self._log("Rate limit detected on a request.")
            
            # Update UI
            progress = completed / total_to_download
            self._update_progress_ui(progress, current_file)
            self.after(0, lambda: self.stats_downloaded.set_value(str(stats.downloaded)))
            self.after(0, lambda: self.stats_failed.set_value(str(stats.failed)))
            
            return success, status_code
        
        idx = 0
        while idx < total_to_download and self.is_downloading:
            current_concurrency = max(min(current_concurrency, total_to_download - idx), 1)
            batch = to_download[idx: idx + current_concurrency]
            semaphore = asyncio.Semaphore(current_concurrency)
            
            self._log(f"Downloading batch {idx + 1}-{idx + len(batch)} / {total_to_download} at concurrency {current_concurrency}.")
            start_time = time.perf_counter()
            results = await asyncio.gather(*[process_memory(m, semaphore) for m in batch])
            elapsed = time.perf_counter() - start_time
            
            failures = sum(1 for r in results if r and not r[0])
            rate_limit_hits = any((r and r[1] == 429) for r in results)
            avg_time = elapsed / max(len(batch), 1)
            
            if auto_tune:
                new_concurrency = current_concurrency
                if rate_limit_hits:
                    new_concurrency = max(min_concurrency, current_concurrency // 2 or 1)
                    self._log(f"Rate limit encountered, reducing concurrency to {new_concurrency}.")
                elif failures / max(len(batch), 1) > 0.3:
                    new_concurrency = max(min_concurrency, current_concurrency - 1)
                    self._log(f"High error rate in batch, lowering concurrency to {new_concurrency}.")
                elif failures == 0 and not rate_limit_hits and avg_time < 1.5 and current_concurrency < max_concurrent:
                    new_concurrency = min(max_concurrent, current_concurrency + 1)
                    self._log(f"Stable & fast ({avg_time:.2f}s each). Bumping concurrency to {new_concurrency}.")
                
                current_concurrency = new_concurrency
            
            idx += len(batch)
        
        if not self.is_downloading:
            self._log("Download cancelled.")
            return
        
        # Complete
        self.after(0, self.progress_section.set_complete)
        self.after(0, lambda: self._update_console_progress(1, "All downloads complete"))
        self.after(0, self._download_complete)
        
        # Show summary
        summary = f"Download complete!\n\n"
        summary += f"📥 Downloaded: {stats.downloaded}\n"
        summary += f"⏭️ Skipped: {stats.skipped}\n"
        summary += f"❌ Failed: {stats.failed}\n"
        summary += f"💾 Size: {stats.mb:.1f} MB"
        self.after(0, lambda: messagebox.showinfo("Done", summary))
    
    def _cancel_download(self):
        self.is_downloading = False
        self._download_complete()
    
    def _download_complete(self):
        self.is_downloading = False
        self.download_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.console_file_label.configure(text="Ready for the next run")


# ============== Entry Point ==============

def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    
    app = SnapchatDownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
