// Research-only SQLCipher reference. Never use with account databases.
// Compile against the pinned official WCDB headers and verified WCDB.dll.
// One controlled SQL statement per input line; output cells are hex UTF-8.
#include <iostream>
#include <string>
#include "CommonCore.hpp"
#include "InnerDatabase.hpp"
#include "InnerHandle.hpp"
#include "Path.hpp"
#include "RecyclableHandle.hpp"

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    auto database = WCDB::CommonCore::shared().getOrCreateDatabase(
        WCDB::Path::normalize(WCDB::UnsafeStringView(argv[1])));
    auto recyclable = database.get()->getHandle(false, false);
    auto* handle = recyclable.get();
    if (!handle) return 3;
    std::string sql;
    int statement = 0;
    const char* digits = "0123456789abcdef";
    while (std::getline(std::cin, sql)) {
        ++statement;
        if (!handle->prepare(WCDB::UnsafeStringView(sql.c_str()))) {
            std::cerr << "prepare_failed " << statement << '\n';
            return 4;
        }
        for (;;) {
            if (!handle->step()) {
                std::cerr << "step_failed " << statement << '\n';
                handle->finalize();
                return 5;
            }
            if (handle->done()) break;
            std::cout << "ROW";
            for (int i = 0; i < handle->getNumberOfColumns(); ++i) {
                auto value = handle->getText(i);
                std::cout << '\t';
                for (size_t j = 0; j < value.length(); ++j) {
                    auto byte = static_cast<unsigned char>(value.data()[j]);
                    std::cout << digits[byte >> 4] << digits[byte & 15];
                }
            }
            std::cout << '\n';
        }
        handle->finalize();
        std::cout << "END " << statement << '\n';
    }
    return 0;
}
