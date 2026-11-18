/* Adapter for the pinned, QQ-layout SQLCipher engine. Windows x64 only. */
#include <windows.h>
#include <string.h>
#include "sqlite3.h"

extern unsigned int echo_pending_byte(void);

static int authorize_read(void *unused, int code, const char *name,
                          const char *argument, const char *schema, const char *trigger) {
    (void)unused;
    (void)schema;
    if (trigger) return SQLITE_DENY;
    switch (code) {
    case SQLITE_SELECT:
    case SQLITE_READ:
    case SQLITE_RECURSIVE:
        return SQLITE_OK;
    case SQLITE_FUNCTION:
        if (argument && (!strcmp(argument, "load_extension") || !strcmp(argument, "writefile")))
            return SQLITE_DENY;
        return SQLITE_OK;
    case SQLITE_PRAGMA:
        if (name && (!strcmp(name, "table_info") || !strcmp(name, "integrity_check")))
            return SQLITE_OK;
        return SQLITE_DENY;
    default:
        return SQLITE_DENY;
    }
}

/* The caller has already authenticated and frozen the three original files.
   This entry accepts raw key bytes in memory only and wipes the key spec. */
__declspec(dllexport) int echo_qq_open(const char *uri, const unsigned char *key, sqlite3 **result) {
    static const char hex[] = "0123456789abcdef";
    char specification[67] = {'x', '\''};
    sqlite3 *db = NULL;
    int rc;

    *result = NULL;
    if (echo_pending_byte() != 0x40000000U - 1024U) return SQLITE_MISUSE;
    rc = sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI | SQLITE_OPEN_PRIVATECACHE, "win32");
    if (rc != SQLITE_OK) goto finish;
    if (sqlite3_db_readonly(db, "main") != 1) { rc = SQLITE_READONLY; goto finish; }
    rc = sqlite3_exec(db,
        "PRAGMA cipher_default_page_size=4096; PRAGMA cipher_default_kdf_iter=4000;"
        "PRAGMA cipher_default_hmac_algorithm=HMAC_SHA1;"
        "PRAGMA cipher_default_kdf_algorithm=PBKDF2_HMAC_SHA512;",
        NULL, NULL, NULL);
    if (rc != SQLITE_OK) goto finish;
    for (int i = 0; i < 32; ++i) {
        specification[2 + 2*i] = hex[key[i] >> 4];
        specification[3 + 2*i] = hex[key[i] & 15];
    }
    specification[66] = '\'';
    rc = sqlite3_key_v2(db, "main", specification, sizeof(specification));
    SecureZeroMemory(specification, sizeof(specification));
    if (rc != SQLITE_OK) goto finish;
    rc = sqlite3_db_config(db, SQLITE_DBCONFIG_DEFENSIVE, 1, NULL);
    if (rc != SQLITE_OK) goto finish;
    rc = sqlite3_exec(db, "PRAGMA temp_store=MEMORY; PRAGMA query_only=ON;", NULL, NULL, NULL);
    if (rc != SQLITE_OK) goto finish;
    rc = sqlite3_set_authorizer(db, authorize_read, NULL);
    if (rc == SQLITE_OK) { *result = db; return SQLITE_OK; }

finish:
    if (db) sqlite3_close(db);
    return rc;
}

__declspec(dllexport) int echo_qq_prepare(sqlite3 *db, const char *sql, sqlite3_stmt **result) {
    const char *tail = NULL;
    int rc = sqlite3_prepare_v3(db, sql, -1, SQLITE_PREPARE_NO_VTAB, result, &tail);
    if (rc != SQLITE_OK) return rc;
    if (!*result || tail[strspn(tail, " \t\r\n\f\v")] || !sqlite3_stmt_readonly(*result)) {
        sqlite3_finalize(*result);
        *result = NULL;
        return SQLITE_READONLY;
    }
    return SQLITE_OK;
}
