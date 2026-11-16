// Echo-owned fictional send-task host. No QQ module, account or DB is accessed.
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

namespace {
struct String24 { unsigned char bytes[24]{}; };
struct Request { String24 command; unsigned char padding[8]{}; void* unread_payload; };
struct Task { Request* request; unsigned char padding[48]{}; String24 account; unsigned type; };
static_assert(offsetof(Task, account) == 56 && offsetof(Task, type) == 80 && offsetof(Request, unread_payload) == 32);
std::atomic<unsigned> calls{0}, after_stop{0};
std::atomic<bool> running{true}, joined{false};
std::thread producer;
unsigned char before[32]{};
void demand(bool ok) { if (!ok) ExitProcess(40); }
String24 text(const char* value, bool heap = false) {
    String24 result{}; const auto n = std::strlen(value);
    if (!heap && n <= 22) { result.bytes[0] = static_cast<unsigned char>(n*2); std::memcpy(result.bytes+1, value, n); }
    else { const std::uint64_t w[] = {(n+8)|1, n, reinterpret_cast<std::uintptr_t>(value)}; std::memcpy(result.bytes, w, 24); }
    return result;
}
template<class F> F function(HMODULE library, const char* name) {
    auto value = GetProcAddress(library, name); demand(value != nullptr); return reinterpret_cast<F>(value);
}
}

extern "C" __declspec(dllexport) __declspec(noinline) std::int64_t EchoFixtureReceive(void*, void**) {
    calls.fetch_add(1); SetLastError(731); return 0x12340000;
}
extern "C" __declspec(dllexport) BOOL EchoFixtureJoin() {
    running.store(false);
    if (!producer.joinable()) return FALSE;
    producer.join();
    if (std::memcmp(before, reinterpret_cast<void*>(EchoFixtureReceive), 32)) return FALSE;
    joined.store(true); return TRUE;
}

int wmain(int argc, wchar_t** argv) {
    demand(argc == 3);
    _setmode(_fileno(stdin), _O_BINARY); _setmode(_fileno(stdout), _O_BINARY);
    const std::wstring scenario = argv[2];
    const bool session = scenario.rfind(L"session-", 0) == 0;
    auto guard = VirtualAlloc(nullptr, 4096, MEM_COMMIT|MEM_RESERVE, PAGE_NOACCESS);
    demand(guard != nullptr);
    // Both matching and nonmatching tasks point at unreadable payload storage.
    Request request{text("OidbSvcTrpcTcp.0xcde_2", scenario == L"heap"), {}, guard};
    Request other{text("fixture.other"), {}, guard};
    Task task{&request, {}, text(scenario == L"invalid" ? "u_not_numeric" : "100000001", scenario == L"heap"), 1};
    Task unrelated{&other, {}, {}, 99};
    void* a = &task; void* b = &unrelated;
    std::memcpy(before, reinterpret_cast<void*>(EchoFixtureReceive), 32);
    if (session) {
        const unsigned header[] = {SessionMagic, GetCurrentProcessId()};
        const auto creation = created_at(GetCurrentProcess());
        demand(std::fwrite(header, sizeof(header), 1, stdout) == 1 && std::fwrite(&creation, 8, 1, stdout) == 1 && !std::fflush(stdout));
        producer = std::thread([&] {
            while (running.load() && !std::memcmp(before, reinterpret_cast<void*>(EchoFixtureReceive), 32)) Sleep(1);
            if (running.load()) {
                Sleep(60);
                EchoFixtureReceive(nullptr, &b);
                if (scenario == L"session-delivery") EchoFixtureReceive(nullptr, &a);
                while (running.load()) { EchoFixtureReceive(nullptr, &b); Sleep(1); }
            }
            for (unsigned i=0; i<128; ++i) { EchoFixtureReceive(nullptr, &a); after_stop.fetch_add(1); }
        });
        const auto end = GetTickCount64()+10000;
        while (!joined.load() && GetTickCount64() < end) {
            DWORD available = 0;
            if (PeekNamedPipe(GetStdHandle(STD_INPUT_HANDLE), nullptr, 0, nullptr, &available, nullptr) && available) {
                demand(EchoFixtureJoin()); break;
            }
            Sleep(2);
        }
        demand(joined.load());
        while (GetModuleHandleW(L"echo_event_fixture.dll") && GetTickCount64() < end) Sleep(2);
        demand(!GetModuleHandleW(L"echo_event_fixture.dll") && after_stop.load() == 128);
        demand(!std::memcmp(before, reinterpret_cast<void*>(EchoFixtureReceive), 32));
        const unsigned finish[] = {SessionMagic, 1, 1, 128};
        demand(std::fwrite(finish, sizeof(finish), 1, stdout) == 1 && !std::fflush(stdout));
    } else {
        const auto library = LoadLibraryExW(argv[1], nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
        demand(library != nullptr);
        const auto install = function<InstallFn>(library, "EchoInstall");
        const auto read = function<ReadFn>(library, "EchoRead");
        const auto stop = function<StopFn>(library, "EchoStop");
        const auto status = function<StatusFn>(library, "EchoGetStatus");
        const auto release = reinterpret_cast<ReleaseFn>(GetProcAddress(library, "EchoReleaseAfterHostJoined"));
        EchoOptions options{sizeof(EchoOptions), 9, 9, 37, 54395, scenario == L"timeout" ? 30u : 1000u,
            scenario == L"install_failure" ? 1u : 0u};
        const bool refused = scenario == L"install_failure" || scenario == L"production_gate";
        demand((install(&options) == 1) != refused);
        EchoEvent event{}; event.size = sizeof(event);
        if (!refused) {
            // Exercise actual ABI, original return and last-error propagation.
            demand(EchoFixtureReceive(nullptr, &b) == 0x12340000 && GetLastError() == 731);
            if (scenario == L"delivery" || scenario == L"heap" || scenario == L"invalid") EchoFixtureReceive(nullptr, &a);
            if (scenario == L"cancel") demand(stop() == 1);
            const bool delivered = read(&event, 100) == 1;
            demand(delivered == (scenario == L"delivery" || scenario == L"heap"));
            if (delivered) {
                const unsigned expected[] = {0x31444945, 1, 1, 9};
                demand(event.length == 36 && !std::memcmp(event.payload, expected, 16) &&
                    !std::memcmp(event.payload+16, "100000001", 9));
            }
            if (scenario == L"invalid") demand(event.state == Rejected);
            if (scenario == L"timeout") demand(event.state == Expired);
            if (scenario == L"cancel") demand(event.state == Cancelled);
            demand(stop() == 1 && status().observation_disabled && status().inflight == 0);
            demand(!read(&event, 0) && status().state != Captured);
        }
        if (release) demand(release() == 1 && status().resources_retained == 0);
        else demand(refused && status().resources_retained == 0);
        demand(FreeLibrary(library) && !GetModuleHandleW(argv[1]));
        demand(!std::memcmp(before, reinterpret_cast<void*>(EchoFixtureReceive), 32));
        demand(EchoFixtureReceive(nullptr, &a) == 0x12340000 && GetLastError() == 731);
        SecureZeroMemory(&event, sizeof(event));
        const unsigned finish[] = {SessionMagic, 1, 1, 0};
        demand(std::fwrite(finish, sizeof(finish), 1, stdout) == 1 && !std::fflush(stdout));
    }
    SecureZeroMemory(&task, sizeof(task));
    demand(VirtualFree(guard, 0, MEM_RELEASE));
    return 0;
}
