// Owned fictional executable. It loads an adapter into ITSELF, never QQ.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "adapter.h"
#include "session.h"
#include <atomic>
#include <cstdio>
#include <cstring>
#include <cstddef>
#include <fcntl.h>
#include <io.h>
#include <thread>
#include <string>
#include <vector>

namespace {
std::atomic<unsigned> calls{0};
std::atomic<bool> session_running{true}, session_joined{false};
std::thread session_producer;
unsigned char session_before[32]{};
struct Work { HANDLE entered, resume; bool block; };
struct String24 { unsigned char bytes[24]{}; };
struct Vector { std::uintptr_t begin, end, capacity; };
struct Response { unsigned char opaque[32]{}; String24 command; Vector* payload = nullptr; };
static_assert(offsetof(Response, command) == 32 && offsetof(Response, payload) == 56);
void demand(bool ok) { if (!ok) ExitProcess(40); } // No raw assertion/exception text.
String24 text(const char* value) {
    String24 result{};
    const auto n = std::strlen(value);
    if (n <= 22) { result.bytes[0] = static_cast<unsigned char>(n * 2); std::memcpy(result.bytes + 1, value, n); }
    else { const std::uint64_t words[] = {((n + 8) | 1), n, reinterpret_cast<std::uintptr_t>(value)}; std::memcpy(result.bytes, words, 24); }
    return result;
}
template<class F> F load(HMODULE library, const char* name) {
    auto function = GetProcAddress(library, name); demand(function != nullptr); return reinterpret_cast<F>(function);
}
}

extern "C" __declspec(dllexport) __declspec(noinline) std::int64_t EchoFixtureReceive(void* context, void** object, std::uint32_t error) {
    auto work = static_cast<Work*>(context);
    calls.fetch_add(1);
    if (work && work->block) { SetEvent(work->entered); WaitForSingleObject(work->resume, 3000); }
    // The host deliberately need not dereference callback payload. This lets a
    // guard-page vector prove that unrelated payload is never read by adapter.
    if (object && *object && error == 0xeeee) RaiseException(0xe0420001, 0, 0, nullptr);
    SetLastError(731);
    return 0x12340000 + error;
}

bool original_exception(void** response) {
    __try { EchoFixtureReceive(nullptr, response, 0xeeee); }
    __except (GetExceptionCode() == 0xe0420001 ? EXCEPTION_EXECUTE_HANDLER : EXCEPTION_CONTINUE_SEARCH) { return true; }
    return false;
}

// Fixture-only proof of exclusive call-site ownership. Production DLL never
// requests or accepts this export. Stop is already complete before this join.
extern "C" __declspec(dllexport) BOOL EchoFixtureJoin() {
    session_running.store(false);
    if (!session_producer.joinable()) return FALSE;
    session_producer.join();
    if (std::memcmp(session_before, reinterpret_cast<void*>(EchoFixtureReceive), 32)) return FALSE;
    session_joined.store(true); return TRUE;
}

int session_host(const std::wstring& scenario) {
    _setmode(_fileno(stdin), _O_BINARY); _setmode(_fileno(stdout), _O_BINARY);
    unsigned n = 0;
    demand(std::fread(&n, sizeof(n), 1, stdin) == 1 && n && n <= EchoEventLimit);
    std::vector<unsigned char> input(n);
    demand(std::fread(input.data(), 1, n, stdin) == n);
    std::memcpy(session_before, reinterpret_cast<void*>(EchoFixtureReceive), 32);
    const unsigned header[] = {SessionMagic, GetCurrentProcessId()};
    const auto creation = created_at(GetCurrentProcess());
    demand(std::fwrite(header, sizeof(header), 1, stdout) == 1 && std::fwrite(&creation, sizeof(creation), 1, stdout) == 1 && !std::fflush(stdout));
    std::atomic<unsigned> after_stop{0};
    session_producer = std::thread([&] {
        Vector bytes{reinterpret_cast<std::uintptr_t>(input.data()), reinterpret_cast<std::uintptr_t>(input.data()+n), reinterpret_cast<std::uintptr_t>(input.data()+n)};
        Response target{}, other{};
        target.command = text("OidbSvcTrpcTcp.0xcde_2"); target.payload = &bytes;
        other.command = text("fixture.unrelated"); other.payload = nullptr;
        void* a = &target; void* b = &other;
        // Wait for the actual load/install, not for a mocked callback.
        while (session_running.load() && !std::memcmp(session_before, reinterpret_cast<void*>(EchoFixtureReceive), 32)) Sleep(1);
        if (session_running.load()) {
            Sleep(60);
            if (scenario == L"session-host_exit") ExitProcess(45);
            if (scenario == L"session-delivery" || scenario == L"session-auth_refused" || scenario == L"session-parse_refused") EchoFixtureReceive(nullptr, &a, 0);
            while (session_running.load()) { EchoFixtureReceive(nullptr, &b, 0); Sleep(1); }
        }
        // Continue producing real target callbacks AFTER the hook is disabled.
        // Bootstrap must see an empty slot and must not send another response.
        for (unsigned i = 0; i < 128; ++i) { EchoFixtureReceive(nullptr, &a, 0); after_stop.fetch_add(1); }
    });
    const auto end = GetTickCount64()+15000;
    while (!session_joined.load() && GetTickCount64() < end) {
        DWORD available = 0;
        if (PeekNamedPipe(GetStdHandle(STD_INPUT_HANDLE), nullptr, 0, nullptr, &available, nullptr) && available) {
            // Owned test harness can release a host whose loader refused before installation.
            demand(EchoFixtureJoin()); break;
        }
        Sleep(2);
    }
    demand(session_joined.load());
    while (GetModuleHandleW(L"echo_event_fixture.dll") && GetTickCount64() < end) Sleep(2);
    demand(!GetModuleHandleW(L"echo_event_fixture.dll") && after_stop.load() == 128);
    demand(!std::memcmp(session_before, reinterpret_cast<void*>(EchoFixtureReceive), 32));
    const unsigned prior = calls.load(); void* object = nullptr;
    demand(EchoFixtureReceive(nullptr, &object, 0) == 0x12340000 && calls.load() == prior+1);
    SecureZeroMemory(input.data(), input.size());
    const unsigned finish[] = {SessionMagic, 1, 1, 128};
    demand(std::fwrite(finish, sizeof(finish), 1, stdout) == 1 && !std::fflush(stdout));
    return 0;
}

int wmain(int argc, wchar_t** argv) {
    if (argc == 2 && !std::wcsncmp(argv[1], L"session-", 8)) return session_host(argv[1]);
    demand(argc == 3);
    _setmode(_fileno(stdin), _O_BINARY); _setmode(_fileno(stdout), _O_BINARY);
    const std::wstring scenario = argv[2];
    unsigned count = 0;
    demand(std::fread(&count, sizeof(count), 1, stdin) == 1 && count && count <= EchoEventLimit);
    std::vector<unsigned char> input(count);
    demand(std::fread(input.data(), 1, count, stdin) == count);
    unsigned char before[32]; std::memcpy(before, reinterpret_cast<void*>(EchoFixtureReceive), 32);
    const auto library = LoadLibraryExW(argv[1], nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    demand(library != nullptr);
    const auto install = load<InstallFn>(library, "EchoInstall");
    const auto read = load<ReadFn>(library, "EchoRead");
    const auto stop = load<StopFn>(library, "EchoStop");
    const auto status = load<StatusFn>(library, "EchoGetStatus");
    auto release = reinterpret_cast<ReleaseFn>(GetProcAddress(library, "EchoReleaseAfterHostJoined"));
    EchoOptions options{sizeof(EchoOptions), 9, 9, 37, 54395, scenario == L"timeout" ? 30u : 1500u,
                        scenario == L"install_failure" ? 1u : 0u};
    if (scenario == L"wrong_version") options.build = 54394;
    const bool rejected = scenario == L"install_failure" || scenario == L"wrong_version" || scenario == L"production_gate";
    demand((install(&options) == 1) != rejected);
    if (scenario == L"production_gate") demand(release == nullptr);
    else demand(release != nullptr);
    Vector vector{reinterpret_cast<std::uintptr_t>(input.data()), reinterpret_cast<std::uintptr_t>(input.data() + input.size()),
                  reinterpret_cast<std::uintptr_t>(input.data() + input.size())};
    Response target{}, unrelated{};
    target.command = text("OidbSvcTrpcTcp.0xcde_2"); target.payload = &vector;
    if (scenario == L"heap_delivery") {
        constexpr char name[] = "OidbSvcTrpcTcp.0xcde_2";
        // libc++ may retain a heap allocation for a short logical string.
        static const char heap_name[] = "OidbSvcTrpcTcp.0xcde_2";
        const std::uint64_t words[] = {65, sizeof(name)-1, reinterpret_cast<std::uintptr_t>(heap_name)};
        std::memcpy(target.command.bytes, words, 24);
    }
    unrelated.command = text("fixture.unrelated");
    auto guard = VirtualAlloc(nullptr, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_NOACCESS);
    demand(guard != nullptr); unrelated.payload = static_cast<Vector*>(guard);
    void* target_owner = &target; void* other_owner = &unrelated;
    Work work{CreateEventW(nullptr, TRUE, FALSE, nullptr), CreateEventW(nullptr, TRUE, FALSE, nullptr), scenario == L"busy_stop"};
    demand(work.entered && work.resume);
    std::atomic<bool> running{true};
    std::thread worker;
    EchoEvent event{}; event.size = sizeof(event);
    unsigned observed_state = Rejected;
    bool busy_refused = false;
    if (!rejected) {
        worker = std::thread([&] {
            if (scenario == L"busy_stop") {
                EchoFixtureReceive(&work, &other_owner, 0);
                return;
            }
            // Both metadata paths run through the actual machine-code detour.
            EchoFixtureReceive(nullptr, &other_owner, 0);
            if (scenario == L"delivery" || scenario == L"heap_delivery" || scenario == L"invalid_layout") {
                if (scenario == L"invalid_layout") target.payload = static_cast<Vector*>(guard);
                EchoFixtureReceive(nullptr, &target_owner, 0);
            }
            while (running.load()) { EchoFixtureReceive(nullptr, &other_owner, 0); Sleep(1); }
        });
        if (scenario == L"cancel") {
            demand(stop() == 1); demand(read(&event, 0) == 0);
            observed_state = status().state; demand(observed_state == Cancelled);
        } else if (scenario == L"busy_stop") {
            demand(WaitForSingleObject(work.entered, 1000) == WAIT_OBJECT_0);
            demand(stop() == 0 && release() == 0 && status().inflight > 0);
            busy_refused = true; observed_state = status().state;
            SetEvent(work.resume);
        } else {
            const bool delivered = read(&event, 1000) == 1;
            demand(delivered == (scenario == L"delivery" || scenario == L"heap_delivery"));
            observed_state = event.state;
            if (delivered) demand(event.length == input.size() && !std::memcmp(event.payload, input.data(), input.size()));
            if (scenario == L"timeout") demand(observed_state == Expired);
            if (scenario == L"invalid_layout") demand(observed_state == Rejected);
        }
        running.store(false); worker.join();
        // An original exception propagates and detour's finally drains inflight.
        demand(original_exception(&other_owner) && status().inflight == 0);
        demand(stop() == 1);
    }
    demand(std::memcmp(before, reinterpret_cast<void*>(EchoFixtureReceive), 32) == 0);
    if (release) demand(release() == 1 && status().resources_retained == 0 && status().state == Released);
    else demand(status().resources_retained == 0); // Production gate refused before any hook/handle allocation.
    demand(FreeLibrary(library) != 0);
    HMODULE still_loaded = nullptr;
    demand(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, argv[1], &still_loaded));
    const auto prior_calls = calls.load();
    demand(EchoFixtureReceive(nullptr, &other_owner, 3) == 0x12340003 && GetLastError() == 731 && calls.load() == prior_calls + 1);
    demand(CloseHandle(work.entered) && CloseHandle(work.resume) && VirtualFree(guard, 0, MEM_RELEASE));
    // Binary anonymous stdout is a private fictional transport, not a log.
    const unsigned header[] = {0x314e5145, event.length, observed_state, busy_refused ? 1u : 0u};
    demand(std::fwrite(header, sizeof(header), 1, stdout) == 1);
    if (event.length) demand(std::fwrite(event.payload, 1, event.length, stdout) == event.length);
    SecureZeroMemory(event.payload, sizeof(event.payload)); SecureZeroMemory(input.data(), input.size());
    return std::fflush(stdout) == 0 ? 0 : 41;
}
