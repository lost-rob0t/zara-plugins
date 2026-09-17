:- use_module(policy).
:- use_module(library(http/json)).
:- use_module(library(time)).
:- multifile user:message_hook/3.
user:message_hook(_,error,_) :- nb_setval(zara_policy_load_error,true).
:- initialization(main,main).

main :-
    set_prolog_flag(encoding,utf8),
    (catch(call_with_time_limit(2,run(Reply)),_,fail) -> true
     ; Reply=_{status:error,reason:invalid_config_or_request}),
    json_write_dict(current_output,Reply,[width(0)]), nl.

run(Reply) :-
    nb_setval(zara_policy_load_error,false),
    current_prolog_flag(argv,Arguments), Arguments=[Config],
    (Config=='-' -> true ; with_output_to(string(_),load_files(Config,[silent(true)]))),
    nb_getval(zara_policy_load_error,false), zara_policy:validate,
    json_read_dict(current_input,Request,[value_string_as(string)]),
    dispatch(Request,Reply).

dispatch(Request,Reply) :-
    (Request.op == "advise" -> zara_policy:advise(Request.text,Request.context,Reply)
    ; Request.op == "rules" ->
        Offset=Request.offset, Limit=Request.limit,
        integer(Offset), between(0,512,Offset), integer(Limit), between(1,128,Limit),
        zara_policy:rules(All), length(All,Total), drop(Offset,All,Rest),
        zara_policy:take(Limit,Rest,Rows),
        Reply=_{status:ok,total:Total,offset:Offset,rules:Rows}
    ).
drop(0,List,List) :- !.
drop(_,[],[]) :- !.
drop(N,[_|Tail],Rest) :- Next is N-1, drop(Next,Tail,Rest).
