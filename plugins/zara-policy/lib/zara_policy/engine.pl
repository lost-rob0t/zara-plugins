:- module(zara_policy, [inspect_json/2, settings_json/1, validate/0,
                       rule/6, pattern/2, disabled/1, override/3, setting/2]).
:- use_module(library(http/json)).
:- use_module(library(error)).
:- use_module(library(time)).
:- use_module(library(solution_sequences)).
:- dynamic rule/6, pattern/2, disabled/1, override/3, setting/2.
:- multifile rule/6, pattern/2, disabled/1, override/3, setting/2.
:- ensure_loaded(defaults).

default_setting(mode, advise).
default_setting(max_repairs, 1).
default_setting(timeout_seconds, 20).
default_setting(max_text_chars, 65536).
default_setting(profile, balanced).
default_setting(review_refusals, false).

configured(Key, Value) :-
    findall(Item, setting(Key, Item), Values),
    ( Values = [] -> default_setting(Key, Value)
    ; Values = [Value] -> true
    ; domain_error(unique_setting, Key) ).

settings_json(Reply) :-
    validate,
    findall(Key-Value, (default_setting(Key,_), configured(Key,Value)), Pairs),
    dict_create(Settings, settings, Pairs), atom_json_dict(Reply, Settings, []).

validate :-
    findall(Id, rule(Id,_,_,_,_,_), Ids), sort(Ids, Unique),
    length(Ids, Count), length(Unique, UniqueCount),
    (Count =:= UniqueCount -> true ; domain_error(unique_rule_ids, Ids)),
    (Count =< 256 -> true ; resource_error(policy_rules)),
    forall(rule(Id,Category,Severity,Gate,Advice,Source),
           (valid_id(Id), bounded_atom(Category), bounded_atom(Source),
            valid_severity(Severity), valid_gate(Gate), valid_advice(Advice))),
    findall(P, pattern(_,P), Patterns), length(Patterns, PatternCount),
    (PatternCount =< 2048 -> true ; resource_error(policy_patterns)),
    forall(pattern(Id,Text), (known_rule(Id), bounded_string(Text,256))),
    forall(disabled(Id), known_rule(Id)),
    forall(override(Id,Key,Value),
           (known_rule(Id), valid_override(Key,Value),
            findall(V,override(Id,Key,V),[_]))),
    forall(setting(Key,_), (default_setting(Key,_) -> true ; domain_error(setting,Key))),
    forall(default_setting(Key,_), (configured(Key,Value), valid_setting(Key,Value))).

known_rule(Id) :- (rule(Id,_,_,_,_,_) -> true ; domain_error(known_rule,Id)).
valid_id(Id) :- bounded_atom(Id), atom_codes(Id,[First|Rest]),
                between(0'a,0'z,First), maplist(id_code,Rest).
id_code(Code) :- between(0'a,0'z,Code); between(0'0,0'9,Code); Code =:= 0'_.
bounded_atom(Value) :- must_be(atom,Value), atom_length(Value,N), between(1,64,N).
bounded_string(Value,Max) :- must_be(string,Value), string_length(Value,N), between(1,Max,N).
valid_advice(Value) :- bounded_string(Value,1024).
valid_severity(Value) :- (memberchk(Value,[info,warning,error]) -> true ; domain_error(severity,Value)).
valid_gate(Value) :- (memberchk(Value,[always,assertion,direct,refusal_review]) -> true ; domain_error(gate,Value)).
valid_override(advice,Value) :- !, valid_advice(Value).
valid_override(severity,Value) :- !, valid_severity(Value).
valid_override(Key,_) :- domain_error(override,Key).
valid_setting(mode,V) :- memberchk(V,[off,observe,advise]).
valid_setting(max_repairs,V) :- must_be(integer,V), between(0,1,V).
valid_setting(timeout_seconds,V) :- must_be(integer,V), between(1,60,V).
valid_setting(max_text_chars,V) :- must_be(integer,V), between(1,65536,V).
valid_setting(profile,V) :- memberchk(V,[balanced,direct]).
valid_setting(review_refusals,V) :- memberchk(V,[true,false]).

inspect_json(Json, Reply) :-
    ( catch(call_with_time_limit(1,
        call_with_inference_limit(inspect_request(Json,Rows),5000000,Outcome)),_,fail),
      Outcome \== inference_limit_exceeded
    -> atom_json_dict(Reply, _{findings:Rows}, [])
    ; atom_json_dict(Reply, _{error:policy_evaluation_failed}, []) ).

inspect_request(Json, Rows) :-
    atom_json_dict(Json,Request,[]), Text=Request.text,
    must_be(string,Text), configured(max_text_chars,Max),
    string_length(Text,N), N =< Max,
    string_lower(Text,Lower), split_string(Lower,".!?;\n\r","",Sentences),
    maplist(tokens,Sentences,TokenSentences),
    once(findnsols(256,Rank-Id-Row, finding(TokenSentences,Rank,Id,Row),Pairs)),
    keysort(Pairs,Sorted), pairs_rows(Sorted,All), take_rows(32,All,Rows).

finding(Sentences,Rank,Id,Row) :-
    rule(Id,Category,BaseSeverity,Gate,BaseAdvice,Source), \+ disabled(Id),
    once((pattern(Id,Phrase), tokens(Phrase,Needle), Needle \= [],
          member(Haystack,Sentences),
          append(Before,Tail,Haystack), append(Needle,_,Tail), allowed(Gate,Before))),
    effective(Id,severity,BaseSeverity,Severity), effective(Id,advice,BaseAdvice,Advice),
    severity_rank(Severity,Rank),
    Row = _{id:Id,category:Category,severity:Severity,advice:Advice,source:Source}.

effective(Id,Key,Default,Value) :- (override(Id,Key,Value) -> true ; Value=Default).
severity_rank(error,1). severity_rank(warning,2). severity_rank(info,3).
allowed(always,_).
allowed(direct,_) :- configured(profile,direct).
allowed(refusal_review,_) :- configured(review_refusals,true).
allowed(assertion,Before) :- \+ (member(Token,Before),
    memberchk(Token,["not","never","cannot","can't","didn't","don't","if","whether","might","could","would","unless"])).

tokens(Text,Tokens) :- string_lower(Text,Lower), string_codes(Lower,Codes), maplist(token_code,Codes,Normalized),
                       string_codes(Spaced,Normalized), split_string(Spaced," "," ",Tokens).
token_code(Code,Code) :- (code_type(Code,alnum); Code =:= 39; Code =:= 95), !.
token_code(_,32).
pairs_rows([],[]).
pairs_rows([_-_-Row|Rest],[Row|Rows]) :- pairs_rows(Rest,Rows).
take_rows(0,_,[]) :- !.
take_rows(_,[],[]) :- !.
take_rows(N,[Row|Rest],[Row|Rows]) :- Next is N-1, take_rows(Next,Rest,Rows).
