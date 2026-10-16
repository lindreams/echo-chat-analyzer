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
ANALYSIS_REVISION = "echo-analysis.v6"
