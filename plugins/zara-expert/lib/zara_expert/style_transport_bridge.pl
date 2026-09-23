:- use_module(library(http/json)).

% Transport-only adapter over the canonical Dotfiles StyleExpert producer.
% ExpertHost invokes registered predicates in SWI's user module. Explicit user:
% qualification keeps this boundary stable even when another source file loaded
% immediately before this one declares its own module.
user:style_policy(ProviderPolicy, MaxModelCalls, ModelCalls) :-
    dotfiles_style_expert:provider_policy(ProviderPolicy),
    dotfiles_style_expert:max_model_calls(MaxModelCalls),
    dotfiles_style_expert:model_calls(ModelCalls).

user:style_rules_json_hex(ProjectId, Generation, Language, Hex) :-
    dotfiles_style_expert:style_rules(ProjectId, Generation, Language, Rules),
    atom_json_dict(Json,
                   _{ project_id:ProjectId,
                      project_generation:Generation,
                      language:Language,
                      rules:Rules
                    },
                   []),
    atom_codes(Json, Codes),
    user:hex_codepoints(Codes, HexCodes),
    atom_codes(Hex, HexCodes).

user:hex_codepoints([], []).
user:hex_codepoints([Code|Codes], HexCodes) :-
    integer(Code),
    Code >= 0,
    Code =< 16'10ffff,
    user:codepoint_hex(Code, Digits),
    append(Digits, Rest, HexCodes),
    user:hex_codepoints(Codes, Rest).

user:codepoint_hex(Code, [D5,D4,D3,D2,D1,D0]) :-
    user:hex_digit((Code >> 20) /\ 16'f, D5),
    user:hex_digit((Code >> 16) /\ 16'f, D4),
    user:hex_digit((Code >> 12) /\ 16'f, D3),
    user:hex_digit((Code >> 8) /\ 16'f, D2),
    user:hex_digit((Code >> 4) /\ 16'f, D1),
    user:hex_digit(Code /\ 16'f, D0).

user:hex_digit(Value, Code) :-
    Value >= 0,
    Value =< 15,
    ( Value < 10 -> Code is 0'0 + Value
    ; Code is 0'a + Value - 10
    ).
