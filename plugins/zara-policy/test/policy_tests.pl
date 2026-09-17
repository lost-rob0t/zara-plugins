:- begin_tests(zara_policy).
:- use_module('../lib/zara_policy/engine').
:- use_module(library(http/json)).

report(Text, Findings) :-
    atom_json_dict(Request, _{text:Text}, []),
    zara_policy:inspect_json(Request, Reply),
    atom_json_dict(Reply, Dict, [value_string_as(atom)]),
    Findings = Dict.findings.
has(Id, Text) :- report(Text, Rows), member(Row, Rows), Row.id == Id.

test(defaults_valid) :- zara_policy:validate.
test(large_catalogue) :- findall(Id, zara_policy:rule(Id,_,_,_,_,_), Ids), length(Ids,N), N >= 35.
test(large_patterns) :- findall(P, zara_policy:pattern(_,P), Ps), length(Ps,N), N >= 200.
test(claim) :- has(test_claim, "All tests pass.").
test(case_and_spacing) :- has(test_claim, "ALL   TESTS\tPASS!").
test(whole_tokens, [fail]) :- has(test_claim, "All tests passage.").
test(negated, [fail]) :- has(test_claim, "I cannot say all tests pass.").
test(conditional, [fail]) :- has(test_claim, "If all tests pass, merge later.").
test(uncertainty) :- report("I do not know. I have not run the tests.", []).
test(legitimate_refusal) :- report("I cannot help steal credentials.", []).
test(separate_sentence) :- has(test_claim, "I have not deployed. All tests pass.").
test(disable, [setup(assertz(zara_policy:disabled(test_claim))), cleanup(retractall(zara_policy:disabled(test_claim)))]) :-
    \+ has(test_claim, "All tests pass.").
test(extension, [setup((assertz(zara_policy:rule(local_demo, style, info, always, "Use concrete words.", local)),
                       assertz(zara_policy:pattern(local_demo,"magic pixie dust")))),
                 cleanup((retractall(zara_policy:rule(local_demo,_,_,_,_,_)), retractall(zara_policy:pattern(local_demo,_))))]) :-
    has(local_demo, "Magic pixie dust.").
test(advice_override, [setup(assertz(zara_policy:override(test_claim, advice, "Show exact test evidence."))),
                       cleanup(retractall(zara_policy:override(test_claim,_,_)))]) :-
    report("All tests pass.", [Row]), Row.advice == 'Show exact test evidence.'.
test(duplicate_id_rejected, [setup(assertz(zara_policy:rule(test_claim,other,info,always,"Advice",local))),
                           cleanup(retract(zara_policy:rule(test_claim,other,info,always,"Advice",local))),
                           throws(error(domain_error(unique_rule_ids,_),_))]) :- zara_policy:validate.
test(unknown_override_rejected, [setup(assertz(zara_policy:override(no_such_rule,severity,error))),
                                cleanup(retractall(zara_policy:override(no_such_rule,_,_))),
                                throws(error(domain_error(known_rule,_),_))]) :- zara_policy:validate.
test(duplicate_results) :- report("All tests pass. All tests pass.", [Row]), Row.id == test_claim.
test(prompt_injection_is_data) :- report("x), halt. assertz(secret).", []).
test(error_is_not_empty_success) :- zara_policy:inspect_json("not json", Reply), sub_atom(Reply,_,_,_,error).
:- end_tests(zara_policy).
