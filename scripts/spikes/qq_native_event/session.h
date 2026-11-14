#pragma once
#include "adapter.h"
#include <bcrypt.h>
#include <cstring>
#include <cstdlib>

// Fixed, single-use IPC. No arbitrary command names, message stream or key API.
constexpr unsigned SessionMagic = 0x32535145;
enum FrameType : unsigned { Ready = 1, Target = 2, Finished = 3 };
struct Frame { unsigned magic, type, length, reserved; };
struct Finish { unsigned reads_stopped, hook_disabled, inflight, retained; };
struct SessionConfig {
    unsigned size, magic, build, timeout_ms, server_pid, target_pid;
    unsigned long long server_created, target_created;
    unsigned char nonce[32];
    wchar_t pipe[100];
};
static_assert(sizeof(Frame) == 16 && sizeof(Finish) == 16);
using SessionFn = DWORD (WINAPI*)(void*);

inline unsigned long long created_at(HANDLE process) {
    FILETIME a{}, b{}, c{}, d{};
    if (!GetProcessTimes(process, &a, &b, &c, &d)) return 0;
    return (static_cast<unsigned long long>(a.dwHighDateTime) << 32) | a.dwLowDateTime;
}
inline bool identity(unsigned pid, unsigned long long creation) {
    HANDLE p = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, pid);
    const bool ok = p && creation && created_at(p) == creation && WaitForSingleObject(p, 0) == WAIT_TIMEOUT;
    if (p) CloseHandle(p);
    return ok;
}

// All private-pipe operations are overlapped, bounded, and cancelled/drained
// before the stack OVERLAPPED or its event is destroyed. Never TerminateThread.
inline bool pipe_io(HANDLE pipe, void* bytes, DWORD size, bool write, ULONGLONG deadline, HANDLE stop = nullptr) {
    OVERLAPPED op{}; op.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!op.hEvent) return false;
    bool ok = true;
    auto at = static_cast<unsigned char*>(bytes);
    while (size && ok) {
        if (GetTickCount64() >= deadline || (stop && WaitForSingleObject(stop, 0) == WAIT_OBJECT_0)) { ok = false; break; }
        ResetEvent(op.hEvent);
        DWORD n = 0;
        BOOL immediate = write ? WriteFile(pipe, at, size, &n, &op) : ReadFile(pipe, at, size, &n, &op);
        if (!immediate && GetLastError() == ERROR_IO_PENDING) {
            HANDLE events[] = {op.hEvent, stop};
            const auto now = GetTickCount64();
            const DWORD wait = WaitForMultipleObjects(stop ? 2 : 1, events, FALSE,
                now < deadline ? static_cast<DWORD>(deadline - now) : 0);
            if (wait != WAIT_OBJECT_0) { CancelIoEx(pipe, &op); ok = false; }
            if (!GetOverlappedResult(pipe, &op, &n, TRUE)) ok = false;
        } else if (!immediate) ok = false;
        if (!n || n > size) ok = false;
        if (ok) { at += n; size -= n; }
    }
    CloseHandle(op.hEvent); return ok;
}
inline bool frame_write(HANDLE pipe, unsigned type, void* data, unsigned n, ULONGLONG deadline) {
    Frame h{SessionMagic, type, n, 0};
    return n <= EchoEventLimit && pipe_io(pipe, &h, sizeof(h), true, deadline) &&
        (!n || pipe_io(pipe, data, n, true, deadline));
}
