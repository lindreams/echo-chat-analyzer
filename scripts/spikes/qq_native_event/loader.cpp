// Echo-owned restricted loader/IPC bridge. Never enumerates/selects QQ by itself.
// --approved-qq is prepared only; executing it requires a separate human approval.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "session.h"
#include "component_identity.h"
#include "fixture_identity.h"
#include <sddl.h>
#include <psapi.h>
#include <string>
#include <vector>
#include <thread>
#include <cwchar>
#include <algorithm>
#include <atomic>

namespace {
struct Handle {
    HANDLE h = nullptr;
    Handle() = default; explicit Handle(HANDLE value): h(value) {}
    ~Handle() { if (h && h != INVALID_HANDLE_VALUE) CloseHandle(h); }
    Handle(const Handle&) = delete; Handle& operator=(const Handle&) = delete;
};
struct Pin {
    Handle file;
    std::wstring path;
    bool open(const wchar_t* name, const unsigned char* digest) {
        wchar_t full[32768];
        DWORD n = GetFullPathNameW(name, _countof(full), full, nullptr);
        if (!n || n >= _countof(full) || std::wcscmp(full, name) || n < 4 || full[1] != L':') return false;
        file.h = CreateFileW(full, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
            FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
        if (file.h == INVALID_HANDLE_VALUE) return false;
        BY_HANDLE_FILE_INFORMATION info{}; LARGE_INTEGER size{};
        wchar_t resolved[32768];
        if (!GetFileInformationByHandle(file.h, &info) || info.nNumberOfLinks != 1 ||
            (info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY)) ||
            !GetFileSizeEx(file.h, &size) || size.QuadPart < 1 || size.QuadPart > 512ll*1024*1024) return false;
        n = GetFinalPathNameByHandleW(file.h, resolved, _countof(resolved), FILE_NAME_NORMALIZED);
        if (!n || n >= _countof(resolved) || std::wcsncmp(resolved, L"\\\\?\\", 4) || _wcsicmp(resolved+4, full)) return false;
        path = full;
        BCRYPT_ALG_HANDLE alg = nullptr; BCRYPT_HASH_HANDLE hash = nullptr;
        unsigned char actual[32]{}, data[32768]{};
        bool ok = BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0 &&
            BCryptCreateHash(alg, &hash, nullptr, 0, nullptr, 0, 0) >= 0;
        DWORD got = 0; unsigned long long total = 0;
        while (ok) {
            if (!ReadFile(file.h, data, sizeof(data), &got, nullptr)) { ok = false; break; }
            if (!got) break;
            total += got;
            if (total > static_cast<unsigned long long>(size.QuadPart) || BCryptHashData(hash, data, got, 0) < 0) ok = false;
        }
        ok = ok && total == static_cast<unsigned long long>(size.QuadPart) && BCryptFinishHash(hash, actual, 32, 0) >= 0 &&
            !std::memcmp(actual, digest, 32);
        SecureZeroMemory(data, sizeof(data)); SecureZeroMemory(actual, sizeof(actual));
        if (hash) BCryptDestroyHash(hash); if (alg) BCryptCloseAlgorithmProvider(alg, 0);
        return ok;
    }
};
bool unhex(const char* value, unsigned char* out) {
    constexpr char digits[] = "0123456789abcdef";
    for (unsigned i = 0; i < 64; ++i) {
        const char* p = std::strchr(digits, value[i]);
        if (!p || !value[i]) return false;
        if (!(i & 1)) out[i/2] = static_cast<unsigned char>((p-digits) << 4);
        else out[i/2] |= static_cast<unsigned char>(p-digits);
    }
    return value[64] == 0;
}
HMODULE module_at(HANDLE process, const std::wstring& path) {
    HMODULE modules[2048]; DWORD needed = 0;
    if (!EnumProcessModulesEx(process, modules, sizeof(modules), &needed, LIST_MODULES_64BIT) ||
        needed > sizeof(modules) || needed % sizeof(HMODULE)) return nullptr;
    for (unsigned i = 0; i < needed / sizeof(HMODULE); ++i) {
        wchar_t name[32768];
        const auto n = GetModuleFileNameExW(process, modules[i], name, _countof(name));
        if (!n || n >= _countof(name)-1) return nullptr;
        if (!_wcsicmp(path.c_str(), name)) return modules[i];
    }
    return nullptr;
}
bool pinned_wrapper(HANDLE process, Pin& wrapper, const std::wstring& image) {
    HMODULE modules[2048]; DWORD needed = 0;
    if (!EnumProcessModulesEx(process, modules, sizeof(modules), &needed, LIST_MODULES_64BIT) ||
        needed > sizeof(modules) || needed % sizeof(HMODULE)) return false;
    std::wstring found;
    const auto root = image.substr(0, image.find_last_of(L'\\')+1);
    for (unsigned i = 0; i < needed / sizeof(HMODULE); ++i) {
        wchar_t path[32768]; const auto n = GetModuleFileNameExW(process, modules[i], path, _countof(path));
        if (!n || n >= _countof(path)-1) return false;
        const wchar_t* name = std::wcsrchr(path, L'\\');
        if (!name || _wcsicmp(name+1, L"wrapper.node")) continue;
        if (!found.empty() || _wcsnicmp(path, root.c_str(), root.size())) return false;
        found = path;
    }
    unsigned char digest[32];
    return !found.empty() && unhex("fed532ad58d2404dcedf2858554e8fa52a5f4e65b271c008d2faca4011d7d4a2", digest) &&
        wrapper.open(found.c_str(), digest);
}
bool same_user_session(HANDLE process, DWORD pid) {
    DWORD ours = 0, theirs = 0;
    if (!ProcessIdToSessionId(GetCurrentProcessId(), &ours) || !ProcessIdToSessionId(pid, &theirs) || ours != theirs) return false;
    Handle a, b; unsigned char one[1024], two[1024]; DWORD needed;
    return OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &a.h) && OpenProcessToken(process, TOKEN_QUERY, &b.h) &&
        GetTokenInformation(a.h, TokenUser, one, sizeof(one), &needed) && GetTokenInformation(b.h, TokenUser, two, sizeof(two), &needed) &&
        EqualSid(reinterpret_cast<TOKEN_USER*>(one)->User.Sid, reinterpret_cast<TOKEN_USER*>(two)->User.Sid);
}
void* system_load_library(HANDLE process) {
    // Resolve the actual export-owning system image, accounting for forwarders
    // and per-process ASLR. Only 32 public executable bytes are compared.
    const auto local = GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryW");
    HMODULE owner = nullptr;
    if (!local || !GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(local), &owner)) return nullptr;
    wchar_t path[32768]; const auto n = GetModuleFileNameW(owner, path, _countof(path));
    if (!n || n >= _countof(path)) return nullptr;
    const auto remote = module_at(process, path);
    if (!remote) return nullptr;
    auto address = reinterpret_cast<unsigned char*>(remote) + (reinterpret_cast<unsigned char*>(local)-reinterpret_cast<unsigned char*>(owner));
    unsigned char bytes[32]; SIZE_T got = 0; MEMORY_BASIC_INFORMATION region{};
    if (!VirtualQueryEx(process, address, &region, sizeof(region)) || region.Type != MEM_IMAGE ||
        !(region.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)) ||
        !ReadProcessMemory(process, address, bytes, sizeof(bytes), &got) || got != sizeof(bytes) ||
        std::memcmp(bytes, reinterpret_cast<void*>(local), sizeof(bytes))) return nullptr;
    return address;
}
// Remote allocation is reclaimed only after its sole reader thread has exited.
// On a load timeout it is deliberately retained until target exit, never freed
// underneath a running thread. Contains paths/session metadata, no key/traffic.
struct RemoteCall {
    HANDLE process; void* bytes = nullptr; Handle thread;
    explicit RemoteCall(HANDLE p): process(p) {}
    ~RemoteCall() {
        if (bytes && (!thread.h || WaitForSingleObject(thread.h, 0) == WAIT_OBJECT_0)) VirtualFreeEx(process, bytes, 0, MEM_RELEASE);
    }
    bool start(void* entry, const void* input, SIZE_T size) {
        if (!entry || size > 65536) return false;
        bytes = VirtualAllocEx(process, nullptr, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        SIZE_T wrote = 0;
        if (!bytes || !WriteProcessMemory(process, bytes, input, size, &wrote) || wrote != size) return false;
        thread.h = CreateRemoteThread(process, nullptr, 0, reinterpret_cast<LPTHREAD_START_ROUTINE>(entry), bytes, 0, nullptr);
        return thread.h != nullptr;
    }
};
HANDLE private_pipe(const wchar_t* name) {
    Handle token;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token.h)) return INVALID_HANDLE_VALUE;
    unsigned char buffer[1024]; DWORD required = 0;
    if (!GetTokenInformation(token.h, TokenUser, buffer, sizeof(buffer), &required)) return INVALID_HANDLE_VALUE;
    LPWSTR sid = nullptr;
    if (!ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(buffer)->User.Sid, &sid)) return INVALID_HANDLE_VALUE;
    const std::wstring sddl = std::wstring(L"D:P(A;;GA;;;") + sid + L")";
    LocalFree(sid);
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1, &descriptor, nullptr)) return INVALID_HANDLE_VALUE;
    SECURITY_ATTRIBUTES security{sizeof(security), descriptor, FALSE};
    HANDLE pipe = CreateNamedPipeW(name, PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, 1, 16384, 1024, 0, &security);
    LocalFree(descriptor); return pipe;
}
bool stdout_bytes(const void* bytes, DWORD n) {
    DWORD wrote = 0;
    return WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), bytes, n, &wrote, nullptr) && wrote == n;
}
bool cancelled(HANDLE stop) { return WaitForSingleObject(stop, 0) == WAIT_OBJECT_0; }
struct Connection {
    HANDLE pipe;
    OVERLAPPED op{};
    Handle event{CreateEventW(nullptr, TRUE, FALSE, nullptr)};
    bool pending = false;
    explicit Connection(HANDLE p): pipe(p) { op.hEvent = event.h; }
    ~Connection() {
        if (pending) { DWORD ignored; CancelIoEx(pipe, &op); GetOverlappedResult(pipe, &op, &ignored, TRUE); }
    }
};
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 7) return 20;
    const bool fixture = !std::wcscmp(argv[1], L"--fixture");
    if (!fixture && std::wcscmp(argv[1], L"--approved-qq")) return 21;
    wchar_t* end = nullptr;
    const auto pid64 = _wcstoui64(argv[2], &end, 10);
    if (!pid64 || pid64 > MAXDWORD || *end) return 22;
    const auto pid = static_cast<DWORD>(pid64);
    const auto creation = _wcstoui64(argv[3], &end, 10);
    if (!creation || *end || !identity(pid, creation)) return 23;
    struct Input { unsigned magic, build, timeout_ms, reserved; unsigned char image_hash[32]; } input{};
    DWORD got = 0;
    if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE), &input, sizeof(input), &got, nullptr) || got != sizeof(input) ||
        input.magic != SessionMagic || input.build != 54395 || !input.timeout_ms || input.timeout_ms > 120000 || input.reserved) return 24;
    unsigned char expected_dll[32], expected_fixture[32];
    if (!unhex(fixture ? echo_fixture_dll_hash : echo_production_dll_hash, expected_dll) ||
        !unhex(echo_fixture_hash, expected_fixture) || (fixture && std::memcmp(expected_fixture, input.image_hash, 32))) return 25;
    Pin image, library;
    if (!image.open(argv[4], input.image_hash) || !library.open(argv[5], expected_dll)) return 26;
    // argv[6] is an explicit version label, never an automatic fallback.
    if (std::wcscmp(argv[6], L"9.9.37-54395") ||
        (!fixture && _wcsicmp(image.path.substr(image.path.find_last_of(L'\\')+1).c_str(), L"QQ.exe"))) return 27;
    Handle process(OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ | SYNCHRONIZE, FALSE, pid));
    wchar_t selected[32768]; DWORD selected_n = _countof(selected);
    if (!process.h || created_at(process.h) != creation ||
        !QueryFullProcessImageNameW(process.h, 0, selected, &selected_n) || _wcsicmp(selected, image.path.c_str())) return 28;
    BOOL wow64 = FALSE;
    Pin wrapper;
    if (!IsWow64Process(process.h, &wow64) || wow64 || !same_user_session(process.h, pid) ||
        module_at(process.h, library.path) || (!fixture && !pinned_wrapper(process.h, wrapper, image.path))) return 29;
    SessionConfig config{sizeof(config), SessionMagic, 54395, input.timeout_ms, GetCurrentProcessId(), pid,
        created_at(GetCurrentProcess()), creation, {}, {}};
    if (BCryptGenRandom(nullptr, config.nonce, sizeof(config.nonce), BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0) return 30;
    wcscpy_s(config.pipe, L"\\\\.\\pipe\\EchoQQ54395-");
    auto at = std::wcslen(config.pipe);
    constexpr wchar_t digits[] = L"0123456789abcdef";
    for (unsigned i = 0; i < 32; ++i) { config.pipe[at+2*i] = digits[config.nonce[i]>>4]; config.pipe[at+2*i+1] = digits[config.nonce[i]&15]; }
    Handle pipe(private_pipe(config.pipe));
    if (pipe.h == INVALID_HANDLE_VALUE) return 31;
    Connection connection(pipe.h);
    if (!connection.event.h) return 32;
    if (!ConnectNamedPipe(pipe.h, &connection.op) && GetLastError() != ERROR_IO_PENDING) return 33;
    connection.pending = true;
    // Only LoadLibraryW and this pinned DLL's one bootstrap export can be run.
    RemoteCall load(process.h);
    if (!load.start(system_load_library(process.h), library.path.c_str(), (library.path.size()+1)*sizeof(wchar_t)) ||
        WaitForSingleObject(load.thread.h, 5000) != WAIT_OBJECT_0) return 34;
    const auto remote_module = module_at(process.h, library.path);
    HMODULE map = LoadLibraryExW(library.path.c_str(), nullptr, DONT_RESOLVE_DLL_REFERENCES);
    if (!map) return 35;
    auto entry = GetProcAddress(map, "EchoSessionRun");
    if (!remote_module || !entry) { FreeLibrary(map); return 36; }
    const auto rva = reinterpret_cast<unsigned char*>(entry)-reinterpret_cast<unsigned char*>(map);
    FreeLibrary(map);
    if (rva < 0 || rva > 1048576) return 36;
    RemoteCall session(process.h);
    if (!session.start(reinterpret_cast<unsigned char*>(remote_module)+rva, &config, sizeof(config))) return 37;
    const ULONGLONG deadline = GetTickCount64() + input.timeout_ms;
    if (WaitForSingleObject(connection.event.h, 2000) != WAIT_OBJECT_0 || !GetOverlappedResult(pipe.h, &connection.op, &got, FALSE)) return 38;
    connection.pending = false;
    ULONG client = 0; SessionConfig received{};
    if (!GetNamedPipeClientProcessId(pipe.h, &client) || client != pid || created_at(process.h) != creation ||
        !pipe_io(pipe.h, &received, sizeof(received), false, deadline) || std::memcmp(&received, &config, sizeof(config))) return 39;
    unsigned char approval = 1;
    if (!pipe_io(pipe.h, &approval, 1, true, deadline)) return 40;
    Handle stop(CreateEventW(nullptr, TRUE, FALSE, nullptr));
    if (!stop.h) return 41;
    // EOF (parent death) and any input byte both cancel. Poll only our inherited
    // anonymous input pipe; never leave a blocked reader thread on cleanup.
    std::atomic<bool> controls_done{false};
    std::thread controls([&] {
        while (!controls_done.load()) {
            DWORD available = 0;
            if (!PeekNamedPipe(GetStdHandle(STD_INPUT_HANDLE), nullptr, 0, nullptr, &available, nullptr) || available) { SetEvent(stop.h); return; }
            Sleep(5);
        }
    });
    bool ok = true, ready = false, delivered = false, finished = false, stopping = false;
#ifdef ECHO_LOGIN_LIFECYCLE
    unsigned metadata_records = 0;
#endif
    unsigned char payload[EchoEventLimit]{};
    while (ok && !finished && GetTickCount64() < deadline+1000) {
        if (cancelled(stop.h) && !stopping) {
            unsigned char cancel = 1;
            ok = pipe_io(pipe.h, &cancel, 1, true, GetTickCount64()+500);
            stopping = true;
        }
        Frame h{};
        // Poll readiness so control cancellation is noticed within 10 ms.
        DWORD available = 0;
        if (!PeekNamedPipe(pipe.h, nullptr, 0, nullptr, &available, nullptr)) { ok = false; break; }
        if (!available) { if (WaitForSingleObject(process.h, 0) == WAIT_OBJECT_0) { ok = false; break; } Sleep(5); continue; }
        if (!pipe_io(pipe.h, &h, sizeof(h), false, deadline+1000) || h.magic != SessionMagic || h.reserved || h.length > EchoEventLimit) { ok = false; break; }
        if (h.length && !pipe_io(pipe.h, payload, h.length, false, deadline+1000)) { ok = false; break; }
        if (h.type == Ready && !ready && !h.length) ready = true;
#ifdef ECHO_LOGIN_LIFECYCLE
        else if (h.type == Target && ready && h.length == 32 && ++metadata_records <= 65) delivered = true;
#else
        else if (h.type == Target && ready && !delivered && h.length) delivered = true;
#endif
        else if (h.type == Finished && h.length == sizeof(Finish)) {
            const auto* f = reinterpret_cast<const Finish*>(payload);
            ok = f->reads_stopped == 1 && f->hook_disabled == 1; finished = true;
        } else { ok = false; break; }
        // Cancelled sessions never forward another target, even if a frame was
        // already in flight when STOP arrived. No frames follow Finished.
        if (!(h.type == Target && (stopping || cancelled(stop.h))))
            ok = stdout_bytes(&h, sizeof(h)) && (!h.length || stdout_bytes(payload, h.length)) && ok;
        SecureZeroMemory(payload, sizeof(payload));
    }
    controls_done.store(true); controls.join();
    DisconnectNamedPipe(pipe.h); CancelIoEx(pipe.h, nullptr);
    SecureZeroMemory(payload, sizeof(payload)); SecureZeroMemory(&received, sizeof(received)); SecureZeroMemory(&config, sizeof(config));
    const auto ended = WaitForSingleObject(session.thread.h, 2000);
    DWORD code = 1;
    if (ended == WAIT_OBJECT_0) GetExitCodeThread(session.thread.h, &code);
    return ok && ready && finished && ended == WAIT_OBJECT_0 && code == 0 ? 0 : 42;
}
