# Independent QQ names and word-review order

Branch: `spike/qq-independent-source`, HEAD `3136950`. Existing uncommitted
work and private accepted-report assets remain protected. No QQ launch, login,
key capture, decryption, NapCat call, commit, merge or push occurred in this work.

## A. Name recovery: omission identified; real recovery remains blocked

Read-only diagnosis used the retained accepted source report. Its **538 members,
537 unnamed members** reproduce the reported copied report's counts. The only
`name_available` member is the viewer fallback, not a recovered contact name.
The serialized remark/context-name counts and named non-viewer count are **0**;
the conversation name is numeric. Existing display-name coverage is **1/538
(0.19%)**, while recovered human-name coverage is **0/538**. No member identity,
name, chat text, timestamp or private path is recorded here. The separately
saved `echo-report(3).json` was not located by scanning user folders; the
diagnosis and preview use the retained source artifact.

The earliest missing operation is source enrichment after Provider materializes
the selected conversation:

- `QQDirectDatabaseImportService._metadata_names()` uses the old provider's
  group-list and friend-list RPCs for group names, remarks and nicknames.
- `_group_sender_names_with_diagnostics()` uses `get_group_member_all()`;
  `_group_member_data()` keys names by each member's UIN, not an opaque map key.
- `_attach_sender_names()` adds displayName/remark/nickname/groupCard to the
  transient records. The existing service merges friend remarks and member
  cards/nicknames, and passes the named conversation through the Facade.
- The independent `finish_report()` bypasses that source service, supplies no
  equivalent local metadata, never attaches sender names, and omits
  `AnalysisRequestDTO.conversation_names`.
- `qq_db_adapter.py` already accepts those name fields. `identity_names.py`
  selects remark, then group card/context name, then nickname/fallback and
  preserves supplied aliases. Presentation computes `name_available` before
  anonymous member labels. These owners do not need a new naming algorithm.

Only the already authorized account's `nt_qq/nt_db` file metadata, 16-byte
headers and plaintext SQLite schema were inspected. Of 22 DB files, 21 had no
plaintext SQLite header. The sole plaintext SQLite file had telemetry schema;
its rows were not read and it offered no identity/name tables. No other account
or unrelated directory was enumerated.

Exact next-input candidates are now bounded:

| Candidate | Bytes | Current evidence |
| --- | ---: | --- |
| `group_info.db` | 20,972,544 | Existing wrapper signature; not authenticated or decoded |
| `profile_info.db` | 20,972,544 | Existing wrapper signature; not authenticated or decoded |
| `recent_contact.db` | 1,024 | Wrapper only; no encrypted page, excluded from decryption |

The signature is not proof that the same authenticated key/profile works for
these files. Their table/column layouts, group/member fields and any UID↔UIN
witness are **unknown**. They were not copied or decrypted. Current report
source hits for group name/card/remark/nickname are zero; potential source-DB
coverage and conflicts are **unmeasured**, not zero. The 537 unnamed members
currently lack collected metadata; their absence must not be attributed to
deleted contacts, departed members or source conflicts without evidence.

### Minimal next authorized validation

After separate authorization, freeze only the two nonempty metadata candidates
under the existing account/path/read-lock/sidecar/ACL rules while QQ is exited.
Reuse the existing single event/key consumer and page-authentication/decryption
components, with an explicitly bounded metadata-only selection; do not rerun
whole-message analysis or retain a key/raw login response. First-page MAC and
SQLite integrity must pass independently for each candidate; an unsupported
format or missing witness stops that source without guessing parameters.

Inspect schema first. Resolve the external authorized group independently of
local partition IDs. Read name values only for the authorized group and stable
members already present in the report. Prefer an explicit UIN; UID-only rows
require a consistent UID↔UIN witness from the same authorized source. Prove
account/group binding, reject conflicting identities, and leave missing or
ambiguous identities unnamed. Reuse the existing attachment, name priority,
alias and `name_available` semantics. Compare every stable member key, message
attribution and analysis counter before/after enrichment; report only aggregate
source hits, coverage and refusal reasons. Clean temporary metadata plaintext
and keys by the existing ownership rules. No automatic capture retry is allowed.

This is an evidence/selection plan, **not a completed local metadata parser or
an already prepared multi-DB capture runner**. Implementing a schema-specific
reader before seeing authenticated columns would invent a source contract.
No real name recovery is claimed, and no new capture is authorized by this note.

## B. Word-review order: implemented and accepted offline

The raw `language_sources.message_refs` were retained in input order. In the
source report, 1,109 terms had increasing timestamps, zero had decreasing
timestamps, and 11 had only ties/unknown times. Thus the assumption of a
previously descending UI did not match this source artifact. The requested
default **newest first** is now explicit in the display layer.

The existing original-message dialog has a compact newest/oldest toggle using
its current typography and button styling. It sorts a display copy by formatted
timestamp, with import ref as the deterministic equal-time tie breaker. Missing
or unusable legacy timestamps stay last in either order. Each new dialog starts
newest first; toggling retains the rendered page size/preview mode, counts,
summary and chronological context. Source refs/data, filtering and analysis are
unchanged. No mobile implementation or new mobile acceptance was added.

Validation:

- **40 focused tests passed**, four slow cases deselected, covering existing
  identity/name semantics and lexical provenance.
- **Two selected desktop browser cases passed**: the extended 55-hit list
  checks 3/10/20/all pagination, both directions, inert authored text and
  unchanged source data; the new case checks equal-time refs, out-of-order
  input, missing legacy timestamp/context, default reset and desktop overflow.
- A new HTML review copy was generated beside the retained report without
  replacing its HTML/JSON/media. Only the known language CSS, JS and dialog
  footer were replaced, with unique-match guards. The complete serialized
  `ECHO_DATA` literal is byte-identical, preserving **588,452 messages**, all
  member identities, statistics and aliases.
- An owned isolated browser opened that actual copy with external host
  resolution blocked. Default newest, oldest, return to newest, 20-hit
  pagination, summary/data immutability and desktop layout passed. Sticker
  statistics stayed 58,264 sends / 5,677 materials / 258 members; all 98 media
  references stayed local, 12 sampled images decoded, and GIF frame changes
  were observed. Owned browser exit and temporary profile removal passed.

The new review HTML uses the retained adjacent `media` folder; keep them
together. Private checker inputs, bounded receipts and the review artifact remain
ignored for review until the current work is accepted or superseded. Name
coverage remains unchanged in this copy. GUI integration and release work remain
outside this task; A awaits the evidence/authorization above.

## Restricted metadata experiment: authorized; offline gate completed

A later explicit authorization permits one new capture for the same account and
previously authorized group. The word-review implementation is frozen: all three
previously recorded source hashes still match. Existing reports and inherited
uncommitted work remain in place; no commit, merge or push was performed.

The existing research runner now has an exclusive metadata mode. It accepts two
explicit, account-scoped frozen inputs (`group_info.db`, `profile_info.db`), with
the previously accepted encrypted message snapshot used only as the login-key
authentication anchor. It does not decrypt that message snapshot, parse messages,
rerun analysis or prepare media. The two metadata files each use their own prefix,
salt, immutable-file hash, page authentication and existing decoder/finalizer.
The shared signature does not establish key compatibility: a failed MAC or
unsupported source stops the experiment, without alternate parameters or retry.

Preparation requires normal QQ exit and the existing write-denying snapshot
handle, no-sidecar checks and protected workspace ACL. The selection pins the old
report hash and must prove its group and viewer account match the authorized
scope. Only explicit numeric report member keys are eligible for UIN lookup;
unknown sender identities remain unchanged. A new exclusive attempt marker
prevents reuse of this experiment's selection.

After capture and process/resource identity verification, both sources must pass
SQLite integrity checking. Automatic inspection returns table/column names and
types only: no row values, defaults, index SQL, chat text or names. The private
schema is temporary; its persistent summary redacts long numeric identifiers.
The existing owned Job and TemporaryDirectory contain all metadata plaintext.
Review is limited to 1,200 seconds inside the unchanged 1,800-second outer budget;
cancellation, refusal and timeout remove the temporary workspace. The authenticated
key remains inside the existing synchronous scoped consumer and is never saved.

Actual columns remain unknown until that gate passes. The allowed value-read
plan is limited to an explicitly proved authorized group identifier, group title,
member UIN/UID and group card, then remarks/nicknames or UID/UIN witnesses for
those same report members. No other group/member profile values may be queried.
An opaque partition or UID cannot substitute for an external group number or UIN;
an absent/ambiguous relationship stops enrichment. No schema-specific field
numbers or mappings have been invented in advance. Existing name priorities,
aliases and `name_available` semantics remain the owners of display behavior.
Before export, every member key, membership/order, message attribution and all
non-name report data must compare equal; only explicitly allowed name fields and
the unnamed-member count may change. Failed verification produces no new report.

Offline evidence for this preparation:

- One fictional native event authenticated two separately salted metadata inputs
  through the actual restricted consumer and existing decoder. Corrupting the
  second source was rejected independently of the successful anchor/first source.
  Incomplete, reordered and duplicate source selections were rejected.
- Synthetic schema inspection excluded row values and default expressions;
  source/report-hash guards and review refusal/cancellation/timeout were checked.
  The owned native tree exited and all fictional plaintext was removed.
- The existing complete fictional wiring check passed again, including group
  identity rejection, reconciled filtering/directions/time bounds, single audited
  import, real analysis/export, formal local/mock-CDN media preparation and cleanup.
- Existing decoder I/O/finalizer failure diagnostics passed; Python/Node syntax,
  dependency consistency and **26 focused name/identity tests** passed. The
  interpreter and source import were verified against this worktree.

At this checkpoint QQ was still running. The snapshot preparer refused before
copying either real metadata file. No capture, real metadata decryption or metadata
value query has occurred; source coverage/conflicts remain unmeasured, with the
accepted report still at 538 members / 537 unnamed. The next required user action
is normal QQ exit so the two snapshots can be frozen safely. Only after that
preparation passes should QQ be opened; login must wait for a fresh `armed`
receipt. This consumes the already granted single authorization, not a request
for an additional attempt. After the eventual experiment, retain only bounded
receipts/new accepted report, remove owned metadata plaintext and unneeded new
encrypted copies, and verify component release against normal QQ process exit.

After the user confirmed normal exit, the process check found zero QQ processes.
Both selected metadata sources were frozen successfully under the existing
read-lock/no-sidecar/ACL rules, at 20,972,544 bytes each. The retained report's
authorized group and viewer-account binding passed; its 538 distinct member keys
are explicit numeric UIN candidates. The prepared selection, exact installed
version/module, native binary hashes and unchanged word-order sources passed
preflight. No capture, plaintext creation or metadata value read has occurred.
The next step is opening QQ without login, then binding that new process
generation and waiting for a fresh `armed` receipt before manual login.

### Single authorized attempt stopped before armed

After QQ was opened without login, one matching main process/generation and its
expected installed module were verified, and the normal-exit monitor was bound.
The attempt then failed in Python input validation, before Node/native observation
started. The operator supplied a relative native build directory; the owned worker
changes its working directory, so `_safe()` could not find that relative path.
This was an invocation error, not evidence about metadata format/key compatibility.
The same path failure was reproduced in an isolated fictional directory; the
absolute build directory resolves correctly there. Any future invocation must
freeze absolute cross-process input paths before launch and verify the actual
arguments, in addition to checking the installed binaries.

There was no `armed`, login request, captured event, acquired key, decrypted
metadata or metadata value query. Read-only module enumeration against the same
selected process generation confirmed this attempt's native event DLL was not
loaded. No owned temporary worker/session directory or schema-review pointer
remained. The two newly owned unused encrypted metadata copies were removed by
exact validated paths; their bounded preparation manifests/receipts remain for
review. The earlier encrypted authentication anchor and accepted report remain
protected; the report hash was rechecked before cleanup.

The attempt is stopped and must not be automatically retried. No new report was
generated: the accepted report remains 538 members / 537 unnamed. Source name
coverage, UID/UIN association and conflict counts are still unmeasured; zero
metadata values read must not be represented as zero source conflicts. Normal QQ
exit and the already-bound monitor's final handle/release evidence are pending.

After the user confirmed normal QQ exit, the bound monitor observed that exact
process generation exit with native code 0 and closed its handle; the monitor
itself also exited with code 0. The QQ process count was zero. Final verification
found no owned temporary worker/session directory, no schema-review pointer and
no remaining new encrypted metadata copy. The accepted report's pinned JSON hash
and all three frozen word-order source hashes still match. No key or metadata
plaintext was produced in this attempt. The attempt is fully stopped; bounded
private receipts/manifests remain for review, and the inherited research assets
remain protected. Name recovery is still unverified; no automatic retry or new
capture was initiated during release verification.

### Offline correction before proposing another attempt

The research owner now validates and resolves the explicitly selected executable,
encrypted anchor, native build directory and metadata-selection path in the
caller directory, before creating an attempt marker. It forwards those absolute
values explicitly when the worker reparses its arguments in the isolated cwd.
No decoder, key derivation, metadata identity semantics or word-order code changed.

The existing wiring checker now covers the real outer Job/temporary-directory/
argument boundary using a fictional Python worker and placeholder inputs, without
QQ/native observation. The relative-build case failed with `owned_worker_refused`
before the correction and passed after it. The enclosing complete fictional
native-event/decryption/group-check/analysis/media/report regression passed too,
including owned-process and temporary-directory cleanup. No real metadata or
account state was used to obtain those test results.

A fresh private controller containing only preparation/verification code has
been staged for review. Current-source/environment, exact installation/module
and pinned native binaries passed preflight; no new real snapshot was copied.
The previous attempt remains stopped and its approval consumed. Another capture
requires a new explicit single-attempt authorization, followed by fresh frozen
metadata inputs, QQ opening, a generation-bound observer and `armed` before login.
The scope and failure-stop conditions remain unchanged.

The user subsequently granted one new attempt. With QQ confirmed exited, fresh
snapshots of both selected metadata files were frozen successfully (20,972,544
bytes each). Account/group binding to the retained 538-member report, prepared
input validation, exact installed module/native binaries and unchanged word-order
sources passed preflight. The actual prepared invocation's five paths (entry
script plus four selected inputs) were verified absolute and existing before any
QQ opening. This new attempt has not captured an event, created plaintext or read
metadata values. Next: open QQ without login, bind its process generation and
wait for `armed` before manual login. The previous failed attempt remains stopped.

### Renewed attempt: armed; no target event before deadline

The corrected invocation reached `armed` with 119,166 ms remaining on the fixed
120,000 ms request-based observation window. Observation stopped after the window
elapsed and returned `no_target_event`: no event was seen or parsed, no key was
authenticated and no metadata snapshot was decrypted. The user's later login
notification arrived after observation had stopped; this does not establish the
actual login time or explain the absent event. No alternate capture or retry was
attempted.

The stop receipt confirms reads stopped, hook disabled and zero in-flight calls;
component resources remain in QQ until normal exit. Installation/resource and
process-generation checks passed. The outer owned worker exited and its temporary
directory was removed; no metadata schema-review pointer exists. Both unused new
encrypted metadata copies were removed through exact owner-validated paths, with
the earlier encrypted anchor and pinned report preserved. No metadata value was
read, no new report was generated and source coverage/mapping/conflicts remain
unmeasured. The accepted report still has 538 members / 537 unnamed. Normal QQ
exit and the generation-bound monitor's release evidence are pending.

The user then exited QQ normally and explicitly requested a new attempt. The
previous generation-bound monitor verified native exit code 0, component release
by process exit and successful handle closure, and itself exited with code 0.
The final owned-workspace/copy checks passed and the accepted report hash still
matched. That attempt remains stopped.

Under the new authorization, a fresh protected controller and two fresh frozen
metadata snapshots were prepared with QQ process count zero. Their account/group
report binding, snapshot validation, installed/native identities and actual
absolute invocation paths passed preflight; word-order sources remain unchanged.
This newly prepared attempt has not started capture or read metadata values.
It awaits QQ opening without login, then fresh `armed` confirmation and prompt
manual login within the existing observation window. No observation budget or
authentication/identity rule was changed to obtain this preparation result.

### Latest attempt: event and anchor authenticated; metadata first page refused

The login event arrived within the observation window (35,406 ms from armed to
stop). It was parsed and the retained encrypted message anchor's first page
authenticated successfully. The first metadata source, `group_info.db`, then
failed at page authentication with `page_hmac_mismatch` on page 1: **0 metadata
pages authenticated, 0 written**, nonzero encrypted page, provisional output
removed, no cleanup errors. Processing stopped immediately; `profile_info.db`
was not attempted. The final `authentication_refused` is the bridge's consumer
failure result and must not erase the earlier successful event/anchor receipt.

Bounded header-only comparison of the frozen inputs established that both
metadata files have the same wrapper signature as the anchor, but each has a
different database salt from the anchor and from the other metadata file. No
salt bytes, identities, names or bodies were printed or saved in this note.
The source code derives the event passphrase into a raw key using the anchor's
salt (`qq_key_source.mjs`), while the new multi-file consumer currently supplies
that same raw key to both metadata decoders. It has therefore not established
per-database passphrase/key binding. Different salts alone do not prove that
these databases share a passphrase/profile, or that a per-source derivation will
succeed; neither alternative parameters nor another authentication was tried.

The positive fictional two-source fixture used one already-derived raw key with
two salts. That proves independent page authentication for raw-key inputs, but
does not cover two passphrase-derived databases with distinct salts. Before any
further real attempt, the offline contract must cover the latter case using the
existing derivation and scoped-secret cleanup, while preserving first-page MAC
refusal for each actual source. This is a source-key-binding gap, not evidence
against the previously accepted full message-database decryption/report chain.
No metadata schema, UID/UIN witness or name coverage was obtained.

The observation stop confirms hook disabled, reads stopped and zero in-flight
calls. Resource/module/process-generation verification passed. The scoped key
consumer ended; no key/raw response was saved. The outer temporary workspace is
gone and no schema-review pointer exists. Both unused encrypted metadata copies
were removed through exact owner-validated paths; the pinned report and prior
message anchor were preserved. Metadata value rows read: **0**. Source name hits,
successful identity links and source conflicts remain **unmeasured**. The accepted
report remains 538 members / 537 unnamed; no new report was produced. The attempt
is stopped without automatic retry. Normal QQ exit and its bound release monitor
remain pending.

The user subsequently exited QQ normally. The exact generation's release monitor
verified process exit with native code 0, component release by process exit and
successful handle closure; the monitor itself exited with code 0. QQ process
count was zero. Final verification confirms no owned temporary plaintext/schema
workspace or new encrypted metadata copy remains. The accepted report's pinned
JSON hash and all three word-order source hashes still match. This latest attempt
is fully stopped; bounded private receipts/manifests remain for review. The
per-database derivation gap above remains an offline prerequisite, with no further
real capture or login scheduled. No commit, merge, push or main modification was
performed; inherited research work remains in place.

### Offline correction: database-specific derivation verified

The source-key-binding prerequisite above is now implemented and verified with
fictional databases. No new QQ observation, login, real database snapshot,
decryption or metadata value read occurred during this correction. The previous
real attempt remains stopped, with its approval consumed and release verified.

The native-event fixture now encrypts the anchor and each metadata database with
the **same passphrase but distinct salts and independently derived raw keys**.
Reusing the anchor raw key reproduces `page_hmac_mismatch`; the earlier positive
raw-key fixture did not test this contract. The corrected fixture failed before
the wiring correction and passes with it.

`withAuthenticatedKey()` now supplies a scoped `withDatabaseKey` callback in
addition to its existing raw-key consumer argument. The callback reuses the
existing derivation, database-prefix binding, first-page authentication and
finally-wipe implementation for each selected database. It borrows only a copy
of the current passphrase lease, shares the original cancellation/deadline and
rejects use after the enclosing consumer ends. Raw-key-only leases cannot derive
other database keys. No secret is returned, persisted or passed to the decoder
except the authenticated database-specific raw key during its synchronous scope.
The existing single-database consumer remains compatible; no KDF, cipher, HMAC,
page layout, native observation window or message-decoder parameter changed.

The metadata branch now uses that callback separately for `group_info` and
`profile_info`. It rejects a raw buffer in place of the scoped callback and has
no anchor-key fallback. A first-page refusal records a fixed, sanitized
`database_key_refused` / `key_scope_failure` receipt. Decoder failures are recorded
before scoped-key exception sanitization so that later-page MAC failures retain
their original stage and authenticated/written counters. Both complete outputs
are required before schema review; the existing outer owned Job and temporary
directory remove partial completed outputs on failure.

Offline verification:

- Both 48-byte and 80-byte SQLite reserve formats passed the existing complete
  fictional native-event, strict group-mapping, Provider/Adapter, analysis, media
  and report wiring regression. For each format, both independently salted
  metadata outputs authenticated every page, passed independent Python SQLite
  `integrity_check = ok`, and matched the finalized source fixture bytes.
- Second-source corruption was refused at both the first and a later page.
  First-page refusal retained 0 authenticated / 0 written; later-page refusal
  retained 1 / 1 and its original `page_hmac_mismatch` receipt. Provisional bad
  outputs were removed and enclosing temporary-workspace cleanup passed.
- Scoped-key checks passed for child-buffer zeroing, parent-buffer cleanup,
  consumer exceptions, raw-only lease refusal, cancellation, the shared original
  deadline and attempted callback use after scope expiry. Existing source
  binding, one-shot acquisition, authentication and cleanup checks still pass.
- Existing metadata selection/report-hash, schema-only output, review refusal,
  cancellation and timeout checks passed. The seven existing fictional native
  refusal/cancellation/process-exit scenarios passed with owned Job release.
  Login-event matching/wrong-key and bounded decoder-diagnostic checks passed.
- The accepted report's pinned hash and all three frozen word-order source
  hashes still match. Diff format checks pass. No production name algorithm,
  word-review UI, GUI integration or unrelated feature was changed.

A fresh protected controller containing preparation/verification code only has
passed static installation/module/native-binary/current-source preflight. It has
no selected real inputs, invocation approval, process target or capture marker;
no real snapshot has been copied. Private offline receipts and source hashes
remain ignored for review. Inherited work and accepted report assets remain in
place, with no commit, merge, push or main modification.

This correction does **not** prove that the real metadata files share the login
passphrase/profile. Their per-source authentication, schema, reliable authorized
group/member mapping and resulting name coverage remain unverified. The report
still has 538 members / 537 unnamed; source coverage and conflicts remain
unmeasured. The next step requires a new explicit single-attempt metadata-read
authorization under the same scope and stop conditions, fresh snapshots while
QQ is exited, then process binding and `armed` before manual login. A MAC failure
must stop without parameter guessing or automatic retry. GUI integration remains
outside this correction and awaits that evidence.

### New single attempt authorized; fresh metadata inputs prepared

The user explicitly authorized one new restricted metadata-read attempt. Its
scope remains the same account, authorized group and existing report members;
no automatic capture retry is permitted. The word-order feature stays frozen.

Preparation initially stopped before any database copy: repeating PowerShell
`Set-Acl` on the already protected controller directory requested the unrelated
`SeSecurityPrivilege`. The QQ-exit assertion itself passed. A fictional empty
directory reproduced first application succeeding and repeated application
failing with `PrivilegeNotHeldException`. Persisting only the changed owner/DACL
sections through `Directory.SetAccessControl` passed first and repeated
application, with protected inheritance and exactly the current user/SYSTEM
FullControl entries verified. The existing owner/protection/principal checks
remain mandatory. This narrow preparation correction requires no elevation and
does not relax source-path, snapshot, authentication or identity checks.

With QQ exited, two fresh metadata snapshots were frozen successfully, each
20,972,544 bytes. Account/group binding to the pinned 538-member report, all 538
explicit numeric member keys, snapshot admission, installed/native binary hashes,
current source and unchanged word-order hashes passed preflight. The actual
invocation's five paths are absolute and existing. No other account directory was
enumerated. No capture has started, no plaintext was created and metadata value
rows read remain zero. Next: open QQ without login, bind the new process
generation, establish the release monitor and wait for `armed` before login.
Earlier attempts remain stopped. No commit, merge, push or main change occurred.

The prepared attempt subsequently reached `armed` with 119,071 ms remaining on
the unchanged request-based 120,000 ms observation window. It stopped after that
window with `no_target_event`: no event was seen or parsed, no key authenticated
and no metadata decrypted. Stop evidence confirms reads stopped, hook disabled
and zero in-flight calls; resource/module/process-generation checks passed.
No metadata schema or values were read and no new report was generated. Both
new encrypted metadata copies were removed through their exact owner-validated
paths. No owned temporary workspace or schema-review pointer remains; the prior
anchor and accepted report are preserved. Component release by normal QQ exit
and closure of the generation-bound monitor handle remain pending.

The user explicitly requested restarting after this stopped attempt. No second
observer was started and the used selection remains one-shot. A fresh attempt
must follow normal QQ exit and verified release of the selected generation,
then new frozen inputs, fresh process binding and `armed` before login. This
restart request does not permit overlapping capture or automatic retry after
another failure; the account/group scope and stop conditions are unchanged.

The user then exited QQ normally. The exact generation's monitor verified
native exit code 0, process-signaled component release and handle closure, and
the monitor exited with code 0. QQ process count was zero. Final checks confirm
no owned temporary plaintext/schema workspace or new encrypted metadata copy
remains; the accepted report hash and all three word-order hashes still match.
That attempt is fully stopped.

While staging the explicitly requested restart, a fresh directory inherited
Modify access without WRITE_OWNER. Reassigning its already-current creator owner
therefore caused `UnauthorizedAccessException`, even with DACL-only persistence
available. Preparation now requires the current user to already own the directory
before changing only its DACL; it never adopts a foreign-owned directory or
requests an unnecessary ownership change. Existing post-protection ownership,
inheritance and allowed-principal checks remain in place. Two empty directories
created by this preparation reproduced the fresh-parent condition and passed
fresh and repeated protection with exactly current-user/SYSTEM FullControl.
Those two exact owned empty directories were removed nonrecursively. No real
database was accessed for these permission checks.

After release verification, a fresh protected controller and two fresh frozen
metadata snapshots were prepared under the user's explicit restart request.
Both snapshots are 20,972,544 bytes. Account/group/report binding, all 538 numeric
member keys, snapshot admission, current installation/native hashes, frozen
word-order sources and all five absolute invocation paths passed verification.
No capture has started, no plaintext exists and metadata values read remain zero.
Next: QQ opening without login, fresh generation binding/release monitor, then
`armed` before login. Scope, budgets and failure-stop conditions are unchanged.
No commit, merge, push or main modification was performed.

### Real names acceptance: independently authenticated metadata and report

The fresh single attempt captured the requested login event within the existing
window (39,367 ms from armed to stop). The anchor authenticated. With the new
per-database derivation, `group_info` authenticated/decrypted all **4,609** logical
pages and `profile_info` all **4,675**; their zero capacity tails were 511 and 445
pages respectively. Both SQLite integrity checks returned `ok`. Observation
stopped with reads stopped, hook disabled and zero in-flight calls. Installed
resources and the selected process generation remained valid. No key or raw
response was persisted; keys were released before schema/value review.

The authenticated schemas contain `group_list`, `group_detail_info_ver1`,
`group_member3`, `profile_info_v2` and `profile_info_v6`. Field interpretation was
cross-checked against the primary implementation
[QQ Local Interface's index reader](https://github.com/Ethan-Wang-dev/qq-local-interface/blob/587b63e880070849240dde3f2bc447d7a7e8b35a/src/qq_local_interface/index.py):
`60001` group code, `60007` group name, `1000` UID, `1002` UIN, `64003` card and
`20002` nickname. That macOS implementation is a field reference, not Windows
54395 acceptance evidence. Only public source was downloaded/read; none was
executed or installed, and no real data was sent to it. The Windows evidence
below comes from the authenticated, explicitly scoped local inputs.

The research metadata owner now contains `scoped_names()`. It queries profile
rows only by existing report UINs and group rows only by the authorized external
group code. UID-only candidates require a unique same-source UID/UIN witness.
It collects all identity witnesses before reading group name values, excludes
conflicting identities, refuses incompatible group titles and does not use
nicknames as keys. Nonzero contradictory UINs cannot be overridden by UID
matching. Unknown remark columns were not guessed or interpreted. Names use
existing `SenderIdentity`, `identity_names` and report member/search semantics.

Scoped results (source-name hit categories overlap):

| Evidence | Count |
| --- | ---: |
| Existing report members | 538 |
| Selected profile rows: v2 / v6 | 29 / 539 |
| Selected group identity rows | 538 |
| Accepted direct-UIN member links | 537 |
| Real UID-only fallback links used | 0 |
| Identity-conflict members withheld | 1 |
| Group card hits | 446 |
| Group nickname hits | 534 |
| Additional profile nickname fallbacks used | 0 |
| Members with recovered name metadata | 535 |
| Non-conflicting members without usable names | 2 |
| Matching group-title rows: list / detail | 1 / 1 |
| Unique consistent nonempty group title | 1 |

The 535 recovered human names plus the pre-existing viewer fallback give
**536/538 name-available members (99.63%)**, up from 1/538; final unnamed count is
**2**. The three identities without new name metadata comprise the identity
conflict and two missing-name cases; the existing viewer display is preserved.
No name was invented, and no conclusion about departed members, deleted contacts
or permanent historical availability follows from these counts. Remarks remain
unverified, so this is not complete remark-source support.

The new private authorized-group HTML/JSON report enriches the accepted report;
it does not reread messages or repeat message-database decryption/analysis. Source
identity binding occurs before projection. Existing unique report display
references are rebound only to their already-known stable member keys, never
used to infer source identity. Only explicitly allowed name/display/alias fields,
the consistent group name and unnamed-member count may change. The comparison
masks only recorded name assignments and requires every other field to compare
equal, including all message text, references, timestamps, counts, order and
statistics. Stable member keys/order, **588,452 messages**, **538 members** and
the sticker manifest are unchanged. All **98 media files** were copied with
matching hashes. The accepted source report remains hash-identical.

The private renderer uses the existing formal HTML/template/CSS/JS and escaped
data encoder boundary with the validated enriched payload and unchanged assets.
It does not introduce a production serializer API or GUI change. The word-order
sources retain their three pinned hashes. The resulting report contains the
already completed order control without any new word-order implementation work.

Verification completed:

- One focused fictional metadata checker covers direct UINs, UID witnesses,
  cross-group/member exclusion, contradictory nonzero UINs, duplicate UID/UIN
  evidence, ambiguous cards, invalid scopes, missing values and group-title
  conflicts. All checks passed using fictional databases.
- **18 existing identity/name regression tests passed**, covering the reused
  priority and alias semantics. No broad test-suite expansion was performed.
- The actual local `file://` report passed an owned isolated desktop browser
  check with external host resolution blocked. All 176 voice cards, 258 expression
  cards and 538 rhythm options matched their bound names; alias search/reset,
  group-name rendering, 98 local media references and order-control presence
  passed. No message body, identity list, screenshot or image pixels were printed.
  The browser tree exited and its owned temporary profile/probe were removed.
- An initial browser assertion incorrectly equated the explicit report cover
  title with the conversation name. Source inspection confirms the formal cover
  uses `data.title`, while the rhythm header uses `conversation.name`. Checking
  each against its actual owner passed; no product change was made for that
  acceptance-script assumption.
- Final receipts confirm metadata acceptance and outer temporary-data removal.
  Both new encrypted metadata copies were removed through exact owned paths;
  no temporary plaintext/schema workspace or review pointer remains. Bounded
  sanitized receipts and the authorized report remain privately ignored for
  review. Normal QQ exit and the generation-bound release monitor remain pending.

This provides real evidence for bounded local name recovery on the accepted
Windows 54395 account/group snapshot. Remaining limits are the withheld conflict,
missing historical names, unverified remark fields and lack of other-version or
cross-machine acceptance. GUI/Facade integration, frozen/setup delivery and a
production metadata import lifecycle are still separate work, not implemented
by this research report. Existing uncommitted work stays on the research branch;
no commit, merge, push or main modification occurred.

The user subsequently exited QQ normally after the successful names report.
The exact generation's monitor verified native exit code 0, signaled process
exit, component release by process exit and handle closure; the monitor itself
exited with code 0. QQ process count was zero. Final release checks confirm no
owned temporary metadata plaintext/schema workspace, new encrypted metadata copy,
review pointer, browser tree or browser profile remains. The accepted source
report and frozen word-order hashes still match. The new report's HTML/JSON
hashes are pinned in its private release receipt, with 538 members / 536
name-available / 2 unnamed unchanged from acceptance. No key or raw response was
saved. This attempt is fully stopped and no new login/capture is scheduled.
The authorized report and bounded private receipts remain for integration review
until this research is accepted or superseded; inherited work remains in place
on `spike/qq-independent-source`, HEAD `3136950`, without commit, merge or push.
