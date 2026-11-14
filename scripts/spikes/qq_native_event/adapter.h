#pragma once
#include <windows.h>
#include <cstdint>

// Research-only in-process ABI; session transport lives in session.cpp.
constexpr unsigned EchoEventLimit = 8192;
enum EchoState : unsigned { Fresh, Armed, Captured, Consumed, Cancelled, Expired, Rejected, Stopped, Released };
struct EchoOptions { unsigned size, major, minor, patch, build, timeout_ms, fixture_fail_after_create; ULONGLONG not_after = 0; };
struct EchoEvent { unsigned size, length, state; unsigned char payload[EchoEventLimit]; };
struct EchoStatus { unsigned state, inflight, resources_retained, observation_disabled; };
using InstallFn = int (*)(const EchoOptions*);
using ReadFn = int (*)(EchoEvent*, unsigned);
using StopFn = int (*)();
using StatusFn = EchoStatus (*)();
using ReleaseFn = int (*)(); // Only the separately built fictional-host DLL exports this.
