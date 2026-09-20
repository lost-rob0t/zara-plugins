:- use_module(library(http/json)).
:- use_module(library(lists)).
:- use_module(library(pairs)).

:- dynamic memory_fact/13.
:- dynamic memory_tombstone/5.
:- dynamic memory_embedding/6.
:- dynamic embedding_pending/4.
:- dynamic kb_clause/4.
:- dynamic kb_embedding/5.
:- dynamic query_text/1.
:- dynamic query_tokens/1.
:- dynamic query_scope/1.
:- dynamic query_limit/1.
:- dynamic query_now/1.
:- dynamic query_vector/1.

query_rule(symbolic_weight, 0.50).
query_rule(embedding_weight, 0.30).
query_rule(confidence_weight, 0.08).
query_rule(importance_weight, 0.07).
query_rule(recency_weight, 0.05).
query_rule(embedding_min_similarity, 0.18).
query_rule(recency_half_life_seconds, 2592000.0).

scope_allowed(QueryScope, FactScope) :- FactScope = "global" ; QueryScope = FactScope.

latest_memory(Id, Version, Scope, Subject, Predicate, ObjectJson, Text, Source, Confidence, Importance, CreatedEpoch, CreatedIso, TextSha) :-
    memory_fact(Id, Version, Scope, Subject, Predicate, ObjectJson, Text, Source, Confidence, Importance, CreatedEpoch, CreatedIso, TextSha),
    \+ (memory_fact(Id, OtherVersion, _, _, _, _, _, _, _, _, _, _, _), OtherVersion > Version),
    \+ (memory_tombstone(Id, TombstoneVersion, _, _, _), TombstoneVersion >= Version).

symbolic_score(Text, Score) :-
    query_tokens(Tokens),
    string_lower(Text, Lower),
    include(token_hit(Lower), Tokens, Hits),
    length(Tokens, TokenCount),
    length(Hits, HitCount),
    ( TokenCount =:= 0 -> Score = 0.0 ; Score is HitCount / TokenCount ).

token_hit(Text, Token) :- sub_string(Text, _, _, _, Token).

embedding_score(_, _, 0.0) :- query_vector([]), !.
embedding_score(memory(Id, Version), _, Score) :-
    query_vector(Query),
    memory_embedding(Id, Version, _, _, _, Vector),
    !,
    cosine_similarity(Query, Vector, Score).
embedding_score(kb(Id), _, Score) :-
    query_vector(Query),
    kb_embedding(Id, _, _, _, Vector),
    !,
    cosine_similarity(Query, Vector, Score).
embedding_score(_, _, 0.0).

cosine_similarity(A, B, Score) :-
    dot_product(A, B, Dot),
    dot_product(A, A, A2),
    dot_product(B, B, B2),
    (( A2 =< 0.0 ; B2 =< 0.0 ) -> Score = 0.0 ; Score is Dot / sqrt(A2 * B2)).

dot_product([], [], 0.0).
dot_product([A|As], [B|Bs], Dot) :- dot_product(As, Bs, Rest), Dot is A * B + Rest.
dot_product(_, _, 0.0).

recency_score(CreatedEpoch, Score) :-
    query_now(Now),
    query_rule(recency_half_life_seconds, HalfLife),
    Age is max(0, Now - CreatedEpoch),
    Score is exp(-0.6931471805599453 * Age / HalfLife).

admitted(Symbolic, _) :-
    Symbolic > 0.0, !.
admitted(_, Embedding) :-
    query_rule(embedding_min_similarity, Minimum),
    Embedding >= Minimum.

memory_result(Score-result{type:"memory", memory_id:Id, version:Version, scope:Scope, subject:Subject, predicate:Predicate, object_json:ObjectJson, text:Text, source:Source, confidence:Confidence, importance:Importance, created_at:CreatedIso, score:Score, symbolic_score:Symbolic, embedding_score:Embedding}) :-
    query_scope(QueryScope),
    latest_memory(Id, Version, Scope, Subject, Predicate, ObjectJson, Text, Source, Confidence, Importance, CreatedEpoch, CreatedIso, _),
    scope_allowed(QueryScope, Scope),
    symbolic_score(Text, Symbolic),
    embedding_score(memory(Id, Version), Text, Embedding),
    admitted(Symbolic, Embedding),
    recency_score(CreatedEpoch, Recency),
    query_rule(symbolic_weight, SW),
    query_rule(embedding_weight, EW),
    query_rule(confidence_weight, CW),
    query_rule(importance_weight, IW),
    query_rule(recency_weight, RW),
    Score is SW * Symbolic + EW * Embedding + CW * Confidence + IW * Importance + RW * Recency.

kb_result(Score-result{type:"kb", clause_id:Id, source:Source, text:Text, score:Score, symbolic_score:Symbolic, embedding_score:Embedding}) :-
    kb_clause(Id, Source, _, Text),
    symbolic_score(Text, Symbolic),
    embedding_score(kb(Id), Text, Embedding),
    admitted(Symbolic, Embedding),
    query_rule(symbolic_weight, SW),
    query_rule(embedding_weight, EW),
    Score is SW * Symbolic + EW * Embedding.

run_query_json :-
    findall(Pair, memory_result(Pair), MemoryPairs),
    findall(Pair, kb_result(Pair), KbPairs),
    append(MemoryPairs, KbPairs, Pairs),
    keysort(Pairs, Ascending),
    reverse(Ascending, Descending),
    query_limit(Limit),
    take(Limit, Descending, LimitedPairs),
    pairs_values(LimitedPairs, Results),
    length(Results, Count),
    json_write_dict(current_output, _{status:"ok", count:Count, results:Results}, [width(0)]).

take(0, _, []) :- !.
take(_, [], []) :- !.
take(N, [X|Xs], [X|Ys]) :- N > 0, N2 is N - 1, take(N2, Xs, Ys).
