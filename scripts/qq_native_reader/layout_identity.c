/* Compiled with the same flags as the read-only SQLCipher objects. */
#include "sqliteInt.h"

unsigned int echo_pending_byte(void) {
    return PENDING_BYTE;
}
