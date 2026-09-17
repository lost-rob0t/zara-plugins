:- module(zara_prolog_session, [query_json/2, catalog/2]).
:- use_module(library(http/json)).
:- use_module(library(solution_sequences)).
:- use_module(library(time)).
:- use_module(library(error)).

query_json(Json, Reply) :-
    ( catch(query_request(Json,Result),_,fail)
    -> atom_json_dict(Reply,Result,[])
    ; atom_json_dict(Reply,_{status:error,error:query_failed,solutions:[]},[]) ).

query_request(Json, Result) :-
    atom_json_dict(Json, Request, []),
    GoalText = Request.goal, Limit = Request.max_solutions,
    must_be(string, GoalText), string_length(GoalText,N), N > 0, N =< 8192,
    must_be(integer, Limit), between(1,64,Limit),
    read_goal(GoalText,Goal,Names), must_be(callable,Goal),
    length(Names,Variables), Variables =< 32,
    call_with_time_limit(2,
        call_with_inference_limit(
            once(findnsols(Limit, Row,
                (zara_prolog_user:call(Goal), bindings(Names,Row)), Rows)),
            1000000, Outcome)),
    (Outcome == inference_limit_exceeded -> resource_error(inferences) ; true),
    (Rows == [] -> Status = failure ; Status = success),
    Result = _{status:Status,solutions:Rows,limit:Limit}.

read_goal(Text,Goal,Names) :-
    catch(setup_call_cleanup(open_string(Text,Stream),
        (read_term(Stream,Goal,[variable_names(Names),syntax_errors(error)]),
         read_term(Stream,End,[syntax_errors(error)]), End == end_of_file),
        close(Stream)), error(syntax_error(end_of_file),_), fail), !.
read_goal(Text,Goal,Names) :-
    string_concat(Text,"\n.",Terminated),
    setup_call_cleanup(open_string(Terminated,Stream),
        (read_term(Stream,Goal,[variable_names(Names),syntax_errors(error)]),
         read_term(Stream,End,[syntax_errors(error)]), End == end_of_file),
        close(Stream)).

bindings(Names, Row) :- maplist(binding,Names,Pairs), dict_create(Row,bindings,Pairs).
binding(Name=Value,Name-Text) :-
    term_string(Value,Text,[quoted(true),max_depth(20),cycles(true)]),
    string_length(Text,Length),
    (Length =< 4096 -> true ; resource_error(binding_size)).

catalog(Name,Arity) :-
    current_predicate(zara_prolog_user:Name/Arity),
    functor(Head,Name,Arity),
    \+ predicate_property(zara_prolog_user:Head,imported_from(_)).
