"""Dashboard-specific engine changes. The original upstream file stays untouched.

PATCH_SOURCE is executed in the original module namespace so its unchanged
functions and these extensions share one state and the same synchronization locks.
Edit the extension definitions here rather than modifying the upstream script.
"""
import asyncio
import base64
import concurrent.futures
import datetime
import difflib
import functools
import hashlib
import http.cookiejar
import io
import json
import math
import os
import platform
import queue
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
import webbrowser
import zipfile
from collections import deque
try:
    import websockets
except ImportError:
    pass
try:
    import winsound
except ImportError:
    pass

PATCH_SOURCE = r'''
import argparse

import asyncio

import base64

import concurrent.futures

import datetime

import difflib

import hashlib

import http.cookiejar

import json

import math

import io

import wave

import functools

import uuid

from collections import deque

import os

import platform

import re

import shutil

import socket

import ssl

import struct

import subprocess

import sys

import tarfile

import tempfile

import threading

import time

import urllib.error

import urllib.parse

import urllib.request

import webbrowser

import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

if sys.platform == "win32" and sys.stdout is not None:
    os.system("")  # Enable ANSI virtual terminal processing on Windows cmd/PowerShell

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

GIST_REVISION = 34

_mask_spoilers: bool = False

_auto_open: bool = False

_browser_fallback: bool = False

DEFAULT_POLL_INTERVAL_SECONDS = 15

MIN_POLL_INTERVAL_SECONDS = 5

_poll_interval: int = DEFAULT_POLL_INTERVAL_SECONDS

_refresh_condition = threading.Condition()

_refresh_generation = 0

_refresh_active = set()

_refresh_clock_running = False

def normalize_poll_interval(value):
    try:
        return max(MIN_POLL_INTERVAL_SECONDS, min(3600, int(value)))
    except (ValueError, TypeError, OverflowError):
        return DEFAULT_POLL_INTERVAL_SECONDS

def wait_for_refresh(generation, worker):
    """All data workers consume the same clock; slow workers skip missed ticks."""
    with _refresh_condition:
        _refresh_active.discard(worker)
        while _refresh_generation <= generation and not _shutdown_event.is_set():
            _refresh_condition.wait(timeout=0.2)
        if _shutdown_event.is_set():
            return None
        _refresh_active.add(worker)
        return _refresh_generation

def refresh_scheduler_thread():
    """Publish one shared refresh tick and countdown for every scheduled feed."""
    global _refresh_generation, _next_poll_time, _refresh_clock_running
    _refresh_clock_running = True
    interval = normalize_poll_interval(_poll_interval)
    deadline = time.monotonic() + interval
    while not _shutdown_event.is_set():
        configured = normalize_poll_interval(_poll_interval)
        if configured != interval:
            interval = configured
            deadline = time.monotonic() + interval
        remaining = max(0.0, deadline - time.monotonic())
        _next_poll_time = time.time() + remaining
        if _shutdown_event.wait(min(remaining, 0.1)):
            break
        if normalize_poll_interval(_poll_interval) != interval:
            continue
        if time.monotonic() < deadline:
            continue
        with _refresh_condition:
            _refresh_generation += 1
            _refresh_condition.notify_all()
        deadline += interval
        if deadline <= time.monotonic():
            deadline = time.monotonic() + interval
    with _refresh_condition:
        _refresh_clock_running = False
        _refresh_condition.notify_all()

_rpc_diagnostics = {}

_website_state = {}

_download_jobs = {}

_download_totals = {'completed': 0, 'failed': 0, 'canceled': 0, 'external': 0}

_download_context = threading.local()

def _sanitize_output(text: str) -> str:
    """Strips ANSI escapes and control characters from untrusted chain-derived text."""
    return _CONTROL_CHAR_RE.sub("", _ANSI_ESCAPE_RE.sub("", str(text)))

def get_or_derive_option_atas(poll_id_hex: str, choice_count: int) -> list[tuple[str, str]]:
    """Derives (wallet_pda, ata_pubkey) for each choice index of a poll."""
    if poll_id_hex in _option_atas_cache:
        return _option_atas_cache[poll_id_hex]
    try:
        poll_id_bytes = bytes.fromhex(poll_id_hex)
        prog_id = _b58decode(PROGRAM_ID)
        token_prog = _b58decode("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        ata_prog = _b58decode("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        mint = _b58decode(TOKEN_MINT)
        res = []
        for idx in range(choice_count):
            opt_wallet, _ = find_program_address([b"option", poll_id_bytes, bytes([idx])], prog_id)
            if not opt_wallet:
                continue
            ata, _ = find_program_address([opt_wallet, token_prog, mint], ata_prog)
            if ata:
                res.append((_b58encode(opt_wallet), _b58encode(ata)))
        if res:
            _option_atas_cache[poll_id_hex] = res
        return res
    except Exception:
        return []

def load_config(config_path: str) -> dict:
    """Loads configuration options from a JSON file, generating defaults if absent."""
    global _last_config_mtime
    defaults = {
        "mask_spoilers": False,
        "auto_open_media": False,
        "enable_sound": True,
        "download_payloads": True,
        "browser_fallback": False,
        "download_dir": "./leaks",
        "poll_interval_seconds": DEFAULT_POLL_INTERVAL_SECONDS,
        "custom_rpc_url": None,
        "custom_ws_url": None,
    }
    if not os.path.exists(config_path):
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(defaults, f, indent=2)
            _last_config_mtime = os.path.getmtime(config_path)
        except Exception:
            pass
        return defaults
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            for k, v in defaults.items():
                if k not in loaded:
                    loaded[k] = v
        loaded["poll_interval_seconds"] = normalize_poll_interval(loaded["poll_interval_seconds"])
        _last_config_mtime = os.path.getmtime(config_path)
        return loaded
    except Exception:
        return defaults

def save_config(config_path: str | None = None):
    """Saves active runtime configuration options atomically to the JSON config file."""
    global _last_config_mtime
    path = config_path or _config_file
    data = {
        "mask_spoilers": _mask_spoilers,
        "auto_open_media": _auto_open,
        "enable_sound": _enable_sound,
        "download_payloads": not _watch_only,
        "browser_fallback": _browser_fallback,
        "download_dir": _download_dir,
        "poll_interval_seconds": _poll_interval,
        "custom_rpc_url": _custom_rpc_url,
        "custom_ws_url": _custom_ws_url,
    }
    try:
        dir_name = os.path.dirname(os.path.abspath(path))
        os.makedirs(dir_name, exist_ok=True)
        tmp_path = f"{path}.{threading.get_ident()}.{os.getpid()}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        try:
            _last_config_mtime = os.path.getmtime(path)
        except Exception:
            pass
        return True
    except Exception as exc:
        log_msg(f'[!] Settings could not be saved: {exc}')
        return False

def config_watcher_thread():
    """Monitors watcher_config.json for external modifications, regenerating if deleted or recovering from errors."""
    global _last_config_mtime, _last_config_warn_ts
    global _mask_spoilers, _auto_open, _enable_sound, _watch_only, _browser_fallback, _poll_interval
    while not _shutdown_event.is_set():
        try:
            if not os.path.exists(_config_file):
                # Config file was deleted - regenerate it automatically from current runtime settings
                save_config(_config_file)
                log_msg(f"[*] '{os.path.basename(_config_file)}' was removed - regenerated config from active runtime settings.")
            else:
                curr_mtime = os.path.getmtime(_config_file)
                if _last_config_mtime > 0 and curr_mtime > _last_config_mtime:
                    _last_config_mtime = curr_mtime
                    try:
                        with open(_config_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        if isinstance(data, dict):
                            changes = []
                            if "mask_spoilers" in data and isinstance(data["mask_spoilers"], bool) and data["mask_spoilers"] != _mask_spoilers:
                                _mask_spoilers = data["mask_spoilers"]
                                changes.append(f"Spoilers={'MASKED' if _mask_spoilers else 'VISIBLE'}")
                            if "auto_open_media" in data and isinstance(data["auto_open_media"], bool) and data["auto_open_media"] != _auto_open:
                                _auto_open = data["auto_open_media"]
                                changes.append(f"Auto-Open={'ON' if _auto_open else 'OFF'}")
                            if "enable_sound" in data and isinstance(data["enable_sound"], bool) and data["enable_sound"] != _enable_sound:
                                _enable_sound = data["enable_sound"]
                                changes.append(f"Chimes={'ON' if _enable_sound else 'MUTED'}")
                            if "download_payloads" in data and isinstance(data["download_payloads"], bool):
                                new_watch_only = not data["download_payloads"]
                                if new_watch_only != _watch_only:
                                    _watch_only = new_watch_only
                                    changes.append(f"Download={'ACTIVE' if not _watch_only else 'WATCH-ONLY'}")
                            if "poll_interval_seconds" in data and isinstance(data["poll_interval_seconds"], (int, float)):
                                new_interval = normalize_poll_interval(data["poll_interval_seconds"])
                                if new_interval != _poll_interval:
                                    _poll_interval = new_interval
                                    changes.append(f"Interval={_poll_interval}s")
                            
                            if changes:
                                log_msg(f"[*] Configuration reloaded from '{os.path.basename(_config_file)}': {', '.join(changes)}")
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        now = time.time()
                        if now - _last_config_warn_ts > 10.0:
                            _last_config_warn_ts = now
                            log_msg(f"[-] Warning: '{os.path.basename(_config_file)}' contains invalid JSON syntax - keeping current runtime settings.")
                    except (PermissionError, OSError):
                        pass
        except Exception:
            pass
        if _shutdown_event.wait(1.5):
            break

def record_manifest_entry(download_dir: str, pda: str, title: str, filename: str, mirrors: list = None):
    """Appends or updates a file mapping in the directory's manifest.json in a thread-safe atomic manner."""
    with _manifest_lock:
        manifest_path = os.path.join(download_dir, "manifest.json")
        manifest = {}
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception:
                manifest = {}
        manifest[pda] = {
            "true_title": title,
            "saved_file": os.path.basename(filename) if filename else "",
            "saved_path": os.path.abspath(filename) if filename else "",
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "mirrors": mirrors or [],
        }
        try:
            tmp_path = f"{manifest_path}.{threading.get_ident()}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, manifest_path)
        except Exception:
            pass

def get_hotkey_status_line(cols: int = 80) -> str:
    """Formats the second bottom status line displaying interactive controls adaptively."""
    sp = "ON" if _mask_spoilers else "OFF"
    sd = "ON" if _enable_sound else "OFF"
    ao = "ON" if _auto_open else "OFF"
    dl = "ON" if not _watch_only else "OFF"
    br = "ON" if _browser_fallback else "OFF"
    
    if cols >= 135:
        sp_l = "MASKED" if _mask_spoilers else "VISIBLE"
        sd_l = "ON" if _enable_sound else "MUTED"
        dl_l = "ACTIVE" if not _watch_only else "WATCH"
        return f"Controls: [S] Spoilers: {sp_l} | [M] Chimes: {sd_l} | [O] Open: {ao} | [D] DL: {dl_l} | [V] Poll | [C] MCAP | [X] Extract | [H] Help | [Q] Quit"
    elif cols >= 105:
        return f"[S] Mask: {sp} | [M] Chime: {sd} | [O] Open: {ao} | [V] Poll | [C] MCAP | [X] Extract | [H] Help | [Q] Quit"
    elif cols >= 68:
        # Standard 80-column terminal (exact <= 76 chars)
        return f"[S] Mask: {sp} | [M] Sound: {sd} | [V] Poll | [C] MCAP | [H] Help | [Q] Quit"
    else:
        # Narrow mobile terminals (Android / Termux / iOS <65 cols)
        return f"[S] Mask | [M] Sound | [C] MCAP | [Q] Quit"

def calculate_mcap_and_milestones(price_usd: float) -> dict:
    """Calculates circulating market cap, dev reserve valuation, and progress towards operator milestones."""
    global _dev_reserve
    if price_usd <= 0:
        return {}
    mcap = current_market_cap(price_usd)
    dev_usd = _dev_reserve * price_usd
    dev_pct = (_dev_reserve / CIRCULATING_SUPPLY * 100) if CIRCULATING_SUPPLY > 0 else 0.0
    
    milestone_progress = []
    next_milestone = None
    for target_mcap, label in MCAP_MILESTONES:
        target_price = target_mcap / CIRCULATING_SUPPLY
        pct_achieved = min(100.0, (mcap / target_mcap * 100.0))
        is_achieved = mcap >= target_mcap
        item = {
            "target_mcap": target_mcap,
            "target_price": target_price,
            "label": label,
            "pct_achieved": pct_achieved,
            "achieved": is_achieved,
        }
        milestone_progress.append(item)
        if not is_achieved and next_milestone is None:
            next_milestone = item
            
    return {
        "price_usd": price_usd,
        "circulating_supply": CIRCULATING_SUPPLY,
        "market_cap_usd": mcap,
        "dev_reserve_cyberleek": _dev_reserve,
        "dev_reserve_usd": dev_usd,
        "dev_reserve_pct": dev_pct,
        "milestones": milestone_progress,
        "next_milestone": next_milestone,
    }

def format_poll_status_line(info: dict | None, cols: int = 80) -> str:
    """Formats live community poll options, token balances, and USD valuations adaptively for status bar."""
    if not info:
        return f"Polls: {len(_known_proposals)}"
    bals = info.get("balances", [])
    usds = info.get("usd_vals", [])
    tot = info.get("total", 0.0)
    rem = info.get("time_rem_str", "")
    price = info.get("price_usd", 0.0)
    leader_idx = info.get("leader_idx", 0)
    leader_pct = info.get("leader_pct", 0.0)
    tot_usd = info.get("total_usd", 0.0)
    
    # If 2 choices, show both choices side by side
    if len(bals) <= 2:
        opt_strs = []
        for i, b in enumerate(bals):
            pct = (b / tot * 100.0) if tot > 0 else 0.0
            u = usds[i] if i < len(usds) else (b * price if price > 0 else 0.0)
            b_str = f"{b/1000:.1f}k" if b >= 1000 else f"{b:,.0f}"
            if cols >= 135:
                opt_strs.append(f"Opt{i}: {b_str} (${u:.2f}, {pct:.0f}%)" if u > 0 else f"Opt{i}: {b_str} ({pct:.0f}%)")
            elif cols >= 105:
                opt_strs.append(f"Opt{i}: {b_str} (${u:.2f})" if u > 0 else f"Opt{i}: {b_str} ({pct:.0f}%)")
            else:
                opt_strs.append(f"O{i}:${u:.2f}" if u > 0 else f"O{i}:{b_str}")
        vs_joined = " vs ".join(opt_strs)
        return f"Poll: [{vs_joined}] [{rem}]" if rem else f"Poll: [{vs_joined}]"
        
    # If > 2 choices (e.g. Proposal #5 with 4 choices):
    if cols >= 150:
        opt_strs = []
        for i, b in enumerate(bals):
            pct = (b / tot * 100.0) if tot > 0 else 0.0
            u = usds[i] if i < len(usds) else (b * price if price > 0 else 0.0)
            b_str = f"{b/1000:.1f}k" if b >= 1000 else f"{b:,.0f}"
            opt_strs.append(f"O{i}:{b_str}(${u:.0f},{pct:.0f}%)")
        return f"Poll: [{', '.join(opt_strs)}] [{rem}]"
    elif cols >= 105:
        l_bal = bals[leader_idx] if leader_idx < len(bals) else 0.0
        l_str = f"{l_bal/1000:.1f}k" if l_bal >= 1000 else f"{l_bal:,.0f}"
        l_u = usds[leader_idx] if leader_idx < len(usds) else 0.0
        tot_u_str = f" (${tot_usd:.0f})" if tot_usd > 0 else ""
        return f"Poll: [Opt {leader_idx} Leads: {l_str} (${l_u:.2f}, {leader_pct:.0f}%)] Tot:{tot/1000:.1f}k{tot_u_str} [{rem}]"
    else:
        # Compact (< 105 cols, 80 cols or mobile)
        l_u = usds[leader_idx] if leader_idx < len(usds) else 0.0
        return f"Poll: [O{leader_idx} Leads: ${l_u:.0f} ({leader_pct:.0f}%)] [{rem}]"

def set_status(status_text: str):
    """Updates the dynamic bottom status lines pinned at the base of the terminal without line wrapping."""
    global _current_status_line
    if _quiet:
        return
    with _status_lock:
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
        max_len = max(20, cols - 1)
        line1 = _sanitize_output(status_text)
        if len(line1) > max_len:
            line1 = line1[:max_len - 3] + "..."
        else:
            line1 = line1.ljust(max_len)
        line2 = get_hotkey_status_line(cols=cols)
        if len(line2) > max_len:
            line2 = line2[:max_len - 3] + "..."
        else:
            line2 = line2.ljust(max_len)
        _current_status_line = (line1, line2)
        sys.stdout.write(f"\r{line1}\n\r{line2}\033[A\r")
        sys.stdout.flush()

def log_msg(msg: str):
    """Outputs a scrollable log message cleanly above the pinned two-line status bar and logs to file if enabled."""
    clean = _sanitize_output(msg)
    if _log_file:
        try:
            with open(_log_file, "a", encoding="utf-8") as f:
                f.write(clean.rstrip() + "\n")
        except Exception:
            pass
    with _status_lock:
        if not _quiet:
            cols = shutil.get_terminal_size(fallback=(80, 24)).columns
            max_len = max(20, cols - 1)
            # Erase the current status bar area
            sys.stdout.write("\r" + " " * max_len + "\n\r" + " " * max_len + "\033[A\r")
            # Print the log message cleanly
            sys.stdout.write(clean.rstrip() + "\n")
            # Redraw status bar if active
            if _current_status_line:
                line1, line2 = _current_status_line
                sys.stdout.write(f"\r{line1}\n\r{line2}\033[A\r")
        else:
            sys.stdout.write(clean.rstrip() + "\n")
        sys.stdout.flush()

def print_interactive_help():
    """Prints a clear reference table of interactive hotkeys and their current states."""
    sp_desc = "MASKED (titles and filenames hidden)" if _mask_spoilers else "VISIBLE (full titles displayed)"
    sd_desc = "ON (chimes sound for new releases)" if _enable_sound else "MUTED (silent mode)"
    ao_desc = "ON (media launches in player)" if _auto_open else "OFF (files saved without opening)"
    dl_desc = "ACTIVE (downloading payloads)" if not _watch_only else "WATCH-ONLY (monitoring only)"
    br_desc = "OFF (downloads stay in background)"
    
    sep = "=" * 76
    help_text = (
        f"\n{sep}\n"
        f"[*] INTERACTIVE RUNTIME CONTROLS REFERENCE:\n"
        f"    [S] Toggle Spoilers      : Currently {sp_desc}\n"
        f"    [M] Toggle Audio Chimes  : Currently {sd_desc}\n"
        f"    [O] Toggle Auto-Open     : Currently {ao_desc}\n"
        f"    [D] Toggle Download Mode : Currently {dl_desc}\n"
        f"    [B] Toggle Browser Tabs  : Currently {br_desc}\n"
        f"    [A] Backfill All Leaks   : Download all historical on-chain leak files now\n"
        f"    [U] Unmask Local Files   : Rename existing masked files on disk using manifest\n"
        f"    [T] Test Audio Chime     : Play chime to verify speakers / audio driver\n"
        f"    [P] Export State Snapshot: Save current on-chain state to JSON\n"
        f"    [V] View Poll Breakdown  : Print live vote tally and USD values for all options\n"
        f"    [C] Market Cap Breakdown : Display circulating market cap, dev reserve USD, and leak tiers\n"
        f"    [X] Extract All Archives : Attempt password recovery extraction on all local archives\n"
        f"    [H] Display Help Menu    : Show this control reference\n"
        f"    [Q] Quit                 : Cleanly stop background threads and exit\n"
        f"{sep}\n"
    )
    log_msg(help_text)

def _handle_hotkey(ch: str):
    """Processes interactive hotkey triggers with descriptive status updates."""
    global _mask_spoilers, _auto_open, _enable_sound, _watch_only, _browser_fallback
    ch = ch.lower()
    if ch == "s":
        _mask_spoilers = not _mask_spoilers
        save_config()
        if _mask_spoilers:
            log_msg("[*] [S] Spoilers are MASKED (leak titles and filenames hidden).")
        else:
            log_msg("[*] [S] Spoilers are VISIBLE (full leak titles displayed).")
    elif ch == "m":
        _enable_sound = not _enable_sound
        save_config()
        if _enable_sound:
            log_msg("[*] [M] Chimes are ON (alerts will sound for releases).")
        else:
            log_msg("[*] [M] Chimes are MUTED.")
    elif ch == "o":
        _auto_open = not _auto_open
        save_config()
        if _auto_open:
            log_msg("[*] [O] Media auto-open is ON (player launches on download).")
        else:
            log_msg("[*] [O] Media auto-open is OFF (files saved without launching).")
    elif ch == "d":
        _watch_only = not _watch_only
        save_config()
        if not _watch_only:
            log_msg("[*] [D] Download mode is ACTIVE (auto-downloading payloads).")
        else:
            log_msg("[*] [D] Download mode is WATCH-ONLY (monitoring only).")
    elif ch == "b":
        _browser_fallback = False
        log_msg('[*] Automated downloads run in the background; browser fallback is disabled.')
    elif ch == "a":
        backfill_assets()
    elif ch == "u":
        log_msg(f"[*] [U] Unmasking local files in '{_download_dir}' using manifest.json...")
        unmask_downloaded_files(_download_dir)
    elif ch == "t":
        log_msg("[*] [T] Triggering test audio chime...")
        play_leak_chime()
    elif ch == "p":
        snap_path = os.path.join(_download_dir, "cyberleek_state_snapshot.json")
        dump_snapshot(snap_path)
        log_msg(f"[*] [P] State snapshot exported to: {snap_path}")
    elif ch == "v":
        if _active_poll_info:
            info = _active_poll_info
            price = info.get("price_usd", 0.0)
            tot = info.get("total", 0.0)
            tot_usd = info.get("total_usd", 0.0)
            log_msg(f"\n[*] [V] LIVE COMMUNITY POLL BREAKDOWN: {info['title']}")
            if price > 0:
                log_msg(f"    CYBERLEEK Token Price: ${price:.6f} USD")
            log_msg(f"    Voting Closes In: {info['time_rem_str']}")
            log_msg(f"    Current Leader: Option {info['leader_idx']} ({info['leader_choice']}) with {info['leader_pct']:.1f}%")
            for idx, (ch_name, bal, u_val) in enumerate(zip(info["choices"], info["balances"], info.get("usd_vals", [0.0]*len(info["choices"])))):
                pct = (bal / tot * 100.0) if tot > 0 else 0.0
                usd_str = f" (${u_val:,.2f} USD)" if price > 0 else ""
                log_msg(f"    - Option {idx} ({ch_name}): {bal:,.2f} CYBERLEEK{usd_str} ({pct:.1f}%)")
            tot_usd_str = f" (${tot_usd:,.2f} USD)" if price > 0 else ""
            log_msg(f"    Total Staked Votes: {tot:,.2f} CYBERLEEK{tot_usd_str}\n")
        else:
            log_msg("\n[*] [V] No active community poll currently open on-chain.\n")
    elif ch == "c":
        price = fetch_cyberleek_usd_price()
        mcap_info = calculate_mcap_and_milestones(price)
        if mcap_info:
            mcap = mcap_info["market_cap_usd"]
            dev_u = mcap_info["dev_reserve_usd"]
            dev_bal = mcap_info["dev_reserve_cyberleek"]
            dev_pct = mcap_info["dev_reserve_pct"]
            log_msg(f"\n[*] [C] MARKET CAP & OPERATOR MILESTONES BREAKDOWN:")
            log_msg(f"    CYBERLEEK Token Price: ${price:.6f} USD")
            log_msg(f"    Circulating Supply   : {CIRCULATING_SUPPLY:,.0f} tokens")
            log_msg(f"    Market Capitalization: ${mcap:,.2f} USD (${mcap/1e6:.2f}M)")
            log_msg(f"    Developer Reserve    : {dev_bal:,.0f} tokens (${dev_u:,.2f} USD, {dev_pct:.2f}% of supply)")
            log_msg(f"\n    Notice Extortion Milestones (Notice #1 & #2 targets):")
            for m in mcap_info["milestones"]:
                status_icon = "[ACHIEVED]" if m["achieved"] else f"[{m['pct_achieved']:.1f}%]"
                target_str = f"${m['target_mcap']/1e6:.1f}M"
                log_msg(f"    - {target_str:<6} : {status_icon:<10} {m['label']} (Target Price: ${m['target_price']:.6f})")
            next_m = mcap_info.get("next_milestone")
            if next_m:
                needed = next_m["target_mcap"] - mcap
                log_msg(f"    --> Next Leak Tier: {next_m['label']} (${next_m['target_mcap']/1e6:.1f}M) - ${needed:,.0f} to go!\n")
            else:
                log_msg(f"    --> ALL ON-CHAIN MILESTONES SURPASSED!\n")
        else:
            log_msg("\n[*] [C] Token price currently unavailable from DEX or zero.\n")
    elif ch == "x":
        log_msg(f"\n[*] [X] Scanning '{_download_dir}' to extract password-protected archives...")
        extract_all_local_archives(_download_dir)
    elif ch == "h":
        print_interactive_help()
    elif ch == "q":
        log_msg("[*] [Q] Shutting down monitor...")
        _shutdown_event.set()

def hotkey_listener_thread():
    """Background listener for non-blocking interactive keyboard input across Windows and POSIX."""
    try:
        import msvcrt
        has_msvcrt = True
    except ImportError:
        has_msvcrt = False

    old_termios = None
    if not has_msvcrt and sys.stdin.isatty():
        try:
            import termios, tty, atexit
            old_termios = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            atexit.register(lambda: termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_termios))
        except Exception:
            pass
    try:
        while not _shutdown_event.is_set():
            try:
                if has_msvcrt:
                    if msvcrt.kbhit():
                        ch = msvcrt.getwch()
                        if ch in ('\x00', '\xe0'):
                            # Extended key prefix (arrow keys, function keys, delete, insert)
                            if msvcrt.kbhit():
                                msvcrt.getwch()
                            continue
                        _handle_hotkey(ch)
                else:
                    import select
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        ch = sys.stdin.read(1)
                        if ch == '\x1b':
                            # Discard ANSI escape sequences from arrow or function keys
                            if select.select([sys.stdin], [], [], 0.01)[0]:
                                sys.stdin.read(2)
                            continue
                        _handle_hotkey(ch)
            except Exception:
                pass
            _shutdown_event.wait(0.05)
    finally:
        if old_termios is not None:
            try:
                import termios
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_termios)
            except Exception:
                pass

def play_leak_chime():
    """High-priority alert reserved for new leak entries."""
    _play_chime("urgent")

def play_info_chime():
    """Lower-priority alert for infrastructure / security events."""
    _play_chime("info")

_audio_lock = threading.Lock()

_chime_wav_cache = {}

def _chime_wav(style):
    """Generate PCM audio for the normal Windows playback device."""
    if style in _chime_wav_cache:
        return _chime_wav_cache[style]
    rate = 22050
    notes = [(880, .16), (1175, .22), (0, .08)] * 6 if style == 'urgent' else [(660, .18), (880, .28), (0, .08)] * 2
    samples = bytearray()
    for frequency, duration in notes:
        count = int(rate * duration)
        for index in range(count):
            envelope = min(1.0, index / (rate * .01), (count - index - 1) / (rate * .035))
            value = int(14000 * envelope * math.sin(2 * math.pi * frequency * index / rate)) if frequency else 0
            samples.extend(struct.pack('<h', value))
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(samples)
    data = stream.getvalue()
    _chime_wav_cache[style] = data
    return data

def _windows_chime_worker(style, test=False):
    if not _audio_lock.acquire(blocking=False):
        if test:
            log_msg('[*] Audio is already playing. Try Test sound again in a moment.')
        return
    try:
        if test:
            log_msg('[*] Playing test audio through the Windows default output device (ignores alert mute).')
        try:
            # Memory WAV playback must be synchronous, so it runs on this worker.
            winsound.PlaySound(_chime_wav(style), winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        except Exception as exc:
            log_msg(f'[!] Audio playback failed: {exc}. Trying the Windows system sound.')
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception as fallback:
                log_msg(f'[!] System sound also failed: {fallback}')
                return
        if test:
            log_msg('[+] Test sound playback completed. If inaudible, check the Windows output device and this app in Volume Mixer.')
    finally:
        _audio_lock.release()

def _play_chime(style: str, force=False):
    if not _enable_sound and not force:
        return
    if HAS_WINSOUND:
        threading.Thread(target=_windows_chime_worker, args=(style, force), daemon=True).start()
        return
    def _urgent():
        if IS_ANDROID and shutil.which("termux-vibrate"):
            try:
                subprocess.Popen(["termux-vibrate", "-d", "400", "-f"])
                if shutil.which("termux-notification"):
                    subprocess.Popen(["termux-notification", "--title", "CYBERLEEK ALERT", "--content", "High-priority on-chain leak or update detected!"])
            except Exception:
                pass
        elif shutil.which("afplay"):
            for snd in ("/System/Library/Sounds/Glass.aiff", "/System/Library/Sounds/Ping.aiff"):
                if os.path.exists(snd):
                    try:
                        subprocess.Popen(["afplay", snd])
                        break
                    except Exception:
                        pass
        elif shutil.which("paplay"):
            for snd in ("/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga", "/usr/share/sounds/gnome/default/alerts/glass.ogg"):
                if os.path.exists(snd):
                    try:
                        subprocess.Popen(["paplay", snd])
                        break
                    except Exception:
                        pass
        else:
            for _ in range(5):
                sys.stdout.write("\a")
                sys.stdout.flush()
                time.sleep(1)
    def _info():
        if IS_ANDROID and shutil.which("termux-vibrate"):
            try:
                subprocess.Popen(["termux-vibrate", "-d", "150"])
            except Exception:
                pass
        elif shutil.which("afplay"):
            for snd in ("/System/Library/Sounds/Tink.aiff", "/System/Library/Sounds/Ping.aiff"):
                if os.path.exists(snd):
                    try:
                        subprocess.Popen(["afplay", snd])
                        break
                    except Exception:
                        pass
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
            time.sleep(1.5)
            sys.stdout.write("\a")
            sys.stdout.flush()
    threading.Thread(target=_info if style == "info" else _urgent, daemon=True).start()

def rpc_call(method: str, params: list, rpc_idx: int = 0, return_full: bool = False) -> dict | None:
    """Executes a JSON-RPC request against Solana endpoints with automatic failover, cooldown, and error tracking."""
    now = time.time()
    candidates = [u for u in RPC_ENDPOINTS if _rpc_cooldowns.get(u, 0) <= now] or RPC_ENDPOINTS
    for offset in range(len(candidates)):
        url = candidates[(rpc_idx + offset) % len(candidates)]
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        started = time.monotonic()
        data, err = http_post_json(url, payload, timeout=4.0)
        with _state_lock:
            diagnostics = _rpc_diagnostics.setdefault(url, {'successes': 0, 'failures': 0, 'last_success': None})
            rpc_error = data.get('error') if isinstance(data, dict) else None
            success = err is None and isinstance(data, dict) and not rpc_error
            diagnostics.update({'latency_ms': (time.monotonic() - started) * 1000,
                                'last_attempt': time.time(), 'method': method,
                                'error': _format_net_exception(err) if err else str(rpc_error.get('message', 'RPC error')) if isinstance(rpc_error, dict) else None if success else 'Invalid RPC response'})
            diagnostics['successes' if success else 'failures'] += 1
            if success:
                diagnostics['last_success'] = time.time()
        if err is None and isinstance(data, dict) and data.get('error'):
            rpc_error = data['error']
            if return_full and isinstance(rpc_error, dict) and rpc_error.get('code') == -32602:
                return data
            _rpc_errors[url] = str(rpc_error)
            continue
        if err is None and isinstance(data, dict):
            _rpc_errors.pop(url, None)
            if return_full:
                return data
            return data.get("result")
        if err is not None:
            _rpc_errors[url] = _format_net_exception(err)
            if isinstance(err, urllib.error.HTTPError) and err.code in (429, 403, 400, 500, 502, 503):
                _rpc_cooldowns[url] = time.time() + 60.0
    return None

def fetch_token_balance(ata_pubkey: str) -> float | None:
    """Retrieves the UI balance of an SPL Token account. Returns 0.0 if closed/liquidated on-chain, or None on RPC network failure."""
    resp = rpc_call("getTokenAccountBalance", [ata_pubkey, {"commitment": "processed"}], return_full=True)
    if resp is None:
        return None
    if "result" in resp and resp["result"] and "value" in resp["result"]:
        value = resp["result"]["value"]
        amount = value.get("uiAmount")
        if amount is None:
            amount = value.get("uiAmountString")
        if amount is None:
            return None
        try:
            balance = float(amount)
            return balance if math.isfinite(balance) and balance >= 0 else None
        except (TypeError, ValueError):
            return None
    err = resp.get("error", {})
    if isinstance(err, dict):
        err_msg = str(err.get("message", "")).lower()
        if err.get("code") == -32602 or "could not find account" in err_msg or "not a token account" in err_msg:
            return 0.0
    return None

def fetch_total_reserve_balance() -> tuple[float | None, dict[str, float]]:
    """Polls all dynamically discovered reserve token accounts and returns (total_sum, per_account_balances)."""
    with _state_lock:
        atas = list(_monitored_reserve_atas.keys())
    if not atas:
        return None, {}
    total = 0.0
    balances = {}
    for ata in atas:
        bal = fetch_token_balance(ata)
        if bal is None:
            # Network / RPC error on account query: abort calculation so an incomplete sum
            # never triggers a false "LARGE RESERVE DECREASE DETECTED" alert.
            return None, {}
        balances[ata] = bal
        total += bal
    with _state_lock:
        for ata, bal in balances.items():
            if ata in _monitored_reserve_atas:
                _monitored_reserve_atas[ata]["balance"] = bal
    return total, balances

def fetch_program_state() -> dict | None:
    """Fetches and parses all program accounts for every monitored program ID.

    Returns None when any program query fails, so partial outage windows never
    masquerade as deleted accounts or missing community polls.
    """
    all_accounts = []
    any_endpoint_ok = False
    for program_id in PROGRAM_IDS:
        res = rpc_call("getProgramAccounts", [program_id, {"encoding": "base64"}])
        if not isinstance(res, list):
            return None
        any_endpoint_ok = True
        all_accounts.extend(res)
    if not any_endpoint_ok:
        return None

    accounts = all_accounts
    links = []
    proposals = []
    configs = []
    registries = []
    notices = []
    integrity = {
        "Link": [0, 0],
        "Proposal": [0, 0],
        "FrontendConfig": [0, 0],
        "Notice": [0, 0],
    }
    for acc in accounts:
        pubkey = acc["pubkey"]
        data_b64 = acc["account"]["data"][0]
        raw_bytes = base64.b64decode(data_b64)

        disc = raw_bytes[:8]
        if disc == DISCRIMINATORS["account_link"]:
            integrity["Link"][0] += 1
            parsed = parse_link_account(raw_bytes, pubkey)
            if parsed:
                links.append(parsed)
                integrity["Link"][1] += 1
        elif disc == DISCRIMINATORS["account_proposal"]:
            integrity["Proposal"][0] += 1
            parsed = parse_proposal_account(raw_bytes, pubkey)
            if parsed:
                proposals.append(parsed)
                integrity["Proposal"][1] += 1
        elif disc == DISCRIMINATORS["account_frontend_config"]:
            integrity["FrontendConfig"][0] += 1
            parsed = parse_frontend_config(raw_bytes, pubkey)
            if parsed:
                configs.append(parsed)
                integrity["FrontendConfig"][1] += 1
        elif disc == DISCRIMINATORS["account_registry"]:
            parsed = parse_registry_account(raw_bytes, pubkey)
            if parsed:
                registries.append(parsed)
        elif disc == DISCRIMINATORS["account_notice"]:
            integrity["Notice"][0] += 1
            parsed = parse_notice_account(raw_bytes, pubkey)
            if parsed:
                notices.append(parsed)
                integrity["Notice"][1] += 1

    return {
        "links": links,
        "proposals": proposals,
        "configs": configs,
        "registries": registries,
        "notices": notices,
        "integrity": integrity,
    }

def open_in_browser(url: str):
    """Legacy hook: automated retrieval never launches a browser."""
    return

def open_asset_and_folder(file_path: str, folder_path: str = None):
    """Opens the downloaded asset and displays it in the system file explorer across desktop and mobile.
    
    - All files are automatically selected and highlighted in the OS file manager.
    - Safe media files (video, audio, images, torrents) are launched in default player/viewer.
    - Documents (.pdf), archives, scripts, database dumps, and binaries highlight in folder without auto-executing.
    """
    if not file_path or not os.path.exists(file_path):
        return
    if not _auto_open:
        log_msg(f"[*] Saved payload to: {os.path.abspath(file_path)} (auto-open disabled)")
        return
        
    folder = folder_path or os.path.dirname(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    
    # 1. Open media in default player / viewer
    if ext in MEDIA_AUTO_OPEN_EXTENSIONS:
        try:
            if sys.platform == "win32":
                os.startfile(file_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", file_path])
            elif IS_ANDROID and shutil.which("termux-open"):
                subprocess.Popen(["termux-open", file_path])
            elif shutil.which("xdg-open") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
                subprocess.Popen(["xdg-open", file_path])
        except Exception:
            pass
            
    # 2. Select file in OS file manager
    try:
        if sys.platform == "win32":
            subprocess.Popen(f'explorer /select,"{os.path.normpath(os.path.abspath(file_path))}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", os.path.abspath(file_path)])
        elif IS_ANDROID and shutil.which("termux-open"):
            subprocess.Popen(["termux-open", folder])
        elif shutil.which("xdg-open") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        pass

def find_candidate_passwords(target_dir: str, hint: str = "") -> list[str]:
    """Discovers archive decryption passwords from companion files, hints, and project dictionary."""
    candidates: list[str] = []
    if hint:
        # 1. Parse specific password patterns from title or hint (e.g. "zip password: cyberleek", "pass: 1234", "password is abc")
        for m in re.finditer(r"(?i)(?:zip\s+password|password|passphrase|pass|pwd|secret|key)[:\s=]+([^\s\"',;]+)", hint):
            w = m.group(1).strip().strip('"').strip("'")
            if w and w not in candidates:
                candidates.append(w)
        for m in re.finditer(r"(?i)(?:password|passphrase|pass|pwd)\s+is\s+([^\s\"',;]+)", hint):
            w = m.group(1).strip().strip('"').strip("'")
            if w and w not in candidates:
                candidates.append(w)
        hint_clean = hint.strip().strip('"').strip("'")
        if hint_clean and hint_clean not in candidates:
            candidates.append(hint_clean)
            
    # Inspect local directory and download root for companion password files
    search_dirs = [target_dir, _download_dir]
    seen_files = set()
    for sdir in search_dirs:
        if not sdir or not os.path.exists(sdir):
            continue
        try:
            for root, _, files in os.walk(sdir):
                if "extracted_" in root:
                    continue
                for f in files:
                    lower_f = f.lower()
                    if any(k in lower_f for k in ("pass", "pwd", "secret", "key", "readme", "instruction", "notice")) or lower_f.endswith(".txt"):
                        full_p = os.path.join(root, f)
                        if full_p in seen_files or os.path.getsize(full_p) > 256 * 1024:
                            continue
                        seen_files.add(full_p)
                        try:
                            with open(full_p, "r", encoding="utf-8", errors="replace") as pf:
                                content = pf.read()
                            # Key-value matches (e.g., password: xyz, pwd = 123)
                            for m in re.finditer(r"(?i)(?:zip\s+password|password|passphrase|pass|pwd|secret|key)[:\s=]+([^\r\n\t \"',;]+)", content):
                                w = m.group(1).strip().strip('"').strip("'")
                                if w and w not in candidates:
                                    candidates.append(w)
                            for m in re.finditer(r"(?i)(?:password|passphrase|pass|pwd)\s+is\s+([^\r\n\t \"',;]+)", content):
                                w = m.group(1).strip().strip('"').strip("'")
                                if w and w not in candidates:
                                    candidates.append(w)
                            # Every non-empty line
                            for line in content.splitlines():
                                sline = line.strip().strip('"').strip("'")
                                if 2 <= len(sline) <= 64 and sline not in candidates and not sline.startswith("#"):
                                    candidates.append(sline)
                        except Exception:
                            pass
        except Exception:
            pass

    # Built-in project password dictionary
    common_passwords = [
        "",
        "cyberleek",
        "Cyberleek",
        "CYBERLEEK",
        "gta6",
        "GTA6",
        "GTA 6",
        "rockstar",
        "Rockstar",
        "lucia",
        "Lucia",
        "jason",
        "Jason",
        "take2",
        "TakeTwo",
        "take-two",
        "Take-Two",
        "cookie",
        "tech-forum",
        "123456",
        "password",
        "Password",
    ]
    for cp in common_passwords:
        if cp not in candidates:
            candidates.append(cp)
            
    return candidates

def extract_archive_with_passwords(file_path: str, candidate_passwords: list[str] = None, dest_dir: str = None) -> list[str]:
    """Attempts multi-engine password-protected archive extraction across 7z, zipfile, tarfile, and unzip."""
    if not file_path or not os.path.exists(file_path):
        return []
        
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ARCHIVE_EXTENSIONS and ".tar." not in file_path.lower():
        return []
        
    parent_dir = os.path.dirname(os.path.abspath(file_path))
    stem = os.path.splitext(os.path.basename(file_path))[0]
    out_dir = dest_dir or os.path.join(parent_dir, f"extracted_{stem}")
    os.makedirs(out_dir, exist_ok=True)
    
    # Locate functional 7z executable
    seven_zip = None
    if sys.platform == "win32":
        for cand_path in (
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
            os.path.expanduser(r"~\scoop\shims\7z.exe"),
        ):
            if os.path.exists(cand_path):
                try:
                    res = subprocess.run([cand_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
                    if res.returncode in (0, 7):
                        seven_zip = cand_path
                        break
                except Exception:
                    pass
    if not seven_zip:
        which_7z = shutil.which("7z") or shutil.which("7za")
        if which_7z:
            try:
                res = subprocess.run([which_7z], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
                if res.returncode in (0, 7):
                    seven_zip = which_7z
            except Exception:
                pass
                
    unzip_bin = shutil.which("unzip")
    
    passwords = []
    # Parse explicit candidate strings (such as link titles) for embedded passwords
    for item in (candidate_passwords or []):
        for m in re.finditer(r"(?i)(?:zip\s+password|password|passphrase|pass|pwd|secret|key)[:\s=]+([^\s\"',;]+)", str(item)):
            w = m.group(1).strip().strip('"').strip("'")
            if w and w not in passwords:
                passwords.append(w)
        if item and str(item) not in passwords:
            passwords.append(str(item))
    for p in find_candidate_passwords(parent_dir, hint=stem):
        if p not in passwords:
            passwords.append(p)
    if "" not in passwords:
        passwords.insert(0, "")  # Try unencrypted first
        
    log_msg(f"[*] Archive detected: {os.path.basename(file_path)} - attempting extraction ({len(passwords)} password candidates)...")
    
    # 1. Primary: 7-Zip (supports .zip, .7z, .rar, .tar, .gz, AES, ZipCrypto)
    if seven_zip:
        for pwd in passwords:
            pwd_flag = f"-p{pwd}" if pwd else "-p"
            cmd = [seven_zip, "x", pwd_flag, f"-o{out_dir}", "-y", os.path.abspath(file_path)]
            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
                if proc.returncode == 0:
                    found_files = [os.path.join(r, f) for r, _, fs in os.walk(out_dir) for f in fs]
                    if found_files:
                        pwd_label = f"'{pwd}'" if pwd else "<none>"
                        log_msg(f"[+] [7z] Successfully extracted {len(found_files)} file(s) from {os.path.basename(file_path)} using password: {pwd_label}")
                        if _auto_open and not _mask_spoilers:
                            media_files = [f for f in found_files if os.path.splitext(f)[1].lower() in MEDIA_AUTO_OPEN_EXTENSIONS]
                            open_asset_and_folder(media_files[0] if media_files else found_files[0], out_dir)
                        return found_files
            except Exception:
                pass

    # 2. Python standard library zipfile (for .zip files)
    if ext == ".zip":
        for pwd in passwords:
            pwd_bytes = pwd.encode("utf-8") if pwd else None
            try:
                with zipfile.ZipFile(file_path, "r") as zf:
                    zf.extractall(path=out_dir, pwd=pwd_bytes)
                    found_files = [os.path.join(r, f) for r, _, fs in os.walk(out_dir) for f in fs]
                    if found_files:
                        pwd_label = f"'{pwd}'" if pwd else "<none>"
                        log_msg(f"[+] [zipfile] Successfully extracted {len(found_files)} file(s) using password: {pwd_label}")
                        if _auto_open and not _mask_spoilers:
                            media_files = [f for f in found_files if os.path.splitext(f)[1].lower() in MEDIA_AUTO_OPEN_EXTENSIONS]
                            open_asset_and_folder(media_files[0] if media_files else found_files[0], out_dir)
                        return found_files
            except (RuntimeError, zipfile.BadZipFile):
                continue
            except NotImplementedError:
                # AES encrypted archive; fall back to external unzip/7z
                break
            except Exception:
                continue

    # 3. External unzip fallback (Linux, macOS, Android/Termux)
    if ext == ".zip" and unzip_bin:
        for pwd in passwords:
            cmd = [unzip_bin, "-o"]
            if pwd:
                cmd.extend(["-P", pwd])
            cmd.extend([os.path.abspath(file_path), "-d", out_dir])
            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
                if proc.returncode == 0:
                    found_files = [os.path.join(r, f) for r, _, fs in os.walk(out_dir) for f in fs]
                    if found_files:
                        pwd_label = f"'{pwd}'" if pwd else "<none>"
                        log_msg(f"[+] [unzip] Successfully extracted {len(found_files)} file(s) using password: {pwd_label}")
                        if _auto_open and not _mask_spoilers:
                            media_files = [f for f in found_files if os.path.splitext(f)[1].lower() in MEDIA_AUTO_OPEN_EXTENSIONS]
                            open_asset_and_folder(media_files[0] if media_files else found_files[0], out_dir)
                        return found_files
            except Exception:
                pass

    # 4. Tarfile fallback (.tar, .tar.gz, .tgz, .tar.bz2, .tar.xz)
    if ext in (".tar", ".gz", ".tgz", ".bz2", ".xz") or ".tar." in file_path.lower():
        try:
            with tarfile.open(file_path, "r:*") as tf:
                tf.extractall(path=out_dir)
                found_files = [os.path.join(r, f) for r, _, fs in os.walk(out_dir) for f in fs]
                if found_files:
                    log_msg(f"[+] [tarfile] Extracted {len(found_files)} file(s) from {os.path.basename(file_path)}")
                    return found_files
        except Exception:
            pass

    log_msg(f"[-] Could not extract {os.path.basename(file_path)} with candidate passwords.")
    return []

def extract_all_local_archives(download_dir: str):
    """Scans the downloads directory and attempts password extraction on any discovered archives."""
    if not os.path.exists(download_dir):
        return
    count = 0
    for root, _, files in os.walk(download_dir):
        if "extracted_" in root:
            continue
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in ARCHIVE_EXTENSIONS:
                archive_path = os.path.join(root, f)
                log_msg(f"[*] Processing local archive: {archive_path}")
                res = extract_archive_with_passwords(archive_path)
                if res:
                    count += 1
    if count:
        log_msg(f"[+] Processed and extracted {count} archive(s).")
    else:
        log_msg("[*] No unextracted archives found in download directory.")

def _update_download(**changes):
    job_id = getattr(_download_context, 'job_id', None)
    with _state_lock:
        if job_id in _download_jobs:
            _download_jobs[job_id].update(changes)

def _download_stream_headers(headers):
    try:
        total = int(headers.get('Content-Length', 0)) or None
        if total is not None and total < 0:
            total = None
    except (TypeError, ValueError):
        total = None
    _update_download(state='downloading', received=0, total=total)

def _download_chunk(size):
    job_id = getattr(_download_context, 'job_id', None)
    with _state_lock:
        if job_id in _download_jobs:
            _download_jobs[job_id]['received'] += size

def tracked_download(function):
    @functools.wraps(function)
    def wrapped(url, dest_base, *args, **kwargs):
        job_id = uuid.uuid4().hex
        _download_context.job_id = job_id
        with _state_lock:
            # Retain recent finished attempts and every active attempt.
            finished = [key for key, value in _download_jobs.items() if value['state'] not in ('connecting', 'downloading')]
            for key in finished[:-80]:
                _download_jobs.pop(key, None)
            _download_jobs[job_id] = {'name': os.path.basename(dest_base),
                'source': urllib.parse.urlparse(url).hostname or 'external client',
                'state': 'connecting', 'received': 0, 'total': None, 'started': time.time()}
        try:
            result = function(url, dest_base, *args, **kwargs)
            abort = kwargs.get('abort_event') or (args[1] if len(args) > 1 else None)
            with _state_lock:
                prior = _download_jobs[job_id]['state']
            state = 'completed' if result else 'external' if prior == 'external' else 'canceled' if abort and abort.is_set() else 'failed'
            _update_download(state=state, finished=time.time(), path=result)
            with _state_lock:
                _download_totals[state] += 1
            return result
        except Exception as exc:
            _update_download(state='failed', finished=time.time(), error=str(exc))
            with _state_lock:
                _download_totals['failed'] += 1
            raise
        finally:
            _download_context.job_id = None
    return wrapped

@tracked_download
def download_raw_media(url: str, dest_base: str, timeout: int = 60, abort_event: threading.Event = None, started_event: threading.Event = None) -> str | None:
    """Streams and saves binary media with mirror session handling and thread-safe temporary paths."""
    # Torrent sources require a torrent engine; never launch an external client.
    if url.startswith("magnet:"):
        _update_download(error='Torrent source cannot be downloaded by the built-in downloader')
        log_msg('[!] Torrent source unsupported by the background downloader; trying other mirrors.')
        return None
    # Bedrive mirror handler
    if "bedrive.ru/" in url:
        try:
            cj = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": url}
            
            req1 = urllib.request.Request(url, headers=headers)
            with opener.open(req1, timeout=15) as r1:
                h1 = r1.read().decode("utf-8", errors="replace")
                
            s1 = re.search(r'data-secret1="([^"]+)"', h1)
            s2 = re.search(r'data-secret2="([^"]+)"', h1)
            if s1 and s2:
                step2_url = base64.b64decode(s1.group(1)).decode() + base64.b64decode(s2.group(1)).decode()
                
                req2 = urllib.request.Request(step2_url, headers=headers)
                with opener.open(req2, timeout=15) as r2:
                    h2 = r2.read().decode("utf-8", errors="replace")
                    
                dl_token_match = re.search(r'href="([^"]*download_token=[^"]*)"', h2)
                if dl_token_match:
                    final_dl = dl_token_match.group(1)
                    req_final = urllib.request.Request(final_dl, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": step2_url})
                    
                    temp_path = f"{dest_base}.{threading.get_ident()}.tmp"
                    with opener.open(req_final, timeout=timeout) as r_fin:
                        _download_stream_headers(r_fin.headers)
                        cd_hdr = r_fin.headers.get("Content-Disposition", "")
                        with open(temp_path, "wb") as fp:
                            first_chunk = True
                            while True:
                                if abort_event and abort_event.is_set():
                                    fp.close()
                                    if os.path.exists(temp_path):
                                        os.remove(temp_path)
                                    return None
                                chunk = r_fin.read(256 * 1024)
                                if not chunk:
                                    break
                                if first_chunk:
                                    if started_event:
                                        started_event.set()
                                    first_chunk = False
                                fp.write(chunk)
                                _download_chunk(len(chunk))
                    if os.path.exists(temp_path) and os.path.getsize(temp_path) > 4:
                        with open(temp_path, "rb") as fp:
                            header_bytes = fp.read(256)
                        valid, ext = is_valid_media(header_bytes, url=url, content_disp=cd_hdr)
                        if valid:
                            final_path = dest_base + ext
                            os.replace(temp_path, final_path)
                            return final_path
                        else:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
        except Exception as e:
            log_msg(f"[-] Bedrive resolver notice: {e}")
            return None

    # Upload.ee mirror handler
    elif "upload.ee/files/" in url:
        res = http_get_text(url, timeout=12)
        if res:
            dl_matches = re.findall(r'href="(https://www\.upload\.ee/download/[^"]+)"', res[0])
            if dl_matches:
                url = dl_matches[0]

    # Transfiles mirror handler
    elif "transfiles.ru/" in url:
        res = http_get_text(url, timeout=12)
        if res:
            dl_matches = re.findall(r'href="(/dl/[^"]+)"', res[0]) or re.findall(r'href="(https://transfiles\.ru/dl/[^"]+)"', res[0])
            if dl_matches:
                u = dl_matches[0]
                url = "https://transfiles.ru" + u if u.startswith("/") else u

    # Pixeldrain mirror handler
    elif "pixeldrain.com/u/" in url:
        fid = url.split("/u/")[1].split("?")[0].split("/")[0]
        url = f"https://pixeldrain.com/api/file/{fid}"

    # Krakenfiles mirror handler
    elif "krakenfiles.com/view/" in url:
        res = http_get_text(url, timeout=12)
        if res:
            dl_matches = re.findall(r'href="(/download/[^"]+)"', res[0])
            if dl_matches:
                url = "https://krakenfiles.com" + dl_matches[0]

    # DropMeFiles mirror handler
    elif "dropmefiles.com/" in url:
        fid = url.split("dropmefiles.com/")[1].split("?")[0].split("/")[0]
        if fid:
            url = f"https://dropmefiles.com/download/{fid}"

    # GoFile mirror handler
    elif "gofile.io/d/" in url:
        _update_download(error='GoFile landing page requires a supported download API')
        log_msg('[!] GoFile landing page unsupported; trying other mirrors.')
        return None

    # Lufi client-side encrypted mirror handler (e.g. upload.disroot.org, lufi.ethibox.fr)
    elif "/r/" in url and ("disroot.org" in url or "lufi" in url or "#" in url):
        _update_download(error='Client-side encrypted Lufi source unsupported')
        log_msg('[!] Lufi encrypted source unsupported; trying other mirrors.')
        return None

    # temp.sh mirror handler
    # temp.sh mirror handler (handles landing page POST download triggers and direct streams)
    elif "temp.sh/" in url:
        try:
            res = http_get_text(url, timeout=12)
            if res:
                html, hdrs, final_url = res
                if "Maximum download limit reached" in html:
                    log_msg(f"[-] temp.sh notice: Maximum download limit reached for {url}")
                else:
                    form_match = re.search(r'<form[^>]*action=["\']([^"\']*)["\']', html)
                    post_target = url
                    if form_match and form_match.group(1):
                        act = form_match.group(1)
                        post_target = "https://temp.sh" + act if act.startswith("/") else act
                    
                    temp_path = f"{dest_base}.{threading.get_ident()}.tmp"
                    try:
                        with http_open(post_target, data=b"", headers={"Referer": url, "Origin": "https://temp.sh"}, timeout=timeout, method="POST") as resp_post:
                            _download_stream_headers(resp_post.headers)
                            cd_hdr = resp_post.headers.get("Content-Disposition", "")
                            with open(temp_path, "wb") as fp:
                                first_chunk = True
                                while True:
                                    if abort_event and abort_event.is_set():
                                        fp.close()
                                        if os.path.exists(temp_path):
                                            os.remove(temp_path)
                                        return None
                                    chunk = resp_post.read(256 * 1024)
                                    if not chunk:
                                        break
                                    if first_chunk:
                                        if started_event:
                                            started_event.set()
                                        first_chunk = False
                                    fp.write(chunk)
                                    _download_chunk(len(chunk))
                        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 4:
                            with open(temp_path, "rb") as fp:
                                header_bytes = fp.read(256)
                            valid, ext = is_valid_media(header_bytes, url=url, content_disp=cd_hdr)
                            if valid:
                                final_path = dest_base + ext
                                os.replace(temp_path, final_path)
                                return final_path
                            else:
                                if os.path.exists(temp_path):
                                    os.remove(temp_path)
                    except urllib.error.HTTPError as e:
                        err_body = e.read().decode("utf-8", errors="replace")
                        if "Maximum download limit reached" in err_body:
                            log_msg(f"[-] temp.sh notice [{url[:50]}]: Maximum download limit reached (403).")
                        else:
                            log_msg(f"[-] temp.sh HTTP {e.code} [{url[:50]}]: {e.reason}")
        except Exception as e:
            log_msg(f"[-] temp.sh error: {e}")

    # Direct decentralized storage and HTTP retrieval
    try:
        temp_path = f"{dest_base}.{threading.get_ident()}.tmp"
        with http_open(url, timeout=timeout) as resp:
            _download_stream_headers(resp.headers)
            cd_hdr = resp.headers.get("Content-Disposition", "")
            with open(temp_path, "wb") as fp:
                first_chunk = True
                while True:
                    if abort_event and abort_event.is_set():
                        fp.close()
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        return None
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    if first_chunk:
                        if started_event:
                            started_event.set()
                        first_chunk = False
                    fp.write(chunk)
                    _download_chunk(len(chunk))
        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 4:
            with open(temp_path, "rb") as fp:
                header_bytes = fp.read(256)
            valid, ext = is_valid_media(header_bytes, url=url, content_disp=cd_hdr)
            if valid:
                final_path = dest_base + ext
                os.replace(temp_path, final_path)
                return final_path
            else:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
    except PermissionError as e:
        _update_download(error=str(e))
        log_msg(f"[!] Filesystem permission denied writing to '{dest_base}': {e}")
        log_msg(f"[!] Check write access to the download directory or restart with a different --download-dir.")
    except Exception as e:
        _update_download(error=str(e))
        log_msg(f"[-] Download failed [{url[:60]}]: {e}")
    return None

def retrieve_raw_arweave_tx(ar_id: str, title: str, download_dir: str):
    """Retrieves raw storage payload by transaction ID racing peers and public gateways concurrently."""
    with _DOWNLOAD_SEMAPHORE:
        os.makedirs(download_dir, exist_ok=True)
        raw_clean = re.sub(r'[^\w\-_\.]', '', title.strip().replace(" ", "_")) or "storage_upload"
        clean_title = os.path.basename(raw_clean)
        dest_base = os.path.join(download_dir, f"{clean_title}_{ar_id}")
        
        log_msg(f"[*] Starting concurrent media download: {clean_title} ({ar_id})")
        
        candidate_targets = []
        for gw in GATEWAYS:
            candidate_targets.append(("Gateway", f"{gw}/{ar_id}"))
        for node in PEER_NODES:
            url = f"{node}/tx/{ar_id}/data" if ":1984" in node else f"{node}/{ar_id}"
            candidate_targets.append(("P2P Node", url))
            
        abort_event = threading.Event()
        def _try_fetch(label, target_url):
            res = download_raw_media(target_url, dest_base, timeout=15, abort_event=abort_event)
            if res:
                abort_event.set()
            return (label, target_url, res)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(candidate_targets))))
        futures = [executor.submit(_try_fetch, lbl, u) for lbl, u in candidate_targets]
        for fut in concurrent.futures.as_completed(futures):
            try:
                lbl, u, saved = fut.result()
                if saved:
                    sz = os.path.getsize(saved)
                    log_msg(f"[+] Retrieved from {lbl} [{u[:50]}]: {os.path.abspath(saved)} ({sz:,} bytes)")
                    ext = os.path.splitext(saved)[1].lower()
                    if ext in ARCHIVE_EXTENSIONS or ".tar." in saved.lower():
                        extract_archive_with_passwords(saved, candidate_passwords=[clean_title])
                    open_asset_and_folder(saved, download_dir)
                    executor.shutdown(wait=False, cancel_futures=True)
                    return
            except Exception:
                continue
                
        executor.shutdown(wait=False, cancel_futures=True)
        log_msg(f"[-] Retrieval pending for: {clean_title} ({ar_id})")

def backfill_assets(links: list[dict] | None = None):
    """Retrieve historical entries missing from the local manifest, without browser fallback."""
    if _watch_only:
        log_msg('[!] Historical downloads are disabled. Enable Download payloads first.')
        return
    if links is None:
        state = fetch_program_state()
        if state is None:
            log_msg('[!] Historical scan failed; try Backfill assets again when RPC recovers.')
            return
        links = state.get('links', [])
    try:
        with _manifest_lock:
            with open(os.path.join(_download_dir, 'manifest.json'), encoding='utf-8') as f:
                manifest = json.load(f)
        if not isinstance(manifest, dict):
            manifest = {}
    except (OSError, ValueError):
        manifest = {}
    pending = []
    skipped = 0
    for link in links:
        saved = manifest.get(link.get('pda'), {})
        filename = os.path.basename(saved.get('saved_file', '')) if isinstance(saved, dict) else ''
        local = os.path.join(_download_dir, filename)
        if filename and os.path.isfile(local) and os.path.getsize(local) > 4:
            skipped += 1
        else:
            pending.append(dict(link, quiet=True))
    log_msg(f'[*] Historical backfill: {len(pending)} missing entries, {skipped} already saved.')
    for link in pending:
        if _shutdown_event.is_set() or _watch_only:
            log_msg('[*] Historical backfill stopped.')
            return
        retrieve_asset(link, _download_dir)
    log_msg('[*] Historical backfill attempts finished. Download status shows saved files and failed sources.')

def retrieve_asset(link_item: dict, download_dir: str):
    """Resolves and downloads all referenced assets for an on-chain link entry across all mirrors concurrently."""
    with _DOWNLOAD_SEMAPHORE:
        raw_title = link_item.get("title", "leak")
        pda = link_item.get("pda", "unknown")
        idx = link_item.get("index", 0)
        
        if _mask_spoilers:
            title_tag = f"leak_{pda[:10]}"
            display_title = format_leak_title(raw_title, pda, idx)
        else:
            raw_clean = re.sub(r'[^A-Za-z0-9_.-]', '_', raw_title).strip('_')
            title_tag = os.path.basename(raw_clean) or f"leak_{pda[:10]}"
            display_title = raw_title
            
        title = title_tag
        mirrors = link_item.get("mirrors", [])
        log_msg(f"[*] Starting concurrent asset retrieval for: {display_title}")
        ar_id = None
        ipfs_cid = None
        for m in mirrors:
            # Extract standalone 43-character base64url Arweave transaction identifiers only from Arweave sources
            url_lower = m.get("url", "").lower()
            label_lower = m.get("label", "").lower()
            is_ar_source = (
                any(dom in url_lower for dom in ("arweave", "ar.io", "vilenarios.com", "turbo-gateway", "permaweb", "ardrive"))
                or url_lower.startswith("ar://")
                or "arweave" in label_lower
                or "ar.io" in label_lower
            )
            if is_ar_source:
                matches = re.findall(r'(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])', m["url"])
                if matches:
                    ar_id = matches[0]
            cid_matches = re.findall(r'(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|bafy[a-z0-9]{55})', m["url"])
            if cid_matches:
                ipfs_cid = cid_matches[0]
                
        candidate_targets = []
        
        # Direct mirrors
        for m in mirrors:
            lbl = m.get("label", "mirror") or "mirror"
            dest = os.path.join(download_dir, f"{title}_{lbl.replace(' ', '_')}")
            candidate_targets.append(("Mirror", m["url"], dest))
            
        # IPFS gateways
        if ipfs_cid:
            dest_ipfs = os.path.join(download_dir, f"{title}_{ipfs_cid[:16]}")
            for igw in IPFS_GATEWAYS:
                candidate_targets.append(("IPFS", f"{igw}/{ipfs_cid}", dest_ipfs))
                
        # Arweave gateways & nodes
        if ar_id:
            dest_ar = os.path.join(download_dir, f"{title}_{ar_id}")
            for gw in GATEWAYS:
                candidate_targets.append(("Gateway", f"{gw}/{ar_id}", dest_ar))
            for node in PEER_NODES:
                url = f"{node}/tx/{ar_id}/data" if ":1984" in node else f"{node}/{ar_id}"
                candidate_targets.append(("P2P Node", url, dest_ar))
                
        abort_event = threading.Event()
        download_started = threading.Event()
        def _try_download(label, url, dest):
            res = download_raw_media(url, dest, timeout=20, abort_event=abort_event, started_event=download_started)
            if res:
                abort_event.set()
            return (label, url, res)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(candidate_targets))))
        futures = [executor.submit(_try_download, lbl, u, d) for lbl, u, d in candidate_targets]
        for fut in concurrent.futures.as_completed(futures):
            try:
                lbl, u, saved = fut.result()
                if saved:
                    sz = os.path.getsize(saved)
                    record_manifest_entry(download_dir, pda, raw_title, saved, mirrors)
                    log_msg(f"[+] Retrieved from {lbl} [{u[:50]}]: {os.path.abspath(saved)} ({sz:,} bytes)")
                    ext = os.path.splitext(saved)[1].lower()
                    if ext in ARCHIVE_EXTENSIONS or ".tar." in saved.lower():
                        extract_archive_with_passwords(saved, candidate_passwords=[raw_title])
                    if not _mask_spoilers:
                        open_asset_and_folder(saved, download_dir)
                    executor.shutdown(wait=False, cancel_futures=True)
                    return
            except Exception:
                continue
                
        executor.shutdown(wait=False, cancel_futures=True)
        log_msg(f"[-] All background download sources failed for: {title}. No browser was opened. Use Backfill assets to retry.")

def handle_new_link(link: dict, is_update: bool = False):
    """Processes newly published or updated link entries and triggers asset downloading."""
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
    touch_event()
    idx = len(_known_links)
    display_title = format_leak_title(link.get("title", ""), link.get("pda", ""), idx)
    header = "Entry Updated" if is_update else "New Entry Published"
    msg = (
        f"\n[{now_str}] {header}: {display_title}\n"
        f"  Account: {link['pda']}\n"
    )
    for m in link.get("mirrors", []):
        msg += f"  Source: [{m['label']}] {m['url']}\n"
    log_msg(msg)
    
    play_leak_chime()
    if not _watch_only:
        link_copy = dict(link)
        link_copy["index"] = idx
        threading.Thread(target=retrieve_asset, args=(link_copy, _download_dir), daemon=True).start()
    else:
        log_msg("  [Watch-Only] Payload download skipped.")

_market_fetch_lock = threading.Lock()

_market_last_attempt = 0.0

_market_data = {}

_market_history = deque(maxlen=3600)

def current_market_cap(price_usd: float) -> float:
    with _state_lock:
        market = dict(_market_data)
    if market.get("price_usd") == price_usd and market.get("market_cap_usd"):
        return market["market_cap_usd"]
    return 0.0 if market.get('market_cap_source') == 'DexScreener price x CoinGecko supply' else CIRCULATING_SUPPLY * price_usd

def select_market_pair(pairs: list) -> dict:
    """Use the deepest Solana pool quoting this mint as the base token."""
    def positive(value):
        try:
            number = float(value)
            return number if math.isfinite(number) and number > 0 else 0.0
        except (ValueError, TypeError):
            return 0.0
    def numeric(value, signed=False):
        try:
            number = float(value)
            return number if math.isfinite(number) and (signed or number >= 0) else None
        except (ValueError, TypeError):
            return None
    candidates = [p for p in pairs if p.get("chainId") == "solana"
                  and p.get("baseToken", {}).get("address") == TOKEN_MINT
                  and positive(p.get("priceUsd"))]
    if not candidates:
        raise ValueError("No valid Solana market pair for the monitored mint")
    pair = max(candidates, key=lambda p: positive((p.get("liquidity") or {}).get("usd")))
    price = positive(pair.get("priceUsd"))
    reported = positive(pair.get("marketCap"))
    fdv = positive(pair.get("fdv"))
    # Matching cap and FDV does not establish an independently verified circulating supply.
    same_as_fdv = bool(reported and fdv and math.isclose(reported, fdv, rel_tol=1e-6))
    estimated = not reported or same_as_fdv
    return {"price_usd": price, "market_cap_usd": price * CIRCULATING_SUPPLY if estimated else reported,
            "basis": "Estimate - configured supply" if estimated else "DexScreener reported",
            "market_cap_estimated": estimated,
            "circulating_supply_used": CIRCULATING_SUPPLY if estimated else None,
            "reported_market_cap_usd": reported or None,
            "reported_cap_equals_fdv": same_as_fdv,
            "pair_address": pair.get("pairAddress", ""), "dex": pair.get("dexId", ""),
            "liquidity_usd": numeric((pair.get("liquidity") or {}).get("usd")),
            "fdv_usd": numeric(pair.get("fdv")),
            "volume": {period: numeric((pair.get("volume") or {}).get(period)) for period in ("m5", "h1", "h6", "h24")},
            "price_change": {period: numeric((pair.get("priceChange") or {}).get(period), signed=True) for period in ("m5", "h1", "h6", "h24")},
            "transactions": {period: {side: numeric(((pair.get("txns") or {}).get(period) or {}).get(side)) for side in ("buys", "sells")} for period in ("m5", "h1", "h6", "h24")}}

_supply_cache = {}
_supply_refresh_lock = threading.Lock()
_supply_next_refresh = 0.0


def refresh_supply_cache():
    """Start an independent supply worker with a 61-second interval."""
    global _supply_next_refresh
    now = time.time()
    if now >= _supply_next_refresh and _supply_refresh_lock.acquire(blocking=False):
        _supply_next_refresh = now + 61
        def worker():
            global _supply_cache, _supply_next_refresh
            try:
                while not _shutdown_event.is_set():
                    try:
                        result = fetch_coingecko_market_cap()
                        supply = result.get('coingecko_circulating_supply')
                        if isinstance(supply, bool) or not isinstance(supply, (int, float)) or not math.isfinite(supply) or supply <= 0:
                            raise ValueError('CoinGecko circulating supply is unavailable')
                        with _state_lock:
                            _supply_cache = {'supply': float(supply), 'observed_at': time.time(), 'error': None}
                    except Exception as exc:
                        with _state_lock:
                            _supply_cache = {**_supply_cache, 'error': str(exc)}
                    _supply_next_refresh = time.time() + 61
                    if _shutdown_event.wait(61):
                        break
            finally:
                _supply_refresh_lock.release()
        threading.Thread(target=worker, daemon=True).start()
    with _state_lock:
        return dict(_supply_cache)


def fetch_coingecko_market_cap():
    """Read Cyberleek's USD market cap directly from CoinGecko; never substitute FDV."""
    url = 'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=cyberleek'
    request = urllib.request.Request(url, headers={'User-Agent': 'Cyberleek-Watcher', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=6.0, context=_SSL_CONTEXT) as response:
        rows = json.loads(response.read().decode('utf-8'))
    row = next((item for item in rows if isinstance(item, dict) and item.get('id') == 'cyberleek'), None) if isinstance(rows, list) else None
    if row is None:
        raise ValueError('CoinGecko did not return Cyberleek market data')
    cap = row.get('market_cap')
    if isinstance(cap, bool) or not isinstance(cap, (int, float)) or not math.isfinite(cap) or cap <= 0:
        raise ValueError('CoinGecko market cap is unavailable')
    return {'market_cap_usd': float(cap), 'basis': 'CoinGecko reported',
            'market_cap_source': 'CoinGecko', 'market_cap_estimated': False,
            'coingecko_last_updated': row.get('last_updated'),
            'coingecko_circulating_supply': row.get('circulating_supply')}


def market_poller_thread():
    """Refresh market data on the shared clock, concurrently with other feeds."""
    generation = _refresh_generation
    while (generation := wait_for_refresh(generation, 'market')) is not None:
        fetch_cyberleek_usd_price(force=True)

def fetch_cyberleek_usd_price(force=False) -> float:
    """Fetch market data at the configured cadence (minimum five seconds)."""
    global _token_price_usd, _token_price_last_ts, _market_last_attempt, _market_data
    if _refresh_clock_running and not force:
        return _token_price_usd
    now = time.time()
    if not force and now - _market_last_attempt < max(5, _poll_interval):
        return _token_price_usd
    if not _market_fetch_lock.acquire(blocking=False):
        return _token_price_usd
    try:
        now = time.time()
        if not force and now - _market_last_attempt < max(5, _poll_interval):
            return _token_price_usd
        _market_last_attempt = now
        url = f"https://api.dexscreener.com/latest/dex/tokens/{TOKEN_MINT}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4.0, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read().decode())
            market = select_market_pair(data.get("pairs") or [])
            supply = refresh_supply_cache()
            market.update({'market_cap_usd': market['price_usd'] * supply['supply'] if supply.get('supply') else None,
                           'basis': 'Estimate - DexScreener price x CoinGecko supply',
                           'market_cap_source': 'DexScreener price x CoinGecko supply',
                           'market_cap_estimated': True, 'circulating_supply_used': supply.get('supply'),
                           'supply_observed_at': supply.get('observed_at'), 'supply_error': supply.get('error')})
            market["observed_at"] = time.time()
            market["error"] = None
            with _state_lock:
                _token_price_usd = market["price_usd"]
                _token_price_last_ts = market["observed_at"]
                _market_data = market
                if market.get('market_cap_usd'):
                    _market_history.append((market["observed_at"], market["market_cap_usd"]))
    except Exception as exc:
        with _state_lock:
            _market_data = {**_market_data, "error": str(exc)}
    finally:
        _market_fetch_lock.release()
    return _token_price_usd

def handle_new_proposal(proposal: dict):
    """Processes newly created community proposals."""
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
    touch_event()
    parts = [
        f"\n[{now_str}] Community Proposal Created: {proposal.get('title', '')}",
        f"  Account: {proposal['pda']}",
        f"  Choices: {', '.join(proposal.get('choices', []))}",
    ]
    finalized = proposal.get("finalized", [])
    if finalized:
        parts.append(f"  Finalized flags: {finalized}")
    ui_bals = proposal.get("ui_balances") or [b / 1e9 for b in proposal.get("final_balances", [])]
    if ui_bals and any(b > 0 for b in ui_bals):
        bal_strs = [f"{c}: {b:,.2f} CYBERLEEK" for c, b in zip(proposal.get("choices", []), ui_bals)]
        parts.append(f"  Tallied Votes: {', '.join(bal_strs)}")
    ends_at = proposal.get("ends_at")
    if ends_at:
        end_str = datetime.datetime.fromtimestamp(ends_at, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        parts.append(f"  Voting ends: {end_str}")

        # If active, query and show live option voting escrow balances with USD value
        if ends_at > time.time() and not all(finalized):
            atas = get_or_derive_option_atas(proposal.get("poll_id", ""), len(proposal.get("choices", [])))
            if atas:
                price_usd = fetch_cyberleek_usd_price()
                live_bals = [fetch_token_balance(a[1]) or 0.0 for a in atas]
                tot = sum(live_bals)
                opt_lines = []
                for idx, (c, b, (wallet_pda, ata_addr)) in enumerate(zip(proposal.get("choices", []), live_bals, atas)):
                    pct = (b / tot * 100.0) if tot > 0 else 0.0
                    usd_str = f" (${b * price_usd:,.2f} USD)" if price_usd > 0 else ""
                    opt_lines.append(f"    Option {idx} ({c}): {b:,.2f} CYBERLEEK{usd_str} ({pct:.1f}%) | Escrow ATA: {ata_addr}")
                parts.append("  Active Voting Escrows:")
                parts.extend(opt_lines)
                if tot > 0:
                    tot_usd_str = f" (${tot * price_usd:,.2f} USD)" if price_usd > 0 else ""
                    parts.append(f"  Total Staked Votes: {tot:,.2f} CYBERLEEK{tot_usd_str}")
    log_msg("\n".join(parts) + "\n")

def handle_new_notice(notice: dict):
    """Processes newly published on-chain notices or bulletins."""
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
    touch_event()
    msg = (
        f"\n[{now_str}] 📢 CRITICAL ON-CHAIN NOTICE / BULLETIN DETECTED\n"
        f"  Account: {notice['pda']}\n"
        f"  Title:   {notice.get('title', '')}\n"
        f"  Message: {notice.get('message', '')}\n"
    )
    log_msg(msg)
    play_leak_chime()

def poll_active_proposals(proposals: list[dict]):
    """Derives option ATAs and checks live vote token balances and USD valuations for active proposals."""
    global _active_poll_info
    now = time.time()
    active_polls = [p for p in proposals if p.get("ends_at", 0) > now and not all(p.get("finalized", []))]
    if not active_polls:
        _active_poll_info = None
        return

    for prop in active_polls:
        pda = prop["pda"]
        poll_id_hex = prop.get("poll_id", "")
        choices = prop.get("choices", [])
        ends_at = prop.get("ends_at", 0)
        if not poll_id_hex or not choices:
            continue

        atas = get_or_derive_option_atas(poll_id_hex, len(choices))
        if len(atas) != len(choices):
            if _active_poll_info and _active_poll_info.get('pda') == pda:
                _active_poll_info = dict(_active_poll_info, stale=True)
            continue

        price_usd = fetch_cyberleek_usd_price()
        current_balances = []
        for choice_idx, (opt_wallet, opt_ata) in enumerate(atas):
            bal = fetch_token_balance(opt_ata)
            if bal is None:
                break
            current_balances.append(bal)
        if len(current_balances) != len(choices):
            if _active_poll_info and _active_poll_info.get('pda') == pda:
                _active_poll_info = dict(_active_poll_info, stale=True)
            continue

        old_balances = _active_poll_balances.get(pda)
        _active_poll_balances[pda] = current_balances

        tot = sum(current_balances)
        usd_vals = [b * price_usd for b in current_balances] if price_usd > 0 else [0.0] * len(current_balances)
        tot_usd = tot * price_usd if price_usd > 0 else 0.0

        leader_idx = 0
        leader_bal = -1.0
        for idx, b in enumerate(current_balances):
            if b > leader_bal:
                leader_bal = b
                leader_idx = idx

        leader_pct = (leader_bal / tot * 100.0) if tot > 0 else 0.0
        leader_choice = choices[leader_idx] if leader_idx < len(choices) else f"Option {leader_idx}"

        rem_sec = max(0, int(ends_at - now))
        d = rem_sec // 86400
        h = (rem_sec % 86400) // 3600
        m = (rem_sec % 3600) // 60
        rem_str = f"{d}d {h}h" if d > 0 else f"{h}h {m}m"

        _active_poll_info = {
            "pda": pda,
            "title": prop.get("title", ""),
            "choices": choices,
            "balances": current_balances,
            "usd_vals": usd_vals,
            "price_usd": price_usd,
            "total": tot,
            "total_usd": tot_usd,
            "leader_idx": leader_idx,
            "leader_choice": leader_choice,
            "leader_pct": leader_pct,
            "time_rem_str": rem_str,
            "ends_at": ends_at,
            "observed_at": time.time(),
            "stale": False,
        }

        # If votes changed since last check, log the update
        if old_balances is not None:
            deltas = [c - o for c, o in zip(current_balances, old_balances)]
            if any(d_val > 0.0001 for d_val in deltas):
                now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
                touch_event()
                parts = [f"\n[{now_str}] 🗳️ LIVE VOTE UPDATE: {prop.get('title', 'Community Poll')}"]
                if price_usd > 0:
                    parts.append(f"  $CYBERLEEK Price: ${price_usd:.6f} USD")
                for idx, (c, b, d_val, u_val) in enumerate(zip(choices, current_balances, deltas, usd_vals)):
                    delta_str = f" (+{d_val:,.2f})" if d_val > 0.0001 else ""
                    pct = (b / tot * 100.0) if tot > 0 else 0.0
                    usd_str = f" (${u_val:,.2f} USD)" if price_usd > 0 else ""
                    parts.append(f"  Option {idx} ({c}): {b:,.2f} CYBERLEEK{usd_str} ({pct:.1f}%){delta_str}")
                tot_usd_str = f" (${tot_usd:,.2f} USD)" if price_usd > 0 else ""
                parts.append(f"  Total Votes: {tot:,.2f} CYBERLEEK{tot_usd_str} | Leader: Option {leader_idx} ({leader_choice})")
                parts.append(f"  Voting Deadline: {rem_str} remaining")
                log_msg("\n".join(parts) + "\n")
                play_info_chime()

def handle_reserve_change(curr_reserve: float, old_reserve: float, ata_pubkey: str = None):
    """Processes developer reserve account balance changes with dynamic account attribution."""
    delta = curr_reserve - old_reserve
    if abs(delta) < 0.01:
        return
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
    is_outflow = delta < -100_000
    label = "LARGE RESERVE DECREASE DETECTED" if is_outflow else "Developer Reserve Balance Change"
    
    ata_info = _monitored_reserve_atas.get(ata_pubkey, {}) if ata_pubkey else {}
    owner_label = ata_info.get("label", "OPERATOR")
    owner_addr = ata_info.get("owner", "")
    
    msg = (
        f"\n[{now_str}] {label}: {curr_reserve:,.2f} CYBERLEEK ({delta:+,.2f})\n"
        f"  Total Monitored Reserve: {curr_reserve:,.2f} CYBERLEEK across {len(_monitored_reserve_atas)} account(s)\n"
    )
    if ata_pubkey:
        msg += f"  Changed Account: {ata_pubkey} [{owner_label}: {owner_addr}]\n"
    if is_outflow:
        msg += f"  Impact: {abs(delta):,.0f} tokens transferred out of reserve\n"
    log_msg(msg)
    if is_outflow:
        play_info_chime()

def arweave_poller_thread():
    """Periodically queries Arweave and Bundlr GraphQL endpoints for new transaction uploads."""
    global _ar_status, _known_ar_txs
    generation = _refresh_generation
    
    q_init = f"""
    {{
      transactions(
        owners: [{", ".join(json.dumps(u) for u in ARWEAVE_UPLOADERS)}]
        first: 50
        sort: HEIGHT_DESC
      ) {{
        edges {{
          node {{
            id
            data {{ size }}
            tags {{ name value }}
          }}
        }}
      }}
    }}
    """
    res = arweave_query(q_init)
    if res:
        edges = res.get("data", {}).get("transactions", {}).get("edges", [])
        for e in edges:
            _known_ar_txs.add(e["node"]["id"])

    q_init_tags = """
    {
      transactions(
        tags: [{ name: "App-Name", values: ["cyberleek", "sol-arweave-ipfs-uploader", "Cyberleek"] }]
        first: 50
        sort: HEIGHT_DESC
      ) {
        edges {
          node {
            id
          }
        }
      }
    }
    """
    res_tags = arweave_query(q_init_tags)
    if res_tags:
        edges = res_tags.get("data", {}).get("transactions", {}).get("edges", [])
        for e in edges:
            _known_ar_txs.add(e["node"]["id"])
            
    while (generation := wait_for_refresh(generation, 'arweave')) is not None:
        try:
            _ar_status = "POLL"
            owners_json = ", ".join(json.dumps(u) for u in ARWEAVE_UPLOADERS)
            ar_queries = [
                f"""
                {{
                  transactions(
                    owners: [{owners_json}]
                    first: 25
                    sort: HEIGHT_DESC
                  ) {{
                    edges {{ node {{ id data {{ size }} tags {{ name value }} }} }}
                  }}
                }}
                """,
                f"""
                {{
                  transactions(
                    tags: [{{ name: "App-Name", values: ["cyberleek", "sol-arweave-ipfs-uploader", "Cyberleek"] }}]
                    first: 25
                    sort: HEIGHT_DESC
                  ) {{
                    edges {{ node {{ id data {{ size }} tags {{ name value }} }} }}
                  }}
                }}
                """,
            ]
            for q in ar_queries:
                res = arweave_query(q)
                if not res:
                    continue
                edges = res.get("data", {}).get("transactions", {}).get("edges", [])
                for e in edges:
                    n = e["node"]
                    tx_id = n["id"]
                    if tx_id not in _known_ar_txs:
                        _known_ar_txs.add(tx_id)
                        sz = int(n.get("data", {}).get("size") or 0)
                        tags = {t["name"]: t["value"] for t in n.get("tags", [])}
                        ct = tags.get("Content-Type", "application/octet-stream")
                        handle_new_arweave_upload(tx_id, sz, ct)

            _ar_status = "IDLE"
        except Exception:
            _ar_status = "ERR"

def _resolve_arns_tx_id(name: str) -> tuple[str, str] | tuple[None, None]:
    """Resolves ArNS name to Arweave transaction ID via official Ar-IO resolver API or gateway HEAD headers."""
    # 1. Primary: Official Ar-IO resolver API endpoint (reliable, immune to HTTP 451 node geo-blocks)
    for api_url in (
        f"https://ardrive.net/ar-io/resolver/{name}",
        f"https://turbo.ardrive.io/ar-io/resolver/{name}",
    ):
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": DEFAULT_UA})
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode())
                tx_id = data.get("txId", "").strip()
                if tx_id:
                    return tx_id, f"https://arweave.net/{tx_id}"
        except Exception:
            continue

    # 2. Fallback: HEAD requests to ArNS subdomain gateways checking x-arns-resolved-id header
    for gw in (
        f"https://{name}.ar.io/",
        f"https://{name}.arweave.tech/",
        f"https://{name}.vilenarios.com/",
    ):
        try:
            with http_open(gw, timeout=10.0, method="HEAD") as resp:
                tx_id = resp.headers.get("x-arns-resolved-id", "").strip()
                if tx_id:
                    return tx_id, gw
        except Exception:
            continue
    return None, None

def _scan_text_for_assets(text: str) -> list[str]:
    """Extracts magnet links, HTTP(S) URLs, and IPFS CIDs from raw site text (incl. minified JS)."""
    hits = re.findall(ASSET_URL_PATTERN, text) + re.findall(CID_PATTERN, text)
    return list(dict.fromkeys(hits))

def site_poller_thread():
    """Monitors configured ArNS records via Ar-IO resolver API and public Arweave gateways.
    On TX ID change: computes unified diff against prior deployment, highlights semantic UI/crypto changes,
    archives copies in website_history/, and scans bundled manifest assets for new leaks."""
    history_dir = os.path.abspath("website_history")
    generation = _refresh_generation
    os.makedirs(history_dir, exist_ok=True)
    status_path = os.path.join(history_dir, 'website_status.json')
    try:
        with open(status_path, encoding='utf-8') as saved:
            records = json.load(saved)
        if isinstance(records, dict):
            with _state_lock:
                for name in ARNS_NAMES:
                    if isinstance(records.get(name), dict):
                        _website_state[name] = records[name]
                        if records[name].get('archived_version'):
                            _site_arns_tx_ids[name] = records[name]['archived_version']
    except (OSError, ValueError):
        pass
    
    last_known_tx_file = os.path.join(history_dir, "latest_tx.txt")
    while (generation := wait_for_refresh(generation, 'website')) is not None:
        for name in ARNS_NAMES:
            try:
                with _state_lock:
                    record = _website_state.setdefault(name, {'summary': 'Waiting for first deployment snapshot.'})
                    record['status'] = 'Checking'
                tx_id, gw_url = _resolve_arns_tx_id(name)
                # A legacy shared latest_tx.txt cannot identify which ArNS name
                # it belongs to; only use the per-site baseline for comparisons.
                known = _site_arns_tx_ids.get(name, "")
                with _state_lock:
                    record = _website_state[name]
                    record['checked_at'] = time.time()
                    if tx_id:
                        record.pop('error', None)
                        if known and tx_id != known and record.get('version') != tx_id:
                            record['changed_at'] = time.time()
                        record.update(version=tx_id, status='Current' if tx_id == known else 'Fetching snapshot')
                    else:
                        record['status'] = 'Resolver unavailable'
                if not tx_id:
                    continue
                if tx_id and tx_id != known:
                    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
                    touch_event()
                    log_msg(f"\n[{now_str}] ArNS record updated: {name}\n"
                            f"  Old TX: {known or '<initial>'}\n"
                            f"  New TX: {tx_id}\n"
                            f"  Gateway: https://arweave.net/{tx_id}")
                    
                    # Fetch new HTML
                    new_html = ""
                    for fetch_gw in ("https://arweave.net", "https://ardrive.net", "https://permagate.io"):
                        res = http_get_text(f"{fetch_gw}/{tx_id}", timeout=20.0)
                        if res:
                            new_html = res[0]
                            break
                            
                    # Load old HTML for diffing if available
                    old_html = ""
                    old_path = os.path.join(history_dir, known, "index.html") if known else ""
                    if old_path and os.path.exists(old_path):
                        try:
                            with open(old_path, "r", encoding="utf-8", errors="replace") as of:
                                old_html = of.read()
                        except Exception:
                            pass
                    elif known and os.path.exists("live_leek_site.html"):
                        try:
                            with open("live_leek_site.html", "r", encoding="utf-8", errors="replace") as of:
                                old_html = of.read()
                        except Exception:
                            pass

                    # Perform unified diffing
                    summary = 'Initial deployment snapshot captured.'
                    if old_html and new_html and old_html != new_html:
                        highlights = diff_website_content(old_html, new_html, known, tx_id, history_dir)
                        summary = '\n'.join(highlights) if highlights else 'Style and markup adjustments detected.'
                        log_msg(f"  [+] Website diff generated (website_history/latest.diff):")
                        if highlights:
                            for hl in highlights:
                                log_msg(f"      - {hl}")
                        else:
                            log_msg(f"      - Style and markup adjustments detected.")
                    elif new_html:
                        if old_html == new_html:
                            summary = 'Deployment changed; HTML content is unchanged.'
                        log_msg(f"  [+] Initial deployment snapshot captured ({len(new_html):,} bytes).")

                    # Archive current deployment
                    archive_saved = False
                    tx_dir = os.path.join(history_dir, tx_id)
                    os.makedirs(tx_dir, exist_ok=True)
                    if new_html:
                        try:
                            with open(os.path.join(tx_dir, "index.html"), "w", encoding="utf-8") as f:
                                f.write(new_html)
                            with open(last_known_tx_file, "w", encoding="utf-8") as f:
                                f.write(tx_id)
                            archive_saved = True
                        except Exception:
                            pass

                    # Scan all bundled assets in manifest
                    try:
                        asset_texts = ([new_html] if new_html else []) + _fetch_manifest_asset_texts(tx_id)
                        actionable: list[str] = []
                        for body in asset_texts:
                            actionable.extend(_scan_text_for_assets(body))
                        actionable = [
                            u for u in dict.fromkeys(actionable)
                            if u.startswith("magnet:")
                            or re.fullmatch(CID_PATTERN, u)
                            or urllib.parse.urlparse(u).path.strip("/")
                        ]
                        new_urls = [u for u in actionable if u not in _known_mirror_urls]
                        if new_urls:
                            log_msg(f"  {len(new_urls)} new asset URL(s) found across {len(asset_texts)} scanned manifest file(s).")
                            synthetic_link = {
                                "pda": f"site_{tx_id}",
                                "title": "site_update",
                                "quiet": True,
                                "mirrors": [{"label": f"site_{i+1}", "url": u} for i, u in enumerate(new_urls)],
                            }
                            if not _watch_only:
                                threading.Thread(target=retrieve_asset, args=(synthetic_link, _download_dir), daemon=True).start()
                            else:
                                log_msg('  [Watch-Only] Website payload downloads skipped.')
                        else:
                            log_msg(f"  No new unindexed asset URLs in bundle.")
                    except Exception as e:
                        log_msg(f"  Failed to scan bundled manifest assets: {e}")

                    with _state_lock:
                        if new_html and archive_saved:
                            _site_arns_tx_ids[name] = tx_id
                            _website_state[name].update(archived_version=tx_id, status='Current', summary=summary)
                        else:
                            _website_state[name].update(status='Snapshot unavailable', summary='Deployment resolved, but its snapshot could not be fetched or saved. Retrying next cycle.')
            except Exception as e:
                with _state_lock:
                    _website_state.setdefault(name, {}).update(status='Check failed', checked_at=time.time(), error=str(e))
                log_msg(f"[-] ArNS poll error ({name}): {e}")
        try:
            with _state_lock:
                records = dict((name, dict(value)) for name, value in _website_state.items())
            temporary = status_path + '.tmp'
            with open(temporary, 'w', encoding='utf-8') as saved:
                json.dump(records, saved, indent=2)
            os.replace(temporary, status_path)
        except OSError as exc:
            log_msg(f'[-] Could not save website status: {exc}')

def run_vanish_detection(curr_state: dict, now_str: str):
    """Detects previously observed accounts that are no longer returned in program state."""
    integrity = curr_state.get("integrity", {})
    groups = (
        ("Link", {l["pda"] for l in curr_state["links"]}, _known_links, "Link"),
        ("Proposal", {p["pda"] for p in curr_state["proposals"]}, _known_proposals, "Proposal"),
        ("FrontendConfig", {c["pda"] for c in curr_state["configs"]}, set(_known_configs.keys()), "FrontendConfig"),
    )
    for label, current_pdas, known_pdas, ikey in groups:
        raw_hits, parsed_ok = integrity.get(ikey, (0, 0))
        if raw_hits > parsed_ok:
            # Suppress vanish alert if on-chain accounts failed to decode due to schema or RPC issues
            if ikey not in _parser_health_warned:
                _parser_health_warned.add(ikey)
                log_msg(
                    f"[!] {label} parse failures detected ({parsed_ok}/{raw_hits} decoded) - "
                    f"vanish checks paused for this type until parsing recovers."
                )
            continue
        if raw_hits == parsed_ok:
            _parser_health_warned.discard(ikey)
        for pda in sorted(known_pdas):
            if pda in current_pdas:
                _vanish_counters.pop(pda, None)
                continue
            count = _vanish_counters.get(pda, 0) + 1
            _vanish_counters[pda] = count
            if count == VANISH_CONFIRMATION_POLLS:
                touch_event()
                log_msg(
                    f"\n[{now_str}] ACCOUNT CLOSED ({label}): {pda}\n"
                    f"  Absent from getProgramAccounts for {count} consecutive polls.\n"
                    f"  Possible account rent-closure or deallocation."
                )

def http_poller_background_thread(interval: int = DEFAULT_POLL_INTERVAL_SECONDS):
    """Background polling loop for Solana RPC state, balance tracking, and transaction detection."""
    global _http_poll_status, _highest_slot, _dev_reserve, _next_poll_time
    global _rpc_fail_streak, _rpc_backfill_pending, _last_full_scan_ts

    generation = _refresh_generation
    while (generation := wait_for_refresh(generation, 'on-chain')) is not None:

        try:
            _http_poll_status = "POLL"
            now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
            
            # Check slot + RPC connectivity health
            curr_slot = rpc_call("getSlot", [{"commitment": "processed"}])
            if curr_slot is None:
                _rpc_fail_streak += 1
                if _rpc_fail_streak == 2:
                    log_msg("[!] All Solana RPC endpoints unresponsive - failover active.")
                    if _rpc_errors:
                        for endpoint, err_detail in list(_rpc_errors.items())[-3:]:
                            log_msg(f"    [-] {endpoint} -> {err_detail}")
            else:
                if _rpc_fail_streak >= 2:
                    _rpc_backfill_pending = True
                    log_msg("[+] Solana RPC connectivity restored - backfilling missed signatures.")
                _rpc_fail_streak = 0
                if curr_slot > _highest_slot:
                    _highest_slot = curr_slot

            # Check reserve across all dynamically discovered ATAs
            tot_reserve, per_acc = fetch_total_reserve_balance()
            if tot_reserve is not None:
                old_res = _dev_reserve
                _dev_reserve = tot_reserve
                if abs(tot_reserve - old_res) > 100:
                    handle_reserve_change(tot_reserve, old_res)
            # Check program accounts (None = total RPC failure; must not look like deletions)
            # Full state, balances, and proposals follow the same selected cadence.
            should_scan_program = True
            if should_scan_program:
                _last_full_scan_ts = time.time()
                curr_state = fetch_program_state()
                if curr_state is not None:
                    for l in curr_state["links"]:
                        pda = l["pda"]
                        new_mirrors = [m["url"] for m in l.get("mirrors", []) if m["url"] not in _known_mirror_urls]
                        if pda not in _known_links:
                            _known_links.add(pda)
                            for u in l.get("mirrors", []):
                                _known_mirror_urls.add(u["url"])
                            handle_new_link(l, is_update=False)
                        elif new_mirrors:
                            for u in l.get("mirrors", []):
                                _known_mirror_urls.add(u["url"])
                            handle_new_link(l, is_update=True)

                        # Authority transfer detection
                        auth_hex = l.get("authority_hex", "")
                        if auth_hex and auth_hex != AUTHORITY_BYTES_HEX and pda not in _alerted_authority_transfers:
                            _alerted_authority_transfers.add(pda)
                            touch_event()
                            log_msg(
                                f"\n[{now_str}] AUTHORITY TRANSFER DETECTED on link {pda}\n"
                                f"  Expected: {AUTHORITY_WALLET}\n"
                                f"  Found:    {auth_hex}\n"
                            )
                            play_info_chime()

                    for p in curr_state["proposals"]:
                        if p["pda"] not in _known_proposals:
                            _known_proposals.add(p["pda"])
                            handle_new_proposal(p)

                    poll_active_proposals(curr_state["proposals"])

                    for n in curr_state.get("notices", []):
                        if n["pda"] not in _known_notices:
                            _known_notices.add(n["pda"])
                            handle_new_notice(n)

                    for c in curr_state["configs"]:
                        pda = c["pda"]
                        content = c.get("content", "")
                        if pda not in _known_configs:
                            _known_configs[pda] = content
                        elif _known_configs[pda] != content:
                            _known_configs[pda] = content
                            handle_frontend_config_update(c)

                    run_vanish_detection(curr_state, now_str)
            # Query recent transaction signatures across monitored programs and accounts
            sweep_targets = [(pid, "PROGRAM") for pid in PROGRAM_IDS]
            sweep_targets += [(addr, label) for label, addr in WATCHED_WALLETS]
            sweep_targets += [(PROGRAM_DATA_ACCOUNT, "PROGRAM_DATA")]
            sweep_limit = 50 if _rpc_backfill_pending else 5
            for target, target_label in sweep_targets:
                sigs = rpc_call("getSignaturesForAddress", [target, {"limit": sweep_limit}]) or []
                for s in sigs:
                    sig_id = s["signature"]
                    s_slot = s.get("slot", 0)
                    if s.get("memo"):
                        _known_sigs.add(sig_id)
                        continue
                    if sig_id not in _known_sigs and s_slot > _highest_slot - 50:
                        _known_sigs.add(sig_id)
                        touch_event()
                        if target == PROGRAM_DATA_ACCOUNT:
                            log_msg(
                                f"\n[{now_str}] PROGRAM UPGRADE DETECTED (Slot {s_slot}): {sig_id}\n"
                                f"  Program data account: {PROGRAM_DATA_ACCOUNT}\n"
                                f"  Account discriminators may have changed - parsers at risk\n"
                            )
                            play_info_chime()
                        else:
                            log_msg(f"[{now_str}] Transaction Detected (Slot {s_slot}) [{target_label}]: {sig_id}")
                            if target_label in ("AUTHORITY", "ROUTER", "RESERVE_OWNER"):
                                inspect_wallet_transaction(sig_id)
            _rpc_backfill_pending = False
            _http_poll_status = "OK" if curr_slot is not None else "ERR"
        except Exception:
            _http_poll_status = "ERR"

async def websocket_worker():
    """Maintains a persistent WebSocket subscription stream with automated reconnection and exponential backoff."""
    global _ws_status, _highest_slot, _dev_reserve, _last_ws_error
    
    if not HAS_WEBSOCKETS:
        _ws_status = "OFF"
        return
        
    endpoint_idx = 0
    backoff_delay = 2.0
    while not _shutdown_event.is_set():
        wss_url = WSS_ENDPOINTS[endpoint_idx % len(WSS_ENDPOINTS)]
        conn_start = time.time()
        try:
            _ws_status = "CONN"
            async with websockets.connect(wss_url, ping_interval=20, ping_timeout=20) as ws:
                _ws_status = "ON"
                backoff_delay = 2.0
                
                sub_id = 1
                for pid in PROGRAM_IDS:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": sub_id,
                        "method": "logsSubscribe",
                        "params": [{"mentions": [pid]}, {"commitment": "processed"}]
                    }))
                    sub_id += 1
                for _, wallet in WATCHED_WALLETS:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": sub_id,
                        "method": "logsSubscribe",
                        "params": [{"mentions": [wallet]}, {"commitment": "processed"}]
                    }))
                    sub_id += 1
                
                _req_id_to_ata = {}
                _sub_id_to_ata = {}
                # Subscribe to discovered token account balances
                for ata_pk in list(_monitored_reserve_atas.keys()):
                    _req_id_to_ata[sub_id] = ata_pk
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": sub_id,
                        "method": "accountSubscribe",
                        "params": [ata_pk, {"encoding": "base64", "commitment": "processed"}]
                    }))
                    sub_id += 1
                for pid in PROGRAM_IDS:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": sub_id,
                        "method": "programSubscribe",
                        "params": [pid, {"encoding": "base64", "commitment": "processed"}]
                    }))
                    sub_id += 1
                
                while not _shutdown_event.is_set():
                    try:
                        raw_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        msg = json.loads(raw_msg)
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        break
                    
                    try:
                        # Capture subscription confirmations
                        if "result" in msg and isinstance(msg.get("result"), int) and msg.get("id") in _req_id_to_ata:
                            _sub_id_to_ata[msg["result"]] = _req_id_to_ata[msg["id"]]

                        method = msg.get("method")
                        params = msg.get("params", {})
                        result = params.get("result", {})
                        
                        if isinstance(result, dict) and "context" in result:
                            slot = result["context"].get("slot")
                            if slot and slot > _highest_slot:
                                _highest_slot = slot
                        if method == "logsNotification":
                            val = result.get("value", {})
                            sig = val.get("signature")
                            if sig and sig not in _known_sigs:
                                _known_sigs.add(sig)
                                now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
                                log_msg(f"[{now_str}] Real-time Event (Slot {_highest_slot}): {sig}")
                                touch_event()

                                new_state = fetch_program_state()
                                if new_state is not None:
                                    for l in new_state["links"]:
                                        pda = l["pda"]
                                        new_mirrors = [m["url"] for m in l.get("mirrors", []) if m["url"] not in _known_mirror_urls]
                                        if pda not in _known_links:
                                            _known_links.add(pda)
                                            for u in l.get("mirrors", []):
                                                _known_mirror_urls.add(u["url"])
                                            handle_new_link(l, is_update=False)
                                        elif new_mirrors:
                                            for u in l.get("mirrors", []):
                                                _known_mirror_urls.add(u["url"])
                                            handle_new_link(l, is_update=True)
                                    for p in new_state["proposals"]:
                                        if p["pda"] not in _known_proposals:
                                            _known_proposals.add(p["pda"])
                                            handle_new_proposal(p)
                                    for c in new_state["configs"]:
                                        cpda = c["pda"]
                                        content = c.get("content", "")
                                        if cpda not in _known_configs:
                                            _known_configs[cpda] = content
                                        elif _known_configs[cpda] != content:
                                            _known_configs[cpda] = content
                                            handle_frontend_config_update(c)
                                        
                        elif method == "accountNotification":
                            sub_id_recv = params.get("subscription")
                            changed_ata = _sub_id_to_ata.get(sub_id_recv)
                            val = result.get("value", {})
                            data_arr = val.get("data", [])
                            if data_arr and len(data_arr) > 0:
                                raw_b64 = data_arr[0]
                                acc_bytes = base64.b64decode(raw_b64)
                                if len(acc_bytes) >= 72:
                                    raw_amt = struct.unpack("<Q", acc_bytes[64:72])[0]
                                    curr_bal = raw_amt / 1e9
                                else:
                                    curr_bal = 0.0
                                with _state_lock:
                                    if changed_ata and changed_ata in _monitored_reserve_atas:
                                        _monitored_reserve_atas[changed_ata]["balance"] = curr_bal
                                    tot_bal = sum(i["balance"] for i in list(_monitored_reserve_atas.values()))
                                    old_res = _dev_reserve
                                    _dev_reserve = tot_bal
                                    handle_reserve_change(tot_bal, old_res, ata_pubkey=changed_ata)
                        elif method == "programNotification":
                            val = result.get("value", {})
                            pda = val.get("pubkey")
                            acc_info = val.get("account", {})
                            data_arr = acc_info.get("data", [])
                            if data_arr and len(data_arr) > 0:
                                raw_bytes = base64.b64decode(data_arr[0])
                                disc = raw_bytes[:8]
                                if disc == DISCRIMINATORS["account_link"]:
                                    parsed_l = parse_link_account(raw_bytes, pda)
                                    if parsed_l:
                                        new_mirrors = [m["url"] for m in parsed_l.get("mirrors", []) if m["url"] not in _known_mirror_urls]
                                        if pda not in _known_links:
                                            _known_links.add(pda)
                                            for u in parsed_l.get("mirrors", []):
                                                _known_mirror_urls.add(u["url"])
                                            handle_new_link(parsed_l, is_update=False)
                                        elif new_mirrors:
                                            for u in parsed_l.get("mirrors", []):
                                                _known_mirror_urls.add(u["url"])
                                            handle_new_link(parsed_l, is_update=True)
                                elif disc == DISCRIMINATORS["account_proposal"]:
                                    if pda not in _known_proposals:
                                        _known_proposals.add(pda)
                                        parsed_p = parse_proposal_account(raw_bytes, pda)
                                        if parsed_p:
                                            handle_new_proposal(parsed_p)
                                elif disc == DISCRIMINATORS["account_frontend_config"]:
                                    parsed_c = parse_frontend_config(raw_bytes, pda)
                                    if parsed_c:
                                        content = parsed_c.get("content", "")
                                        if pda not in _known_configs:
                                            _known_configs[pda] = content
                                        elif _known_configs[pda] != content:
                                            _known_configs[pda] = content
                                            handle_frontend_config_update(parsed_c)
                                elif disc == DISCRIMINATORS["account_notice"]:
                                    if pda not in _known_notices:
                                        _known_notices.add(pda)
                                        parsed_n = parse_notice_account(raw_bytes, pda)
                                        if parsed_n:
                                            handle_new_notice(parsed_n)
                    except Exception:
                        pass
        except Exception as e:
            endpoint_idx += 1
            _ws_status = "RECONN"
            err_msg = _format_net_exception(e)
            if err_msg != _last_ws_error:
                _last_ws_error = err_msg
                log_msg(f"[!] WebSocket disconnected ({wss_url}): {err_msg}")
            if time.time() - conn_start >= 30.0:
                backoff_delay = 2.0
            await asyncio.sleep(backoff_delay)
            backoff_delay = min(60.0, backoff_delay * 2.0)

def update_check_thread():
    """Re-run the revision check on the shared refresh clock."""
    generation = _refresh_generation
    while (generation := wait_for_refresh(generation, 'updates')) is not None:
        check_for_update()

def dump_snapshot(output_path: str | None = None):
    """Queries all on-chain program accounts, forensic diagnostics, and environment state, exporting to JSON."""
    slot = rpc_call("getSlot", [{"commitment": "processed"}]) or 0
    global _monitored_reserve_atas, _dev_reserve
    if not _monitored_reserve_atas:
        _monitored_reserve_atas = resolve_reserve_accounts()
    tot_bal, per_acc = fetch_total_reserve_balance() if _monitored_reserve_atas else (0.0, {})
    _dev_reserve = tot_bal
    state = fetch_program_state() or {"links": [], "proposals": [], "configs": [], "registries": [], "notices": [], "integrity": {}}
    price_usd = fetch_cyberleek_usd_price()
    now_ts = time.time()
    
    # 1. Enrich active community proposals with live voting escrows & USD values
    for prop in state.get("proposals", []):
        if prop.get("ends_at", 0) > now_ts and not all(prop.get("finalized", [])):
            atas = get_or_derive_option_atas(prop.get("poll_id", ""), len(prop.get("choices", [])))
            if atas:
                escrows = []
                for idx, (ch, (w_pda, a_pk)) in enumerate(zip(prop.get("choices", []), atas)):
                    bal = fetch_token_balance(a_pk) or 0.0
                    u = bal * price_usd if price_usd > 0 else 0.0
                    escrows.append({
                        "option_index": idx,
                        "choice": ch,
                        "escrow_wallet_pda": w_pda,
                        "escrow_ata": a_pk,
                        "balance_cyberleek": bal,
                        "usd_value": round(u, 2),
                    })
                prop["live_voting_escrows"] = escrows
                prop["cyberleek_price_usd"] = price_usd

    with _state_lock:
        reserve_snapshot = {k: dict(v) for k, v in _monitored_reserve_atas.items()}
        diagnostics_snapshot = dict(_rpc_errors)

    # 2. System Environment Diagnostics (helps diagnose OS, Python, storage, permissions, dependencies)
    storage_path = os.path.abspath(_download_dir if _download_dir else "./leaks")
    disk_free_gb = None
    disk_total_gb = None
    dir_writable = False
    try:
        os.makedirs(storage_path, exist_ok=True)
        usage = shutil.disk_usage(storage_path)
        disk_free_gb = round(usage.free / (1024 ** 3), 2)
        disk_total_gb = round(usage.total / (1024 ** 3), 2)
        test_file = os.path.join(storage_path, f".write_test_{int(now_ts)}")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("ok")
        if os.path.exists(test_file):
            os.remove(test_file)
        dir_writable = True
    except Exception:
        dir_writable = False

    degraded_flags = check_environment_health(storage_path, silent=True)

    system_diagnostics = {
        "os_platform": platform.platform(),
        "os_type": sys.platform,
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "terminal_columns": shutil.get_terminal_size(fallback=(80, 24)).columns,
        "terminal_encoding": getattr(sys.stdout, "encoding", "utf-8") or "utf-8",
        "websockets_installed": HAS_WEBSOCKETS,
        "winsound_available": HAS_WINSOUND,
        "download_directory": storage_path,
        "download_dir_writable": dir_writable,
        "disk_free_gb": disk_free_gb,
        "disk_total_gb": disk_total_gb,
        "environment_warnings": degraded_flags,
    }

    # 3. Network & RPC Connectivity Diagnostics
    cluster_version = rpc_call("getVersion", []) or {}
    t0 = time.time()
    health_res = rpc_call("getHealth", [])
    rpc_latency_ms = round((time.time() - t0) * 1000, 1)

    network_diagnostics = {
        "active_solana_rpc": RPC_ENDPOINTS[0] if RPC_ENDPOINTS else None,
        "rpc_roundtrip_latency_ms": rpc_latency_ms,
        "solana_cluster_version": cluster_version.get("solana-core", "unknown"),
        "solana_cluster_health": health_res if health_res else "ok",
        "candidate_rpc_endpoints": RPC_ENDPOINTS,
        "active_websocket_endpoint": WSS_ENDPOINTS[0] if WSS_ENDPOINTS else None,
        "websocket_status": _ws_status,
        "websocket_last_error": _last_ws_error,
        "arweave_status": _ar_status,
        "dexscreener_price_usd": price_usd,
        "recent_rpc_errors": diagnostics_snapshot,
    }

    # 4. Watched Wallets SOL Balances (helps diagnose if authority/router ran out of gas)
    wallet_diagnostics = {}
    for label, addr in WATCHED_WALLETS:
        bal_res = rpc_call("getBalance", [addr])
        lamports = bal_res.get("value", 0) if isinstance(bal_res, dict) else (bal_res or 0)
        wallet_diagnostics[label] = {
            "address": addr,
            "lamports": lamports,
            "sol_balance": round(lamports / 1e9, 4),
            "is_funded": lamports >= 5000,
        }

    # 5. Token Mint Diagnostics
    token_mint_diagnostics = {
        "mint_address": TOKEN_MINT,
        "decimals": 9,
        "price_usd": price_usd,
    }
    supply_res = rpc_call("getTokenSupply", [TOKEN_MINT])
    if isinstance(supply_res, dict) and "value" in supply_res:
        val = supply_res["value"]
        ui_amt = val.get("uiAmount", 0.0)
        token_mint_diagnostics["circulating_supply"] = ui_amt
        if price_usd > 0 and ui_amt:
            token_mint_diagnostics["market_cap_usd"] = round(ui_amt * price_usd, 2)

    # 6. Runtime Watcher Settings & Counters
    runtime_diagnostics = {
        "gist_revision": GIST_REVISION,
        "poll_interval_seconds": _poll_interval,
        "mask_spoilers": _mask_spoilers,
        "enable_sound": _enable_sound,
        "auto_open": _auto_open,
        "watch_only": _watch_only,
        "browser_fallback": _browser_fallback,
        "tracked_links_count": len(_known_links),
        "tracked_proposals_count": len(_known_proposals),
        "tracked_notices_count": len(_known_notices),
        "tracked_configs_count": len(_known_configs),
        "tracked_arweave_txs_count": len(_known_ar_txs),
        "tracked_signatures_count": len(_known_sigs),
    }

    snapshot = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "gist_revision": GIST_REVISION,
        "slot": slot,
        "dev_reserve_cyberleek": tot_bal,
        "reserve_accounts": reserve_snapshot,
        "total_links": len(state["links"]),
        "total_proposals": len(state["proposals"]),
        "total_notices": len(state.get("notices", [])),
        "total_configs": len(state["configs"]),
        "total_registries": len(state["registries"]),
        "links": state["links"],
        "proposals": state["proposals"],
        "notices": state.get("notices", []),
        "configs": state["configs"],
        "registries": state["registries"],
        "account_integrity": state.get("integrity", {}),
        "market_cap_and_milestones": calculate_mcap_and_milestones(price_usd),
        "debug_diagnostics": {
            "system_environment": system_diagnostics,
            "network_connectivity": network_diagnostics,
            "watched_wallets": wallet_diagnostics,
            "token_mint": token_mint_diagnostics,
            "runtime_settings": runtime_diagnostics,
        }
    }
    json_str = json.dumps(snapshot, indent=2)
    if output_path and output_path != "-":
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(json_str + "\n")
        log_msg(f"[+] State snapshot successfully exported to: {os.path.abspath(output_path)}")
    else:
        sys.stdout.write(json_str + "\n")
        sys.stdout.flush()

def start_monitor(
    interval: int = DEFAULT_POLL_INTERVAL_SECONDS,
    download_dir: str = "./leaks",
    enable_sound: bool = True,
    download_all: bool = False,
    watch_only: bool = False,
    no_auto_open: bool = True,
    no_browser_fallback: bool = True,
    log_file: str | None = None,
    quiet: bool = False,
    test_chime: bool = False,
    custom_rpc: str | None = None,
    custom_ws: str | None = None,
    custom_reserve_atas: list | None = None,
    custom_reserve_owners: list | None = None,
    mask_spoilers: bool = False,
    config_file: str | None = None,
    interactive: bool = True,
):
    """Initializes and runs the main monitoring loop and worker threads."""
    global _enable_sound, _download_dir, _auto_open, _browser_fallback, _watch_only, _quiet, _log_file, _highest_slot
    global _last_event_ts, _dev_reserve, _next_poll_time, _mask_spoilers, _config_file, _poll_interval, _custom_rpc_url, _custom_ws_url
    
    _config_file = os.path.abspath(config_file or "watcher_config.json")
    interval = normalize_poll_interval(interval)
    _poll_interval = interval
    _download_dir = os.path.abspath(download_dir)
    _mask_spoilers = mask_spoilers
    _auto_open = not no_auto_open
    _browser_fallback = False
    _watch_only = watch_only
    _quiet = quiet
    _log_file = log_file
    _custom_rpc_url = custom_rpc
    _custom_ws_url = custom_ws
    # Insert custom RPC/WS endpoints if supplied
    active_rpc = custom_rpc or os.environ.get("SOLANA_RPC_URL")
    if active_rpc and active_rpc not in RPC_ENDPOINTS:
        RPC_ENDPOINTS.insert(0, active_rpc)
        
    active_ws = custom_ws or os.environ.get("SOLANA_WSS_URL")
    if active_ws and active_ws not in WSS_ENDPOINTS:
        WSS_ENDPOINTS.insert(0, active_ws)

    if not _watch_only:
        try:
            os.makedirs(_download_dir, exist_ok=True)
        except Exception as e:
            log_msg(f"[!] Cannot create download directory '{_download_dir}': {e}")
            log_msg(f"[!] Check write access or omit --download-dir to use the default.")
            sys.exit(1)
    _enable_sound = enable_sound
    _last_event_ts = time.time()
    
    check_environment_health(download_dir=_download_dir)
    log_msg("Initializing monitoring engine...")
    
    if test_chime and _enable_sound:
        log_msg("[*] Testing audio chimes...")
        play_leak_chime()
        time.sleep(0.5)

    slot = rpc_call("getSlot", [{"commitment": "processed"}]) or 0
    _highest_slot = max(_highest_slot, slot)
    global _monitored_reserve_atas
    log_msg("Discovering on-chain reserve token accounts...")
    discovered_atas = resolve_reserve_accounts(custom_atas=custom_reserve_atas, custom_owners=custom_reserve_owners)
    with _state_lock:
        _monitored_reserve_atas = discovered_atas
        _dev_reserve = sum(info["balance"] for info in list(_monitored_reserve_atas.values()))
    init_state = fetch_program_state()
    if init_state is None:
        log_msg("[!] Initial RPC sweep failed - starting with an empty baseline.")
        with _state_lock:
            rpc_errs = list(_rpc_errors.items())
        if rpc_errs:
            log_msg("    Detailed diagnostics:")
            for endpoint, err_detail in rpc_errs:
                log_msg(f"    [-] {endpoint} -> {err_detail}")
        init_state = {"links": [], "proposals": [], "configs": [], "registries": []}
    for l in init_state["links"]:
        _known_links.add(l["pda"])
        for m in l.get("mirrors", []):
            _known_mirror_urls.add(m["url"])
    for p in init_state["proposals"]:
        _known_proposals.add(p["pda"])
    for notice in init_state.get("notices", []):
        _known_notices.add(notice["pda"])
    for c in init_state["configs"]:
        _known_configs[c["pda"]] = c.get("content", "")
    for target in [pid for pid in PROGRAM_IDS] + [addr for _, addr in WATCHED_WALLETS] + [PROGRAM_DATA_ACCOUNT]:
        sigs = rpc_call("getSignaturesForAddress", [target, {"limit": 10}]) or []
        for s in sigs:
            _known_sigs.add(s["signature"])
    with _state_lock:
        atas_snapshot = list(_monitored_reserve_atas.items())
    curr_price = fetch_cyberleek_usd_price()
    mcap_meta = calculate_mcap_and_milestones(curr_price)
    if mcap_meta:
        mcap_val = mcap_meta["market_cap_usd"]
        dev_u = mcap_meta["dev_reserve_usd"]
        next_m = mcap_meta.get("next_milestone")
        next_str = f" | Next Tier: {next_m['label']} (${next_m['target_mcap']/1e6:.1f}M)" if next_m else " | All Tiers Surpassed!"
        log_msg(f"  Market Cap: ${mcap_val:,.2f} USD (${mcap_val/1e6:.2f}M) @ ${curr_price:.6f} USD{next_str}")
        log_msg(f"  Developer Reserve: {_dev_reserve:,.0f} CYBERLEEK (${dev_u:,.2f} USD, {mcap_meta['dev_reserve_pct']:.2f}% of supply) ({len(atas_snapshot)} account(s) tracked dynamically)")
    else:
        log_msg(f"  Developer Reserve: {_dev_reserve/1e6:.2f}M CYBERLEEK ({len(atas_snapshot)} account(s) tracked dynamically)")
    for ata_pk, ata_info in atas_snapshot:
        log_msg(f"    - [{ata_info['label']}]: {ata_pk} ({ata_info['balance']:,.2f} tokens)")
    log_msg(f"  Monitored Accounts: {len(_known_links)} links, {len(_known_proposals)} proposals")
    log_msg(f"  Extortion Notices Monitored: Notice #1 ($2M-$6M Leak Tiers), Notice #2 ($30M Full Build Demanded)")
    poll_active_proposals(init_state["proposals"])
    if _active_poll_info:
        info = _active_poll_info
        price_usd = info.get("price_usd", 0.0)
        tot_usd = info.get("total_usd", 0.0)
        tot_usd_str = f" (${tot_usd:,.2f} USD)" if price_usd > 0 else ""
        price_str = f" @ ${price_usd:.6f} USD" if price_usd > 0 else ""
        leader_u = info.get("usd_vals", [])[info["leader_idx"]] if info.get("usd_vals") else 0.0
        leader_usd_str = f", ${leader_u:,.2f} USD" if price_usd > 0 else ""
        log_msg(f"  Active Community Poll: {info['title']} ({info['time_rem_str']} remaining){price_str}")
        log_msg(f"    Current Leader: Option {info['leader_idx']} ({info['leader_choice']}) with {info['leader_pct']:.1f}% ({info['balances'][info['leader_idx']]:,.2f} CYBERLEEK{leader_usd_str})")
        for idx, (ch, bal, u_val) in enumerate(zip(info["choices"], info["balances"], info.get("usd_vals", [0.0]*len(info["choices"])))):
            pct = (bal / info["total"] * 100) if info["total"] > 0 else 0.0
            usd_str = f" (${u_val:,.2f} USD)" if price_usd > 0 else ""
            log_msg(f"    - Option {idx} ({ch}): {bal:,.2f} CYBERLEEK{usd_str} ({pct:.1f}%)")
        log_msg(f"    Total Staked: {info['total']:,.2f} CYBERLEEK{tot_usd_str}")
    log_msg(f"  Storage Directory: {_download_dir}")
    log_msg(f"  Active Feeds: WebSocket stream, HTTP RPC polling ({interval}s), Decentralized storage indexing\n")

    if download_all and not _watch_only:
        threading.Thread(target=backfill_assets, args=(init_state['links'],), daemon=True).start()

    _next_poll_time = time.time() + interval
    start_ws_thread()
    threading.Thread(target=config_watcher_thread, daemon=True).start()
    if interactive:
        threading.Thread(target=hotkey_listener_thread, daemon=True).start()
    threading.Thread(target=site_poller_thread, daemon=True).start()
    threading.Thread(target=arweave_poller_thread, daemon=True).start()
    threading.Thread(target=update_check_thread, daemon=True).start()
    threading.Thread(target=http_poller_background_thread, args=(interval,), daemon=True).start()
    threading.Thread(target=market_poller_thread, daemon=True).start()
    threading.Thread(target=refresh_scheduler_thread, daemon=True).start()
    
    try:
        while not _shutdown_event.is_set():
            now = time.time()
            now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S UTC")
            
            if _http_poll_status == "POLL":
                sync_display = "SYNC"
            else:
                remaining = max(0, int(_next_poll_time - now))
                sync_display = f"{remaining}s"
                
            price_usd = _token_price_usd
            mcap_val = current_market_cap(price_usd) if price_usd > 0 else 0.0
            dev_usd = _dev_reserve * price_usd if price_usd > 0 else 0.0
            
            mcap_disp = format_usd(mcap_val) if mcap_val > 0 else "N/A"
            if dev_usd > 0:
                dev_disp = f"{format_tokens(_dev_reserve)} ({format_usd(dev_usd)})"
            else:
                dev_disp = format_tokens(_dev_reserve)
            
            cols = shutil.get_terminal_size(fallback=(80, 24)).columns
            p_lead = format_poll_status_line(_active_poll_info, cols=cols)

            if cols >= 140:
                status_text = (
                    f"[{now_str}] WS: {_ws_status} | Sync: {sync_display} | "
                    f"MCAP: {mcap_disp} | Dev: {dev_disp} | "
                    f"{p_lead} | Evt: {format_event_age()}"
                )
            elif cols >= 110:
                status_text = (
                    f"[{now_str.split()[0]}] WS: {_ws_status} | Sync: {sync_display} | "
                    f"MCAP: {mcap_disp} | Dev: {dev_disp} | {p_lead}"
                )
            elif cols >= 70:
                # Standard terminal (<= 75 chars)
                time_short = now_str.split()[0] if " " in now_str else now_str
                status_text = (
                    f"[{time_short}] MCAP: {mcap_disp} | Dev: {dev_disp} | {p_lead}"
                )
            else:
                # Narrow mobile terminals (Android / Termux / iOS <70 cols)
                time_short = now_str.split()[0] if " " in now_str else now_str
                status_text = (
                    f"[{time_short}] MCAP: {mcap_disp} | {p_lead}"
                )
            set_status(status_text)
            time.sleep(1)
            
    except KeyboardInterrupt:
        _shutdown_event.set()
    log_msg("\n[*] Monitor stopped.")

def main():
    config_data = load_config(os.path.abspath("watcher_config.json"))
    
    parser = argparse.ArgumentParser(
        description="Solana Program & Decentralized Storage Monitor",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--interval", "-i", type=int, default=config_data.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS), help="RPC polling interval in seconds")
    parser.add_argument("--download-dir", "-d", type=str, default=config_data.get("download_dir", "./leaks"), help="Local directory for retrieved assets")
    parser.add_argument("--download-all", action="store_true", help="Download all historical on-chain leak assets on startup")
    parser.add_argument("--watch-only", action="store_true", default=not config_data.get("download_payloads", True), help="Monitoring mode only; do not download asset payloads")
    parser.add_argument("--no-sound", action="store_true", default=not config_data.get("enable_sound", True), help="Disable audio chime notifications")
    parser.add_argument("--test-chime", action="store_true", help="Play a test audio chime on startup")
    parser.add_argument("--no-auto-open", action="store_true", default=not config_data.get("auto_open_media", False), help="Disable auto-opening media or selecting files in Explorer")
    parser.add_argument("--auto-open", action="store_true", help="Enable auto-opening media in default players upon download")
    parser.add_argument("--no-browser-fallback", action="store_true", help="Disable opening browser tabs for interactive mirrors")
    parser.add_argument("--no-spoilers", "--mask-spoilers", action="store_true", default=config_data.get("mask_spoilers", False), help="Mask leak titles and filenames to prevent spoilers")
    parser.add_argument("--show-spoilers", action="store_true", help="Display full unmasked leak titles and save with story titles")
    parser.add_argument("--unmask-files", action="store_true", help="Rename existing masked download files using manifest.json and exit")
    parser.add_argument("--config", type=str, default="watcher_config.json", help="Path to JSON configuration file")
    parser.add_argument("--log-file", type=str, default=None, help="Append log output to a file on disk")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress the dynamic bottom status line")
    parser.add_argument("--snapshot", nargs="?", const="-", default=None, metavar="FILE", help="Export parsed on-chain state to JSON (stdout or file) and exit")
    parser.add_argument("--extract-archives", "--extract-all", action="store_true", help="Scan local download directory and extract all archives using password discovery")
    parser.add_argument("--reserve-account", action="append", default=[], metavar="PUBKEY", help="Additional SPL token account to track as part of developer reserve")
    parser.add_argument("--reserve-owner", action="append", default=[], metavar="PUBKEY", help="Additional wallet address to dynamically discover token accounts for")
    parser.add_argument("--rpc", type=str, default=config_data.get("custom_rpc_url"), help="Custom Solana HTTP RPC endpoint URL")
    parser.add_argument("--ws", type=str, default=config_data.get("custom_ws_url"), help="Custom Solana WebSocket endpoint URL")
    args = parser.parse_args()

    if args.extract_archives:
        extract_all_local_archives(args.download_dir)
        return

    if args.unmask_files:
        unmask_downloaded_files(args.download_dir)
        return

    if args.snapshot is not None:
        if args.rpc:
            RPC_ENDPOINTS.insert(0, args.rpc)
        dump_snapshot(output_path=args.snapshot if args.snapshot != "-" else None)
        return

    mask_spoilers = not args.show_spoilers if args.show_spoilers else args.no_spoilers

    start_monitor(
        interval=args.interval,
        download_dir=args.download_dir,
        enable_sound=not args.no_sound,
        download_all=args.download_all,
        watch_only=args.watch_only,
        no_auto_open=args.no_auto_open,
        no_browser_fallback=args.no_browser_fallback,
        log_file=args.log_file,
        quiet=args.quiet,
        test_chime=args.test_chime,
        custom_rpc=args.rpc,
        custom_ws=args.ws,
        custom_reserve_atas=args.reserve_account,
        custom_reserve_owners=args.reserve_owner,
        mask_spoilers=mask_spoilers,
        config_file=args.config,
    )
'''

def install(engine):
    exec(compile(PATCH_SOURCE, 'dashboard_extensions.py', 'exec'), engine.__dict__)
