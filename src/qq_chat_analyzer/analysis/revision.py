"""Revision of the analysis semantics recorded in newly generated reports."""

# Advance when acquisition interpretation, identity, filtering, tokenization,
# or statistical rules change results. Presentation-only changes do not advance it.
# v2: local burst bounds, unordered expression pairs, message-level expression
# counts, mixed-expression classification, and intact laughter tokens.
# v3: sender filtering is scoped to the stable sender identity, so messages from
# a member who shares a nickname are no longer removed (Smart Profile decisions
# and burst-run continuity); interactive automation evidence is kept for review
# and never deletes messages on its own.
# v4: literal placeholder text in user messages is escaped before the detector
# inserts its own markers, so a repeated template that contains text such as
# "{number}" can no longer widen its automatic deletion beyond the messages it
# was detected from, nor fail to match them.
# v5: expression rankings retain all candidates so presentation can filter
# stickers and fill the global/member leaderboards without losing lower ranks.
# Combination rankings likewise retain candidates until asset filtering.
# Application report construction retains only raw prefixes and display-selected
# candidates; full rankings remain transient during analysis and selection.
# v6: Unicode 18.0 official emoji sequences, explicit presentation selectors,
# and keycap-safe lexical masking replace broad Unicode block heuristics.
# Member expression context counts and nearby words use that member's messages.
# v7: separate scoped sticker aggregates retain unknown sends and reliable
# material/member identities, with message denominators from the kept Rich scope.
# v8: full sticker frequency ordering and experimental per-member longitudinal
# signature evidence (calendar dates and ISO year/week), shared by conversation kinds.
# v9: copy-and-redeem reward campaigns are excluded by message content even
# when variable codes and wording keep individual templates below the threshold.
# v10: weekday daily averages use one calendar span of kept messages for
# the conversation and all members; unobserved weekdays remain unavailable.
# v11: WeChat group text strips the confirmed non-self sender storage header
# before authored projection, filtering, expression context and lexical analysis.
# v12: exact whole-message repetitions also recognize sentence-length units,
# retaining the three-repeat minimum without the old 12-character unit cap.
# v13: member profiles expose their first appearance order in the retained
# imported records, independent of the existing message-volume ranking.
# v14: verified WeChat private pats have their own scoped interaction channel;
# they never contribute to ordinary message, session or lexical statistics.
# v15: QQ private pokes share the independent interaction channel after
# authenticated UID/UIN binding and agreement of both gray-tip representations.
ANALYSIS_REVISION = "echo-analysis.v15"
