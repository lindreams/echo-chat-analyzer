// Research profile only. Reuses the existing hash gate, MinHook, owner thread,
// private transport and stop/retained-trampoline contract. No protocol payload.
struct LoginPoint { unsigned begin, end; unsigned char prefix[32]; const char* hash; const char* fixture; };
#include "login_lifecycle_points.h"
constexpr unsigned LoginLimit = 64, LoginMagic = 0x314c5145;
constexpr unsigned LoginPointCount = sizeof(login_points)/sizeof(login_points[0]);
struct LoginRecord { unsigned magic, version, sequence, kind; std::uint64_t value, tick; };
static_assert(sizeof(LoginRecord) == 32);
LoginRecord records[LoginLimit]{};
unsigned written = 0, consumed = 0;
void* listener = nullptr;
void* login_targets[LoginPointCount]{};
void* login_originals[LoginPointCount]{};
bool login_created[LoginPointCount]{}, login_enabled[LoginPointCount]{};
std::atomic<unsigned> login_failure{0};
bool failure_reported = false;

void fail_login(unsigned reason) {
    unsigned empty = 0; login_failure.compare_exchange_strong(empty, reason);
    state.store(Rejected); if (arrived) SetEvent(arrived);
}
void capture_login(unsigned kind, void* self, std::uint64_t value, const void* success = nullptr) {
    if (state.load() != Armed) return;
    if (!TryAcquireSRWLockExclusive(&data_lock)) { fail_login(4); return; }
    __try {
        if (state.load() != Armed) __leave;
        if (GetTickCount64() >= deadline) { state.store(Expired); SetEvent(arrived); __leave; }
        __try {
            if (!self) { fail_login(1); __leave; }
#ifndef ECHO_FIXTURE_BUILD
            // Confirm native listener role at the actual callback, not by a
            // numeric account or an arbitrary source pointer supplied by GUI.
            auto base = reinterpret_cast<unsigned char*>(GetModuleHandleW(L"wrapper.node"));
            if (*static_cast<void**>(self) != base+0x4436218) { fail_login(1); __leave; }
#endif
            if (listener && listener != self) { fail_login(2); __leave; }
            listener = self;
            if (written == LoginLimit) { fail_login(3); __leave; }
            // Object ABI, not the old User scalar. Read exactly eight bytes;
            // no account/uid/nickname, strings or object copy. SEH fails closed.
            if (kind == 1) {
                if (!success) { fail_login(1); __leave; }
                value = *reinterpret_cast<const volatile std::uint64_t*>(
                    static_cast<const unsigned char*>(success)+0x30);
            }
            if (kind == 1 && !value) { fail_login(5); __leave; }
            records[written] = {LoginMagic, 1, written+1, kind, value, GetTickCount64()};
            ++written; SetEvent(arrived);
        } __except (EXCEPTION_EXECUTE_HANDLER) { fail_login(1); }
    } __finally { ReleaseSRWLockExclusive(&data_lock); }
}

void login_success(void* self, void* value) {
    const auto error = GetLastError(); inflight.fetch_add(1);
    capture_login(1, self, 0, value); SetLastError(error);
    __try { reinterpret_cast<void (*)(void*, void*)>(login_originals[0])(self, value); }
    __finally { inflight.fetch_sub(1); }
}
template<unsigned Index, typename Value> void login_value(void* self, Value value) {
    const auto error = GetLastError(); inflight.fetch_add(1);
    capture_login(Index+1, self, value); SetLastError(error);
    __try { reinterpret_cast<void (*)(void*, Value)>(login_originals[Index])(self, value); }
    __finally { inflight.fetch_sub(1); }
}
template<unsigned Index> void login_empty(void* self) {
    const auto error = GetLastError(); inflight.fetch_add(1);
    capture_login(Index+1, self, 0); SetLastError(error);
    __try { reinterpret_cast<void (*)(void*)>(login_originals[Index])(self); }
    __finally { inflight.fetch_sub(1); }
}

bool login_code_hash(const unsigned char* bytes, unsigned size, const char* expected) {
    BCRYPT_ALG_HANDLE algorithm = nullptr; BCRYPT_HASH_HANDLE hash = nullptr;
    unsigned char digest[32]{};
    bool ok = BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0 &&
        BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0 &&
        BCryptHashData(hash, const_cast<PUCHAR>(bytes), size, 0) >= 0 &&
        BCryptFinishHash(hash, digest, 32, 0) >= 0;
    constexpr char digits[] = "0123456789abcdef";
    for (unsigned i=0; ok && i<32; ++i)
        ok = digits[digest[i]>>4] == expected[2*i] && digits[digest[i]&15] == expected[2*i+1];
    if (hash) BCryptDestroyHash(hash); if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    return ok;
}
bool select_login_targets() {
#ifdef ECHO_FIXTURE_BUILD
    const auto module = GetModuleHandleW(nullptr);
    if (!file_hash(module, echo_fixture_hash)) return false;
    for (unsigned i=0; i<LoginPointCount; ++i) {
        login_targets[i] = reinterpret_cast<void*>(GetProcAddress(module, login_points[i].fixture));
        if (!login_targets[i]) return false;
    }
#else
    const auto module = GetModuleHandleW(L"wrapper.node");
    if (!module || !file_hash(module, qq_hash)) return false;
    const auto base = reinterpret_cast<unsigned char*>(module);
    for (unsigned i=0; i<LoginPointCount; ++i) {
        const auto& p = login_points[i]; DWORD64 image = 0;
        auto address = base+p.begin;
        auto unwind = RtlLookupFunctionEntry(reinterpret_cast<DWORD64>(address), &image, nullptr);
        if (!unwind || image != reinterpret_cast<DWORD64>(module) || unwind->BeginAddress != p.begin ||
            unwind->EndAddress != p.end || std::memcmp(address, p.prefix, 32) ||
            !login_code_hash(address, p.end-p.begin, p.hash)) return false;
        login_targets[i] = address;
    }
#endif
    return true;
}
bool disable_login_hooks() {
    bool ok = true;
    for (unsigned i=0; i<LoginPointCount; ++i) if (login_enabled[i]) {
        if (MH_DisableHook(login_targets[i]) == MH_OK) login_enabled[i] = false;
        else ok = false;
    }
    return ok;
}
bool remove_login_hooks() { // Only never-enabled install or joined fictional host.
    if (!disable_login_hooks() || inflight.load()) return false;
    for (unsigned i=0; i<LoginPointCount; ++i) if (login_created[i]) {
        if (MH_RemoveHook(login_targets[i]) != MH_OK) return false;
        login_created[i] = false;
    }
    if (initialized) { if (MH_Uninitialize() != MH_OK) return false; initialized = false; }
    if (arrived) { CloseHandle(arrived); arrived = nullptr; }
    return true;
}
} // namespace

extern "C" __declspec(dllexport) int EchoInstall(const EchoOptions* options) {
    if (attempted.exchange(true)) return 0;
    owner = GetCurrentThreadId(); state.store(Rejected);
    if (!options || options->size != sizeof(EchoOptions) || options->major != 9 || options->minor != 9 ||
        options->patch != 37 || options->build != 54395 || !options->timeout_ms || options->timeout_ms > 120000) return 0;
#ifndef ECHO_FIXTURE_BUILD
    if (options->fixture_fail_after_create) return 0;
#endif
    if (!select_login_targets()) return 0;
    arrived = CreateEventW(nullptr, TRUE, FALSE, nullptr); if (!arrived) return 0;
    initialized = MH_Initialize() == MH_OK;
    if (!initialized) { CloseHandle(arrived); arrived = nullptr; return 0; }
    void* detours[] = {reinterpret_cast<void*>(login_success),
        reinterpret_cast<void*>(login_value<1, std::uint32_t>), reinterpret_cast<void*>(login_empty<2>),
        reinterpret_cast<void*>(login_empty<3>), reinterpret_cast<void*>(login_empty<4>),
        reinterpret_cast<void*>(login_empty<5>)};
    static_assert(sizeof(detours)/sizeof(detours[0]) == LoginPointCount);
    for (unsigned i=0; i<LoginPointCount; ++i) {
        login_created[i] = MH_CreateHook(login_targets[i], detours[i], &login_originals[i]) == MH_OK;
        if (!login_created[i] || options->fixture_fail_after_create) { remove_login_hooks(); return 0; }
    }
    deadline = GetTickCount64()+options->timeout_ms;
    if (options->not_after && options->not_after < deadline) deadline = options->not_after;
    if (GetTickCount64() >= deadline) { remove_login_hooks(); return 0; }
    for (unsigned i=0; i<LoginPointCount; ++i) {
        login_enabled[i] = MH_EnableHook(login_targets[i]) == MH_OK;
        if (!login_enabled[i]) {
            // Some hooks may have run. Disable, retain trampoline/DLL until
            // normal exit; never remove live call sites after partial enable.
            state.store(Rejected); disable_login_hooks(); return 0;
        }
    }
    if (GetTickCount64() >= deadline) { disable_login_hooks(); return 0; }
    // Every observation point must be active before Ready can be emitted.
    state.store(Armed);
    return 1;
}
extern "C" __declspec(dllexport) int EchoRead(EchoEvent* result, unsigned wait_ms) {
    if (!owned() || !result || result->size != sizeof(EchoEvent) || wait_ms > 2000 || !arrived) return 0;
    const auto now = GetTickCount64();
    const auto remaining = now < deadline ? deadline-now : 0;
    WaitForSingleObject(arrived, static_cast<DWORD>(remaining < wait_ms ? remaining : wait_ms));
    AcquireSRWLockExclusive(&data_lock);
    result->length = 0;
    if (state.load() == Armed && GetTickCount64() >= deadline) state.store(Expired);
    LoginRecord item{};
    if (login_failure.load() && !failure_reported) {
        failure_reported = true; item = {LoginMagic, 1, consumed+1, 0, login_failure.load(), GetTickCount64()};
    } else if (state.load() == Armed && consumed < written) {
        item = records[consumed]; SecureZeroMemory(&records[consumed], sizeof(item)); ++consumed;
    }
    if (item.magic) { std::memcpy(result->payload, &item, sizeof(item)); result->length = sizeof(item); }
    if (consumed == written) ResetEvent(arrived);
    result->state = state.load(); SecureZeroMemory(&item, sizeof(item));
    ReleaseSRWLockExclusive(&data_lock); return result->length != 0;
}
extern "C" __declspec(dllexport) int EchoStop() {
    if (!owned()) return 0;
    AcquireSRWLockExclusive(&data_lock);
    if (state.load() == Armed) state.store(Stopped);
    SecureZeroMemory(records, sizeof(records)); listener = nullptr; consumed = written;
    if (arrived) SetEvent(arrived);
    ReleaseSRWLockExclusive(&data_lock);
    const bool disabled = disable_login_hooks();
    const auto end = GetTickCount64()+100;
    while (inflight.load() && GetTickCount64()<end) Sleep(1);
    return disabled && !inflight.load();
}
extern "C" __declspec(dllexport) EchoStatus EchoGetStatus() {
    bool any = false; for (bool value : login_enabled) any = any || value;
    return {state.load(), inflight.load(), static_cast<unsigned>(arrived || initialized), !any};
}
#ifdef ECHO_FIXTURE_BUILD
extern "C" __declspec(dllexport) int EchoReleaseAfterHostJoined() {
    if (!owned() || inflight.load() || !remove_login_hooks()) return 0;
    state.store(Released); return 1;
}
#endif
