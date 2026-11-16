// Echo-owned research implementation, included ONLY with ECHO_IDENTITY_METADATA.
// The field offsets are hypotheses until independently verified at runtime.
// No request/response payload pointer, vector, bytes, key parser or DB is read.
void inspect_identity(void** owner_ptr) {
    __try {
        if (!owner_ptr || !*owner_ptr) return;
        auto packet = static_cast<unsigned char*>(*owner_ptr);
        auto request = *reinterpret_cast<unsigned char**>(packet);
        if (!request) return;
        std::uint64_t words[3]; std::memcpy(words, request, sizeof(words));
        const bool heap = (words[0]&1) != 0;
        const auto n = heap ? words[1] : (words[0]&255)>>1;
        if (n != sizeof(command)-1 || (!heap && n > 22) || (heap && (words[0]&~1ull) < n)) return;
        auto name = heap ? reinterpret_cast<const void*>(words[2]) : request+1;
        if (std::memcmp(name, command, sizeof(command)-1)) return;
        if (!TryAcquireSRWLockExclusive(&data_lock)) return;
        __try {
            if (state.load() != Armed) __leave;
            if (GetTickCount64() >= deadline) { state.store(Expired); SetEvent(arrived); __leave; }
            // Fixed private wire record: magic, version, raw type, length, ASCII[20].
            // Raw type has no assumed UID/UIN meaning in this observer.
            std::uint32_t header[4] = {0x31444945, 1, 0, 0};
            std::memcpy(&header[2], packet+80, 4);
            std::memcpy(words, packet+56, sizeof(words));
            const bool account_heap = (words[0]&1) != 0;
            const auto count = account_heap ? words[1] : (words[0]&255)>>1;
            if (!count || count > 20 || (account_heap && (words[0]&~1ull) < count)) {
                state.store(Rejected); SetEvent(arrived); __leave;
            }
            auto account = account_heap ? reinterpret_cast<const unsigned char*>(words[2]) : packet+57;
            if (account[0] == '0') { state.store(Rejected); SetEvent(arrived); __leave; }
            for (unsigned i = 0; i < count; ++i) {
                if (account[i] < '0' || account[i] > '9') { state.store(Rejected); SetEvent(arrived); __leave; }
            }
            header[3] = static_cast<unsigned>(count);
            std::memcpy(data, header, sizeof(header));
            std::memcpy(data+sizeof(header), account, static_cast<size_t>(count));
            length = 36; // Remaining bytes were initialized/cleared to zero.
            state.store(Captured); SetEvent(arrived);
        } __finally { ReleaseSRWLockExclusive(&data_lock); }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        AcquireSRWLockExclusive(&data_lock);
        SecureZeroMemory(data, sizeof(data)); length = 0;
        state.store(Rejected); SetEvent(arrived);
        ReleaseSRWLockExclusive(&data_lock);
    }
}
