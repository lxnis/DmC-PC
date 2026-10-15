#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Ports the DmC Definitive Edition fixes of bbport (branch dmc, commit da73c72) onto the
Windows-capable GetLostIn/CTR-NitroFueled-PC tree.

    python dmc_windows_patch.py G:\\Project\\CTR-NitroFueled-PC

Idempotent (every block carries a "bbport-dmc" marker); keeps the files' CRLF line endings.
What is ported:
  runtime_thread.c  tid as the FIRST field of the ScePthread handle (UE3 reads *(int*)handle),
                    scePthreadGetthreadid returns it; scePthreadGet/Setschedparam (SCE codes)
  runtime_kernel.c  sceKernelSetVirtualRangeName, sceKernelLoadStartModule (NTJobCode is linked),
                    POSIX sem_* (winpthreads on Windows), NP / Ngs2 / dialog / trophy stubs
  liverpool.cpp     occlusion counters (ZPASS_DONE) written in recording order (RunInOrder), so a
                    pending reset fill cannot wipe them (DmC's loading screen waited forever)
  runtime_thread.c  Windows: timeBeginPeriod(1) at start (waits time out on a 15.6 ms tick otherwise;
                    DmC's Bink cutscenes ran at 8 FPS)
  runtime_kernel.c  Windows: sem_timedwait with precise short timeouts (Bink cutscenes ran at 8 FPS:
                    winpthreads waited a whole timer tick for a poll); runtime_mutex.c the same for
                    condition variable waits whose deadline has passed
  regs_shader.h     the shader header lookup trusts the offset after s_mov_b32 vcc_hi only inside
                    the 0x4000-dword search window (Windows crash: a bogus offset sent the read to
                    0x1493c45bb0, outside guest memory); otherwise it searches as before
Not ported: the Linux-only register dump in probe.c (diagnostics), and import_names.inc (this tree
names the imports at preparation time from shadPS4's aerolib list, tools/gen_import_names.py).
"""
import sys
from pathlib import Path

MARK = 'bbport-dmc'


def load(path):
    raw = path.read_bytes().decode('utf-8')
    crlf = '\r\n' in raw
    return raw.replace('\r\n', '\n'), crlf


def save(path, text, crlf):
    if crlf:
        text = text.replace('\n', '\r\n')
    path.write_bytes(text.encode('utf-8'))


def replace_once(text, old, new, what):
    n = text.count(old)
    if n != 1:
        sys.exit(f'ERROR: {what}: anchor found {n} times (expected 1). The tree differs from the one '
                 'this script was written for; nothing was written for this file.')
    return text.replace(old, new)


# ---- runtime_thread.c -----------------------------------------------------------------------
def patch_thread(text):
    text = replace_once(text, '''typedef struct GuestThread {
    /* Guest-visible TCB is allocated separately; this is the ScePthread handle. */
''', '''typedef struct GuestThread {
    /* bbport-dmc: first field = thread id, as FreeBSD's struct pthread (long tid). Guest code
     * reads it straight from the handle (UE3: ThreadID = *(int *)handle after scePthreadCreate),
     * so it must equal scePthreadGetthreadid() and be set before the thread is created. */
    int64_t tid;
    /* Guest-visible TCB is allocated separately; this is the ScePthread handle. */
''', 'GuestThread')
    text = replace_once(text, '''static GuestThread *new_thread(void) {
    GuestThread *t=calloc(1,sizeof(*t));
    if (!t) return NULL;
''', '''static int64_t next_tid=100000; /* bbport-dmc: FreeBSD thread ids start at 100000 */
static GuestThread *new_thread(void) {
    GuestThread *t=calloc(1,sizeof(*t));
    if (!t) return NULL;
    t->tid=__atomic_fetch_add(&next_tid,1,__ATOMIC_RELAXED);
''', 'new_thread')
    text = replace_once(text, '''#ifdef _WIN32
static ABI int32_t thread_getthreadid(void) { return (int32_t)compat_thread_id(); }
#else
static ABI int32_t thread_getthreadid(void) { return (int32_t)syscall(SYS_gettid); }
#endif
''', '''/* bbport-dmc: the guest thread id (first field of the ScePthread handle), not the host's. */
static ABI int32_t thread_getthreadid(void) { return (int32_t)runtime_thread_current()->tid; }
''', 'thread_getthreadid')
    text = replace_once(text, '''    t->attr.policy=policy; t->attr.prio=param->priority; return 0;
}
''', '''    t->attr.policy=policy; t->attr.prio=param->priority; return 0;
}
/* bbport-dmc: the scePthread* versions: same behaviour, SCE error codes (0x80020000 + errno). */
static ABI int32_t sce_getschedparam(GuestThread *t,int32_t *policy,GuestSchedParam *param) {
    const int32_t e=posix_getschedparam(t,policy,param); return e ? ERR(e) : 0;
}
static ABI int32_t sce_setschedparam(GuestThread *t,int32_t policy,const GuestSchedParam *param) {
    const int32_t e=posix_setschedparam(t,policy,param); return e ? ERR(e) : 0;
}
''', 'posix_setschedparam')
    text = replace_once(text, '''        {"FIs3-UQT9sg",posix_getschedparam}, {"Xs9hdiD7sAA",posix_setschedparam},
''', '''        {"FIs3-UQT9sg",posix_getschedparam}, {"Xs9hdiD7sAA",posix_setschedparam},
        {"P41kTWUS3EI#libkernel",sce_getschedparam}, {"oIRFTjoILbg#libkernel",sce_setschedparam}, /* bbport-dmc */
''', 'thread export table')
    return text


# ---- runtime_kernel.c -----------------------------------------------------------------------
KERNEL_BLOCK = r'''/* ---- bbport-dmc: DmC Definitive Edition (Unreal Engine 3) ---- */
/* sceKernelSetVirtualRangeName(addr, len, name): names a memory range for Sony's debug tools only;
 * nothing changes, so it is logged and succeeds. */
static ABI int32_t kernel_set_virtual_range_name(const void *addr, size_t len, const char *name) {
    static int reported;
    if (reported < 8) {
        reported++;
        printf("Runtime: sceKernelSetVirtualRangeName(%p, 0x%zx, \"%s\") -> 0\n",
               addr, len, name ? name : "(null)");
    }
    return 0;
}
/* sceKernelLoadStartModule(path, args, argp, flags, opt, result): the game's modules are linked
 * into the image by link_modules.py, so nothing is loaded. A PS4 module handle is positive;
 * *result is module_start's return value (0 = success). */
static ABI int32_t kernel_load_start_module(const char *path, size_t args, const void *argp,
                                            uint32_t flags, const void *opt, int32_t *result) {
    static int32_t next_handle = 0x100;
    (void)args; (void)argp; (void)opt;
    const int32_t handle = next_handle++;
    printf("Runtime: sceKernelLoadStartModule(\"%s\", flags=0x%x) -> handle 0x%x (linked)\n",
           path ? path : "(null)", flags, handle);
    if (result) *result = 0;
    return handle;
}
/* POSIX semaphores: the guest's sem_t holds a pointer to a host semaphore (winpthreads on
 * Windows, glibc on Linux). */
#include <semaphore.h>
typedef struct { int64_t sec, nsec; } DmcGuestTimespec;   /* FreeBSD x86-64 struct timespec */
static sem_t *guest_sem(void *sem) { return sem ? *(sem_t **)sem : NULL; }
static ABI int32_t posix_sem_init(void *sem, int32_t pshared, uint32_t value) {
    (void)pshared;
    if (!sem) return fail_posix(EINVAL);
    sem_t *host = malloc(sizeof(sem_t));
    if (!host) return fail_posix(ENOMEM);
    if (sem_init(host, 0, value)) { const int e = errno; free(host); return fail_posix(e); }
    *(sem_t **)sem = host;
    return 0;
}
static ABI int32_t posix_sem_destroy(void *sem) {
    sem_t *host = guest_sem(sem);
    if (!host) return fail_posix(EINVAL);
    sem_destroy(host);
    free(host);
    *(sem_t **)sem = NULL;
    return 0;
}
static ABI int32_t posix_sem_wait(void *sem) {
    sem_t *host = guest_sem(sem);
    if (!host) return fail_posix(EINVAL);
    while (sem_wait(host)) if (errno != EINTR) return fail_posix(errno);
    return 0;
}
static ABI int32_t posix_sem_trywait(void *sem) {
    sem_t *host = guest_sem(sem);
    if (!host) return fail_posix(EINVAL);
    return sem_trywait(host) ? fail_posix(errno) : 0;
}
/* The deadline is an absolute CLOCK_REALTIME time, converted field by field (Windows' timespec
 * has a 32-bit tv_nsec). */
static ABI int32_t posix_sem_timedwait(void *sem, const DmcGuestTimespec *deadline) {
    sem_t *host = guest_sem(sem);
    if (!host || !deadline) return fail_posix(EINVAL);
    struct timespec ts;
    ts.tv_sec = (time_t)deadline->sec;
    ts.tv_nsec = (long)deadline->nsec;
    while (sem_timedwait(host, &ts)) if (errno != EINTR) return fail_posix(errno);
    return 0;
}
static ABI int32_t posix_sem_post(void *sem) {
    sem_t *host = guest_sem(sem);
    if (!host) return fail_posix(EINVAL);
    return sem_post(host) ? fail_posix(errno) : 0;
}
static ABI int32_t posix_sem_getvalue(void *sem, int32_t *value) {
    sem_t *host = guest_sem(sem);
    if (!host || !value) return fail_posix(EINVAL);
    int v = 0;
    if (sem_getvalue(host, &v)) return fail_posix(errno);
    *value = v;
    return 0;
}

#define DMC_NP_SIGNED_OUT ((int32_t)0x80550006)
#define DMC_LOG(name) do { static int n_; if (n_ < 4) { n_++; printf("Runtime: dmc-stub %s\n", name); } } while (0)
/* NP: an offline console, signed out. */
static ABI int32_t dmc_np_signed_out(void) { DMC_LOG("NP call -> SIGNED_OUT"); return DMC_NP_SIGNED_OUT; }
static ABI int32_t dmc_np_ok(void) { DMC_LOG("NP cleanup -> 0"); return 0; }
static ABI int32_t dmc_np_get_account_id(int32_t user, uint64_t *account) {
    DMC_LOG("sceNpGetAccountId -> SIGNED_OUT");
    (void)user;
    if (account) *account = 0;
    return DMC_NP_SIGNED_OUT;
}
static ABI int32_t dmc_np_new_id(void) {   /* contexts/requests/handles: a positive id */
    static atomic_int next = 1;
    DMC_LOG("NP create -> id");
    return atomic_fetch_add(&next, 1);
}
/* libSceNgs2: fake handles, silent rendering (the game's sound goes through AudioOut + Ajm). */
typedef struct { void *buffer; size_t size; uint32_t waveform_type; uint32_t channels; } DmcNgs2RenderBuffer;
static ABI int32_t dmc_ngs2_system_create(const void *option, const void *allocator, uint64_t *handle) {
    (void)option; (void)allocator;
    DMC_LOG("sceNgs2SystemCreateWithAllocator (silent)");
    if (handle) *handle = 0x4e475332; /* "NGS2" */
    return 0;
}
static ABI int32_t dmc_ngs2_rack_create(uint64_t system, uint32_t rack_id, const void *option,
                                        const void *allocator, uint64_t *handle) {
    (void)system; (void)option; (void)allocator;
    static uint64_t next = 0x52000000; /* "R" */
    DMC_LOG("sceNgs2RackCreateWithAllocator");
    if (handle) *handle = next++ + ((uint64_t)rack_id << 8);
    return 0;
}
static ABI int32_t dmc_ngs2_rack_voice(uint64_t rack, uint32_t index, uint64_t *handle) {
    if (handle) *handle = (rack << 16) | (index + 1);
    return 0;
}
static ABI int32_t dmc_ngs2_voice_flags(uint64_t voice, uint32_t *flags) {
    (void)voice;
    if (flags) *flags = 0; /* not playing */
    return 0;
}
static ABI int32_t dmc_ngs2_render(uint64_t system, DmcNgs2RenderBuffer *buffers, uint32_t count) {
    (void)system;
    for (uint32_t i = 0; buffers && i < count; i++)
        if (buffers[i].buffer && buffers[i].size) memset(buffers[i].buffer, 0, buffers[i].size);
    return 0;
}
static ABI int32_t dmc_ngs2_ok(void) { return 0; }
static ABI int32_t dmc_ngs2_parse_waveform(const void *data, size_t size, void *info) {
    (void)data; (void)size; (void)info;
    DMC_LOG("sceNgs2ParseWaveformData -> error (no decoder yet)");
    return (int32_t)0x804A0000; /* libSceNgs2 error facility; exact code not verified */
}
/* Common dialogs nobody needs offline: open, finish at once, "user cancelled". */
static ABI int32_t dmc_dialog_ok(void) { DMC_LOG("dialog -> 0"); return 0; }
static ABI int32_t dmc_dialog_finished(void) { return 3; /* SCE_COMMON_DIALOG_STATUS_FINISHED */ }
static ABI int32_t dmc_dialog_result(int32_t *result) {
    if (result) *result = 1; /* SCE_COMMON_DIALOG_RESULT_USER_CANCELED */
    return 0;
}
/* System service / app content. */
typedef struct { float ratio; uint8_t reserved[128]; } DmcSafeArea;
static ABI int32_t dmc_safe_area(DmcSafeArea *info) {
    DMC_LOG("sceSystemServiceGetDisplaySafeAreaInfo -> 1.0");
    if (!info) return (int32_t)0x80A10003;
    memset(info, 0, sizeof(*info));
    info->ratio = 1.0f;
    return 0;
}
static ABI int32_t dmc_temp_mount2(uint32_t option, char *mount_point) {
    (void)option;
    DMC_LOG("sceAppContentTemporaryDataMount2 -> /temp0");
    if (mount_point) strcpy(mount_point, "/temp0"); /* SceAppContentMountPoint: char[16] */
    return 0;
}
static ABI int32_t dmc_ok(void) { DMC_LOG("setter/no-op -> 0"); return 0; }
static ABI int32_t dmc_no_socket(void) { DMC_LOG("accept/recv -> EBADF"); return fail_posix(EBADF); }
static ABI int32_t dmc_trophy_unlock_state(int32_t context, int32_t handle, uint32_t *flags, uint32_t *count) {
    (void)context; (void)handle;
    DMC_LOG("sceNpTrophyGetTrophyUnlockState -> none unlocked");
    if (flags) memset(flags, 0, 4 * sizeof(uint32_t));
    if (count) *count = 0;
    return 0;
}

'''

KERNEL_EXPORTS = '''    /* ---- bbport-dmc ---- */
    {"sceKernelSetVirtualRangeName",kernel_set_virtual_range_name},
    {"sceKernelLoadStartModule",kernel_load_start_module},
    {"sem_init",posix_sem_init}, {"sem_destroy",posix_sem_destroy}, {"sem_wait",posix_sem_wait},
    {"sem_trywait",posix_sem_trywait}, {"sem_timedwait",posix_sem_timedwait},
    {"sem_post",posix_sem_post}, {"sem_getvalue",posix_sem_getvalue},
    {"sceNpGetAccountId",dmc_np_get_account_id},
    {"sceNpTusCreateNpTitleCtx",dmc_np_new_id}, {"sceNpTssCreateNpTitleCtx",dmc_np_new_id},
    {"sceNpTusCreateRequest",dmc_np_new_id}, {"sceNpTusDeleteNpTitleCtx",dmc_np_ok},
    {"sceNpTusDeleteRequest",dmc_np_ok}, {"sceNpTusAbortRequest",dmc_np_ok},
    {"sceNpTusPollAsync",dmc_np_signed_out}, {"sceNpTusGetDataAsync",dmc_np_signed_out},
    {"sceNpTusSetDataAsync",dmc_np_signed_out}, {"sceNpTssGetDataAsync",dmc_np_signed_out},
    {"sceNpTusGetMultiSlotVariableAsync",dmc_np_signed_out},
    {"sceNpTusSetMultiSlotVariableAsync",dmc_np_signed_out},
    {"sceNpInGameMessageInitialize",dmc_np_new_id}, {"sceNpInGameMessageCreateHandle",dmc_np_new_id},
    {"sceNpInGameMessagePrepare",dmc_np_signed_out}, {"sceNpInGameMessageSendData",dmc_np_signed_out},
    {"sceNpInGameMessageDeleteHandle",dmc_np_ok}, {"sceNpInGameMessageTerminate",dmc_np_ok},
    {"sceNpLookupCreateRequest",dmc_np_new_id}, {"sceNpLookupWaitAsync",dmc_np_signed_out},
    {"sceNpBandwidthTestInitStart",dmc_np_signed_out}, {"sceNpBandwidthTestGetStatus",dmc_np_signed_out},
    {"sceNpBandwidthTestAbort",dmc_np_ok}, {"sceNpBandwidthTestShutdown",dmc_np_signed_out},
    {"sceNgs2SystemCreateWithAllocator",dmc_ngs2_system_create},
    {"sceNgs2RackCreateWithAllocator",dmc_ngs2_rack_create},
    {"sceNgs2RackGetVoiceHandle",dmc_ngs2_rack_voice}, {"sceNgs2VoiceGetStateFlags",dmc_ngs2_voice_flags},
    {"sceNgs2SystemRender",dmc_ngs2_render}, {"sceNgs2VoiceControl",dmc_ngs2_ok},
    {"sceNgs2RackDestroy",dmc_ngs2_ok}, {"sceNgs2SystemDestroy",dmc_ngs2_ok},
    {"sceNgs2ParseWaveformData",dmc_ngs2_parse_waveform},
    {"sceNpFriendListDialogInitialize",dmc_dialog_ok}, {"sceNpFriendListDialogOpen",dmc_dialog_ok},
    {"sceNpFriendListDialogUpdateStatus",dmc_dialog_finished},
    {"sceNpFriendListDialogGetResult",dmc_dialog_result}, {"sceNpFriendListDialogTerminate",dmc_dialog_ok},
    {"sceGameCustomDataDialogInitialize",dmc_dialog_ok}, {"sceGameCustomDataDialogOpen",dmc_dialog_ok},
    {"sceGameCustomDataDialogUpdateStatus",dmc_dialog_finished},
    {"sceGameCustomDataDialogGetResult",dmc_dialog_result}, {"sceGameCustomDataDialogTerminate",dmc_dialog_ok},
    {"sceSystemServiceGetDisplaySafeAreaInfo",dmc_safe_area},
    {"sceSystemServiceShowDisplaySafeAreaSettings",dmc_ok},
    {"sceAppContentTemporaryDataMount2",dmc_temp_mount2}, {"sceAppContentTemporaryDataFormat",dmc_ok},
    {"sceVoiceSetMuteFlag",dmc_ok}, {"sceVoiceSetVolume",dmc_ok}, {"scePadSetLightBar",dmc_ok},
    {"sceKernelUtimes",dmc_ok}, {"msync",dmc_ok},
    {"accept",dmc_no_socket}, {"recv",dmc_no_socket},
    {"sceNpTrophyGetTrophyUnlockState",dmc_trophy_unlock_state}, {"sceNpTrophyAbortHandle",dmc_ok},
'''


def patch_kernel(text):
    anchor = 'static const RuntimeExport exports[]={\n    {"sceKernelIsNeoMode",is_neo_mode},'
    text = replace_once(text, anchor, KERNEL_BLOCK + 'static const RuntimeExport exports[]={\n' +
                        KERNEL_EXPORTS + '    {"sceKernelIsNeoMode",is_neo_mode},', 'kernel export table')
    return text


# ---- liverpool.cpp --------------------------------------------------------------------------
ZPASS_FN = '''// bbport-dmc: the fixed-sequence occlusion counters, written in recording order. A query reset
// (DMA fill of the results with zero) runs on the recording thread; written at decode time the
// counters could land first and be wiped by the fill (DmC's loading screen waited forever).
struct ZpassFixedEvent {
    VAddr address;
    u32 pairs;
    u64 value;
};
void RunZpassFixed(Vulkan::Rasterizer& rasterizer, const u8* data) {
    ZpassFixedEvent event;
    std::memcpy(&event, data, sizeof(event));
    u64* results = reinterpret_cast<u64*>(event.address);
    for (u32 i = 0; i < event.pairs; ++i, results += 2) {
        *results = event.value;
        rasterizer.NoteLateCommandWrite(reinterpret_cast<VAddr>(results), results, sizeof(*results));
    }
}

void RunDmaData(Vulkan::Rasterizer& rasterizer, const u8* data) {'''


def patch_liverpool(text):
    if '#include <cstring>' not in text:
        text = replace_once(text, '#include <chrono>\n', '#include <chrono>\n#include <cstring>\n', 'includes')
    text = replace_once(text, 'void RunDmaData(Vulkan::Rasterizer& rasterizer, const u8* data) {', ZPASS_FN,
                        'RunDmaData')
    text = replace_once(text, '''                        u64* results = event->Address<u64*>();
                        for (s32 i = 0; i < num_counter_pairs; ++i, results += 2) {
                            *results = pixel_counter | OcclusionCounterValidMask;
                            if (rasterizer) {
                                rasterizer->NoteLateCommandWrite(reinterpret_cast<VAddr>(results),
                                                                 results, sizeof(*results));
                            }
                        }
                        pixel_counter += OcclusionCounterStep;''', '''                        if (rasterizer) {
                            // bbport-dmc: in recording order, after an earlier reset fill.
                            const ZpassFixedEvent fixed{event->Address<VAddr>(), u32(num_counter_pairs),
                                                        pixel_counter | OcclusionCounterValidMask};
                            rasterizer->RunInOrder(&RunZpassFixed, &fixed, sizeof(fixed),
                                                   BbToggle::PipelinedMemoryWrites, false);
                        } else {
                            u64* results = event->Address<u64*>();
                            for (s32 i = 0; i < num_counter_pairs; ++i, results += 2) {
                                *results = pixel_counter | OcclusionCounterValidMask;
                            }
                        }
                        pixel_counter += OcclusionCounterStep;''', 'ZPASS_DONE loop')
    return text


# ---- regs_shader.h --------------------------------------------------------------------------
def patch_regs_shader(text):
    return replace_once(text, '''    if (code[0] == token_mov_vcchi) {
        const auto* info = std::bit_cast<const BinaryInfo*>(code + (code[1] + 1) * 2);
        if (info->Valid()) {
            return *info;
        }
    }''', '''    // bbport-dmc: the offset in the literal is trusted only inside the search window; a bogus
    // one (DmC on Windows: a read at 0x1493c45bb0, outside guest memory) falls back to the search.
    if (code[0] == token_mov_vcchi && (u64(code[1]) + 1) * 2 < 0x4000) {
        const auto* info = std::bit_cast<const BinaryInfo*>(code + (code[1] + 1) * 2);
        if (info->Valid()) {
            return *info;
        }
    }''', 'SearchBinaryInfo')


# ---- runtime_thread.c: Windows timer resolution -----------------------------------------------
TIMER_MARK = 'bbport-dmc-timer'
TIMER_BLOCK = """#define ERR(n) ((int32_t)(UINT32_C(0x80020000)|(n)))
#ifdef _WIN32
/* bbport-dmc-timer: Windows times out every wait (winpthreads condition variables and semaphores,
 * WaitForSingleObject) on the system timer tick, 15.6 ms unless a process asks for less. DmC's
 * Bink cutscenes wait in short timed steps: on the default tick a frame took ~156 ms (8 FPS, GPU
 * idle) while gameplay ran at 150 FPS. timeBeginPeriod(1) makes the tick 1 ms for this process,
 * as games and emulators do. BB_TIMER_1MS=0 leaves the system default (A/B). */
__attribute__((constructor)) static void dmc_timer_resolution(void) {
    const char *env = getenv("BB_TIMER_1MS");
    if (env && env[0] == '0') { printf("Runtime: Windows timer resolution left at the default (BB_TIMER_1MS=0)\\n"); return; }
    HMODULE winmm = LoadLibraryA("winmm.dll");
    typedef UINT (WINAPI *TimeBeginPeriod)(UINT);
    TimeBeginPeriod begin = winmm ? (TimeBeginPeriod)(void *)GetProcAddress(winmm, "timeBeginPeriod") : NULL;
    printf("Runtime: Windows timer resolution 1 ms: %s\\n", begin && begin(1) == 0 ? "on" : "not available");
}
#endif
"""


def patch_timer(text):
    return replace_once(text, '#define ERR(n) ((int32_t)(UINT32_C(0x80020000)|(n)))\n', TIMER_BLOCK,
                        'runtime_thread.c ERR macro')


# ---- runtime_thread.c: Windows CPU sampler (diagnostics) --------------------------------------
SAMPLER_MARK = 'bbport-dmc-sampler4'
SAMPLER_BLOCK = r"""#ifdef _WIN32
/* bbport-dmc-sampler4: BB_SAMPLE=1 (Windows; Linux has BB_SAMPLE_THREAD). Every millisecond each
 * guest thread is suspended for a moment: its instruction pointer and, from a scan of its stack,
 * the nearest return addresses into sacredfire.exe (the port) and into the game are noted. Every
 * 5 s: per thread, the share of time in game code and blocked in the kernel; then the hottest
 * (thread, where, port caller, game caller) entries. Host code: module+offset (llvm-symbolizer
 * --relative-address for sacredfire.exe); game code: guest+offset from 0x800000000. */
enum { DMC_SLOTS = 8192, DMC_TOP = 40, DMC_NAMES = 64, DMC_SCAN = 1024 };
typedef struct { uint64_t rip, host, host2, guest, guest2, guest3; uint32_t count; char name[24]; } DmcSample;
static DmcSample dmc_samples[DMC_SLOTS];
static uint64_t dmc_exe_lo, dmc_exe_hi;
static int dmc_is_guest(uint64_t a) { return a >= 0x800000000ull && a < 0x810000000ull; }
/* Guest code: the eboot's text and the linked modules (libc, Fios2, NTJobCode) after 0x4260000. */
static int dmc_is_guest_code(uint64_t a) {
    const uint64_t o = a - 0x800000000ull;
    return a >= 0x800000000ull && ((o >= 0x1000ull && o < 0x2f7c000ull) || (o >= 0x4260000ull && o < 0x4800000ull));
}
/* A plausible return address: the bytes before it are a call (e8 rel32, ff /2 forms). */
static int dmc_after_call(uint64_t a) {
    /* Read through ReadProcessMemory: a stale stack value may point at an unmapped page. */
    unsigned char bytes[8];
    SIZE_T got = 0;
    if (!ReadProcessMemory(GetCurrentProcess(), (LPCVOID)(uintptr_t)(a - 8), bytes, 8, &got) || got != 8) return 0;
    const unsigned char *p = bytes + 8;
    if (p[-5] == 0xe8) return 1;
    if (p[-2] == 0xff && (p[-1] & 0xf8) == 0xd0) return 1;                 /* call reg */
    if (p[-2] == 0xff && (p[-1] & 0xf8) == 0x10 && (p[-1] & 7) != 4 && (p[-1] & 7) != 5) return 1; /* call [reg] */
    if (p[-3] == 0xff && (p[-2] & 0xf8) == 0x50) return 1;                 /* call [reg+d8] */
    if (p[-6] == 0xff && (p[-5] == 0x15 || (p[-5] & 0xf8) == 0x90)) return 1; /* call [rip+d32] / [reg+d32] */
    if (p[-3] == 0x41 && p[-2] == 0xff && (p[-1] & 0xf8) == 0xd0) return 1; /* call r8-r15 */
    return 0;
}
static void dmc_where(uint64_t rip, char *out, size_t size) {
    HMODULE m = NULL;
    if (!rip) { snprintf(out, size, "-"); return; }
    if (dmc_is_guest(rip)) { snprintf(out, size, "guest+0x%llx", (unsigned long long)(rip - 0x800000000ull)); return; }
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           (LPCSTR)(uintptr_t)rip, &m) && m) {
        char path[MAX_PATH] = "?";
        GetModuleFileNameA(m, path, sizeof(path));
        const char *base = strrchr(path, '\\');
        snprintf(out, size, "%s+0x%llx", base ? base + 1 : path, (unsigned long long)(rip - (uint64_t)(uintptr_t)m));
    } else {
        snprintf(out, size, "0x%llx", (unsigned long long)rip);
    }
}
static int dmc_cmp(const void *a, const void *b) {
    const DmcSample *x = a, *y = b;
    return x->count < y->count ? 1 : x->count > y->count ? -1 : 0;
}
static void dmc_report(uint64_t total) {
    static DmcSample sorted[DMC_SLOTS];
    struct { char name[24]; uint32_t count, guest, kernel; } names[DMC_NAMES];
    int nnames = 0, n = 0;
    for (int i = 0; i < DMC_SLOTS; ++i) {
        if (!dmc_samples[i].count) continue;
        sorted[n++] = dmc_samples[i];
        int k = 0;
        while (k < nnames && strcmp(names[k].name, dmc_samples[i].name)) ++k;
        if (k == nnames && nnames < DMC_NAMES) { memset(&names[k], 0, sizeof(names[k])); memcpy(names[k].name, dmc_samples[i].name, 24); ++nnames; }
        if (k < nnames) {
            char where[160]; dmc_where(dmc_samples[i].rip, where, sizeof(where));
            names[k].count += dmc_samples[i].count;
            if (!strncmp(where, "guest+", 6)) names[k].guest += dmc_samples[i].count;
            if (!strncmp(where, "ntdll", 5) || !strncmp(where, "win32u", 6) || !strncmp(where, "KERNELBASE", 10)) names[k].kernel += dmc_samples[i].count;
        }
    }
    qsort(sorted, n, sizeof(*sorted), dmc_cmp);
    printf("Sampler: %llu samples in 5 s (1 per ms per guest thread)\n", (unsigned long long)total);
    for (int k = 0; k < nnames; ++k)
        if (names[k].count * 50 >= total / 10)
            printf("Sampler thread %-24s %6u samples: guest code %3u%%, blocked in the kernel %3u%%\n", names[k].name,
                   names[k].count, names[k].guest * 100 / names[k].count, names[k].kernel * 100 / names[k].count);
    for (int i = 0; i < n && i < DMC_TOP; ++i) {
        char where[160], host[160], host2[160], guest[48], guest2[48], guest3[48];
        dmc_where(sorted[i].rip, where, sizeof(where));
        dmc_where(sorted[i].host, host, sizeof(host));
        dmc_where(sorted[i].host2, host2, sizeof(host2));
        dmc_where(sorted[i].guest, guest, sizeof(guest));
        dmc_where(sorted[i].guest2, guest2, sizeof(guest2));
        dmc_where(sorted[i].guest3, guest3, sizeof(guest3));
        printf("Sampler hot %2d: %6u  %-20s %-24s port %s < %s  game %s < %s < %s\n", i + 1, sorted[i].count,
               sorted[i].name, where, host, host2, guest, guest2, guest3);
    }
    fflush(stdout);
    memset(dmc_samples, 0, sizeof(dmc_samples));
}
static DWORD WINAPI dmc_sampler(void *arg) {
    (void)arg;
    static uint64_t stack[DMC_SCAN];
    HMODULE exe = GetModuleHandleA(NULL);
    const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)exe;
    const IMAGE_NT_HEADERS *nt = (const IMAGE_NT_HEADERS *)((const char *)exe + dos->e_lfanew);
    dmc_exe_lo = (uint64_t)(uintptr_t)exe;
    dmc_exe_hi = dmc_exe_lo + nt->OptionalHeader.SizeOfImage;
    uint64_t total = 0;
    ULONGLONG last = GetTickCount64();
    for (;;) {
        Sleep(1);
        pthread_mutex_lock(&lock);
        for (GuestThread *t = threads; t; t = t->next) {
            if (t->finished) continue;
            HANDLE h = (HANDLE)pthread_gethandle(t->host);
            if (!h || GetThreadId(h) == GetCurrentThreadId()) continue;
            if (SuspendThread(h) == (DWORD)-1) continue;
            CONTEXT c; memset(&c, 0, sizeof(c)); c.ContextFlags = CONTEXT_CONTROL;
            BOOL ok = GetThreadContext(h, &c);
            uint64_t host = 0, host2 = 0, guest = 0, guest2 = 0, guest3 = 0;
            if (ok) {
                SIZE_T got = 0;
                ReadProcessMemory(GetCurrentProcess(), (LPCVOID)(uintptr_t)c.Rsp, stack, sizeof(stack), &got);
                const uint64_t rip = c.Rip;
                if (rip >= dmc_exe_lo && rip < dmc_exe_hi) host = rip;
                if (dmc_is_guest_code(rip)) guest = rip;
                for (SIZE_T i = 0; i < got / 8 && (!host2 || !guest3); ++i) {
                    const uint64_t v = stack[i];
                    if (v >= dmc_exe_lo + 0x1000 && v < dmc_exe_hi && dmc_after_call(v)) {
                        if (!host) host = v; else if (!host2 && v != host) host2 = v;
                    } else if (dmc_is_guest_code(v) && dmc_after_call(v)) {
                        if (!guest) guest = v; else if (!guest2) guest2 = v; else if (!guest3) guest3 = v;
                    }
                }
            }
            ResumeThread(h);
            if (!ok) continue;
            const uint64_t rip = c.Rip;
            uint32_t hash = (uint32_t)(((rip ^ (host << 7) ^ (host2 << 3) ^ (guest << 13) ^ (guest2 << 17) ^ (guest3 << 21)) * 0x9E3779B97F4A7C15ull) >> 40);
            for (const char *q = t->name; *q; ++q) hash = hash * 31u + (unsigned char)*q;
            for (uint32_t i = 0; i < DMC_SLOTS; ++i) {
                DmcSample *e = &dmc_samples[(hash + i) % DMC_SLOTS];
                if (!e->count) { e->rip = rip; e->host = host; e->host2 = host2; e->guest = guest; e->guest2 = guest2; e->guest3 = guest3;
                                 snprintf(e->name, sizeof(e->name), "%s", t->name); }
                if (e->rip == rip && e->host == host && e->host2 == host2 && e->guest == guest && e->guest2 == guest2 && e->guest3 == guest3 &&
                    !strncmp(e->name, t->name, sizeof(e->name) - 1)) { ++e->count; break; }
            }
            ++total;
        }
        pthread_mutex_unlock(&lock);
        if (GetTickCount64() - last >= 5000) { dmc_report(total); total = 0; last = GetTickCount64(); }
    }
    return 0;
}
__attribute__((constructor)) static void dmc_sampler_start(void) {
    const char *env = getenv("BB_SAMPLE");
    if (env && env[0] == '1') {
        printf("Runtime: CPU sampler on (BB_SAMPLE=1): a report every 5 s\n");
        CreateThread(NULL, 0, dmc_sampler, NULL, 0, NULL);
    }
}
#endif
uintptr_t runtime_thread_resolve(const char *name) {
"""


def patch_sampler(text):
    # An earlier sampler (bbport-dmc-sampler without the stack scan) is replaced.
    old = text.find('#ifdef _WIN32\n/* bbport-dmc-sampler')
    if old >= 0:
        end = text.index('#endif\nuintptr_t runtime_thread_resolve(const char *name) {\n', old)
        text = text[:old] + text[end + len('#endif\n'):]
    return replace_once(text, 'uintptr_t runtime_thread_resolve(const char *name) {\n', SAMPLER_BLOCK,
                        'runtime_thread_resolve')


# ---- runtime_kernel.c: semaphore timing trace (diagnostics) ----------------------------------
SEMTRACE_MARK = 'bbport-dmc-semtrace'
SEMTRACE_OLD = """    struct timespec ts;
    ts.tv_sec = (time_t)deadline->sec;
    ts.tv_nsec = (long)deadline->nsec;
    while (sem_timedwait(host, &ts)) if (errno != EINTR) return fail_posix(errno);
    return 0;
}"""
SEMTRACE_NEW = r"""    struct timespec ts;
    ts.tv_sec = (time_t)deadline->sec;
    ts.tv_nsec = (long)deadline->nsec;
    /* bbport-dmc-semtrace: BB_SEM_TRACE=1 prints, for the first calls and every 500th, how far
     * the deadline lies from the host's CLOCK_REALTIME, how long the wait took and how it ended. */
    static int trace = -1;
    if (trace < 0) { const char *e = getenv("BB_SEM_TRACE"); trace = e && e[0] == '1'; }
    struct timespec t0 = {0, 0};
    if (trace) clock_gettime(CLOCK_REALTIME, &t0);
    int r;
    while ((r = sem_timedwait(host, &ts)) && errno == EINTR) {}
    const int err = r ? errno : 0;
    if (trace) {
        static atomic_int calls;
        const int k = atomic_fetch_add(&calls, 1);
        if (k < 80 || k % 500 == 0) {
            struct timespec t1;
            clock_gettime(CLOCK_REALTIME, &t1);
            const double ahead = (double)(ts.tv_sec - t0.tv_sec) * 1e3 + (double)(ts.tv_nsec - t0.tv_nsec) / 1e6;
            const double waited = (double)(t1.tv_sec - t0.tv_sec) * 1e3 + (double)(t1.tv_nsec - t0.tv_nsec) / 1e6;
            printf("SemTrace #%d: deadline %.3f ms ahead (guest %lld.%09lld), waited %.3f ms, %s\n", k, ahead,
                   (long long)deadline->sec, (long long)deadline->nsec, waited,
                   !err ? "posted" : err == ETIMEDOUT ? "timed out" : "error");
        }
    }
    return r ? fail_posix(err) : 0;
}"""


def patch_semtrace(text):
    return replace_once(text, SEMTRACE_OLD, SEMTRACE_NEW, 'posix_sem_timedwait body')


# ---- runtime_kernel.c + runtime_mutex.c: precise short timeouts on Windows --------------------
WINSEM_MARK = 'bbport-dmc-winsem'
WINSEM_HELPER = r"""/* bbport-dmc-winsem: winpthreads' sem_timedwait rounds a timeout up to the system timer tick:
 * a deadline that has already passed (a poll) or lies 5 ms ahead still waited 10-19 ms. DmC's Bink
 * sound thread paces the video with such polls, so Bink cutscenes ran at 8 FPS on Windows
 * (BB_SEM_TRACE: deadline 0.000 ms ahead, waited ~15 ms, timed out). On Windows: try at once, poll
 * the last 20 ms with high-resolution sleeps, and block in sem_timedwait only until 20 ms before a
 * farther deadline. */
static int dmc_sem_timedwait(sem_t *host, const struct timespec *ts) {
#ifdef _WIN32
    for (unsigned round = 0;; ++round) {
        if (!sem_trywait(host)) return 0;
        if (errno != EAGAIN && errno != EBUSY && errno != EINTR) return -1;
        struct timespec now;
        clock_gettime(CLOCK_REALTIME, &now);
        const int64_t left = (int64_t)(ts->tv_sec - now.tv_sec) * 1000000000 + (int64_t)(ts->tv_nsec - now.tv_nsec);
        if (left <= 0) { errno = ETIMEDOUT; return -1; }
        if (left > 20000000) {   /* far deadline: block until 20 ms before it */
            const int64_t until = (int64_t)now.tv_sec * 1000000000 + now.tv_nsec + left - 20000000;
            struct timespec early = { (time_t)(until / 1000000000), (long)(until % 1000000000) };
            if (!sem_timedwait(host, &early)) return 0;
            if (errno != ETIMEDOUT && errno != EINTR) return -1;
            continue;
        }
        compat_sleep_ns(round < 16 ? 50000 : (uint64_t)(left < 500000 ? left : 500000));
    }
#else
    int r;
    while ((r = sem_timedwait(host, ts)) && errno == EINTR) {}
    return r;
#endif
}
static ABI int32_t posix_sem_timedwait("""


def patch_winsem(text):
    text = replace_once(text, 'static ABI int32_t posix_sem_timedwait(', WINSEM_HELPER, 'posix_sem_timedwait')
    old_loop = '    while ((r = sem_timedwait(host, &ts)) && errno == EINTR) {}\n'
    if old_loop in text:   # the traced version (bbport-dmc-semtrace)
        text = replace_once(text, old_loop, '    r = dmc_sem_timedwait(host, &ts);\n', 'traced wait loop')
    else:
        text = replace_once(text, '    while (sem_timedwait(host, &ts)) if (errno != EINTR) return fail_posix(errno);\n',
                            '    if (dmc_sem_timedwait(host, &ts)) return fail_posix(errno);\n', 'wait loop')
    return text


CONDPOLL_MARK = 'bbport-dmc-condpoll'
CONDPOLL_OLD = """    if (!mutex || (uintptr_t)*mutex < 3 || !end) return orbis_error(EINVAL);
    ++waits;
"""
CONDPOLL_NEW = """    if (!mutex || (uintptr_t)*mutex < 3 || !end) return orbis_error(EINVAL);
    ++waits;
#ifdef _WIN32
    /* bbport-dmc-condpoll: a deadline already past times out at once (winpthreads would still
     * wait for a timer tick, 10-16 ms). */
    {
        struct timespec now;
        clock_gettime(CLOCK_REALTIME, &now);
        if (now.tv_sec > end->tv_sec || (now.tv_sec == end->tv_sec && now.tv_nsec >= end->tv_nsec))
            return timed_error(ETIMEDOUT);
    }
#endif
"""


def patch_condpoll(text):
    return replace_once(text, CONDPOLL_OLD, CONDPOLL_NEW, 'cond_wait_until')


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1])
    jobs = [('src/runtime_thread.c', patch_thread, MARK + ':'),
            ('src/runtime_thread.c', patch_timer, TIMER_MARK),
            ('src/runtime_thread.c', patch_sampler, SAMPLER_MARK),
            ('src/runtime_kernel.c', patch_kernel, MARK),
            ('src/runtime_kernel.c', patch_semtrace, SEMTRACE_MARK),
            ('src/runtime_kernel.c', patch_winsem, WINSEM_MARK),
            ('src/runtime_mutex.c', patch_condpoll, CONDPOLL_MARK),
            ('gpu/shadps4/video_core/amdgpu/liverpool.cpp', patch_liverpool, MARK),
            ('gpu/shadps4/video_core/amdgpu/regs_shader.h', patch_regs_shader, MARK)]
    texts = {}
    for rel, fn, marker in jobs:
        path = root / rel
        if not path.is_file():
            sys.exit(f'ERROR: {path} not found (give the CTR-NitroFueled-PC folder).')
        if rel not in texts:
            texts[rel] = [*load(path), path, False]
        text = texts[rel][0]
        if marker in text:
            print(f'{rel} [{fn.__name__}]: already patched')
            continue
        texts[rel][0] = fn(text)
        texts[rel][3] = True
        print(f'{rel} [{fn.__name__}]: patched')
    for rel, (text, crlf, path, changed) in texts.items():
        if changed:
            save(path, text, crlf)

if __name__ == '__main__':
    main()
