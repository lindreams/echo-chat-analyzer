// Owned fictional native listener. Never loads QQ or a database.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "session.h"
#include <atomic>
#include <cstdio>
#include <cwchar>
#include <fcntl.h>
#include <io.h>
#include <thread>
#include <string>

namespace {
std::atomic<unsigned> calls{0};
std::atomic<bool> running{true}, joined{false};
std::thread producer;
void demand(bool ok) { if (!ok) ExitProcess(40); }
}
std::atomic<void*> forwarded{nullptr};
extern "C" __declspec(dllexport) __declspec(noinline) void EchoFixtureSuccess(void*, void* value) { forwarded.store(value); calls.fetch_add(1); SetLastError(731); }
extern "C" __declspec(dllexport) __declspec(noinline) void EchoFixtureState(void*, std::uint32_t) { calls.fetch_add(2); SetLastError(732); }
extern "C" __declspec(dllexport) __declspec(noinline) void EchoFixtureLogout(void*) { calls.fetch_add(3); SetLastError(733); }
extern "C" __declspec(dllexport) __declspec(noinline) void EchoFixtureDisconnected(void*) { calls.fetch_add(4); SetLastError(734); }
extern "C" __declspec(dllexport) __declspec(noinline) void EchoFixtureConnecting(void*) { calls.fetch_add(5); SetLastError(735); }
extern "C" __declspec(dllexport) __declspec(noinline) void EchoFixtureConnected(void*) { calls.fetch_add(6); SetLastError(736); }
namespace {
void* targets[] = {reinterpret_cast<void*>(EchoFixtureSuccess), reinterpret_cast<void*>(EchoFixtureState),
    reinterpret_cast<void*>(EchoFixtureLogout), reinterpret_cast<void*>(EchoFixtureDisconnected), reinterpret_cast<void*>(EchoFixtureConnecting), reinterpret_cast<void*>(EchoFixtureConnected)};
unsigned char before[6][32]{};
bool restored() { for (unsigned i=0; i<6; ++i) if (std::memcmp(before[i], targets[i], 32)) return false; return true; }
bool all_hooked() { for (unsigned i=0; i<6; ++i) if (!std::memcmp(before[i], targets[i], 32)) return false; return true; }
void* success_object = nullptr;
void success(void* self) {
    EchoFixtureSuccess(self, success_object);
    demand(GetLastError() == 731 && forwarded.load() == success_object);
}
void exercise(void* self) {
    EchoFixtureConnecting(self); demand(GetLastError() == 735);
    EchoFixtureConnected(self); demand(GetLastError() == 736);
    EchoFixtureState(self, 17); demand(GetLastError() == 732);
    success(self);
    EchoFixtureLogout(self); demand(GetLastError() == 733);
    EchoFixtureDisconnected(self); demand(GetLastError() == 734);
    success(self);
}
template<class F> F function(HMODULE module, const char* name) {
    auto value = GetProcAddress(module, name); demand(value != nullptr); return reinterpret_cast<F>(value);
}
}
extern "C" __declspec(dllexport) BOOL EchoFixtureJoin() {
    running.store(false);
    if (!producer.joinable()) return FALSE;
    producer.join(); if (!restored()) return FALSE;
    joined.store(true); return TRUE;
}
int wmain(int argc, wchar_t** argv) {
    demand(argc == 3);
    _setmode(_fileno(stdin), _O_BINARY); _setmode(_fileno(stdout), _O_BINARY);
    const std::wstring scenario = argv[2];
    for (unsigned i=0; i<6; ++i) std::memcpy(before[i], targets[i], 32);
    // Put +0x30..+0x37 immediately before a guard page to detect over-read.
    auto object_pages = static_cast<unsigned char*>(VirtualAlloc(nullptr, 12288, MEM_COMMIT|MEM_RESERVE, PAGE_NOACCESS));
    demand(object_pages != nullptr);
    DWORD old = 0; demand(VirtualProtect(object_pages+4096, 4096, PAGE_READWRITE, &old));
    auto uin = reinterpret_cast<std::uint64_t*>(object_pages+8192-8);
    *uin = 100000001;
    success_object = reinterpret_cast<void*>(reinterpret_cast<std::uintptr_t>(uin)-0x30);
    auto guard = VirtualAlloc(nullptr, 4096, MEM_COMMIT|MEM_RESERVE, PAGE_NOACCESS); demand(guard != nullptr);
    if (scenario.rfind(L"session-", 0) == 0) {
        const unsigned head[] = {SessionMagic, GetCurrentProcessId()}; const auto created = created_at(GetCurrentProcess());
        demand(std::fwrite(head, sizeof(head), 1, stdout) == 1 && std::fwrite(&created, 8, 1, stdout) == 1 && !std::fflush(stdout));
        producer = std::thread([&] {
            while (running.load() && !all_hooked()) Sleep(1);
            Sleep(60);
            if (running.load() && scenario == L"session-delivery") exercise(guard);
            while (running.load()) Sleep(1);
            for (unsigned i=0; i<128; ++i) success(guard);
        });
        const auto end = GetTickCount64()+10000;
        while (!joined.load() && GetTickCount64()<end) {
            DWORD available = 0;
            if (PeekNamedPipe(GetStdHandle(STD_INPUT_HANDLE), nullptr, 0, nullptr, &available, nullptr) && available) {
                demand(EchoFixtureJoin()); break;
            }
            Sleep(2);
        }
        demand(joined.load());
        while (GetModuleHandleW(L"echo_event_fixture.dll") && GetTickCount64()<end) Sleep(1);
        demand(!GetModuleHandleW(L"echo_event_fixture.dll") && restored());
    } else {
        auto library = LoadLibraryExW(argv[1], nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32); demand(library != nullptr);
        auto install = function<InstallFn>(library, "EchoInstall"); auto read = function<ReadFn>(library, "EchoRead");
        auto stop = function<StopFn>(library, "EchoStop"); auto status = function<StatusFn>(library, "EchoGetStatus");
        auto release = reinterpret_cast<ReleaseFn>(GetProcAddress(library, "EchoReleaseAfterHostJoined"));
        EchoOptions options{sizeof(EchoOptions), 9, 9, 37, 54395, 1000u,
            scenario == L"install_failure" ? 1u : 0u};
        bool refused = scenario == L"production_gate" || scenario == L"install_failure";
        demand((install(&options) == 1) != refused);
        EchoEvent item{}; item.size = sizeof(item);
        if (!refused) {
            if (scenario == L"timeout") Sleep(options.timeout_ms+1);
            if (scenario == L"delivery") exercise(guard);
            if (scenario == L"conflict") { success(guard); EchoFixtureLogout(static_cast<unsigned char*>(guard)+1); }
            const bool bad_object = scenario.rfind(L"object_", 0) == 0;
            if (bad_object) {
                if (scenario == L"object_null") success_object = nullptr;
                if (scenario == L"object_unreadable") success_object = guard;
                if (scenario == L"object_zero") *uin = 0;
                if (scenario == L"object_partial") success_object = static_cast<unsigned char*>(success_object)+4;
                success(guard);
            }
            if (scenario == L"overflow") for (unsigned i=0; i<65; ++i) EchoFixtureState(guard, i);
            if (scenario == L"cancel") demand(stop() == 1);
            unsigned count = 0;
            while (read(&item, 30)) {
                demand(item.length == 32); unsigned fields[4]; std::memcpy(fields, item.payload, 16);
                demand(fields[0] == 0x314c5145 && fields[1] == 1);
                if (scenario == L"delivery") demand(fields[2] == ++count);
                else {
                    std::uint64_t reason = 0; std::memcpy(&reason, item.payload+16, 8);
                    demand(fields[3] == 0 && fields[2] == 1 &&
                        ((scenario == L"conflict" && reason == 2) || (scenario == L"overflow" && reason == 3) ||
                         (bad_object && reason == (scenario == L"object_zero" ? 5 : 1))));
                    ++count;
                }
                if (item.state != Armed) break;
            }
            demand(scenario != L"delivery" || count == 7);
            demand(!bad_object || count == 1);
            demand(scenario != L"timeout" || item.state == Expired);
            demand(stop() == 1 && status().observation_disabled && status().inflight == 0);
            demand(!read(&item, 0) && restored());
        }
        if (release) demand(release() == 1 && !status().resources_retained);
        else demand(refused && !status().resources_retained);
        demand(FreeLibrary(library) && restored()); SecureZeroMemory(&item, sizeof(item));
    }
    demand(VirtualFree(guard, 0, MEM_RELEASE));
    demand(VirtualFree(object_pages, 0, MEM_RELEASE));
    const unsigned finish[] = {SessionMagic, 1, 1, 0};
    demand(std::fwrite(finish, sizeof(finish), 1, stdout) == 1 && !std::fflush(stdout));
    return 0;
}
