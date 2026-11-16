# QQ 54395: first complete local-read preparation

Research branch only. No production QQ/WeChat changes, merge, push, or new real
process loading in this preparation. Prior session-loader and authorized live
homepage evidence were reviewed and preserved in commit `3136950`.

## Corrected input identity

The previously authenticated encrypted main was only 422,912 bytes, with a 2024
modification time. Its successful MAC is real evidence for that file, **not**
evidence that the currently requested large conversation was read.

A metadata-only check of the QQ `UserDataInfo.ini` path setting located the
custom data root. It contains a recently updated, approximately 896 MiB main
for the user-supplied account. Neither private paths, account IDs, group IDs nor
the selected group's name belong in this document or source.

With QQ exited, no WAL/SHM/journal was present for that main. Preparation held a
Windows share-read-only handle, rejected all sidecars, copied encrypted bytes,
checked handle/path identity and complete length, and independently hashed the
copy. The new random task directory grants access only to the current user and
SYSTEM. Source files were not modified. The copied main has **not yet been
authenticated with a newly captured event** and no real plaintext was created.

## Minimal integration

- Existing native receiver, exact module/version gates and private IPC remain
  unchanged. One command, one response of at most 8 KiB, at most 120 seconds.
- An optional scoped consumer in the existing event authenticator runs only
  after native Stop and loader exit have been confirmed. A bounded response
  waits in memory until then; no key or raw response is persisted.
- The existing codec gained a synchronous page sink and bounded random reads.
  HMAC, cipher/KDF parameters, current header-count validation and complete-page
  truncation refusal use the same implementation as the buffered path. This
  removes the full-database buffer requirement; it does not repair or tolerate
  damaged data. The preparation originally refused the buffered memory budget.
- Full reads are limited to 1 GiB input, a 120-second synchronous decode budget
  and a 600-second outer worker deadline. Observation ends before decode starts.
- Only a complete authenticated copy reaches the existing standalone-header
  finalizer, full SQLite `integrity_check`, selected-session Provider,
  Adapter/ImportService and AnalysisApplicationService. No framework API runs.
- Each fresh attempt ID permits one capture. Reusing a verified encrypted copy
  requires a new explicitly authorized attempt; prior markers/receipts remain.
- No-WAL closed-main acquisition is the verified path prepared here. A sidecar
  appearing during preparation causes refusal. Live WAL merging remains an
  existing capability, **not a newly verified real-data path in this experiment**.

The installed jieba default dictionary was missing. The already cached 0.42.1
wheel supplies the original dictionary, verified against the installed RECORD
SHA256. It is used explicitly inside the research worker. No shared environment
installation, upgrade, fabricated vocabulary or analysis-algorithm change.

## Validation completed

One fictional SQLite fixture traversed the actual owned native host, IPC,
existing event parser/authentication, page sink, full SQLite integrity check,
scoped Provider and existing report generator. It selected two authorized
fixture messages, including one self message, and excluded a different group.
The host continued running and unloaded its fixture DLL; the owned Job exited
and the test temporary tree was removed.

The sink additionally refused a corrupted later page, whole-page truncation and
a wrong key, removing provisional plaintext each time. The existing native
session scenarios confirmed that cancellation, timeout, wrong identity, parser
failure, authentication failure and unconfirmed process exit never consume a
key. Existing SQLCipher/WCDB interoperability checks still pass after the sink
change. These are wiring/regression evidence, **not a real QQ report result**.

## Real-run authorization and cleanup

Next: ask the user to open the already verified QQ and remain logged out, verify
the new process identity and module, then obtain separate approval for loading
the same bounded native component. Only announce manual login after `armed`.
Do not restart/terminate QQ, automate login, retry, modify installation files or
change protections. A missing/mismatched event stops the attempt.

The new event must authenticate the newly selected snapshot, then all its pages.
Any MAC/count/integrity/scope mismatch stops before report generation. Only the
explicitly selected conversation is materialized. Counts, timestamp endpoints
and known/unknown sender directions are checked against scoped source metadata.
Content semantics use the existing Adapter; a user spot-check remains necessary
before claiming human semantic acceptance or completeness versus another export.

The worker's private temporary directory owns the decrypted DB and selected
payload. The outer controller owns its worker Job and containing temporary tree:
on normal/error/cancel paths it drains only its own processes and removes those
temporary files. A final report stays local in the protected task root. A partial
report is explicitly labelled failed and retained there for review, never called
a successful report. The encrypted prepared copy remains local until this
experiment is reviewed and its exact assets are authorized for disposal.

Power loss or forced death of the outer controller can leave protected temporary
files. Do not claim secure erasure or guaranteed cleanup in that case. The task
root and temporary owner markers identify recovery scope; first verify the
owned process tree has ended, then inspect and clean only those marked assets.
Do not automatically reuse an attempt ID or delete unknown
files. A stopped hook is not an unloaded DLL: real QQ retains the inert component
until the user normally exits QQ. No force-exit fallback.

Current acceptance: real database decryption pending; real selected-message read
pending; real report pending. Preparation is ready for the next separately
approved live session, subject to fresh process/module and resource checks.

## First large-main live attempt: refused, no retry

The user separately approved one native load and manually logged in after the
`armed` notification. The native transport emitted `stopped`. The worker then
refused `input_or_generation_changed` before selecting any conversation or
creating a report directory. The outer controller exited with failure.

Metadata-only follow-up found the same process creation identity, exact supported
version and loaded wrapper hash. Of the tracked installation resources, only
`config.json` had a modification timestamp after attempt creation. The evidence
points to QQ's own mutable update configuration invalidating whole-resource
equality. No Echo operation changed installation files. The admission check has
not been relaxed or retried.

The worker previously emitted capture/authentication outcomes only after this
final equality check. Consequently this attempt's event, parser and page-one
authentication outcomes are unavailable from its retained diagnostic output.
Do not infer success from `stopped`, or recover discarded keys/responses/plaintext
to fill that gap. The research runner now emits the existing sanitized capture
outcomes before final identity verification, explicitly labelled unverified;
message/report consumption still remains after the unchanged rejection gate.
That diagnostic-order correction has not been retried against real QQ.

Post-exit checks: no experiment helper processes, no owned worker temporary
directories, no `snapshot.db` or `selected.json`, and no report directory.
The protected encrypted snapshot and single-attempt marker remain for review.
The stopped native component still requires the user's normal QQ exit for full
release. New validation requires a new explicit decision and approval.

## Targeted identity and evidence correction

The previous attempt did not retain the pre-login configuration object. Its exact
historical changed fields cannot be reconstructed from mtime alone. The current
configuration was inspected read-only; no claim is made that a particular field
value changed previously. The conservative correction permits only equal JSON
content with changed serialization, timestamps or atomic-replacement identity.
Every configuration value, including `curVersion` and staging/counter fields,
must remain semantically unchanged; unknown field changes also refuse. Config
location, active package text/path, version, wrapper path and all non-config file
states remain fixed. Non-config resources additionally retain SHA256 witnesses.
The existing process-creation check remains, with a final loaded-module check.

The existing fictional native-host check now reproduces the previous whole-
resource comparison refusal on config rewrite, verifies the correction, and
refuses a version change, a configuration counter change, and a same-size native
module change with restored metadata. Its native-to-report closure still passes.

Native authentication and decryption emit synchronous fixed-status pipe records.
The owning worker appends/fsyncs sanitized stage records to a private per-attempt
`verification.jsonl` before later identity/SQLite/message/report checks. A later
refusal appends a separate result and cannot overwrite prior primitive evidence.
Full SQLite success and selected-message verification likewise publish before
downstream work. No keys, raw responses, message bodies, IDs or private paths
enter these receipts. Existing test coverage confirms completed evidence remains
after a later refusal. No real process load has retried this correction yet.

The same encrypted copy was rehashed and its no-WAL acquisition manifest,
ownership, native build/module, dictionary and memory admission rechecked. A
transient memory admission refusal was retained; a subsequent read-only check
passed without lowering the guard. No real plaintext was created in preparation.

## Corrected live attempt and bounded zero-capacity compatibility

A new separately approved load reached `armed`; the user manually logged in.
Its retained stage receipt proves target event delivery, successful parsing and
page-one authentication against the **large** frozen main. The final identity
check passed: config JSON was identical with no serialization/field changes,
while config metadata changed. Process generation and loaded module matched.
This is stronger evidence than the previous mtime-only inference and verifies
the targeted identity correction on real QQ.

Full decoding then refused `page_hmac_mismatch`; SQLite, selected-session reads
and report generation were not reached. No failure page or authenticated logical
header count was retained by that decoder revision, so its exact failing page
must not be claimed. The scoped key was cleared, helpers exited, temporary
plaintext was removed, and no report directory was created. No automatic retry.

A bounded read of the unchanged encrypted copy found 229,376 physical pages:
the first all-zero page is 225,958, with a contiguous 3,419-page all-zero suffix
and no subsequent nonzero page. This suggests unused capacity, but **does not
yet prove that the real authenticated logical end is 225,957 or that the observed
MAC refusal happened at that boundary**.

The research streaming consumer now opts into a narrowly checked capacity rule:
only after authenticating/decrypting page one, a nonzero header count with equal
change/version-valid counters establishes the logical end. All bytes beyond it
must be zero, all logical pages must pass MAC, and declared count must match the
complete output. A nonzero tail, missing logical page, stale count or bad logical
MAC refuses and removes provisional output. Default buffered decoding remains
strict. No source file, header count or damaged page is repaired. This follows
the [SQLite valid in-header size rule](https://www.sqlite.org/fileformat.html#in_header_database_size).

The existing SQLCipher cross-check was extended with this one capacity format:
reference SQLCipher accepts the zero-extended fixture; independent output is
identical to the reference-derived plaintext, and full standard SQLite integrity
passes. Logical corruption, nonzero capacity, wrong keys and logical truncation
still refuse; stale counters refuse in both decoder modes. The existing native
fixture-to-report regression remains passing. These checks validate the rule,
not its applicability to the real QQ copy.

Future live receipts additionally expose only authenticated header counts,
physical/zero-capacity counts and numeric failure-page coordinates. They contain
no message/response/key material. A new actual event is required to test the
real logical boundary; the completed attempt's approval is consumed and its key
is unavailable. Normal QQ exit and new separate load approval are required.

## Cleared-history clue and exact failure diagnostics

The account owner reports having cleared history using QQ settings. This is a
possible explanation for changed space usage, not evidence of the logical end.
Rehashing and rescanning the retained encrypted copy confirmed the same physical
page count and contiguous zero suffix described above. Reviewing the original
append-only receipt confirmed that the first failed MAC coordinate was not
recorded. It cannot be recovered from that receipt or ciphertext without a key.
In particular, page 225,958 must not be reported as the historical failing page.

SQLite freelist pages remain inside the logical database. Header offsets 32/36
describe the first freelist trunk and total freelist count; clearing records does
not itself authorize discarding these pages. The next attempt records these two
authenticated numeric fields alongside the header count and its validity flag.
It also preserves the first MAC failure's one-based page number and whether the
entire encrypted page is zero. No message bodies, raw header bytes or secrets
are recorded. A nonzero failing logical page immediately refuses; a zero failing
logical page also refuses. There is no freelist authentication exception.

The existing cross-implementation check now additionally zeroes an entire page
inside the authenticated logical range. The full-read consumer refuses precisely
at that page and deletes its partial plaintext, distinguishing it from a nonzero
corruption at the same coordinate. Header freelist metadata is checked against
the known fictional plaintext. SQLCipher capacity acceptance, output equality,
full SQLite integrity and the existing native-host-to-report check pass. These
checks do not establish the real copy's logical end or classify its zero suffix.

Read-only preparation reconfirmed protected-root access controls, encrypted-copy
identity/hash, dictionary identity and the unchanged memory admission guard.
There were no QQ/helper processes, owned temporary plaintext or report directory.
The next separately approved single login capture will authenticate this same
frozen copy, persist header/first-failure evidence, and, only if all logical MACs
pass, proceed directly through SQLite integrity, authorized-session conversion
and the existing report pipeline. No real process was operated in this follow-up.

## Separately approved live boundary verification

One approved pre-login window expired without an event. Its receipt confirms
observation stopped, Hook disabled and no in-flight callbacks; the user normally
exited QQ and release/temporary cleanup were checked before a new selection.

The next separately approved capture received and parsed the target event and
authenticated page one of the same large frozen copy. Its authenticated header
reports 225,957 logical pages, current size counters, zero freelist pages and a
zero first freelist trunk. Together with the unchanged ciphertext layout, this
establishes that the 3,419 all-zero physical pages are beyond the logical database
boundary, rather than logical freelist pages. It does not prove why QQ retained
that capacity or reconstruct the original failed MAC coordinate.

Full decoding nevertheless refused `full_snapshot_refused`; no MAC failure page
was emitted. Final process/module/resource identity checks passed. The retained
attempt-marker/receipt timestamps span approximately 18 seconds, providing no
support for a 120-second decode timeout. The wrapper had collapsed other fixed
guard/I/O/finalization errors into this generic code. Its actual underlying error
cannot be recovered from the retained receipt after key and partial output were
cleared. Neither all-page authentication, SQLite checks, selected-message reads
nor report generation has been established by this attempt.

Only diagnostics were then changed: preserve a shared allowlist of fixed error
codes, fixed failure stage, number of pages already authenticated and elapsed
milliseconds; expose authenticated page size/reserved-byte and format-version
numbers. Unknown exception strings and paths remain suppressed. Authentication,
logical boundary, reserve-byte, deadline and integrity guards are unchanged.
The existing cross-implementation refusals now verify stage/count preservation;
the existing native-host-to-report regression also passes. No further real load
or capture was performed. Real helpers and temporary plaintext were absent;
the stopped component still requires a normal QQ exit for complete release.

## Offline follow-up after normal exit

The user normally exited QQ after this refusal. Follow-up confirmed zero QQ and
experiment helper processes, zero owned temporary worker directories, no temporary
plaintext/payload and no report directory. The loaded component was released by
QQ process exit. The frozen encrypted copy remains under its existing ownership.
No new process load, login or key capture is authorized for this investigation.

The new error codes, stage and authenticated-page count did not exist in the
failed attempt. Its receipt still contains only the generic refusal after the
authenticated header; adding diagnostics cannot reconstruct that lost evidence.
Reviewing the code narrows reachable causes to the subsequent format guard,
bounded reads/writes, final input checks and standalone-copy finalization; it
does not identify which one actually threw. No reserve-byte or format guard was
removed, and no unsupported profile was added based on this uncertainty.

A bounded read-only check of the same encrypted copy reproduced none of the
input identity/hash failures. Access timestamps changed on reads while the
identity fields actually checked by the reader remained unchanged. Current free
disk space exceeds the plaintext budget; this is a current observation, not
retrospective proof that no historical I/O failure occurred.

One existing SQLCipher capacity fixture was adjusted from two zero pages to
3,419, matching the real suffix length and exercising multiple 1 MiB reads.
The same codec/full-read consumer successfully decrypted its logical pages;
reference SQLCipher and complete standard SQLite integrity/readback accepted it.
Logical corruption, a zero logical page and a nonzero tail still fail with fixed
codes, phase and authenticated-page counts, and partial plaintext is removed.
This is a focused geometry regression, not real large-database acceptance.

The real refusal remains unlocated, so no decryption fix is claimed and no new
login is requested. The missing evidence is the original fixed error/stage/page
progress and authenticated format fields. With the scoped key and provisional
output already cleared, neither those fields nor the failing operation can be
recovered from the current ciphertext and generic receipt alone. Work remains
stopped at this evidence boundary rather than changing guards or repeating live
captures without a diagnosed fix.

## Complete offline refusal-path audit

This follow-up reaches the second stop condition: the remaining real-format and
logical-page questions require a newly authenticated key. It does **not** locate
the historical real refusal or claim a real report. No QQ process was started,
loaded, logged in, or captured during this audit. No commit, merge or push.

The retained failed receipt was inspected again using only its fixed statuses
and numeric fields. It contains an authenticated logical count of 225,957,
229,376 physical pages, current size counters and zero freelist fields, followed
by the generic refusal. It contains no page size, reserve-byte count, format
versions, failure stage or full-page progress. The key scope wiped its material
and provisional plaintext was removed. Adding fields now cannot reconstruct
those missing historical values. Current frozen-copy hash/ownership/ACL checks
pass; path/descriptor identity fields also agree in the current Node runtime.

All reachable research-reader refusal families were traced through the bridge:

| Operation / guard | Fixed failure and stage | Authentication evidence |
| --- | --- | --- |
| Selection fields, 1 GiB bound, alignment, input/output separation | `snapshot_selection_refused` / `selection_validation` | 0 decoder pages; bridge separately retains prior homepage authentication |
| Linked/missing path, regular-file/single-link/size admission, open identity | `snapshot_path_refused`, `snapshot_identity_refused`, `snapshot_changed` or fixed OS code / path, identity or open stage | 0 |
| Frozen prefix and first whole-input SHA256 | `snapshot_changed`, bounded/short-read or OS code / separate prefix/hash stages | 0 |
| Exclusive output creation | OS code, including `EEXIST`, `EACCES`, `ENOSPC` / `output_open` | 0; an existing output is never removed |
| Decoder setup and salt | `invalid_sink`, `invalid_size`, `salt_mismatch` / `decoder_setup` | 0 |
| Logical page reads and HMAC | read/OS error or `page_hmac_mismatch` / `page_authentication` | Exactly the preceding authenticated pages; MAC refusal also records one-based page and all-zero boolean |
| AES and authenticated-header callback | fixed crypto code or redacted exception category / `page_decryption` or `header_receipt` | Includes the page whose MAC passed, even before any successful write |
| Current/nonzero header count, physical bound, page size and reserve | `untrusted_page_count`, `page_count_mismatch`, `invalid_sqlite_header` / `header_validation` | 1; authenticated header numbers precede these guards |
| Entire suffix beyond the authenticated count | `nonzero_capacity_tail` or read/OS error / `capacity_validation` | 1; no zero logical page exemption |
| Deadline, partial/failed page writes | `full_decode_deadline`, `snapshot_short_write` or OS code / `output_write` | MAC count and fully written page count recorded separately |
| Completed decoded count | count refusal / `page_count_validation` | Exact authenticated count; no inferred or repaired completeness |
| Output close, second hash, descriptor/path identity | fixed OS error or `snapshot_changed` / distinct close/hash/descriptor/path stages | Complete logical MAC progress retained |
| Standalone-copy finalizer | `plaintext_snapshot_invalid`, `plaintext_header_invalid`, `short_read`, `short_write` or OS code / `finalization` | Complete MAC progress plus the finalizer's numeric/boolean guard witness |
| Finalizer receipt and final input close | fixed/redacted failure / `finalization_receipt` or `input_close` | Complete MAC progress retained; complete image is not published on error |
| Cleanup after any refusal | Separate close/remove failure codes | Original failure, stage and counts retained; failed deletion is never called successful |

Unknown exceptions still map to `full_snapshot_refused`, with a fixed stage and
one of four exception categories; their text, stack, path and arbitrary native
codes never enter receipts. The real bridge now sends a synchronous failure
record before the key-scope wrapper suppresses consumer exceptions. The owning
Python worker appends/fsyncs that record. Eight relevant source hashes and a
diagnostic-contract version identify the actual implementation used. Fixed
milestones and at most eight page-progress receipts fit the bounded pipe reader;
its former eight-line cap was increased for this protocol. Fatal process loss
cannot provide an exact final page, but earlier fsynced evidence remains.
Key-scope deadline/cleanup failures after a consumer returns also retain a fixed
`key_scope_failure` instead of appearing to be unexplained MAC failures.

The standalone finalizer's format checks remain strict: SQLite signature, 4096
page size, supported equal read/write versions, exact output size and its count
predicate. The codec still requires 48 reserved bytes and a current logical
count, authenticates every logical page and rejects every nonzero capacity byte.
After full decode, `all_pages_authenticated` can remain true on a later I/O or
finalizer failure, while `complete_image` is withheld. Full standard SQLite
integrity occurs later in Python; it cannot be the source of this decoder's
`full_snapshot_refused`. It now has separate start/failure receipts with fixed
stages and numeric SQLite error codes, including interruption/deadline evidence.
SQL errors and integrity-result text are never logged.

Offline fault checks reproduced and fixed the diagnostic loss at preflight,
cleanup masking the original write error, and miscounting MAC progress through
the sink. A separate finalizer fault reproduced a zero-byte header write being
retried without progress. It now fails closed with `short_write`; this is a
bounded-I/O fix, **not evidence that zero-byte writes caused the real refusal**.
Fault checks cover partial page writes, cleanup failure, header callback failure,
output close failure and authenticated unsupported finalizer format, using a
small fictional input. A format refusal followed by the finalizer's own close
failure was also reproduced: the original guard now survives, with a separate
fixed close-failure witness. Checks confirm redaction and provisional-output
handling.

A single SQLCipher-created large fixture now matches **both** real counts:
225,957 logical pages plus 3,419 zero-capacity pages, 939,525,120 wrapped bytes.
It contains one fictional zero BLOB rather than chat records. The actual bounded
consumer, with a 512 MiB Node heap limit and unchanged guards, authenticated every
logical page, wrote 925,519,872 plaintext bytes and finalized the standalone copy.
The final implementation traversed the actual scoped-key owner, including both
full fingerprint passes, decode, progress receipts and finalization, in
approximately 44.5 s; key material was cleared and its scope released. Peak
process RSS was approximately 129 MiB. SQLCipher reference integrity and
standard SQLite full integrity/readback passed. This directly exercises large
offsets/page numbers, the real zero-tail length, the 1 GiB admission bound and
both 120 s budgets on this machine. It does not prove real format equivalence,
historical free resources or real-data integrity. Large fictional database files
were removed after verification; their sanitized result receipt remains local.

The existing SQLCipher interoperability/corruption checks, native-fixture session
cases and fictional native-to-report closure pass. Focused finalizer regressions
pass. The pre-existing production launch-gate changes were reviewed and left
unchanged; their focused tests pass with one existing pinned-archive prerequisite
skip. Full/Frozen/Setup and real-report acceptance were not run for this research
audit. No large fictional report or mobile acceptance was added.

Remaining discriminators for one separately authorized future capture are:
authenticated reserve/page-size/format numbers; the first failing logical MAC
coordinate if any; otherwise the exact read/write, post-read identity or finalizer
guard and cleanup outcome. Those format fields and logical MAC results cannot be
derived from ciphertext plus the retained generic receipt without a key. A fresh
run can classify its own failure; it cannot prove a transient historical I/O
condition. No unsupported profile or reserve-byte workaround is justified yet.

The existing protected encrypted copy, attempt markers and original receipts
remain unchanged for that decision. No owned temporary plaintext/payload, report,
QQ process or experiment helper remained after verification. Newly generated
fictional cross-check/native result artifacts stay in ignored build directories
for review and may be reduced to their result receipts when this audit is
accepted. The pre-existing untracked PowerShell cache has unknown task ownership
and is preserved, excluded from this change. Source changes remain uncommitted
on `spike/qq-independent-source`; main is unchanged. Their next step is review
and, only after explicit new authorization, one real capture with these receipts.

## Authorized follow-up: controller refused before load (November 15)

The user authorized one bounded capture and started QQ at the login screen.
Focused diagnostic and fictional native-to-report checks passed; frozen-copy
hash/ACL, native binary identity, dictionary and memory admission passed. The
selected process had the exact supported resources and no experiment component.

The worker refused `selected_process_changed` **before** starting Node or the
native loader. The controller had transported the 64-bit process creation time
as a JSON number through JavaScript and then formatted the rounded number as a
decimal command-line argument. That timestamp exceeds JavaScript's safe integer
range. Read-only diagnosis reproduced the supplied argument exactly by applying
the same Number/decimal conversion to the actual timestamp; the exact integers
differed. This is a controller parameter error, not evidence of a changed QQ
generation or a database refusal. The worker's identity guard correctly refused.

The controller correction keeps the creation time as a decimal string at the
Python-to-JavaScript boundary and converts it to an integer only inside Python
or to BigInt inside Node. A read-only JSON round trip matched the selected
process exactly. Future selections must be freshly queried using that encoding,
never reconstructed from a rounded number. No database guard was changed.

The attempt's append-only private receipt retains the admission failure,
transport diagnosis/correction and cleanup verification. No `armed` record,
native load, key capture, provisional plaintext, payload, report or experiment
helper process was present. No component needed unloading. The frozen copy and
earlier receipts remain unchanged. Per the user's failure-stop requirement, no
retry was performed; further execution awaits a new explicit instruction.

## Explicit restart: observation ended without target event (November 15)

The user explicitly requested a restart. A fresh attempt and freshly queried
decimal-string process creation time passed exact identity admission. Frozen
copy hash, supported resources, module identity, dictionary, memory and the
focused diagnostic check passed before the single native load. The component
was absent before this load. The controller received `armed` and prompted the
user to scan; it did not operate the login UI.

The observation ended with `no_target_event`: no target event was delivered or
parsed, no key was obtained, and the full-read consumer never ran. Stop evidence
shows observation stopped, Hook disabled and zero in-flight callbacks. Final
process, module and installation-resource identity checks passed. This attempt
provides no new evidence about the real database's decryption refusal.

The append-only attempt receipt retains the code-contract hashes, capture and
identity results, and post-attempt cleanup. The frozen-copy hash is unchanged;
owned worker temporary trees, plaintext/payload, report and helper processes
were absent. No native retry was performed. Read-only module metadata confirmed
that the stopped component remained resident until the user's normal QQ exit.
After the user reported exit, a native process-exit-code check proved that the
selected generation had ended. Zero QQ and experiment helper processes remained;
component release is therefore verified by process exit, not observation Stop.
The private receipt additionally retains that release evidence, unchanged
snapshot hash and absence of worker temporary trees, plaintext/payload and report.

## Next explicit attempt: authenticated reserve-byte mismatch (November 15)

Another separately authorized single load used a fresh process selection and
attempt identity. The user logged in after `armed`. Observation stopped cleanly:
Hook disabled, zero in-flight callbacks and successful final generation/module/
installation-resource checks. The target event was delivered and parsed; its
key authenticated page one of the same large frozen copy.

The authenticated header reports 4096-byte pages, **80 SQLite reserved bytes**,
read/write format versions 2/2, 225,957 logical pages, current counters and zero
freelist fields. The independent codec's header guard requires 48 reserved bytes.
It therefore refused `invalid_sqlite_header` after authenticating one page and
before writing any page. This precisely identifies the refusal in this attempt;
it does not retrospectively recover a different attempt's discarded evidence.
The zero-capacity tail and subsequent logical MACs were not reached. SQLite,
Provider/Adapter and report generation were not reached.

The fixed failure receipt retains one authenticated page, zero written pages,
elapsed time, successful provisional-output deletion and no cleanup failures.
Its stage label is `header_receipt`: the callback changes the stage and the codec
does not restore `header_validation` before its guard. The emitted authenticated
header plus the exact guard identifies the actual operation unambiguously. A
separate append-only diagnosis records `sqlite_reserved_bytes_mismatch` and
`header_validation`, preserving the original record and this labelling defect.
No reserve-byte guard or authentication parameter has been changed from this
observation alone; SQLite usable-page reserve and cipher footer geometry must
be distinguished before any compatibility change.

The scoped key was cleared, helpers exited, owned worker temporary trees and
plaintext/payload were absent, and no report was created. The frozen-copy hash
is unchanged. No retry was performed. After the user's first exit notification,
native exit-code verification still found the selected generation active; a
follow-up process check agreed. After the user completed QQ's normal exit,
native exit-code verification proved the selected generation ended and its
component was released. Zero QQ/helper processes, worker temporary trees and
plaintext/payload remained; the encrypted-copy hash was unchanged. Both pending
and completed release checks remain in the append-only receipt. No forced
termination or further load was used.

## Offline reserve-layout correction (November 15)

Continued on the same research branch and actual `3136950` HEAD, preserving all
pre-existing uncommitted work and unrelated untracked assets. No real QQ process,
key capture, account configuration or original database was accessed this round.

The pinned [SQLCipher reserve setup and page cipher implementation](https://github.com/sqlcipher/sqlcipher/blob/f049bed66ca26741f09a6e4f0603ed3af195ac96/src/crypto_impl.c)
distinguishes the codec footer from SQLite's B-tree reserve. SHA1 uses a
16-byte IV plus 20-byte MAC, rounded to 48 bytes for AES block alignment.
For 4096-byte pages the IV occupies offsets 4048..4063, the MAC 4064..4083,
and the remaining 12 bytes are footer padding. Page one starts with 16 bytes
of salt instead of encrypted SQLite magic. Authentication covers ciphertext,
IV and the little-endian page number. Existing parameters remain AES-256-CBC
without padding, PBKDF2-HMAC-SHA512/4000 for passphrases and /2 for the MAC key
using the salt XOR 0x3a. No SHA512 MAC or 80-byte cipher footer was introduced.

When the authenticated SQLite header declares reserve 80, usable B-tree bytes
end at offset 4016. The next 32 bytes remain encrypted and authenticated under
the existing SHA1 geometry. The successful real homepage MAC already supports
this layout; the header alone would not prove it. The codec now explicitly
names its fixed cipher reserve and accepts the independently verified SQLite
reserves 48 and 80 in both buffered and streaming decoding. Unknown reserves
remain refused. The header callback's completion restores `header_validation`;
a callback failure itself correctly remains `header_receipt`.

Independent fixture construction used standard SQLite's reserve-byte file
control and VACUUM to create an empty one-page reserve-80 database. Node only
bootstrapped encryption of that empty seed. The pinned WCDB/SQLCipher then
created the schema and inserted all fictional records, rewriting page one and
creating every data page. This avoids patching the header of a populated
reserve-48 database or relying on Node's self round trip as reference evidence.
Before the decoder fix, this fixture reproduced `invalid_sqlite_header`, one
authenticated page, zero written pages and the erroneous `header_receipt` stage.

Validation with the verified existing venv and current-checkout imports:

- Both reserve-48 and reserve-80 fixtures passed SQLCipher -> Node -> standard
  SQLite, Node -> SQLCipher, raw-key-plus-salt reading, full integrity and all
  fictional row/BLOB comparisons. Every page's ciphertext corruption was
  rejected by both implementations. Additional reserve-80 corruptions at the
  encrypted reserve, IV and MAC offsets also failed in both implementations.
- The existing zero-capacity and negative checks passed for both formats:
  bad logical pages (including an entirely zero logical page), nonzero tail,
  wrong key/profile, partial/whole-page truncation and stale counters refuse.
  Diagnostic faults passed, including completed header receipt followed by a
  guard refusal labelled `header_validation`, with provisional output removed.
- The existing owned native-host -> report regression passed using reserve 80
  and header read/write versions 2/2. SQLite integrity, selected conversation,
  Provider/Adapter, direction/time checks, real analysis/report generation and
  owned Job/temporary-tree cleanup passed with fictional messages only.
- The existing scale check passed at exactly 225,957 logical pages plus 3,419
  zero capacity pages, reserve 80, with every logical MAC verified. Reference
  and standard SQLite integrity were `ok`; payload length matched. The full
  consumer took 7,305 ms with peak RSS 135,114,752 bytes on this machine,
  within the unchanged deadline. Its owned large fixtures were removed; only
  sanitized evidence and isolated directories remain.
- Shared main/WAL snapshot focused regressions passed (49 cases). Full,
  Frozen/Setup and GUI release acceptance were not run: this is a research
  codec compatibility correction, not a product release or real-data result.

No architecture or native capture changes were needed. This round changed only
the codec, existing offline drivers and this record. Small fictional fixtures
and sanitized local receipts remain in ignored task output for review; they can
be disposed of after review under exact ownership checks. Prior real encrypted
assets and receipts were left untouched. All source work remains uncommitted
in place for review; no branch creation, merge, commit or push occurred.

Remaining gate: a fresh explicitly approved real single capture. Offline checks
remove the known reserve/header-stage blocker, but do not establish the real
database's later-page MACs, SQLite integrity, selected-message semantics or a
real report. The next approved attempt should use the existing full-read path
directly through these gates and report generation, with no automatic retry.

## Approved real full decryption: session-scope guard refused (November 15)

The user approved one fresh real capture and supplied the exact report group
and self identity again; these private values were used only by local controller
processes, never added to repository files or sanitized receipts. Fresh process
selection preserved creation ticks as a decimal string. Frozen-copy SHA256,
protected-root ACL, dictionary, memory, version, wrapper identity and absence of
the component passed preflight. The user logged in only after this attempt's
durable `armed` record. No automatic retry occurred.

The target event was delivered and parsed, page one authenticated, observation
stopped, Hook disabled and zero in-flight callbacks were confirmed. The real
header again reported reserve 80 and read/write versions 2/2. This time ALL
225,957 logical pages authenticated and were written; all 3,419 capacity pages
were zero. Standalone finalization passed every retained header/count/size guard.
Final process generation, loaded module and installation resources matched;
config JSON was identical despite changed metadata. Full standard SQLite
`integrity_check` returned `ok`. These are actual large-real-database results,
not inference from the offline fixtures or homepage authentication.

The next selected-session guard refused `authorized_partition_mismatch`. The
query found one nonzero local partition key for the authorized external group,
but querying all rows by that partition failed its count/external-group invariant.
The retained receipt does not contain the counts or individual conflicting
values. It cannot establish whether this is missing/zero historical identifiers,
migration, another conversation, or another layout issue. The existing Provider
documents partition identity separately from external session-object identity;
that contract alone does not prove which case the actual data contains.
Do not weaken the scope check or infer that other conversations are authorized.
Provider materialization, Adapter verification and HTML generation were not
reached. The failure record retains `authenticated:false` at the outer operation
level; this does not erase earlier explicit all-page/SQLite success receipts.

The owned worker and helpers ended; no owned worker temporary tree, `snapshot.db`
or `selected.json` remained. The encrypted snapshot hash was unchanged. The
created report directory was empty (zero report files), retained as failed-attempt
evidence; it is not a report. Sanitized post-attempt cleanup evidence was appended
to the same private receipt. No key, raw response or chat text was retained.
Normal QQ exit was requested to release its stopped component; process Stop
alone is not unload evidence. Release confirmation is recorded separately below
when the selected generation's native exit can be verified.

The current blocker is now authorized-session scope, not page decryption or
SQLite integrity. A further real capture needs new explicit approval after
investigation/preparation; this single approval has been consumed. Source work,
encrypted snapshot, prior receipts and the empty failed report directory remain
in place for review. No Git commit, branch change, merge or push occurred.

After the user normally exited QQ, the handle held for this exact selected
generation signalled exit and `GetExitCodeProcess` returned 0. Zero QQ processes
and zero experiment loaders remained; component release is therefore confirmed
by native process-exit evidence. A final check again found zero owned temporary
trees or plaintext/payload files and the unchanged encrypted-copy hash. The
append-only private receipt retains these checks. The single real decoding pass
authenticated/wrote all logical pages in 6,816 ms before final hash verification
and SQLite checking; this timing does not include report work, which was refused.

## Offline group identity investigation and next minimal validation

The successful real decryption receipt was re-read, not repeated. Its only
session-level evidence is `authorized_partition_mismatch`; it contains no
conflicting group values or counts. Plaintext was already removed, so the exact
real cause cannot be reconstructed offline. This round did not operate QQ or
decrypt real data. The existing uncommitted work and branch/HEAD were preserved.

The actual identity chain is:

| Value | Source | Consumer |
| --- | --- | --- |
| Authorized external group number | Explicit account-owner input | Metadata anchor query on `40030` |
| Local conversation partition | `40027` in the matching rows | `group:<key>` selection ID, Provider predicate |
| External group/session object | Nonzero `40030`; Provider discovery uses its MAX | `QQSession.session_object`, payload query identity |
| Row-level group object witness | Optional `40021` column | New research authorization check; Provider already preserves this field |
| Message sender/account direction | `40033` versus explicit self context | Existing Adapter canonicalization and count verification |

No code here converts a partition name to a QQ group number. The old group
selector filters `40030` directly, while the typed session API reads the entire
`40027` partition. Switching to the old selector would omit zero-number records
and would not prove the whole partition's identity. The Adapter's typed-session
membership check uses `40027`, so it cannot establish external-group ownership
on behalf of the authorization gate. Provider discovery's MAX value is also not
proof that every row belongs to that external group. No group-code/group-UIN
arithmetic or alias conversion exists in this path, and none was added by guess.

The [original field investigation for 40027](https://github.com/QQBackup/nt_msg_db_util/blob/master/db_docs/group_msg_table/40027.md)
and [40021](https://github.com/QQBackup/nt_msg_db_util/blob/master/db_docs/group_msg_table/40021.md)
describe local partitions separately from external group identity, including
zero `40030` records. This is evidence for an offline hypothesis, not proof of
the real frozen copy's layout or the historical refusal's specific cause.

A fictional reserve-80/version-2/2 fixture reproduced the old refusal with one
normal group-number row plus one zero-number row whose `40021` still names the
same authorized group. The research reader now verifies a strict metadata-only
binding before any Provider materialization:

- A nonzero `40030` anchor must resolve to one nonzero partition. Two candidate
  partitions refuse; the diagnostic candidate count is capped at two.
- If `40021` exists, EVERY selected row must explicitly name the authorized
  group there. Its `40030` must either name the same group or be exactly zero.
  Zero is accepted only with that same row's object witness. Null, blank,
  conflicting nonzero group IDs, unsupported storage types and missing/conflicting
  objects refuse as `authorized_partition_mismatch`.
- Without `40021`, the old all-rows-explicitly-match-40030 requirement remains.
  No partition-only fallback, raw-field rewriting or arbitrary alias acceptance.
- Distinct SQLite storage types collapsed by CAST cannot authorize one partition.
  Existing Provider lookup must still return the expected external group, and
  Adapter row counts, endpoints and sender directions must all match.

One bounded `group_partition_mapping` receipt now records verified/refused state,
candidate count, partition row count, explicit-number matches, zero-number rows
with object confirmation, unproven-number rows, object-conflict rows and partition
storage-type cardinality. No identifiers, object values, names, text, raw rows or
message bodies enter it. A failed proof still stops before body materialization.

The modified native-host -> real analysis/HTML fixture passed and included the
zero-number row in the two-row authorized report. Negative fixtures refused a
missing object witness, conflicting nonzero group number, conflicting object,
NULL number, multiple partitions, mixed key storage types and an unwitnessed
zero in the legacy schema. The existing focused discovery/materialization/self
identity regressions passed (25 cases). Existing uncommitted version/resource
admission regressions passed (22 cases; one pinned-archive audit skipped because
its prerequisites are absent). Snapshot diagnostic faults passed. These are
offline regressions, not a successful real group mapping or real report.

The outstanding research changes were reviewed across the native transport,
scoped key consumer, codec, snapshot finalizer, cleanup/receipts and report reader;
the pre-existing production launch-admission changes were preserved. This is a
scoped review, not a new repository-wide or release audit. Current codec, reader,
bridge, key-scope, transport and finalizer hashes match the successful real
decryption attempt. No decryption/native code changed in this round.

Preparation also rechecked the unchanged encrypted-copy SHA256, ACL, dictionary,
memory and native build hashes. QQ/helper temporary data were absent. The prior
empty failed report directory remains untouched. The existing runner now permits
a new report inside its freshly marked attempt directory as well as the prior
task-root location; other parents, wrong names and existing outputs still refuse.
This gives the next attempt a fresh report destination without deleting earlier
evidence. No attempt was loaded or approval consumed during preparation.

Missing real evidence is precise: whether the selected partition's discrepant
`40030` values are zero AND each has `40021` equal to the authorized group, and
whether any conflicting/missing object or nonzero group ID exists. A fresh
explicitly approved single capture can verify this using the unchanged decode
path, persist only the bounded metadata counts, then directly reuse Provider,
Adapter, Analysis and Report if the binding passes. Any unknown mapping still
refuses with no retry. Temporary plaintext/payload cleanup and normal QQ-exit
release verification remain required. Full/Frozen/Setup acceptance was not run;
no merge, commit or push occurred. Work remains in place pending this review and
the user's decision on that one real validation.

## Approved real mapping verification: passed; Adapter count refused

The user explicitly approved one further capture for the same authorized group,
with strict per-row identity evidence and no retry on failure. Preparation
reconfirmed the frozen-copy hash, ACL, native build, dictionary, memory and the
unchanged successful decryption chain. Before loading, the report reader gained
one bounded numeric Provider/Adapter verification receipt so a later refusal
retains counts rather than only an error code. The existing fictional full-chain
and conflict checks passed again. No Provider, Adapter, Analysis, Report, native
capture, key acquisition or cipher implementation was changed in this attempt.

After fresh exact process/module admission, the user logged in only after the
new durable `armed` record. All 225,957 logical pages again authenticated and
were written, the 3,419 zero capacity pages passed, finalization passed, and
standard SQLite integrity was `ok`. Final generation/module/resource identity
checks passed with identical config JSON. Logical authentication/writing took
6,857 ms before final fingerprint and SQLite checks.

The real authorized-group mapping PASSED with these retained numeric facts:

| Mapping check | Count/result |
| --- | --- |
| Candidate local partition | 1 |
| Rows in that partition | 617,487 |
| Rows explicitly matching authorized group in `40030` | 582,294 |
| Rows with `40030=0` and same-row `40021` matching authorized group | 35,193 |
| Unproven group-number rows | 0 |
| Missing/conflicting group objects | 0 |
| SQLite partition-key storage types | 1 |

Thus the zero-number/same-row-object layout is now established for this actual
frozen copy and authorized group. The mapping did not authorize a different
group, guess an alias, rewrite zero fields, or trust partition membership alone.

Provider lookup/materialization proceeded, then ImportService/Adapter returned
the following actual evidence before a strict refusal:

| Verification | Source rows | Adapter rows |
| --- | --- | --- |
| Total | 617,487 | 590,238 (Rich and Chat counts agree) |
| Own sender direction | 3,346 | 3,346 |
| Other known sender direction | 578,268 | 578,268 |
| Unknown sender direction | 35,873 | 8,624 |

The difference is 27,249 rows, entirely within the unknown-sender count category.
Timestamp endpoint equality was false. No raw endpoints, record IDs, sender IDs,
group values, names or message bodies were logged. The available counts do NOT
prove which record types or parser conditions caused skipping, nor whether the
timestamp difference follows solely from those skipped rows. Do not classify
them all as system messages or declare them safe to omit from this evidence.

The worker refused `adapter_message_count_mismatch`, before Analysis or HTML
generation. No count/time expectation was weakened and no second capture was
requested or performed. The new attempt-owned report directory contains zero
files and remains failed-attempt evidence; the earlier empty report directory
and prior receipts are unchanged. There is still no real report.

Post-attempt checks confirmed zero experiment helper processes, owned worker
temporary trees, plaintext databases or selected payload files. The frozen-copy
hash was unchanged. After the user normally exited QQ, the held handle for the
exact selected generation signalled exit and native exit code was 0. Zero QQ
processes/loaders remained, proving component release by process exit. Sanitized
cleanup and release evidence was appended to this attempt's private receipt.
Keys/raw responses and provisional plaintext were not retained.

The next blocking contract is Adapter/source row and time reconciliation, not
group identity or decryption. This attempt ends here per the user's failure-stop
instruction. All uncommitted research work and local encrypted/evidence assets
remain in place for review; branch/HEAD remain unchanged. No merge, commit or
push occurred, and no further login approval is requested by this attempt.

## Offline Adapter reconciliation (2026-11-15): prepared for one real acceptance

This round accessed no QQ process, login event or real plaintext. The prior
single-capture approval was already consumed. The existing encrypted copy and
sanitized receipts remained available; its SHA256 still matches its manifest.
Branch and HEAD remain `spike/qq-independent-source`, `3136950`; previous
uncommitted work and unrelated untracked assets remain in place.

The actual retained evidence still establishes only 617,487 source rows versus
590,238 Rich/Chat messages, with the 27,249 difference entirely in the unknown
direction category and unequal raw/Adapter endpoints. It contains no native
message-type distribution, sender NULL/zero/blank distribution, individual skip
reasons or endpoint values. Therefore this round does NOT establish that the
real difference is entirely valid missing-sender messages or normal system rows.

Source review and fictional reproduction found a concrete inconsistency:
Provider skips rows whose `40800` is not a nonempty BLOB; Adapter separately
required a stringifiable `40033` even when content was recognized. The same
supported text survived sender `0`, but disappeared for NULL/missing/empty UIN.
Identity mapping already canonicalizes these values to unknown. The Adapter now
preserves recognized content with missing UIN as `sender_id=None`, empty name,
`is_self=None`; incidental names never supply an identity. Invalid sender field
types remain rejected. Newly admitted missing-sender records with only opaque
unknown content remain unresolved and skipped, rather than being declared chat
or system messages. Existing zero-sender compatibility is retained.

The existing parser now offers an optional in-process observer of its actual
decisions. No second protobuf decoder or parallel analysis implementation was
introduced. Its existing tolerant protobuf reader can attach fixed diagnostic
failure categories without changing its decoding behavior. Provider preserves
optional native fields `40011`/`40012` for the selected group when present.
Normal parsing return shapes and ImportService consumers remain compatible.

The research reader records bounded counts for each actual disposition:

- Sender NULL/missing, zero, blank, identified or invalid; own/other/unknown.
- Bounded native `40011`/`40012` codes and per-row `45002` segment types, with
  explicit overflow/other buckets; these are observed codes, not inferred
  system-message classifications.
- Base64 failures, missing supported semantics, unresolved missing-sender
  content, invalid field types and concrete protobuf structural errors.
- Relative time quartiles, invalid timestamps and whether each category
  reaches a raw endpoint. No actual timestamp, sender/group/message identity,
  name, body, URL or blob is serialized.
- Separately, Provider-rejected `40800` storage types, sender states, available
  native types and relative endpoints, queried without selecting body bytes.

Accounting requires every selected source row to be explained, verifies each
accepted Rich/Chat projection's direction, identity and timestamp against its
own raw row, and refuses unclassified skips or malformed accepted content.
No native type has yet been proven a normal non-chat exclusion for this real
copy, so unsupported skips are not allowlisted. Group authorization remains the
previously proven strict same-row `40030` / `40021` check, unchanged. The worker
stdout limit increased from 32 to 48 bounded lines to accommodate these receipts;
the 2,048-byte line limit, owned process cleanup and failure behavior remain.

The earlier research acceptance incorrectly required raw row count and raw
MIN/MAX timestamps to equal every downstream result. It now reconciles the
existing application's raw/import/scope/filtered/analyzed counters instead.
Report volume must equal retained input volume; report time uses valid dates
of kept messages after existing scope, Smart Profile and quality filters.
Activity, conversation summaries and view counts/calendar span must agree.
Report own/unknown-identity counts are checked separately from raw directions.
`analyzed_messages` now uses the actual analyzed counter, rather than the
historically raw `processed_message_count`. Analysis, filtering and report
implementations themselves were not changed.

Offline validation:

- 163 focused regressions passed: Adapter content/replies/media, Import,
  Provider, unknown identity/global versus participant statistics, Rich filter
  associations and existing private-nudge identity protection. The environment
  lacks jieba's default dictionary; tests explicitly reused the already pinned,
  SHA256-verified local research dictionary without installing dependencies or
  changing the environment. Initial unconfigured dictionary failures were
  environment failures; the configured rerun passed.
- Existing owned-native fixture -> codec -> Provider -> Adapter -> Analysis ->
  HTML/JSON wiring passed for both reserve-48 and reserve-80 fictional formats.
  Four imported rows included two missing senders; the normal long-text quality
  filter retained three. Report endpoints legitimately narrowed and passed.
  Conflicting/missing group witnesses still refused. Invalid-body metadata,
  malformed protobuf and opaque missing-sender content diagnostics were checked;
  unexplained skips refused after emitting counts. Fixture temporary data and
  owned native resources were released.
- A separate **fictional** same-count fixture used 617,487 rows, deliberately
  assigning 27,249 NULL senders and 8,624 zero senders to reproduce one possible
  explanation of the historical counts. This is not evidence about the real
  rows. All 617,487 imported; existing quality filtering removed 619, leaving
  616,868 report messages, including 3,342 own and 35,837 unknown-identity
  messages. Raw/import/report endpoints differed as intended. Count, direction
  and retained-date verification passed, and existing HTML/JSON generation
  completed in 78.45 seconds including fixture construction. Its temporary
  fictional database, payload and report were removed.

The disposable same-count reproduction script and numeric validation receipt
remain in ignored `build/qq-adapter-offline-20261115/` for review/reproduction.
Their only inputs are fabricated data and the existing reserve-80 empty seed;
they are not release assets. Keep these until this change is reviewed and real
acceptance is resolved, then review their exact owned scope before disposal.

Missing real evidence and the next minimal authorized run:

1. Reuse the unchanged frozen encrypted image and proven full-decode components.
   Revalidate hashes/resources/ownership and create a fresh marked attempt and
   report directory. No consumed attempt or approval is reused.
2. After separate approval, bind one exact pre-login QQ generation and wait for
   durable `armed` before the user logs in once. Stop observation and release
   the key consumer under the existing verified sequence.
3. Reprove full integrity and strict same-row identity for the authorized group.
   Capture the above bounded metadata in that same run. This will determine
   how many of the historical missing rows were Provider body exclusions,
   valid missing-UIN content, opaque/unsupported content or genuine errors,
   and which categories explain the raw endpoint difference.
4. If all records reconcile without guessed exclusions, immediately reuse the
   existing application to generate HTML/JSON, verifying retained counts,
   report directions and filtered time span. If an unresolved condition remains,
   retain only its numeric/type/reason evidence and stop; no automatic retry or
   additional login request.
5. Always remove temporary plaintext/payload/key state through existing ownership
   cleanup; leave QQ for the user's normal exit and verify release afterward.

There is still **no real QQ HTML report**. Frozen/Setup/Full release acceptance
was not performed; these focused/local checks make no release claim. No cipher,
key acquisition or group-binding code was changed in this round; no commit,
merge, push, branch change or disposal of prior research assets occurred.

## Approved real Adapter diagnosis: missing bodies proven; research counter refused

The user approved one capture after the above offline preparation, opened QQ,
and logged in only after the new attempt's durable `armed` status. Exact native
build/resource hashes, the frozen encrypted image, dictionary, memory, protected
root ACL and fresh process generation were checked. The decryption-role hashes
still matched the previous successful real capture. An independent query/exit
synchronization handle was retained for the user's later normal-exit verification.

All 225,957 logical pages again authenticated/decrypted, the 3,419 all-zero
capacity pages passed, image finalization passed, and SQLite integrity was `ok`.
Authentication/writing reached the logical end at 7,519 ms, and finalization
started at 8,295 ms. Process/module/resource identity passed. The same strict
group binding again proved all 617,487 rows, including 35,193 zero-number rows
whose same-row group object matched; conflicts and unproven rows remained zero.

The new real metadata decisively located the previously unexplained difference:

| Stage / fact | Actual count |
| --- | --- |
| Authorized database source rows | 617,487 |
| Provider excludes because `40800` is SQL NULL | 27,249 |
| Provider materialized rows | 590,238 |
| Adapter accepted rows | 590,238 |
| Adapter skipped rows | 0 |
| Rich/Chat identity, direction or timestamp mismatches | 0 |
| Protobuf structural errors | 0 |
| Newly recovered NULL/missing-sender content | 0 |
| Accepted own / other-known / unknown direction | 3,346 / 578,268 / 8,624 |

All 27,249 Provider exclusions have zero sender identity and native field
`40011=1`; `40012=0` occurs 1,488 times and `40012=1` occurs 25,761 times.
Separately, 1,488 excluded timestamps fail normalization and 25,761 normalize.
These are marginal counts; no subtype/time joint distribution was logged.
Every accepted row has a normalizable timestamp. The source raw minimum fails
the timestamp normalizer; the accepted maximum matches the raw maximum. Relative
quartiles were unavailable because their raw lower bound was invalid. Actual
timestamps, identities and bodies were not logged.

Thus the difference is NOT content lost in Adapter conversion or 27,249 valid
messages with NULL sender. It is already excluded by the Provider's existing
nonempty-BLOB requirement. These source rows have no body available for analysis;
the evidence does not establish their business meaning as system events,
placeholders, recalls or deleted messages. They must not be fabricated into
messages merely to match database volume. The earlier independent NULL-sender
bug remains covered, but did not explain this actual copy.

The experiment still stopped before Analysis/HTML: the research reader wrongly
required Provider rows to equal all source rows despite having emitted the exact
exclusions. Its precise refusal was `provider_record_accounting_mismatch`; the
outer worker subsequently refused. This was an incomplete research acceptance
rule, not a new cipher, ownership or Adapter defect. No real report was generated.

Post-attempt verification found zero owned helpers, owned temporary trees,
plaintext databases and selected payloads. The failed attempt's report directory
contains zero files; previous evidence remains untouched. The encrypted-copy
SHA256 still matches its original manifest. Numeric cleanup and diagnosis were
appended to this attempt's private receipt. Observation was stopped; normal QQ
exit/release remains separately verified through the retained generation handle.

After that worker had exited and plaintext was removed, the offline research
counter was corrected using the observed structural evidence. It reconciles
source rows as Provider rows plus verified unavailable-body rows, and reconciles
unknown directions with the same exclusion count. The currently admitted
exclusion requires SQL NULL `40800`, zero sender, integer native `40011=1` and
integer `40012` in `{0,1}` on the already-authorized partition. This labels
missing available content, not an inferred event type. Other malformed/missing
field combinations remain `provider_unclassified_records`; no fixed real row
count is hardcoded as success. All rows, including unavailable bodies, still
undergo the unchanged strict group proof BEFORE any exclusion.

Application raw/import counters describe the materialized payload, while the
research source counter separately retains the full database row count. The
report continues to require the existing application's actual retained input
count, direction and filtered valid-date span. Provider/Adapter/Analysis/Report
production behavior and key acquisition/decryption were not changed after this
experiment. The changed acceptance was not run against real data in this attempt.

Both reserve-48 and reserve-80 fictional native-to-HTML checks passed again:
six source rows reconcile as two verified unavailable-body rows plus four
imported messages, with three retained after existing quality filtering. Invalid
raw time bounds and a later unavailable-body row do not extend report time.
Six other unavailable/invalid-body shapes refuse; group conflicts still refuse,
and malformed/opaque content diagnostics remain covered. This is offline
evidence, not real report acceptance.

A second disposable **fictional** same-count fixture reproduced the now-observed
unavailable-body shape: 617,487 authorized source rows, 27,249 NULL-body/zero-sender
rows with the observed native-code membership, and 590,238 materialized/converted
messages. Existing quality filtering retained 589,646 report messages, including
3,342 own and 8,615 unknown-identity messages. Source/exclusion/import/report
accounting, direction and filtered valid-date verification passed; HTML/JSON
generation completed in 377.62 seconds including construction and checks. All
fictional temporary database/payload/report files were removed. This fixture
does not reconstruct the real chat content or subtype/time joint distribution,
and does not establish real Analysis/HTML behavior or timing. Its disposable
script and numeric receipt remain beside the earlier offline reproduction until
review and real acceptance are resolved.

Per the agreed failure-stop boundary, this single capture ends here. No retry,
additional key capture or next-login request was made. The real HTML report
remains outstanding; this experiment's key/plaintext state was not retained.
Branch/HEAD and all previous uncommitted assets remain; no commit, merge or push.

## Final offline acceptance review and component release

The user reported normal QQ exit and requested final offline review before any
next capture. No new QQ session, key observation or real plaintext read occurred.
The previous single-capture authorization remains consumed.

Release is now verified. Live process enumeration found zero QQ processes, zero
experiment helpers and no live selected PID. The earlier exit monitor had timed
out before the user's exit and closed its handle; its timeout is not exit proof.
The original terminated kernel process object was still queryable. A fresh
query/synchronization handle matched its exact creation ticks, observed the exit
signal, obtained native exit code **0**, and closed successfully. This completes
component release by actual process exit, rather than window disappearance.
The private attempt receipt records both the monitor timeout and this later
positive kernel evidence. Owned temporary trees, plaintext and selected payloads
are absent; the encrypted image still matches its original SHA256.

The exclusion review uses source facts and the Provider's existing contract:

- All 27,249 unavailable-body rows are SQL NULL in `40800`, zero sender,
  integer native `40011=1`, and integer `40012` in `{0,1}`. The recorded marginal
  counts prove membership in that condition for every excluded row; no
  subtype/time correlation is assumed. Their business event meaning remains
  unclassified, and no chat message or sender is fabricated.
- The strict group proof covers ALL 617,487 rows before body exclusion. Excluded
  rows cannot hide a nonzero conflicting group, a missing same-row witness or
  an unauthorized partition.
- Source volume reconciles as `617487 = 27249 + 590238`; unknown direction as
  `35873 = 27249 + 8624`. Own and other-known directions remain 3,346 and 578,268.
  The Adapter accepted all 590,238 Provider records with no field mismatch or
  protobuf error. The earlier missing-UIN content fix is separate from these
  absent-body rows.
- Application raw/import counters refer to the materialized payload, not every
  database row. Report count and time span refer to messages retained by the
  existing application filters. Neither final report count nor raw timestamp
  endpoint equality is forced to match database volume or its invalid minimum.

The review found one further research-only status error: the owning application
can successfully generate HTML/JSON with `expression_only` status after lexical
content is absent/filtered. The research verifier had accepted only `completed`.
It now accepts these two existing success statuses, still requiring artifacts
and every count/direction/time check. Statuses without a valid report are not
admitted. No analysis algorithm, production status, group guard or cipher changed.

Final validation used the current checkout's explicit virtual-environment Python
and isolated synthetic user/cache/temp directories, with the pinned dictionary:

- 185 focused tests passed; one pre-existing NapCat archive/bundled-Node audit
  skipped because its pinned archive resources were unavailable. No dependencies
  were installed and that archive path is not part of this independent reader.
- Both reserve-48 and reserve-80 owned-native fixture-to-HTML/JSON checks passed.
  The normal filtered-report case and an actual expression-only report both
  completed. Missing/extra Provider rows cannot be hidden by subtracting the
  body exclusions twice. Six unproven unavailable-body shapes, group conflicts,
  malformed content and unexplained skips still refuse.
- The earlier 617,487-row fictional unavailable-body fixture already established
  `617487 -> 590238 -> 589646` source/import/retained accounting with generated
  HTML/JSON and verified direction/time. This review did not repeat that costly
  run: the new production-path check concerns status admission and metadata;
  its existing completed-status accounting path did not change.

Preparation for the next single report acceptance passed without starting QQ:
encrypted-copy hash/ownership/ACL, unchanged successful decode-role hashes,
native binary receipt hashes, exact QQ 54395 installation resources, dictionary
and memory checks passed. A new attempt identifier is reserved; its attempt and
report directories remain uncreated so the existing exclusive creation guard
can own them. No prior failed report or receipt is overwritten. A fresh process
generation must be selected after separate authorization, and the user must
wait for durable `armed` before logging in once.

After approval, the next run will reuse the frozen image, reprove full integrity
and strict group identity, reconcile the actual source/Provider/Adapter counters,
and immediately run the existing Analysis/Report chain. The final report count
is intentionally not predetermined; it must agree with the actual retained
application input. Unclassified exclusions, conversion mismatches or report
inconsistency still stop the run with cleanup and no automatic retry.

The real HTML report is still outstanding. No new real operation is authorized
by this preparation alone. All uncommitted work remains on
`spike/qq-independent-source`, HEAD `3136950`; no merge, commit or push. Frozen,
Setup and Full release acceptance were outside this research check. Local
numeric receipts and disposable fictional reproduction assets remain for review
until this change and real report acceptance are resolved.

## First real independent QQ HTML report accepted

After separate explicit approval, one fresh QQ 54395 process generation was
selected and armed before the user's single login. The unchanged reviewed
capture/decryption path reused the protected frozen encrypted image; no new
cipher investigation, source-database modification or automatic retry occurred.
This report describes that frozen image, not subsequent live QQ writes.

All 225,957 logical pages authenticated and decrypted. The image finalizer
verified the logical boundary and the 3,419 trailing zero-capacity pages;
SQLite integrity returned `ok`. Strict identity proof again covered all 617,487
selected rows before excluding any unavailable bodies: 582,294 had an explicit
matching `40030`, and 35,193 had zero `40030` with a matching same-row `40021`.
Unproven or conflicting rows: zero. No group guard was relaxed.

Real accounting passed with the actual application counters:

- Source: 617,487 rows; verified unavailable-body exclusion: 27,249 rows;
  Provider output and Adapter accepted input: 590,238 messages. Conversion
  skips, unexplained exclusions and field mismatches: zero.
- Every excluded body was SQL NULL, with zero sender and the previously
  verified integer native-code condition. These are unavailable bodies, not
  proven system/recall events. Their business meaning remains unclassified;
  no sender or content was invented.
- Existing analysis filtering retained **588,452** messages, excluding 1,786
  imported messages. Source and application raw counters were kept distinct;
  no equality with database volume or fictional-fixture totals was imposed.
- Imported directions were 3,346 own, 578,268 other-known and 8,624 unknown.
  The report retained 3,341 own and 8,624 unknown-identity messages. Direction
  checks passed against the existing model and report profile.
- Timestamp fields and the retained valid-date span passed. For this actual
  report, the retained endpoints also equal the Adapter's valid endpoints;
  the invalid raw database minimum did not determine the report range.

The existing Provider, Adapter, AnalysisApplicationService and Echo Report
pipeline completed with `completed` status and generated HTML plus JSON.
This is the first successful real independent QQ report in this research:
no NapCat acquisition/runtime was used. Postflight local verification parsed
both artifacts without emitting names, identities or message excerpts:
embedded HTML data equals JSON, both report 588,452 messages, hourly/weekday
totals agree, and the viewer message total is 3,341. Artifact hashes and bounded
aggregate receipts remain private. Report ownership/ACL and Git exclusion were
verified. Automated checks do not establish every message's semantic fidelity;
the user can inspect the local report for that remaining manual acceptance.

The user normally exited QQ while analysis continued from the independent
copy. The generation-bound kernel monitor observed the exit signal and native
exit code **0**, verified component release by process exit, and closed its
handle. Final enumeration found zero QQ or experiment helper processes. The
runner exited successfully and emitted its cleanup receipt; postflight found
zero temporary databases, selected payloads or owned session/owner temporary
trees. No key or raw login response was saved. The retained encrypted image
still matches its original size and SHA256. QQ's original database was not
modified by the experiment.

No production or research executable code changed during this live run. The
preceding offline evidence remains 185 focused passes, one resource-dependent
skip, both reserve-format fixture-to-report checks, and the same-count fictional
accounting reproduction; these are separate from the real acceptance above.
Frozen, Setup, Full release and cross-machine acceptance were not performed.

The generated report pair and protected encrypted image remain local and
ignored for user review; previous failed attempts and all uncommitted research
work are preserved. Their disposition awaits review and explicit asset/Git
instructions rather than automatic deletion. Disposable offline reproduction
assets remain with their bounded receipts for reviewing the change. Branch
`spike/qq-independent-source`, HEAD `3136950`, are unchanged. No commit, merge,
push or further login request occurred.

## Sticker media diagnosis of the first real report

The user observed missing sticker images and authorized read-only examination
of source and aggregate report fields, plus a minimal fix verifiable with
fictional data. No QQ login, key observation, real database/plaintext access,
real cache/media content read or real CDN request occurred in this investigation.
The original real HTML/JSON pair remains byte-identical to its delivery hashes.
Only numeric sticker fields and fixed media states were extracted from the
existing JSON; arbitrary authored strings, member labels and media payloads
were skipped without decoding or emitting them.

The real report is not missing sticker sending statistics:

- `stickers.available` is true, with **58,264 sends**, **5,677 distinct
  materials**, 1,883 unresolved-identity sends and zero unattributed sends.
  Covered messages: 588,452. Of 538 member entries, 258 have nonzero sends;
  their send counts sum to 58,264. Shared/exclusive material counts are
  1,160/4,517. These are distinct from expression-culture counts.
- There are **553 selected display assets**, all with empty `data_uri`:
  **526** are `not_requested/no_trusted_roots`, and **27** are
  `unsupported/original_digest_unproven`. Exported media files: **zero**.
  The latter generic resolver reason does not prove a missing sending identity:
  MFACE resource coordinates intentionally are not an original file MD5.
  The JSON does not establish how many of these 27 have recoverable MFACE
  coordinates versus only legacy opaque evidence.
- Expression culture is also populated: 42,922 expression-containing messages,
  28,560 expression-only messages and 919 expression keys. These are not the
  sticker-send count and do not establish media recovery.

Source tracing locates the earliest missing step at report composition:

1. QQDatabaseProvider materializes the unchanged base64 message blob and PIC
   locator columns. The Adapter builds original RichMessage contents, including
   ExpressionContent/NonTextContent, StickerIdentity and compact QQPicMediaFact.
   ImportService keeps both the Rich graph and its legacy projection. The
   independent script does not replace this with a legacy-only export.
2. AnalysisApplicationService calls `collect_sticker_sends` on kept Rich pairs,
   aggregates members/materials, and builds `view.stickers`. The real JSON's
   nonzero totals establish that this stage ran; the original in-memory result
   and its compact locators were not retained for new post-hoc inspection.
3. The independent experiment called `execute()` with default empty
   `sticker_media_roots` and immediate export. Its generic local resolver has
   no authority to read PIC files and does not implement MFACE resource
   recovery. It therefore produced the exact two failure states above.
4. Formal QQ reporting first obtains narrow PIC scopes from the authenticated
   account/runtime generation, supplies source media context, defers export,
   selects report targets, and invokes Facade media preparation. That owning
   implementation uses PIC local validation and MFACE local-cache/raw200
   recovery, followed by `export_sticker_report`. The independent composition
   omitted that entire preparation step and its trusted scopes. Supplying roots
   to the generic resolver alone would still not run MFACE recovery.
5. The serializer and HTML template consume the selected assets and their
   addresses. Empty addresses yield placeholders; no exportable image bytes
   reached the HTML writer. This identifies an upstream recovery omission,
   not evidence that HTML discarded successfully recovered assets. Real visual
   rendering was not inspected through a browser in this diagnosis.

The minimal fix stays in the existing research composition. An explicit
`--recover-sticker-media` option now defers the first export and reuses
`ChatAnalyzerFacade._prepare_qq_report_media`, then the existing
`AnalysisApplicationService.export_sticker_report` and serializer. Repeatable
`--sticker-media-root` arguments provide only caller-authorized narrow scopes;
roots without the recovery option and media options without full-read selection
refuse before capture. Recovery is opt-in: this diagnosis never grants access
to real caches or CDN resources. A default run still produces statistics and
now reports that recovery was not requested.

The helper Facade has no QQ connection, source builder or runtime identity.
Thus it cannot instantiate/acquire NapCat, discover account directories or
perform native PIC downloads. Confirmed PIC uses the existing authorized-root
and full-file digest/decode validator; confirmed MFACE uses the existing
bounded local/cache/CDN worker. Missing PIC cache content stays unavailable;
opaque or ambiguous MFACE evidence is not promoted to a resource locator.
The research composition closes its owned stored media after export, including
on export failure. No Adapter, core sticker algorithm, downloader, group guard,
cipher or production Facade behavior changed. A new bounded sticker receipt
records retained sends by fixed identity basis, compact PIC fact count, selected
asset states and address count without identities, paths or content.

Verification used only fictional inputs and the existing isolated interpreter:

- Extended the existing native-to-report check with four kept mixed PIC/MFACE
  messages: eight sends, two materials and four compact PIC facts. Disabled
  recovery reproduces the empty-image problem without losing sends. Explicit
  recovery yields one validated local PIC asset and one MFACE preview; both
  local MFACE and mocked-CDN cases export the expected bytes and HTML-relative
  media paths. The fixture forbids QQ-provider access. Workers release and
  disposable databases/payloads/reports clean up. Both reserve-48 and reserve-80
  complete fixture chains pass, including prior identity/count/time refusals.
- 144 focused tests passed, with three marked slow cases deselected. Coverage
  includes Rich import, sticker statistics, cache/CDN validation, formal media
  export and cancellation/export-failure ownership. Initial test invocation
  failed due Windows spawn from standard input and overly long temporary paths;
  a real guarded launcher and short isolated pytest root resolved those harness
  conditions without changing production code. The rerun above is the valid
  test result.
- Explicit media-option admission checks pass without opening a QQ process or
  database. Git whitespace checks pass; original real artifacts are unchanged.

This is an offline composition fix, not real-media recovery acceptance. The
current report JSON intentionally contains presentation asset keys rather than
trusted PIC/MFACE recovery locators, so it cannot reconstruct the discarded
compact sending facts for this repair. A future separately authorized real run
must retain those facts in memory through the new media stage and supply
explicitly authorized cache scopes. No new login or authorization was requested
in this investigation. Local aggregate receipts and fictional reproduction
assets remain ignored for review; the existing real report and encrypted image
remain protected. All work stays uncommitted on `spike/qq-independent-source`,
HEAD `3136950`; no main change, merge or push occurred.

## Real sticker-media acceptance preparation

The user requested actual media acceptance, with separate authorization before
any new key observation. This preparation did not start QQ, capture a key,
decrypt a real database, read real cache-file content or request real CDN media.

Read-only scope discovery examined only the explicitly selected account. Its
default Documents account skeleton exists but does not contain the required
media roots. QQ's existing data-path configuration identifies a different
account root. Appending only the already authorized account, without enumerating
other accounts, found **60 existing narrow PIC/emoji original scopes** and
**one existing MFACE scope**. Only month-directory metadata was enumerated;
all ancestors were checked for reparse points. No directories or cache files
were created, changed or removed in QQ's data tree. Private locations remain in
controller memory rather than this document or public receipts.

The research composition now validates every explicit media root against the
formal account/layout contract before capture and again before analysis. It
reuses the existing safe-path checks and PIC scope coalescer; it does not
implement another media-directory locator or infer authority from message path
hints. Wrong-account roots, broad parent directories and linked paths refuse.
The 60 original scopes plus MFACE scope pass this check. PIC inventory receives
only the original scopes; the MFACE directory is read by its existing exact
resource-coordinate recovery component rather than traversed for PIC files.

A transient research observer records the existing local resolver's fixed
status/reason for selected PIC targets before the formal no-connected-provider
fallback overwrites it. It retains neither bytes nor locators in diagnostics.
This enables reconciled target categories: PIC local success, MFACE local
success, MFACE raw200 preview, insufficient evidence, PIC cache unrecovered,
resource unavailable, budget-limited and other failures. A name/path miss or
digest mismatch means this authorized lookup did not recover an original; it
does not prove deletion or absence elsewhere. Final reason counts remain
available separately. The receipt also records priority-target coverage,
usable assets, animated-GIF assets and distinct exported files: several assets
may legitimately share one digest-named exported file.

Priority review reproduced one scheduling defect with fictional sends:
MFACE resources were queued in historical send order rather than selected
report order. The shared Facade now passes the same selected target order to
the existing MFACE recovery component. A focused regression failed before and
passes after this two-line scheduling change. Neither selection/ranking nor
the downloader, integrity checks, concurrency ceiling or **30/45-second stage
budget** changed. Report leaders get their chance before the member long tail;
553 targets do not authorize extending the budget until everything succeeds.

Offline evidence for this prepared composition:

- Both reserve formats completed the existing owned-native fixture chain.
  The updated reserve-80 media fixture uses **61 fictional, account-bound
  scopes**, including the existing PIC coalescing path. It preserves eight
  sends, two materials and four compact PIC facts; local PIC plus local or
  mocked-CDN MFACE recovery produces the expected classifications and exported
  relative paths. Wrong-account and broad-root admission checks refuse.
- **145 focused tests passed; three marked slow cases were deselected.** This
  includes the new priority regression and the preceding Rich/statistics/media
  export and failure-ownership coverage. No dependency changes were required.
- An actual isolated local browser opened a fictional report over `file:` with
  its exported `media/` file: the sticker chapter was visible, the sampled image
  decoded, and real compositor captures of the GIF showed frame changes.
  Browser traffic was restricted to local resources, and only aggregate counts
  left the check; screenshots/pixels and DOM content were not emitted. The
  browser-plugin bootstrap was unavailable due its runtime import restriction,
  so the local check used a fresh owned headless-browser process/profile rather
  than an existing user browser session. Browser-tree exit was positively
  verified before its new profile was removed. The first canvas/virtual-time
  probe did not prove animation and was replaced by actual rendered-frame
  sampling; no image or report implementation was changed to satisfy it.
- Preflight revalidated all 61 real directory scopes using metadata only, the
  protected encrypted-copy SHA256, unchanged native-binary receipt hashes,
  exact installed QQ 54395 resources, dictionary identity, memory availability
  and current-checkout source import. A private numeric receipt freezes the
  reviewed code hashes. QQ process count is zero. The fresh attempt identifier
  is reserved; its attempt/report directories remain uncreated.

The next separately approved single run will reuse the proven frozen-image
capture/decryption and strict selected-group proof, enable media recovery with
these exact account scopes, keep the existing 45-second budget, and export to
a fresh report directory. The old report is preserved. Acceptance will require
all selected targets to reconcile into the actual outcome categories, compare
unchanged sending/statistical totals, verify actual media files and their HTML
references, and sample offline browser display/GIF playback. An unavailable or
static GIF is not an animation pass; incomplete work must be reported explicitly.
The final count is usable display assets plus classified unavailable targets,
not an assumption that all 553 become images. No automatic capture retry is
authorized. Keys, temporary plaintext and owned browser profiles follow their
existing cleanup boundaries; QQ exits normally under user control.

**Real recovery is still pending separate capture authorization.** No new real
PIC/MFACE recovery quantities or real GIF-display result exist at this point;
the earlier zero-image report remains unchanged. The new private preparation
directory holds only synthetic display assets, checker code and bounded
receipts for the imminent acceptance/review. Existing research assets remain
protected and uncommitted on `spike/qq-independent-source`, HEAD `3136950`.
No main change, commit, merge or push occurred.

Preparation housekeeping note: the last isolated browser check removed its
new profile after verified tree exit. Automatic approval review subsequently
blocked recursive removal of earlier, already exited **fictional** browser
profiles/probe files, returning only `blocked by policy`. Those task-owned
synthetic leftovers remain private and ignored for review; no alternative
deletion route was attempted. This does not authorize access to real media or
prevent the separately gated real acceptance.

## Single authorized media-acceptance observation: no target event

The user separately approved one real observation and opened QQ before login.
The prepared runner bound the fresh selected process generation, revalidated
the frozen encrypted image and the explicit media scopes, and durably recorded
`armed`. An independent read/query/synchronize monitor was bound to that same
generation before capture. The user was instructed to log in only after the
durable armed receipt was confirmed.

This observation ended with `no_target_event`: `event_seen=false`,
`authenticated=false`, and no first-page authentication. The helper confirmed
`observation_stopped=true`, `reads_stopped=true`, `hook_disabled=true`, and
`inflight=0`. Its final resource and process-generation checks passed. The
runner correctly refused with `full_snapshot_not_authenticated`, followed by
the outer `owned_worker_refused`; it did not enter decryption, Provider,
Adapter, media recovery or export. No automatic retry was made. The bounded
receipt does not establish why the target event was absent, or precisely when
the user's login action occurred relative to the observation window.

The new attempt contains only its ownership marker and bounded verification
receipt; no report directory was created. The owned temporary directories are
gone, and no capture runner/worker remains. Only the independent exit monitor
continues waiting for the user's normal QQ exit. There is no captured key or
new plaintext/report/media artifact to retain. SHA256 checks confirm both old
report files are unchanged.

The stopped helper explicitly reported `component_unloaded=false` and
`resources_retained_at_stop=true`; disabling the hook was not a full release
claim. The user subsequently exited QQ normally. The already bound monitor
confirmed the selected generation's process-exit signal, verified native exit
code **0**, and closed its handle successfully. Its durable receipt records
`capture_armed=true` and `component_release_by_process_exit=true`; the monitor
itself also exited with code 0. A final metadata check found zero attempt-bound
Python/Node/loader processes, zero owned temporary directories and zero files
in the isolated controller TEMP. The attempt still contains only its marker
and verification receipt. Thus component and helper release is confirmed by
process/handle evidence rather than window disappearance.

Consequently the 553-target real recovery categories, exported media count and
real offline GIF-display acceptance remain **unmeasured in this attempt**.
The previous offline verification still stands; this failed observation is not
evidence of media-recovery failure or success. The consumed single-run approval
does not authorize another login/capture. No production code was changed for
this outcome; research work remains uncommitted on the same branch and HEAD,
without main changes, merge or push.

## Offline observation-window diagnostics after the missed event

The user approved offline preparation before any further real observation.
Tracing the existing transport and native session confirmed a diagnostic gap:
the native session starts its bounded deadline before installation/Ready, while
the controller previously recorded `armed` without a timestamp or remaining
login window. Thus `armed + 120 seconds` would overstate the valid interval.
The earlier receipt cannot establish when the actual login action occurred;
no claim is made that the user logged in late or that timing caused the miss.

The existing JS transport now records UTC observations for request start,
armed, target delivery (if any) and stop, together with monotonic elapsed
durations. Its login deadline is explicitly **conservative_request_start**:
request start plus the unchanged timeout precedes native setup and is a safe
operator cutoff, not an exact native-expiry measurement. Native code, binary
pins, the 120-second ceiling, authentication, key lifetime and cleanup remain
unchanged. No new timer, retry, command matching or payload diagnostic was added.

The existing approved bridge forwards these fixed timing fields. The Python
receipt writer adds UTC recording time and bounds the remaining login interval
again when it receives armed. An already elapsed armed record produces
`manual_login_window_open=false` and `window_elapsed_do_not_login`; stopped
always produces `observation_stopped_do_not_login`. Timing metadata contains no
account, identity, private path, response or key. Existing line and output-count
limits remain enforced. A controller must recheck the latest durable phase and
current UTC against the stated cutoff immediately before prompting; it must
show the current cutoff/remaining time and promptly hand control to the user.
A later login-confirmation receipt may record only the time confirmation was
received, explicitly not the unobserved instant of the user's actual login.

Offline verification reused the existing fixture checks and explicit isolated
venv/current-source import:

- All eight existing owned-native scenarios passed with timing assertions:
  delivery, authentication refusal, parse refusal, cancellation, timeout,
  controller exit, host exit and identity refusal. No-event timeout still
  refuses; incomplete sessions do not acquire invented armed/stop timestamps.
  Every owned fixture process tree released. Output stayed within the existing
  2048-byte diagnostic constraint.
- The existing complete fictional native-to-database-to-HTML check passed after
  adding receipt assertions for UTC timestamps, live armed, delayed/expired
  armed and stopped prompts. SQLite integrity, strict group mapping/conflict
  refusals, Provider/Adapter accounting, local PIC/local-or-mocked-CDN MFACE
  export and owned temporary-data cleanup passed on the same run. No real QQ,
  real database/cache, CDN request or user configuration was accessed.
- JS syntax and Git whitespace checks passed. An initial inline Python
  environment probe hit PowerShell native-argument quote stripping; a real
  isolated probe file verified interpreter, source and dependency versions
  before the valid integration run. No environment/dependency change was made.

These diagnostics can establish window state at each observed boundary; they
cannot alone prove the unique cause of a future no-event result. The earlier
145 focused media-test result still stands; media algorithms and production
media composition were not changed in this follow-up. The real 553-target
media acceptance remains pending a **new separately authorized single run**.
No QQ launch or capture was performed here. Existing report/encrypted assets
and prior uncommitted work remain protected on `spike/qq-independent-source`,
HEAD `3136950`; no commit, merge or push occurred. Private synthetic checker
assets and bounded validation evidence remain ignored for review until this
diagnostic preparation is reviewed or superseded.

## Next single media acceptance: capture succeeds, total runner deadline reached

The user separately authorized the next single observation and opened QQ
before login. Non-invasive preparation revalidated the same 60 narrow PIC
original scopes and one MFACE scope for the already authorized account,
using only the QQ data-path configuration and directory metadata. Other
accounts were not enumerated. The frozen encrypted copy, installed 54395
resources, native binary hashes, dictionary, available memory and current
source import passed. A fresh attempt and controller were used; the previous
attempts and report were preserved. The selected-generation exit monitor
was bound before capture.

The new timing receipt worked: the target event was observed about 37.4 seconds
after the request, within the unchanged conservative 120-second login window.
The event parsed and authenticated. Native observation stopped with hook
disabled and zero inflight calls before decryption. All **225,957 logical
pages** authenticated and decrypted, with the same 3,419 zero capacity pages
outside the logical boundary. Final resource and process-generation checks
passed; SQLite integrity was **ok**.

All **617,487** selected rows passed the existing strict group proof:
582,294 explicit group-number rows, 35,193 zero-number/same-row-object witnesses,
zero unproven identities and zero object conflicts. Provider again excluded
exactly **27,249** missing-40800 rows, all NULL body/zero sender/native type
40011=1, with 40012=0/1 counts 1,488/25,761; no unexplained exclusion occurred.
Adapter accepted **590,238**, skipped zero and reconciled all source rows.
Directions were 3,346 own, 578,268 identified other, and 8,624 unknown. Direction
and timestamp-field checks passed without fabricating a sender.

The attempt nevertheless **did not generate a report**. After the completed
`messages_verified` receipt, the existing application/report call did not
return within the outer runner's fixed **600-second** total budget. At about
600.522 seconds the supervisor emitted `owned_worker_stop_unconfirmed` and
terminated its owned process tree. This fixed final refusal is not evidence
that earlier authentication failed; the durable authentication/decryption and
identity/count receipts remain successful. No automatic capture retry occurred.

There is no `full_read_result`, `report_verification`, `sticker_verification`
or `sticker_media_verification` for this attempt, and the fresh report directory
contains **zero files**. The last completed public phase is Adapter/message
verification. Existing code discards its verification import and lets the
application perform a second import; this is a confirmed extra cost, not a
measured unique cause of the remaining runtime. The current receipt has no
internal analysis/media/export boundary timestamps, so it cannot prove whether
media preparation was reached or assign the remaining time to a particular
analysis operation. The 45-second media budget was not extended. The 553 target
categories are **unmeasured**, rather than 553 asserted cache failures; exported
media count is zero and real offline display/GIF acceptance was not run.

The enhanced isolated browser/reference checker passed again on fictional
assets only, including actual rendered GIF frame changes. It is prepared to
compare the hash of the complete serialized relative-reference set with the
exported file set, report fixed sticker counts and sampled image decoding,
without emitting identity, text, material bytes or filenames. This synthetic
result must not be presented as real-media acceptance.

The user normally exited QQ after final process checks. The bound monitor
verified the selected generation's exit signal, native exit code **0** and
handle close; component release by process exit is confirmed. After timeout,
metadata checks found zero attempt-bound helper processes, zero owned temporary
directories and zero controller-TEMP files. The attempt retains only its
ownership marker, bounded receipts and an empty report directory; no key,
temporary plaintext or selected raw payload remains. Both prior report-file
SHA256 checks are unchanged. The encrypted copy and prior report remain for
review, as do private ignored controller/synthetic verification assets.

The remaining blocker is completion of the research runner's post-Adapter
report flow within its total budget, with enough bounded phase evidence to
locate any further delay. Real cache/CDN success quantities remain unknown.
This consumed approval does not authorize another login. Existing source work
is preserved uncommitted on `spike/qq-independent-source`, HEAD `3136950`;
no production-code change, main change, commit, merge or push was made during
this real attempt.

## Offline repair of the post-Adapter acceptance runner

The redundant verification import was removed from the research script. Its
existing per-record audit now observes the owning ImportService's actual single
Rich/PIC parse in the dedicated worker and returns those exact parsed objects.
The scoped binding is restored on both success and refusal. Group proof,
Provider exclusions, malformed-data refusal, sender/direction/time checks and
normal application filtering remain intact; no production analysis API,
algorithm, downloader or QQ launch path was changed in this follow-up.

Provider materialization, analysis progress/completion, media preparation and
report export now have bounded phase/duration receipts. Analysis progress
records contain only an ordinal and elapsed time, never callback text. The
fictional wiring check also reserves space for acquisition/result/cleanup within
the existing 48-line forwarding limit. A total-runner expiry now reports
`full_read_total_deadline`, separately from cancellation/worker-stop refusal.

The complete fictional native-to-HTML wiring check passed, including one actual
parse, binding restoration after an injected field conflict, strict group
refusals, known missing-body exclusions, expression-only success, preserved
Rich/PIC facts, local PIC and local/mock-CDN MFACE export. The focused Adapter,
Provider and MFACE selection passed **48 tests**, with three slow integrations
deselected. A first invocation selected an obsolete fixture build, and a direct
pytest invocation encountered the environment's missing default Jieba dictionary;
both were setup errors. Valid reruns used the existing verified IPC fixture and
existing hash-pinned dictionary without dependency/environment changes. Current
venv/source/dependency checks, syntax and Git whitespace checks passed.

A separate fictional row/material-scale timing check was prepared: **617,487**
database rows, **590,238** authored records, the same **27,249** NULL-body/zero-
sender exclusions, **58,264** sticker sends and **5,677** material identities.
Its plaintext SQLite file is **485,646,336 bytes**, not an 896 MiB cipher-geometry
test. Every authored record contains unique long synthetic text, many members
share high-frequency words, and additional synthetic expressions are present;
this deliberately heavy workload does not predict real-corpus duration or the
real report's 553 selected targets. Only fake narrow account scopes and local
fake media are used, with network forbidden by the existing local-only worker.

An initial numeric-counter corpus was cancelled after its artificial repeated-
template workload was identified; it is not a performance pass. The corrected
alphabetic-counter corpus completed analysis in **1,090,819 ms**, but the offline
supervisor's **1,200-second** allowance expired after media preparation started.
That run did not pass export. Its private supervisor also failed to join its
reader before closing pipes; subsequent process metadata found zero fixture-
bound Python processes. Both cancelled/deadline runs retain bounded evidence and
small fake assets for review; their two large DB/payload files were removed only
after checking exact workspace ownership and absence of bound processes.

The candidate 900-second allowance was therefore rejected. The research full-
read runner now has a finite **1,800-second** total allowance; the native login,
authenticated-key/decryption, SQLite and formal **30/45-second media** limits
remain unchanged. A final full-size offline run with that allowance is required
before another real acceptance is requested. Its private supervisor now waits
for the owned tree and registered reader before releasing resources. New checker
staging contains no approval and does not start capture. The previous real
approval remains consumed; no real QQ/database/cache access or capture occurred
during this offline work.

### Final row/material-scale offline acceptance

The final bounded run **passed** using the same corrected heavy fictional
corpus. Fixture creation took 11,907 ms; the complete SQLite/Provider/Adapter/
Analysis/media/HTML path took **1,182,891 ms** (about 19 min 43 sec), including:

- Provider materialization: **44,360 ms**.
- The single audited import and complete analysis/view construction:
  **1,012,230 ms**.
- Media preparation: **44,711 ms**, within the unchanged 45-second allowance.
- JSON/HTML export: **65,629 ms**.

All 617,487 rows reconciled, the known 27,249 exclusions matched, and all
590,238 authored records imported and survived this corpus's normal filters.
Direction, valid kept-message time range, report counters and **58,264** sticker
sends matched. The existing selector chose **517 fictional targets**, not the
real report's 553. Results were **1 PIC local**, **152 MFACE local previews**,
and **364 budget-limited**; all **10 primary targets** were usable. No CDN was
accessed. All 153 usable assets were animated GIFs referring to one deduplicated
fake GIF file, which existed in the report during verification. This file count
reflects intentionally identical fixture bytes, not real-media recovery.

The parser ran exactly once and its binding was restored. Category totals,
exported-file existence and report accounting passed. The owned Windows Job
had zero active processes before resource release; the final supervisor release
receipt passed. Subsequent metadata found zero fixture-bound Python processes
and zero fixture directories. The fictional DB, payload, cache and report were
removed by their own TemporaryDirectory after success. Only bounded numeric
evidence and isolated environment directories remain ignored for review.

The fixed 1,800-second research allowance therefore has measured headroom for
this heavy report plus the separately bounded acquisition stages; it does not
guarantee every real corpus will finish. The real 553-target classification,
export count, offline image display and real GIF playback remain **unverified**.
The previously verified fictional browser/GIF checker is preserved, and fresh
checker staging is unapproved and unstarted. Next work is one separately
authorized real acceptance, with non-invasive preflight before asking for QQ
operations. No automatic login/capture retry is permitted. Existing results and
uncommitted work remain on `spike/qq-independent-source`, HEAD `3136950`;
main, commits, merge and push are untouched. Ignored preparation/evidence assets
are retained only until this acceptance preparation is reviewed or superseded.

## Real 54395 report with sticker media: acceptance passed

The user granted a new single acceptance, manually opened QQ before login,
logged in only after the fresh `armed` prompt, and normally exited after
capture/identity proof completed. No second capture or automatic retry occurred.
Non-invasive preparation verified current source hashes against the completed
offline checks, the same immutable encrypted copy, pinned native binaries,
installed 54395 resources and the existing dictionary. The QQ data-path
configuration and directory metadata confirmed **60 narrow PIC original scopes
and one MFACE scope** under the already authorized account. Other accounts were
not enumerated and no media content was read during preparation.

The target event arrived about **29.7 seconds** after the observation request.
Authentication passed; the hook stopped with zero inflight calls before the
existing authenticated consumer ran. All **225,957 logical pages** authenticated
and decrypted; the same 3,419 zero capacity pages remained outside the logical
boundary. SQLite integrity was **ok**. Resource/config semantics, process
generation and expected loaded-module checks passed before report processing.
The bound normal-exit monitor subsequently confirmed native exit code **0**,
selected-generation exit, component release by process exit and handle close.

Strict group proof again covered **617,487 rows**: 582,294 explicit-number rows
and 35,193 zero-number/same-row-object witnesses, with zero conflicts/unproven
identities. Provider excluded the same **27,249** NULL-body/zero-sender/native-
type rows (1,488/25,761 by the established subtype split), with zero unclassified
exclusions. The actual owning import accepted **590,238**, skipped zero and
reconciled direction/time fields: 3,346 own, 578,268 identified other and 8,624
unknown. The unchanged application filters retained **588,452 report messages**,
including 3,341 own and 8,624 unknown-identity messages. Report counters,
directions and the valid kept-message time range passed; this run's report
endpoints equalled the Adapter endpoints.

The complete attempt finished in about **563.6 seconds**, including cleanup.
Provider materialization took **43,609 ms**; the single audited import plus
analysis/view took **359,266 ms**; media preparation **24,396 ms**; JSON/HTML
export **10,211 ms**. The finite 1,800-second total ceiling and unchanged
45-second media allowance were respected. The existing Facade/Provider/Adapter/
Analysis/Report and PIC/MFACE recovery components were reused. No NapCat runtime,
PIC RPC downloader, replacement parser or analysis algorithm was introduced.

All **553 selected targets** received an explicit disposition:

| Disposition | Targets | Evidence |
| --- | ---: | --- |
| PIC local original | 72 | Original digest and image checks passed |
| MFACE local preview | 13 | Existing pack/resource cache and preview checks passed |
| MFACE raw200 preview | 13 | Existing fixed-CDN path and preview checks passed |
| PIC cache unrecovered | 454 | 401 had no digest-name match; 53 had a candidate digest mismatch |
| MFACE resource unavailable | 1 | Existing raw200 request returned HTTP 404 |
| Insufficient digest evidence | 0 | Selected-target category only |
| Budget limited | 0 | No target stopped for the media deadline |
| Other failure | 0 | No additional target failure category |

The PIC miss counts describe only the authorized search, not proof that a file
was deleted or is absent everywhere. No integrity/source check was weakened to
recover these targets. MFACE resources without original message-digest proof
remain previews. **14 of 18 primary targets** were usable. Sending statistics
remain **58,264 sends**, **5,677 materials**, **258 sending members**; a missing
image does not remove a sending fact.

The report contains **98 usable local media references and 98 actual exported
files**, totaling **52,351,260 bytes**: 91 GIF, six JPEG and one PNG; **65 GIFs
have multiple frames**. Every filename matched its file SHA256 and every image
passed file validation. The complete serialized relative-reference set matched
the exported-file set by digest. All report media references were local to the
retained report/media bundle; the HTML must remain alongside its media folder.

An owned, isolated headless browser opened the actual HTML via `file://` with
external host resolution blocked. The sticker chapter was present, serialized
statistics matched, and all **12 sampled images decoded**. An actual rendered
GIF sample produced **14 distinct-frame changes** across 15 compositor captures;
no screenshot or material bytes were emitted or retained. This verifies a real
animation sample, not playback sampling of all 65 animations. Browser Job exit
and profile removal passed, followed by the complete acceptance checker.

The selected QQ generation exited normally; attempt-bound helpers, owned
temporary directories, controller-TEMP files and browser profiles all numbered
**zero** after completion. No key, raw login response, temporary decrypted DB or
selected raw payload remains. Both hashes of the earlier report are unchanged.
The authorized new HTML/JSON/media bundle and encrypted copy remain in the
existing protected research area; bounded receipts and checker staging remain
ignored for review. No private source/cache path, account/member identity,
chat text or material content is written into this document. Only this record
and ignored acceptance assets changed during the real run. Source work remains
uncommitted on `spike/qq-independent-source`, HEAD `3136950`; main, merge and push
are untouched. Remaining scope is the explicit missing-media evidence above;
GUI/release integration is outside this acceptance. Retained experiment assets
await review of the accepted report and a later explicit retention/cleanup
decision; this acceptance does not grant another capture.
