:- multifile output_policy:advice/5.

output_policy:advice(no_ai_preamble, 100, _Context, Text,
    "Remove the AI preamble and answer the question directly.") :-
    output_policy:text_matches(icontains("as an ai language model"), Text).

output_policy:advice(no_unsupported_completion, 200, _Context, Text,
    "State only what was actually verified. Distinguish tests run from tests not run.") :-
    output_policy:text_matches(
        all([icontains("all tests passed"), not(icontains("verified"))]), Text).
