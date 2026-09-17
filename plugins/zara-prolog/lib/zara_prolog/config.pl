% Operator-owned executable Prolog, loaded on plugin startup.
% This is code, not a data-only configuration or a sandbox.
% Additional modules and API clients may be loaded using use_module/1.
:- module(zara_prolog_user, [prolog_mode/1, example/2]).
:- use_module(library(clpfd)).
prolog_mode(symbolic).
example(square, X-Y) :- between(1, 10, X), Y #= X*X.
