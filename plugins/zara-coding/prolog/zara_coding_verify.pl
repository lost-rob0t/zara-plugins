:- module(zara_coding_verify,
          [ verify_repository/3
          ]).

:- use_module(library(http/json), [json_read_dict/2]).

verify_repository(ok(Frozen), Evidence, Outcome) :-
    is_dict(Frozen),
    is_dict(Evidence),
    get_dict(requirements, Frozen, Requirements),
    is_list(Requirements),
    repository_evidence(Evidence, Root, Head, Branch, Dirty),
    maplist(repository_observation(Root, Head, Branch, Dirty),
            Requirements,
            Observations),
    zara_coding_assertions:registry(Registry),
    rlm_verify:spec_verify(Frozen, Observations, Registry, Outcome).

repository_observation(Root, Head, Branch, Dirty, Requirement, Observation) :-
    Kind = Requirement.assertion.kind,
    repository_value(Kind, Requirement.assertion.args, Root, Head, Branch, Dirty, Value),
    Observation = _{
        requirement_id:Requirement.id,
        assertion:Requirement.assertion,
        status:passed,
        value:Value,
        evidence_refs:[_{kind:git_repository_snapshot,root:Root,head:Head}],
        source_class:repository,
        trust_class:observed,
        provenance:_{provider:zara_coding_repository,version:1},
        verifier:Requirement.verifier,
        collector:Requirement.collector,
        snapshot:_{root:Root,head:Head},
        freshness:current,
        coherence:none,
        state_ref:_{root:Root,head:Head}
    }.

repository_value(repository_head, Args, Root, Head, _, _, Value) :-
    get_dict(root, Args, ExpectedRoot),
    get_dict(head, Args, ExpectedHead),
    observed_text(ExpectedRoot, Root, ValueRoot),
    observed_text(ExpectedHead, Head, ValueHead),
    Value = _{root:ValueRoot,head:ValueHead}.
repository_value(repository_branch, Args, Root, _, Branch, _, Value) :-
    get_dict(root, Args, ExpectedRoot),
    get_dict(branch, Args, ExpectedBranch),
    observed_text(ExpectedRoot, Root, ValueRoot),
    observed_text(ExpectedBranch, Branch, ValueBranch),
    Value = _{root:ValueRoot,branch:ValueBranch}.
repository_value(repository_clean, Args, Root, _, _, Dirty, Value) :-
    get_dict(root, Args, ExpectedRoot),
    observed_text(ExpectedRoot, Root, ValueRoot),
    Value = _{root:ValueRoot,dirty:Dirty}.

repository_evidence(Evidence, Root, Head, Branch, Dirty) :-
    dict_keys(Evidence, [branch,dirty,head,root]),
    get_dict(root, Evidence, Root),
    nonempty_text(Root),
    get_dict(head, Evidence, Head),
    git_object_id(Head),
    get_dict(branch, Evidence, Branch),
    nonempty_text(Branch),
    get_dict(dirty, Evidence, Dirty),
    memberchk(Dirty, [true,false]).

observed_text(Expected, Observed, Value) :-
    text_codes(Expected, ExpectedCodes),
    text_codes(Observed, ObservedCodes),
    (   ExpectedCodes == ObservedCodes
    ->  Value = Expected
    ;   Value = Observed
    ).

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
