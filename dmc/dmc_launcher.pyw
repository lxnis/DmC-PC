#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""DmC Definitive Edition (PS4, CUSA01022) - compact Windows launcher for the native port
(GetLostIn/CTR-NitroFueled-PC build, branch dmc, patched by dmc_windows_patch.py).

One small window: game folder, FPS, present mode, display, Play. The first start of a game
folder prepares the game image (prepare.py, link_modules.py + NTJobCode.prx, import names,
content profile) into DATA\\out; saves and the shader cache go to DATA\\user; every run is logged
to DATA\\dmc_play.log. Settings: DATA\\launcher.json (launcher) and DATA\\bbport.ini (the port).

Two modes:
- portable (DmC-Launcher.exe next to bin\\sacredfire.exe, python\\, scripts\\): everything is
  beside the launcher (out\\, user\\, bbport.ini, launcher.json, dmc_play.log); nothing to install.
- development (this script in G:\\Project): the MSYS2 build in G:\\Project\\CTR-NitroFueled-PC,
  data in G:\\PS4\\dmc_win. Start: C:\\msys64\\clang64\\bin\\pythonw.exe dmc_launcher.pyw
  (Tkinter: pacman -S mingw-w64-clang-x86_64-tk).
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

TITLE_ID = 'CUSA01022'
BASE = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
PORTABLE = (BASE / 'bin' / 'sacredfire.exe').is_file()
MSYS2 = Path(os.environ.get('MSYS2_ROOT', r'C:\msys64')) / 'clang64' / 'bin'
if PORTABLE:
    PORT = BASE
    PROBE = BASE / 'bin' / 'sacredfire.exe'
    DATA = Path(os.environ.get('DMC_DATA', BASE))
    DEFAULT_GAME = None
    DLL_DIR = BASE / 'bin'
else:
    PORT = Path(os.environ.get('DMC_PORT', r'G:\Project\CTR-NitroFueled-PC'))
    PROBE = PORT / 'out' / 'sacredfire.exe'
    DATA = Path(os.environ.get('DMC_DATA', r'G:\PS4\dmc_win'))
    DEFAULT_GAME = Path(r'H:\PS4\CUSA01022')
    DLL_DIR = MSYS2
OUT, USER, LOG = DATA / 'out', DATA / 'user', DATA / 'dmc_play.log'
CONF, INI = DATA / 'launcher.json', DATA / 'bbport.ini'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

UNLIMITED = 'Unlimited'
FPS = ['60', '120', '144', '165', '180', UNLIMITED]
PRESENT = {'Mailbox': 'Mailbox', 'VSync': 'Fifo', 'Immediate': 'Immediate'}
MODE = ('Fullscreen', 'Windowed')

# As on Linux: BB_ANISO=0 (no red speckles), serial recording (no screen glitches).
DMC_ENV = {
    'BB_SKIP_GAME_CHECK': '1', 'BB_GAME_PROFILE': 'dmc', 'BB_NEO': '0',
    'BB_GAME_MENU': '0', 'BB_UPSCALER': 'off', 'BB_ANISO': '0',
    'BB_PREP_WORKERS': '0', 'BB_VK_RECORD_THREAD': '0', 'BB_VK_RECORD_THREADS': '1',
    'BB_ASYNC_SUBMIT': '0', 'BB_ASYNC_FENCES': '0',
    # As run.py on Windows (the PC memory model is Linux only).
    'BB_PREUPLOAD': '1', 'BB_GUEST_IN_PLACE': '0', 'BB_UFFD': '0', 'BB_COPY_GPU_BUFFERS': '1',
    'BB_GPU_WRITE_TWINS': '1', 'BB_GPU_WRITE_TWINS_MAX': '65536',
}

BG, PANEL, FG, DIM, ACCENT, WARN = '#1e1f24', '#2a2c33', '#e8e8ec', '#9a9ca6', '#c8102e', '#e0a040'


def read_sfo(folder):
    """TITLE_ID, TITLE, APP_VER, ... from sce_sys/param.sfo (PSF format)."""
    try:
        data = (Path(folder) / 'sce_sys' / 'param.sfo').read_bytes()
        magic, _ver, keys, vals, n = struct.unpack_from('<4sIIII', data, 0)
        if magic != b'\0PSF':
            return {}
        out = {}
        for i in range(n):
            koff, fmt, length, _max, doff = struct.unpack_from('<HHIII', data, 20 + 16 * i)
            key = data[keys + koff:data.index(b'\0', keys + koff)].decode()
            raw = data[vals + doff:vals + doff + length]
            out[key] = struct.unpack_from('<I', raw)[0] if fmt == 0x0404 else \
                raw.split(b'\0')[0].decode('utf-8', 'replace')
        return out
    except (OSError, struct.error, ValueError):
        return {}


def find_python():
    """A Python for the preparation scripts: the bundled one (portable), MSYS2's (it built the
    port), else py/python."""
    for candidate in (BASE / 'python' / 'python.exe', MSYS2 / 'python.exe'):
        if candidate.is_file():
            return [str(candidate)]
    if not getattr(sys, 'frozen', False) and Path(sys.executable).name.lower().startswith('python'):
        return [str(Path(sys.executable).with_name('python.exe'))]
    for name, extra in (('py', ['-3']), ('python', [])):
        if shutil.which(name):
            return [shutil.which(name), *extra]
    return None


def write_ini(path, updates):
    """Rewrites `updates` in the port's bbport.ini and keeps every other line."""
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        lines = ['# bbport settings (DmC launcher)']
    done, out = set(), []
    for line in lines:
        key = line.split('=', 1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else None
        if key in updates:
            out.append(f'{key}={updates[key]}')
            done.add(key)
        else:
            out.append(line)
    out += [f'{k}={v}' for k, v in updates.items() if k not in done]
    path.write_text('\n'.join(out) + '\n', encoding='utf-8')


class Launcher:
    def __init__(self, root):
        self.root = root
        self.busy = False
        self.icon = None
        try:
            self.conf = json.loads(CONF.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.conf = {}

        root.title('DmC: Definitive Edition')
        root.configure(bg=BG)
        root.resizable(False, False)
        self.style()

        f = ttk.Frame(root, padding=12)
        f.pack(fill='both', expand=True)
        top = ttk.Frame(f)
        top.pack(fill='x')
        self.lbl_icon = ttk.Label(top, text='DmC')
        self.lbl_icon.pack(side='left', padx=(0, 10))
        right = ttk.Frame(top)
        right.pack(side='left', fill='x', expand=True)
        ttk.Label(right, text='DmC Devil May Cry', style='Title.TLabel').pack(anchor='w')
        self.lbl_info = ttk.Label(right, text=f'Definitive Edition  ·  {TITLE_ID}  ·  PC port',
                                  style='Dim.TLabel')
        self.lbl_info.pack(anchor='w', pady=(2, 0))

        opts = ttk.Frame(f, style='Panel.TFrame', padding=10)
        opts.pack(fill='x', pady=10)
        opts.columnconfigure(1, weight=1)
        ttk.Label(opts, text='Game folder', style='Panel.TLabel').grid(row=0, column=0, sticky='w')
        row = ttk.Frame(opts, style='Panel.TFrame')
        row.grid(row=0, column=1, sticky='e', pady=2)
        self.lbl_folder = ttk.Label(row, style='Folder.TLabel')
        self.lbl_folder.pack(side='left')
        ttk.Button(row, text='Browse…', width=8, command=self.browse).pack(side='left', padx=(6, 0))

        def combo(r, label, var, values):
            ttk.Label(opts, text=label, style='Panel.TLabel').grid(row=r, column=0, sticky='w')
            c = ttk.Combobox(opts, textvariable=var, values=values, state='readonly', width=14)
            c.grid(row=r, column=1, sticky='e', pady=2)
            c.bind('<<ComboboxSelected>>', lambda e: self.changed())
            return c

        self.v_fps = tk.StringVar(value=self.conf.get('fps') if self.conf.get('fps') in FPS else '60')
        self.v_present = tk.StringVar(value=self.conf.get('present') if self.conf.get('present') in PRESENT else 'Mailbox')
        self.v_mode = tk.StringVar(value=self.conf.get('mode') if self.conf.get('mode') in MODE else 'Fullscreen')
        self.v_showfps = tk.BooleanVar(value=bool(self.conf.get('show_fps', False)))
        # Background shader compiles: a new shader no longer stops the game (cutscene stutter);
        # an effect may be missing for a frame or two while it compiles.
        self.v_async = tk.BooleanVar(value=bool(self.conf.get('async_pipelines', True)))
        combo(1, 'FPS', self.v_fps, FPS)
        combo(2, 'Present mode', self.v_present, list(PRESENT))
        combo(3, 'Display', self.v_mode, list(MODE))
        ttk.Checkbutton(opts, text='Compile shaders in the background (less stutter)', variable=self.v_async,
                        command=self.changed, style='Panel.TCheckbutton').grid(row=4, column=0, columnspan=2,
                                                                               sticky='w', pady=(4, 0))
        ttk.Checkbutton(opts, text='Show FPS counter', variable=self.v_showfps, command=self.changed,
                        style='Panel.TCheckbutton').grid(row=5, column=0, columnspan=2, sticky='w')
        self.lbl_note = ttk.Label(opts, style='Note.TLabel')
        self.lbl_note.grid(row=6, column=0, columnspan=2, sticky='w')

        buttons = ttk.Frame(f)
        buttons.pack(fill='x')
        self.btn_play = ttk.Button(buttons, text='▶  Play', style='Play.TButton', command=self.play)
        self.btn_play.pack(side='left', fill='x', expand=True)
        for text, width, cmd in (('Log', 5, self.open_log), ('Saves', 6, self.open_saves),
                                 ('Cache', 6, self.clear_cache), ('Prepare', 8, self.reprepare)):
            ttk.Button(buttons, text=text, width=width, command=cmd).pack(side='left', padx=(6, 0))
        self.lbl_status = ttk.Label(f, style='Dim.TLabel')
        self.lbl_status.pack(anchor='w', pady=(8, 0))

        root.bind('<Return>', lambda e: self.play())
        root.bind('<Escape>', lambda e: root.destroy())
        self.refresh()
        self.status('Ready. Enter = Play, Esc = quit.')

    def style(self):
        s = ttk.Style(self.root)
        s.theme_use('clam')
        font = ('Segoe UI', 10)
        s.configure('.', background=BG, foreground=FG, fieldbackground=PANEL, bordercolor=PANEL,
                    lightcolor=PANEL, darkcolor=PANEL, font=font)
        s.configure('TFrame', background=BG)
        s.configure('Panel.TFrame', background=PANEL)
        s.configure('TLabel', background=BG, foreground=FG)
        s.configure('Title.TLabel', font=('Segoe UI', 13, 'bold'))
        s.configure('Dim.TLabel', foreground=DIM, font=('Segoe UI', 9))
        s.configure('Panel.TLabel', background=PANEL)
        s.configure('Folder.TLabel', background=PANEL, foreground=DIM, font=('Segoe UI', 9))
        s.configure('Note.TLabel', background=PANEL, foreground=WARN, font=('Segoe UI', 9))
        s.configure('Panel.TCheckbutton', background=PANEL, foreground=FG)
        s.map('Panel.TCheckbutton', background=[('active', PANEL)],
              indicatorcolor=[('selected', ACCENT), ('!selected', BG)])
        s.configure('TCombobox', arrowcolor=FG, foreground=FG, padding=3)
        s.map('TCombobox', fieldbackground=[('readonly', BG)], foreground=[('readonly', FG)],
              selectbackground=[('readonly', BG)], selectforeground=[('readonly', FG)])
        s.configure('TButton', background=PANEL, foreground=FG, padding=6, borderwidth=0)
        s.map('TButton', background=[('active', '#383b44'), ('disabled', PANEL)],
              foreground=[('disabled', DIM)])
        s.configure('Play.TButton', background=ACCENT, font=('Segoe UI', 11, 'bold'))
        s.map('Play.TButton', background=[('active', '#e0283f'), ('disabled', PANEL)])
        self.root.option_add('*TCombobox*Listbox.background', PANEL)
        self.root.option_add('*TCombobox*Listbox.foreground', FG)
        self.root.option_add('*TCombobox*Listbox.selectBackground', ACCENT)

    # ---- state ---------------------------------------------------------------------------
    def game(self):
        g = self.conf.get('game') or DEFAULT_GAME
        return Path(g) if g else None

    def save(self):
        self.conf.update(fps=self.v_fps.get(), present=self.v_present.get(), mode=self.v_mode.get(),
                         show_fps=self.v_showfps.get(), async_pipelines=self.v_async.get())
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            CONF.write_text(json.dumps(self.conf, indent=1), encoding='utf-8')
        except OSError:
            pass

    def changed(self):
        self.save()
        self.refresh()

    def refresh(self):
        g = self.game()
        ok = bool(g) and (g / 'eboot.bin').exists()
        self.lbl_folder.configure(text=f'…\\{g.parent.name}\\{g.name}' if g else '(not set)',
                                  foreground=DIM if ok else WARN)
        note = ''
        if not PROBE.exists():
            note = 'Port not found: sacredfire.exe is missing.'
        elif not ok:
            note = 'Game folder not found. Browse to your CUSA01022 folder.'
        elif self.v_fps.get() != '60':
            note = 'FPS above 60 is experimental.'
        self.lbl_note.configure(text=note)
        (self.lbl_note.grid if note else self.lbl_note.grid_remove)()
        if self.icon is None and ok:
            try:
                img = tk.PhotoImage(file=str(g / 'sce_sys' / 'icon0.png'))
                self.icon = img.subsample(max(1, img.width() // 64))
                self.lbl_icon.configure(image=self.icon, text='')
                self.root.iconphoto(False, self.icon)
            except tk.TclError:
                pass

    def status(self, text):
        self.lbl_status.configure(text=text)

    def browse(self):
        start = self.game() or Path.home()
        start = start if start.exists() else (start.parent if start.parent.exists() else Path.home())
        f = filedialog.askdirectory(parent=self.root, title='Select the DmC game folder (contains eboot.bin)',
                                    initialdir=str(start), mustexist=True)
        if not f:
            return
        f = Path(f)
        if not (f / 'eboot.bin').exists():
            messagebox.showerror('DmC', f'No eboot.bin in:\n{f}\n\nSelect the {TITLE_ID} folder.')
            return
        sfo = read_sfo(f)
        if sfo.get('TITLE_ID') != TITLE_ID:
            messagebox.showerror('DmC', f'{sfo.get("TITLE", "?")} ({sfo.get("TITLE_ID", "TITLE_ID unreadable")}) '
                                 f'is not DmC Definitive Edition {TITLE_ID}.')
            return
        self.conf['game'] = str(f)
        self.icon = None
        self.save()
        self.refresh()
        self.status(f'Using: {sfo.get("TITLE", "DmC")} v{sfo.get("APP_VER", "?")}')

    # ---- launching -----------------------------------------------------------------------
    def needs_prepare(self):
        try:
            same = (OUT / 'source.txt').read_text(encoding='utf-8').strip() == str(self.game())
        except OSError:
            same = False
        return not (same and (OUT / 'boot-linked.bin').exists() and (OUT / 'content.bin').exists())

    def prepare(self, env, step):
        python = find_python()
        if not python:
            raise RuntimeError('No Python found for the preparation scripts (MSYS2 CLANG64 Python).')
        game = self.game()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / 'source.txt').unlink(missing_ok=True)
        ntjob = game / 'Binaries' / 'ntjobcode' / 'ORBIS' / 'Submission' / 'NTJobCode.prx'
        steps = [('Preparing the game image (first start, takes a while)…', 'scripts/prepare.py',
                  [game, '--out', OUT]),
                 # No link_libc.py: DmC's libc.prx has plain-name symbols; link_modules.py links it.
                 ('Linking modules…', 'scripts/link_modules.py',
                  [game, '--out', OUT, '--modules', 'libc.prx', 'libSceFios2.prx', ntjob]),
                 ('Import names…', 'tools/gen_import_names.py', ['--out', OUT]),
                 ('Content profile…', 'scripts/content_profile.py',
                  [game, '--out', OUT, '--sku', 'full', '--dlc-dir', DATA / 'dlc'])]
        with open(OUT / 'prepare.log', 'w', encoding='utf-8', errors='replace') as log:
            for text, script, args in steps:
                step(text)
                cmd = [*python, '-X', 'utf8', str(PORT / script), *map(str, args)]
                log.write('$ ' + ' '.join(cmd) + '\n')
                log.flush()
                r = subprocess.run(cmd, cwd=PORT, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
                if r.returncode != 0:
                    raise RuntimeError(f'{script} failed.\nSee {OUT / "prepare.log"}')
        (OUT / 'source.txt').write_text(str(game) + '\n', encoding='utf-8')

    def launch_env(self):
        env = dict(os.environ)
        for key, value in DMC_ENV.items():
            env.setdefault(key, value)
        if DLL_DIR.is_dir():   # SDL3, FFmpeg, ... (bin\\ beside the port, or MSYS2's for a source build)
            env['PATH'] = f'{DLL_DIR}{os.pathsep}{env.get("PATH", "")}'
        fps = self.v_fps.get()
        env['BB_CONFIG'] = str(INI)
        env['BB_GPU_USER_DIR'] = str(USER)
        env['BB_PRESENT_MODE'] = PRESENT[self.v_present.get()]
        env['BB_FULLSCREEN'] = '1' if self.v_mode.get() == 'Fullscreen' else '0'
        # DmC (UE3) has a variable timestep: the virtual vblank and the limit follow the choice.
        env['BB_VBLANK_HZ'] = '480' if fps == UNLIMITED else fps
        env['BB_FPS_LIMIT'] = '0' if fps == UNLIMITED else fps
        env['BB_ASYNC_PIPELINES'] = '1' if self.v_async.get() else '0'
        write_ini(INI, {'fullscreen': env['BB_FULLSCREEN'], 'fps_limit': env['BB_FPS_LIMIT'],
                        'show_fps': '1' if self.v_showfps.get() else '0', 'upscaler': 'off',
                        'async_pipelines': env['BB_ASYNC_PIPELINES']})
        return env

    def play(self):
        if self.busy:
            return
        probe = PROBE
        if not probe.exists():
            messagebox.showerror('DmC', f'{probe} not found.\nBuild the port first (bash build.sh in MSYS2 CLANG64).')
            return
        game = self.game()
        if not game or not (game / 'eboot.bin').exists():
            messagebox.showerror('DmC', f'Game files not found:\n{game}\nBrowse to your {TITLE_ID} folder.')
            return
        self.save()
        DATA.mkdir(parents=True, exist_ok=True)
        USER.mkdir(parents=True, exist_ok=True)
        env = self.launch_env()
        prepare = self.needs_prepare() or self.conf.pop('force_prepare', False)
        self.busy = True
        self.btn_play.state(['disabled'])

        def worker():
            try:
                if prepare:
                    self.prepare(env, lambda t: self.root.after(0, self.status, t))
            except (RuntimeError, OSError) as e:
                self.root.after(0, self.failed, str(e))
                return
            cmd = [str(probe), str(OUT / 'boot-linked.bin'), '--import-names', str(OUT / 'import_names.txt'),
                   '--content-profile', str(OUT / 'content.bin'), '--app0', str(game), '--user', str(USER),
                   '--timeout', '0']
            self.root.after(0, self.started)
            with open(LOG, 'w', encoding='utf-8', errors='replace') as log:
                rc = subprocess.run(cmd, cwd=PORT, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, creationflags=NO_WINDOW).returncode
            self.root.after(0, self.finished, rc)

        threading.Thread(target=worker, daemon=True).start()

    def started(self):
        self.status('Running DmC …')
        self.root.withdraw()

    def failed(self, message):
        self.busy = False
        self.btn_play.state(['!disabled'])
        self.status('Could not start.')
        messagebox.showerror('DmC', message)

    def finished(self, rc):
        self.busy = False
        self.btn_play.state(['!disabled'])
        self.root.deiconify()
        try:
            lines = LOG.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            lines = []
        issues = [l for l in lines if re.match(r'^(STOP|Fault|Guest fault|Host fault)', l)]
        if issues:
            self.status('The game stopped with an error. See Log.')
            messagebox.showerror('DmC', 'The game stopped:\n' + '\n'.join(issues[:4]) + f'\n\nFull log: {LOG}')
        else:
            self.status(f'Finished (exit code {rc}).')

    def open_log(self):
        if LOG.exists():
            os.startfile(str(LOG))
        else:
            messagebox.showinfo('DmC', 'No log yet. Play once first.')

    def open_saves(self):
        USER.mkdir(parents=True, exist_ok=True)
        os.startfile(str(USER))

    def clear_cache(self):
        shutil.rmtree(USER / 'cache' / TITLE_ID, ignore_errors=True)
        self.status('Shader cache cleared.')

    def reprepare(self):
        self.conf['force_prepare'] = True
        (OUT / 'source.txt').unlink(missing_ok=True)
        self.status('The game image will be prepared again on the next Play.')


if __name__ == '__main__':
    root = tk.Tk(className='dmc-launcher')
    Launcher(root)
    root.mainloop()
