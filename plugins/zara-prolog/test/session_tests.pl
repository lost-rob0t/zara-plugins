:- begin_tests(zara_prolog_session).
:- use_module('../lib/zara_prolog/session').
:- use_module('../lib/zara_prolog/config').
:- use_module(library(http/json)).

query(Text,Limit,Dict) :-
    atom_json_dict(Request, _{goal:Text,max_solutions:Limit}, []),
    zara_prolog_session:query_json(Request,Reply),
    atom_json_dict(Reply,Dict,[value_string_as(atom)]).

test(binding) :- query("X = 42",16,Dict), Dict.status == success,
                 Dict.solutions = [Row], Row.'X' == '42'.
test(failure) :- query("fail",16,Dict), Dict.status == failure, Dict.solutions == [].
test(bounded_solutions) :- query("between(1,100,X)",3,Dict), length(Dict.solutions,3).
test(default_executable_config) :- query("example(square,3-Y)",16,Dict), Dict.status == success.
test(catalog) :- zara_prolog_session:catalog(example,2).
test(malformed_goal) :- query("(",16,Dict), Dict.status == error.
test(inference_limit) :- query("repeat,fail",16,Dict), Dict.status == error.
test(invalid_limit) :- query("true",0,Dict), Dict.status == error.
test(trailing_terms) :- query("true. fail.",16,Dict), Dict.status == error.
:- end_tests(zara_prolog_session).
