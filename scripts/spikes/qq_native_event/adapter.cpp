// Echo-owned implementation. Layout facts are recorded in the research note;
// no QScope/NapCat implementation is incorporated. MinHook is BSD-2-Clause.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "adapter.h"
#include "MinHook.h"
#include <bcrypt.h>
#include <atomic>
#include <cstring>
#include <cwchar>
#ifdef ECHO_FIXTURE_BUILD
#include "fixture_identity.h"
#endif

namespace {
constexpr char command[] = "OidbSvcTrpcTcp.0xcde_2";
constexpr char qq_hash[] = "fed532ad58d2404dcedf2858554e8fa52a5f4e65b271c008d2faca4011d7d4a2";
// Derived independently from this exact disk image's two semantic LEA anchors
// and PE exception entry. This is a version-pinned FUNCTION RVA, never a key
// address. The 32-byte prologue alone matches hundreds of unrelated functions.
constexpr unsigned receive_rva = 0x1c39de8, receive_end = 0x1c3a274;
constexpr unsigned char receive_prefix[] = {0x55,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x56,0x57,0x53,0x48,0x81,0xec,0x28,0x01,0x00,0x00,0x48,0x8d,0xac,0x24,0x80,0x00,0x00,0x00,0x48,0xc7,0x85,0xa0,0x00};
using Receive = std::int64_t (*)(void*, void**, std::uint32_t);
Receive original = nullptr;
void* target = nullptr;
std::atomic<unsigned> state{Fresh}, inflight{0};
std::atomic<bool> attempted{false};
SRWLOCK data_lock = SRWLOCK_INIT;
HANDLE arrived = nullptr;
unsigned char data[EchoEventLimit]{};
unsigned length = 0;
ULONGLONG deadline = 0;
bool initialized = false, created = false, enabled = false;
DWORD owner = 0;

// Deny concurrent lifecycle callers. Only the install owner may read/stop.
bool owned() { return owner == GetCurrentThreadId(); }
bool file_hash(HMODULE module, const char* expected) {
    wchar_t path[32768];
    const DWORD n = GetModuleFileNameW(module, path, 32768);
    if (!n || n >= 32768) return false;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                              FILE_FLAG_SEQUENTIAL_SCAN | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (file == INVALID_HANDLE_VALUE) return false;
    BY_HANDLE_FILE_INFORMATION info{};
    LARGE_INTEGER size{};
    bool ok = GetFileInformationByHandle(file, &info) && info.nNumberOfLinks == 1 &&
        !(info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY)) &&
        GetFileSizeEx(file, &size) && size.QuadPart > 0 && size.QuadPart <= 512ll * 1024 * 1024;
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE hash = nullptr;
    unsigned char digest[32]{}, buffer[32768];
    ok = ok && BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0 &&
         BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0;
    DWORD got = 0;
    ULONGLONG total = 0;
    while (ok) {
        if (!ReadFile(file, buffer, sizeof(buffer), &got, nullptr)) { ok = false; break; }
        if (!got) break;
        total += got;
        if (total > static_cast<ULONGLONG>(size.QuadPart) || BCryptHashData(hash, buffer, got, 0) < 0) ok = false;
    }
    ok = ok && total == static_cast<ULONGLONG>(size.QuadPart) && BCryptFinishHash(hash, digest, 32, 0) >= 0;
    constexpr char digits[] = "0123456789abcdef";
    for (unsigned i = 0; ok && i < 32; ++i)
        ok = digits[digest[i] >> 4] == expected[i*2] && digits[digest[i] & 15] == expected[i*2+1];
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    SecureZeroMemory(buffer, sizeof(buffer));
    CloseHandle(file);
    return ok;
}

void* select_target() {
#ifdef ECHO_FIXTURE_BUILD
    const auto module = GetModuleHandleW(nullptr);
    if (!file_hash(module, echo_fixture_hash)) return nullptr;
    return reinterpret_cast<void*>(GetProcAddress(module, "EchoFixtureReceive"));
#else
    const auto module = GetModuleHandleW(L"wrapper.node"); // Never load a QQ module ourselves.
    if (!module || !file_hash(module, qq_hash)) return nullptr;
    auto base = reinterpret_cast<unsigned char*>(module);
    auto dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE || dos->e_lfanew < 64 || dos->e_lfanew > 1048576) return nullptr;
    auto nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE || nt->FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64 ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC || nt->FileHeader.NumberOfSections > 96 ||
        nt->OptionalHeader.SizeOfImage > 512u * 1024 * 1024) return nullptr;
    if (receive_end > nt->OptionalHeader.SizeOfImage || receive_end <= receive_rva) return nullptr;
    bool executable = false;
    auto section = IMAGE_FIRST_SECTION(nt);
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; ++i) {
        if (!(section[i].Characteristics & IMAGE_SCN_MEM_EXECUTE)) continue;
        const auto start = section[i].VirtualAddress, count = section[i].Misc.VirtualSize;
        if (start > nt->OptionalHeader.SizeOfImage || count > nt->OptionalHeader.SizeOfImage - start) return nullptr;
        if (start <= receive_rva && receive_end <= start + count) executable = true;
    }
    auto found = base + receive_rva;
    if (!executable || std::memcmp(found, receive_prefix, sizeof(receive_prefix))) return nullptr;
    DWORD64 image_base = 0;
    auto unwind = RtlLookupFunctionEntry(reinterpret_cast<DWORD64>(found), &image_base, nullptr);
    if (!unwind || image_base != reinterpret_cast<DWORD64>(module) ||
        base + unwind->BeginAddress != found || unwind->EndAddress != receive_end) return nullptr;
    // Confirm both semantic references inside the same pinned unwind function.
    const char* anchors[] = {"DidRecvResponseData", "MSF recv seq:{} cmd:{} data_size:{}, error_code:{}"};
    for (const char* literal : anchors) {
        bool referenced = false;
        const auto n = std::strlen(literal) + 1;
        for (unsigned i = receive_rva; i + 7 <= receive_end; ++i) {
            if ((base[i] & 0xf8) != 0x48 || base[i+1] != 0x8d || (base[i+2] & 0xc7) != 5) continue;
            std::int32_t relative; std::memcpy(&relative, base+i+3, 4);
            const auto destination = static_cast<std::int64_t>(i) + 7 + relative;
            if (destination >= 0 && static_cast<std::uint64_t>(destination) + n <= nt->OptionalHeader.SizeOfImage &&
                !std::memcmp(base + destination, literal, n)) referenced = true;
        }
        if (!referenced) return nullptr;
    }
    return found;
#endif
}

// The only native business-memory reads follow the current receive callback's
// owner -> response -> bounded command; only a matching command reaches payload.
// This is not a process-memory search. SEH keeps a bad layout from crashing host.
void inspect_response(void** owner_ptr, unsigned error) {
    __try {
        if (error || !owner_ptr || !*owner_ptr) return;
        auto response = static_cast<unsigned char*>(*owner_ptr);
        std::uint64_t words[3];
        std::memcpy(words, response + 32, sizeof(words));
        const bool heap = (words[0] & 1) != 0;
        const auto n = heap ? words[1] : (words[0] & 255) >> 1;
        if (n != sizeof(command) - 1 || (!heap && n > 22) || (heap && (words[0] & ~1ull) < n)) return;
        auto text = heap ? reinterpret_cast<const void*>(words[2]) : response + 33;
        if (std::memcmp(text, command, sizeof(command) - 1)) return;
        if (!TryAcquireSRWLockExclusive(&data_lock)) return;
        // Lock release is exception-safe even if a callback-owned pointer faults.
        __try {
            if (state.load() != Armed) __leave;
            if (GetTickCount64() >= deadline) { state.store(Expired); SetEvent(arrived); __leave; }
            auto vector = *reinterpret_cast<std::uintptr_t**>(response + 56);
            if (!vector || vector[1] < vector[0] || vector[2] < vector[1] ||
                !vector[0] || vector[1] - vector[0] == 0 || vector[1] - vector[0] > EchoEventLimit) {
                state.store(Rejected); SetEvent(arrived); __leave;
            }
            length = static_cast<unsigned>(vector[1] - vector[0]);
            std::memcpy(data, reinterpret_cast<void*>(vector[0]), length);
            state.store(Captured); SetEvent(arrived);
        } __finally { ReleaseSRWLockExclusive(&data_lock); }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        AcquireSRWLockExclusive(&data_lock);
        SecureZeroMemory(data, sizeof(data)); length = 0;
        state.store(Rejected); SetEvent(arrived);
        ReleaseSRWLockExclusive(&data_lock);
    }
}

std::int64_t receive(void* self, void** object, std::uint32_t error) {
    const auto saved_error = GetLastError();
    inflight.fetch_add(1);
    if (state.load() == Armed) {
        if (GetTickCount64() >= deadline) { unsigned armed = Armed; state.compare_exchange_strong(armed, Expired); SetEvent(arrived); }
        else inspect_response(object, error);
    }
    SetLastError(saved_error);
    __try { return original(self, object, error); }
    __finally { inflight.fetch_sub(1); }
}

bool rollback() {
    bool ok = true;
    if (enabled) { ok = MH_DisableHook(target) == MH_OK; if (ok) enabled = false; }
    if (!enabled && created) { ok = MH_RemoveHook(target) == MH_OK && ok; if (ok) created = false; }
    if (!created && initialized) { ok = MH_Uninitialize() == MH_OK && ok; if (ok) initialized = false; }
    if (ok && arrived) { CloseHandle(arrived); arrived = nullptr; }
    return ok;
}
}

extern "C" __declspec(dllexport) int EchoInstall(const EchoOptions* options) {
    if (attempted.exchange(true)) return 0;
    owner = GetCurrentThreadId();
    state.store(Rejected);
    if (!options || options->size != sizeof(EchoOptions) || options->major != 9 || options->minor != 9 ||
        options->patch != 37 || options->build != 54395 || !options->timeout_ms || options->timeout_ms > 120000) return 0;
#ifndef ECHO_FIXTURE_BUILD
    if (options->fixture_fail_after_create) return 0;
#endif
    target = select_target();
    if (!target) return 0;
    arrived = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!arrived) return 0;
    initialized = MH_Initialize() == MH_OK;
    if (!initialized) { rollback(); return 0; }
    created = MH_CreateHook(target, reinterpret_cast<void*>(receive), reinterpret_cast<void**>(&original)) == MH_OK;
    if (!created || options->fixture_fail_after_create) { rollback(); return 0; }
    deadline = GetTickCount64() + options->timeout_ms;
    state.store(Armed);
    enabled = MH_EnableHook(target) == MH_OK;
    if (!enabled) { state.store(Rejected); rollback(); return 0; }
    return 1;
}

extern "C" __declspec(dllexport) int EchoRead(EchoEvent* result, unsigned wait_ms) {
    if (!owned() || !result || result->size != sizeof(EchoEvent) || wait_ms > 2000 || !arrived) return 0;
    const auto current = GetTickCount64();
    const auto remaining = current < deadline ? deadline - current : 0;
    WaitForSingleObject(arrived, static_cast<DWORD>(remaining < wait_ms ? remaining : wait_ms));
    AcquireSRWLockExclusive(&data_lock);
    if (state.load() == Armed && GetTickCount64() >= deadline) state.store(Expired);
    result->length = 0; result->state = state.load();
    if (result->state == Captured) {
        result->length = length; std::memcpy(result->payload, data, length);
        SecureZeroMemory(data, sizeof(data)); length = 0; state.store(Consumed);
    }
    ReleaseSRWLockExclusive(&data_lock);
    return result->length != 0;
}

extern "C" __declspec(dllexport) int EchoStop() {
    if (!owned()) return 0;
    AcquireSRWLockExclusive(&data_lock);
    if (state.load() == Armed) state.store(Cancelled);
    else if (state.load() == Captured || state.load() == Consumed) state.store(Stopped);
    SecureZeroMemory(data, sizeof(data)); length = 0;
    if (arrived) SetEvent(arrived);
    ReleaseSRWLockExclusive(&data_lock);
    if (enabled) { if (MH_DisableHook(target) != MH_OK) return 0; enabled = false; }
    const auto end = GetTickCount64() + 100;
    while (inflight.load() && GetTickCount64() < end) Sleep(1);
    // No production RemoveHook/FreeLibrary: zero alone does not prove no
    // thread is about to enter the detour. Retain trampoline until host exit.
    return inflight.load() == 0;
}

extern "C" __declspec(dllexport) EchoStatus EchoGetStatus() {
    return {state.load(), inflight.load(), static_cast<unsigned>(arrived || initialized || created)};
}

#ifdef ECHO_FIXTURE_BUILD
// Caller MUST have joined every fixture thread that can call the target, and
// hold exclusive ownership of the fixture call site. Not in production DLL.
extern "C" __declspec(dllexport) int EchoReleaseAfterHostJoined() {
    if (!owned() || enabled || inflight.load()) return 0;
    if (!rollback()) return 0;
    state.store(Released);
    return 1;
}
#endif
