% Trusted operator code. Never auto-consult an LLM output or downloaded KB.
% Copy selected clauses into the plugin-private config.pl seeded by install.
:- multifile zara_policy:option/2, zara_policy:user_rule/6,
             zara_policy:disabled/1, zara_policy:suppress/2.

zara_policy:option(mode, advice).
zara_policy:option(max_findings, 8).
zara_policy:option(disabled_categories, [style]).

% Same ID overrides a shipped rule; a new ID extends the KB.
zara_policy:user_rule(completion_tests, verification, 98,
    any(["all tests pass", "ci is green"]),
    "Give the exact command, exit status and commit SHA; never equate mocked tests with a live integration run.",
    [local]).

zara_policy:user_rule(starintel_release, local, 96,
    all(["starintel", "production ready"]),
    "Name the schema version, test gate, candidate SHA and remaining operational gaps.",
    [local]).

zara_policy:user_rule(repeated_apology, style, 25,
    count("sorry", 3),
    "Replace repeated apologies with a specific correction and evidence.",
    [local]).

% Delete this clause to re-enable the shipped flattery check.
zara_policy:disabled(sycophancy_flattery).

% Phrase-based exceptions are only heuristics; they are not proof of evidence.
zara_policy:suppress(future_background, phrase("scheduled task exists")).

% Native trusted adapters may call advise/3 with real context metadata.
% The model-facing tool always supplies {} and cannot assert these facts.
% zara_policy:user_rule(checked_tests, verification, 99,
%     unless("all tests pass", flag(tests_verified, true)),
%     "Obtain a successful test result for this exact candidate.", [local]).
