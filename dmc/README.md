# DmC Devil May Cry: Definitive Edition — native PC port (Windows)

An experimental native Windows port of **DmC Devil May Cry: Definitive Edition** (PS4, CUSA01022,
update 01.03). The game's own x86-64 code runs on your CPU and its graphics go through Vulkan.
No emulator, no game files included: **you need your own decrypted dump of the game.**

This branch (`dmc`) is [GetLostIn/CTR-NitroFueled-PC](https://github.com/GetLostIn/CTR-NitroFueled-PC)
(bbport → SacredFire → GetLostIn, with the Windows layer from Supermedo/bloodborne_pc) plus the
DmC changes described below. The CTR port itself is unchanged.

## Download and play

1. Download `DmC-PC-portable-windows.zip` from the Releases page and unpack it somewhere writable
   (not Program Files).
2. Run `DmC-Launcher.exe`, press **Browse…** and select your `CUSA01022` folder
   (the one with `eboot.bin`, `sce_module\` and `sce_sys\param.sfo`).
3. Press **Play**. The first start prepares the game image from your dump (`out\`, about a minute).

Requirements: 64-bit Windows 10 (1903+) or 11, a Vulkan 1.3 GPU with current drivers (tested on an
NVIDIA RTX 3080 Ti, driver 616.92), about 6 GB of free memory. Nothing else to install.

Status: boots, menus, gameplay and Bink cutscenes run (60 FPS default, higher limits experimental).
Known issues: shadows look wrong in places; some stutter on first loads while shaders compile; no
online features (the game sees a signed-out console).

## What the DmC changes are

All in `dmc/dmc_windows_patch.py` (already applied in this branch; marked `bbport-dmc` in the code):

| File | Change |
|---|---|
| `src/runtime_thread.c` | the thread id is the first field of the `ScePthread` handle (UE3 reads `*(int *)handle`); `scePthreadGetthreadid` returns it; `scePthreadGet/Setschedparam`; Windows: `timeBeginPeriod(1)`; an optional CPU sampler (`BB_SAMPLE=1`) |
| `src/runtime_kernel.c` | `sceKernelSetVirtualRangeName`, `sceKernelLoadStartModule` (NTJobCode.prx is linked), POSIX `sem_*`, NP / Ngs2 / dialog / trophy stubs; Windows: `sem_timedwait` with precise short timeouts (winpthreads waited a whole timer tick for a poll: Bink cutscenes ran at 8 FPS); optional trace (`BB_SEM_TRACE=1`) |
| `src/runtime_mutex.c` | Windows: a condition wait whose deadline has passed times out at once |
| `gpu/.../liverpool.cpp` | occlusion counters (ZPASS_DONE) written in recording order, after a pending reset fill (the loading screen waited forever) |
| `gpu/.../regs_shader.h` | the shader header lookup does not follow a bogus offset outside its search window (crash on Windows) |

`dmc/dmc_launcher.pyw` is the launcher; `dmc/make_dmc_portable.py` builds the portable ZIP.

## Build from source

In the **MSYS2 CLANG64** shell, with the packages from `packaging/windows/README.md`:

```bash
git clone -b dmc https://github.com/<you>/CTR-NitroFueled-PC
cd CTR-NitroFueled-PC
git submodule update --init --recursive
bash build.sh                       # out/sacredfire.exe
```

The portable package (python.org Python 3.13 with Tkinter, in PowerShell):

```powershell
py -3.13 dmc\make_dmc_portable.py
```

## License

GPL-2.0-or-later, like the projects it is built on (see `LICENSE`). The bundled libraries and their
licenses are listed in the package's `THIRD-PARTY.txt`.

Not affiliated with Sony Interactive Entertainment, Capcom or Ninja Theory. No game files, keys or
copyrighted game data are included or distributed; you need your own copy of the game.
