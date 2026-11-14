// Echo-owned single-session bootstrap, called OUTSIDE DllMain/loader lock.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "session.h"
#include <atomic>
#include <cwchar>

extern "C" int EchoInstall(const EchoOptions*);
extern "C" int EchoRead(EchoEvent*, unsigned);
extern "C" int EchoStop();
extern "C" EchoStatus EchoGetStatus();
#ifdef ECHO_FIXTURE_BUILD
extern "C" int EchoReleaseAfterHostJoined();
#endif

namespace {
std::atomic<bool> session_used{false};
bool valid(const SessionConfig& c) {
    if (c.size != sizeof(c) || c.magic != SessionMagic || c.build != 54395 || !c.timeout_ms || c.timeout_ms > 120000 ||
        c.target_pid != GetCurrentProcessId() || c.target_created != created_at(GetCurrentProcess()) ||
        !identity(c.server_pid, c.server_created)) return false;
    constexpr wchar_t prefix[] = L"\\\\.\\pipe\\EchoQQ54395-";
    if (std::wcsncmp(c.pipe, prefix, _countof(prefix)-1)) return false;
    // The name is derived from the same 256-bit nonce, with no external paths.
    constexpr wchar_t hex[] = L"0123456789abcdef";
    const auto offset = _countof(prefix)-1;
    for (unsigned i = 0; i < 32; ++i)
        if (c.pipe[offset+2*i] != hex[c.nonce[i] >> 4] || c.pipe[offset+2*i+1] != hex[c.nonce[i] & 15]) return false;
    return c.pipe[offset+64] == 0;
}
}

extern "C" __declspec(dllexport) DWORD WINAPI EchoSessionRun(void* parameter) {
    if (session_used.exchange(true) || !parameter) return 10;
    SessionConfig c{};
    // Loader owns and retains this small non-secret config until this thread exits.
    __try { std::memcpy(&c, parameter, sizeof(c)); }
    __except (EXCEPTION_EXECUTE_HANDLER) { return 11; }
    if (!valid(c)) { SecureZeroMemory(&c, sizeof(c)); return 12; }
    const ULONGLONG end = GetTickCount64() + c.timeout_ms;
    HANDLE pipe = CreateFileW(c.pipe, GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING,
        FILE_FLAG_OVERLAPPED | SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, nullptr);
    ULONG server = 0;
    bool ok = pipe != INVALID_HANDLE_VALUE && GetNamedPipeServerProcessId(pipe, &server) && server == c.server_pid &&
        identity(server, c.server_created);
    if (ok) ok = pipe_io(pipe, &c, sizeof(c), true, end);
    unsigned char approval = 0;
    if (ok) ok = pipe_io(pipe, &approval, 1, false, end) && approval == 1;
    bool installed = false;
    EchoEvent event{}; event.size = sizeof(event);
    if (ok) {
        const auto now = GetTickCount64();
        EchoOptions options{sizeof(EchoOptions), 9, 9, 37, 54395, now < end ? static_cast<unsigned>(end-now) : 0, 0};
        options.not_after = end;
        installed = EchoInstall(&options) == 1;
        ok = installed && frame_write(pipe, Ready, nullptr, 0, end);
    }
    bool cancelled = false;
    while (ok && GetTickCount64() < end) {
        DWORD available = 0;
        if (!PeekNamedPipe(pipe, nullptr, 0, nullptr, &available, nullptr)) { cancelled = true; break; }
        if (available) { cancelled = true; break; } // Any command cancels; no restart/reconfiguration.
        if (EchoRead(&event, 10)) break;
        if (event.state != Armed) break;
    }
    // EchoRead has consumed and wiped the sole slot; no second capture is
    // possible. Deliver this final response BEFORE the stop barrier. Explicit
    // cancellation discards it instead. No payload may be sent after EchoStop.
    DWORD available = 0;
    if (ok && (!PeekNamedPipe(pipe, nullptr, 0, nullptr, &available, nullptr) || available)) cancelled = true;
    if (ok && !cancelled && event.length && GetTickCount64() < end)
        ok = frame_write(pipe, Target, event.payload, event.length, end);
    SecureZeroMemory(&event, sizeof(event));
    if (installed) EchoStop();
    const auto status = EchoGetStatus();
    Finish finish{installed && status.observation_disabled && !status.inflight ? 1u : 0u,
        status.observation_disabled, status.inflight, status.resources_retained};
    // A short cleanup grace is transport-only; it cannot extend observation.
    if (pipe != INVALID_HANDLE_VALUE) {
        if (ok) frame_write(pipe, Finished, &finish, sizeof(finish), GetTickCount64()+500);
        CancelIoEx(pipe, nullptr); CloseHandle(pipe);
    }
    SecureZeroMemory(&c, sizeof(c));
#ifdef ECHO_FIXTURE_BUILD
    // Only our hash-pinned host can provide this exclusive-call-site join proof.
    const auto join = reinterpret_cast<BOOL (*)()>(GetProcAddress(GetModuleHandleW(nullptr), "EchoFixtureJoin"));
    EchoEvent after{}; after.size = sizeof(after);
    if (installed && join && join() && !EchoRead(&after, 0) && EchoGetStatus().state != Captured &&
        EchoReleaseAfterHostJoined()) {
        HMODULE self = nullptr;
        if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR>(EchoSessionRun), &self)) FreeLibraryAndExitThread(self, 0);
    }
#endif
    // Production keeps its loader reference and trampoline until normal exit.
    return installed && status.observation_disabled ? 0 : 13;
}
