:- module(zara_coding_assertions,
          [ registry/1,
            repository_head_args/1,
            repository_clean_args/1,
            repository_head_evaluator/3,
            repository_clean_evaluator/3
          ]).

registry([
    assertion_provider(
        repository_head,
        1,
        zara_coding_assertions:repository_head_args,
        zara_coding_assertions:repository_head_evaluator,
        none,
        _{ verifier:_{id:zara_coding_repository,version:1},
           collector:_{id:none,version:1},
           evidence_policy:_{required_evidence:true,
                             source_classes:[repository],
                             trust_classes:[trusted,observed],
                             freshness:current},
           latency:pure,
           argument_schema:_{type:dict,required:_{root:text,head:git_object_id}},
           description:"require an exact HEAD commit for one repository root"
         }),
    assertion_provider(
        repository_clean,
        1,
        zara_coding_assertions:repository_clean_args,
        zara_coding_assertions:repository_clean_evaluator,
        none,
        _{ verifier:_{id:zara_coding_repository,version:1},
           collector:_{id:none,version:1},
           evidence_policy:_{required_evidence:true,
                             source_classes:[repository],
                             trust_classes:[trusted,observed],
                             freshness:current},
           latency:pure,
           argument_schema:_{type:dict,required:_{root:text,clean:boolean}},
           description:"require the dirty state for one repository root to match"
         })
]).

repository_head_args(Args) :-
    is_dict(Args),
    dict_keys(Args, [head,root]),
    get_dict(root, Args, Root),
    nonempty_text(Root),
    get_dict(head, Args, Head),
    git_object_id(Head).

repository_clean_args(Args) :-
    is_dict(Args),
    dict_keys(Args, [clean,root]),
    get_dict(root, Args, Root),
    nonempty_text(Root),
    get_dict(clean, Args, Clean),
    memberchk(Clean, [true,false]).

repository_head_evaluator(Assertion, Observation, Status) :-
    (   get_dict(root, Assertion.args, ExpectedRoot),
        get_dict(head, Assertion.args, ExpectedHead),
        is_dict(Observation.value),
        get_dict(root, Observation.value, ActualRoot),
        get_dict(head, Observation.value, ActualHead),
        ActualRoot == ExpectedRoot,
        ActualHead == ExpectedHead
    ->  Status = passed
    ;   Status = failed
    ).

repository_clean_evaluator(Assertion, Observation, Status) :-
    (   get_dict(root, Assertion.args, ExpectedRoot),
        get_dict(clean, Assertion.args, ExpectedClean),
        is_dict(Observation.value),
        get_dict(root, Observation.value, ActualRoot),
        get_dict(dirty, Observation.value, Dirty),
        ActualRoot == ExpectedRoot,
        memberchk(Dirty, [true,false]),
        clean_dirty_match(ExpectedClean, Dirty)
    ->  Status = passed
    ;   Status = failed
    ).

clean_dirty_match(true, false).
clean_dirty_match(false, true).

nonempty_text(Value) :-
    text_codes(Value, Codes),
    Codes \== [].

git_object_id(Value) :-
    text_codes(Value, Codes),
    length(Codes, Length),
    memberchk(Length, [40,64]),
    maplist(hex_code, Codes).

text_codes(Value, Codes) :-
    atom(Value),
    !,
    atom_codes(Value, Codes).
text_codes(Value, Codes) :-
    string(Value),
    string_codes(Value, Codes).

hex_code(Code) :-
    code_type(Code, xdigit).
