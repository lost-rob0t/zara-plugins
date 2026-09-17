:- module(zara_policy, [advise/3, rules/1, validate/0, user_rule/6,
                       disabled/1, suppress/2, option/2]).
:- use_module(library(error)).
:- use_module(library(lists)).
:- use_module(library(apply)).
:- use_module(library(solution_sequences)).
:- multifile user_rule/6, disabled/1, suppress/2, option/2.
:- dynamic user_rule/6, disabled/1, suppress/2, option/2.
:- include('defaults.pl').
:- include('config.pl').

setting(Key, Value) :- findall(V, option(Key, V), Values), last(Values, Value).

rule(Id, Category, Priority, Matcher, Advice, Sources, user) :-
    user_rule(Id, Category, Priority, Matcher, Advice, Sources).
rule(Id, Category, Priority, Matcher, Advice, Sources, builtin) :-
    default_rule(Id, Category, Priority, Matcher, Advice, Sources),
    \+ user_rule(Id, _, _, _, _, _).

validate :-
    findnsols(513, r(I,C,P,M,A,S,O), rule(I,C,P,M,A,S,O), Rows),
    length(Rows, Count), (Count =< 512 -> true ; domain_error(rule_limit, Count)),
    maplist(valid_rule, Rows),
    findall(I, member(r(I,_,_,_,_,_,_), Rows), Ids),
    sort(Ids, Unique), length(Unique, Count),
    forall(disabled(Id), must_be(atom, Id)),
    forall(suppress(Id, Matcher), (must_be(atom, Id), must_be(ground, Matcher), valid_matcher(Matcher, 0))),
    setting(mode, Mode), memberchk(Mode, [advice, off]),
    setting(max_findings, Maximum), must_be(integer, Maximum), between(1, 32, Maximum),
    setting(disabled_categories, Categories), must_be(list(atom), Categories).

valid_rule(r(Id,Category,Priority,Matcher,Advice,Sources,_)) :-
    must_be(atom, Id), must_be(atom, Category),
    atom_length(Id, N), N > 0, N =< 64,
    must_be(integer, Priority), between(0, 100, Priority),
    must_be(string, Advice), string_length(Advice, A), A > 0, A =< 1024,
    must_be(list(atom), Sources), Sources \= [], length(Sources, NS), NS =< 8,
    must_be(ground, Matcher), valid_matcher(Matcher, 0).

valid_matcher(Matcher, Depth) :-
    Depth =< 8,
    ( string(Matcher) -> valid_phrase(Matcher)
    ; Matcher = phrase(Phrase) -> valid_phrase(Phrase)
    ; Matcher = any(Matchers) -> valid_matchers(Matchers, Depth)
    ; Matcher = all(Matchers) -> valid_matchers(Matchers, Depth)
    ; Matcher = unless(Match, Except) -> D is Depth+1,
        valid_matcher(Match,D), valid_matcher(Except,D)
    ; Matcher = count(Phrase, N) -> valid_phrase(Phrase), must_be(integer,N), between(2,16,N)
    ; Matcher = flag(Key,Value) -> must_be(atom,Key), must_be(ground,Value)
    ; domain_error(policy_matcher, Matcher)
    ).
valid_matchers(Matchers, Depth) :-
    must_be(list, Matchers), length(Matchers,N), between(1,32,N), D is Depth+1,
    forall(member(M,Matchers), valid_matcher(M,D)).
valid_phrase(Phrase) :-
    must_be(string,Phrase), string_length(Phrase,N), between(1,160,N),
    tokens(Phrase,Tokens), Tokens \= [].

active(Id, Category) :-
    \+ disabled(Id), setting(disabled_categories, Categories), \+ memberchk(Category,Categories).

advise(Text, Context, Report) :-
    must_be(string, Text), string_length(Text, Length),
    (Length =< 32768 -> true ; domain_error(text_limit, Length)),
    must_be(dict, Context), validate,
    setting(mode, Mode),
    ( Mode == off -> Status=disabled, Findings=[], Total=0, Capped=false
    ; Status=ok, prose_segments(Text,Segments),
      findall(Key-Finding, finding(Segments,Context,Key,Finding), Pairs),
      keysort(Pairs, Sorted), pairs_values_local(Sorted, All), length(All,Total),
      setting(max_findings,Maximum), take(Maximum,All,Findings),
      (Total > Maximum -> Capped=true ; Capped=false)
    ),
    Report=_{status:Status,mode:Mode,basis:lexical_heuristic,verdict:not_assessed,
             version:"0.1.0",total_findings:Total,capped:Capped,findings:Findings}.

finding(Segments, Context, Key, Finding) :-
    rule(Id,Category,Priority,Matcher,Advice,Sources,Origin), active(Id,Category),
    once((nth1(Index,Segments,Segment), tokens(Segment,Tokens),
          matches(Matcher,Tokens,Context,Evidence),
          \+ (suppress(Id,Except), matches(Except,Tokens,Context,_)))),
    Negative is -Priority, Key=Negative-Id,
    severity(Priority,Severity),
    Finding=_{id:Id,category:Category,priority:Priority,severity:Severity,
              evidence:Evidence,segment:Index,advice:Advice,sources:Sources,origin:Origin}.

severity(P, high) :- P >= 80, !.
severity(P, medium) :- P >= 50, !.
severity(_, low).

rules(Rows) :-
    validate,
    findall(Key-Row,
        (rule(Id,Category,Priority,Matcher,Advice,Sources,Origin),
         Negative is -Priority, Key=Negative-Id,
         term_string(Matcher,Pattern,[quoted(true)]),
         (active(Id,Category) -> Enabled=true ; Enabled=false),
         Row=_{id:Id,category:Category,priority:Priority,matcher:Pattern,
               advice:Advice,sources:Sources,origin:Origin,enabled:Enabled}),
        Pairs),
    keysort(Pairs,Sorted), pairs_values_local(Sorted,Rows).

pairs_values_local([], []).
pairs_values_local([_-V|Rest], [V|Values]) :- pairs_values_local(Rest,Values).
take(0, _, []) :- !.
take(_, [], []) :- !.
take(N, [H|T], [H|R]) :- Next is N-1, take(Next,T,R).

matches(Matcher,Tokens,Context,Evidence) :-
    ( string(Matcher) -> matches(phrase(Matcher),Tokens,Context,Evidence)
    ; Matcher=phrase(Phrase) -> tokens(Phrase,Needle), positive_occurrence(Needle,Tokens), Evidence=[Phrase]
    ; Matcher=any(Matchers) -> member(M,Matchers), matches(M,Tokens,Context,Evidence)
    ; Matcher=all(Matchers) -> maplist(match_on(Tokens,Context),Matchers,Parts), append(Parts,Evidence)
    ; Matcher=unless(M,Except) -> matches(M,Tokens,Context,Evidence), \+ matches(Except,Tokens,Context,_)
    ; Matcher=count(Phrase,N) -> tokens(Phrase,Needle),
        findall(1,positive_occurrence(Needle,Tokens),Occurrences), length(Occurrences,Count), Count>=N, Evidence=[Phrase]
    ; Matcher=flag(Key,Value) -> get_dict(Key,Context,Actual), Actual==Value, Evidence=[]
    ).
match_on(Tokens,Context,Matcher,Evidence) :- matches(Matcher,Tokens,Context,Evidence).

positive_occurrence(Needle,Tokens) :-
    append(Before,Rest,Tokens), append(Needle,_,Rest),
    reverse(Before,Reverse), take(6,Reverse,Window),
    \+ (member(Negator,["not","never","cannot","false","avoid","without"]), memberchk(Negator,Window)),
    \+ append(_,["t","don"|_],Window),
    \+ append(_,["t","can"|_],Window).

tokens(Text,Tokens) :-
    string_lower(Text,Lower), string_codes(Lower,Codes), maplist(word_code,Codes,Clean),
    string_codes(Normal,Clean), split_string(Normal," "," ",Tokens).
word_code(Code,Code) :- code_type(Code,alnum), !.
word_code(_,32).

prose_segments(Text,Segments) :-
    split_string(Text,"\n","\r",Lines), prose_lines(Lines,none,Kept),
    atomics_to_string(Kept,"\n",Joined), string_codes(Joined,Codes),
    visible_codes(Codes,Clean), string_codes(Visible,Clean),
    split_string(Visible,".!?\n"," \t\r",Raw), exclude(=(""),Raw,Segments).

prose_lines([],_,[]).
prose_lines([Line|Lines],Fence,Kept) :-
    normalize_space(string(Trim),Line),
    ( fence_marker(Trim,Marker) ->
        (Fence==none -> Next=Marker ; Fence==Marker -> Next=none ; Next=Fence),
        Kept=["."|Tail], prose_lines(Lines,Next,Tail)
    ; Fence\==none -> Kept=["."|Tail], prose_lines(Lines,Fence,Tail)
    ; sub_string(Trim,0,1,_,">") -> Kept=["."|Tail], prose_lines(Lines,none,Tail)
    ; sub_string(Line,0,4,_,"    ") -> Kept=["."|Tail], prose_lines(Lines,none,Tail)
    ; Kept=[Line|Tail], prose_lines(Lines,Fence,Tail)
    ).
fence_marker(Text,backtick) :- sub_string(Text,0,3,_,"```"), !.
fence_marker(Text,tilde) :- sub_string(Text,0,3,_,"~~~").

visible_codes([],[]).
visible_codes([Code|Codes],[46|Visible]) :-
    quote_end(Code,End), !, skip_quote(Codes,End,Rest), visible_codes(Rest,Visible).
visible_codes([Code|Codes],[Code|Visible]) :- visible_codes(Codes,Visible).
quote_end(34,34).
quote_end(96,96).
quote_end(8220,8221).
skip_quote([],_,[]).
skip_quote([End|Rest],End,Rest) :- !.
skip_quote([_|Codes],End,Rest) :- skip_quote(Codes,End,Rest).
