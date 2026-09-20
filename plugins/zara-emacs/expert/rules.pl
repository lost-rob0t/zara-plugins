emacs_command(Symbol) :-
    emacs_symbol_kind(Symbol, command).

emacs_function(Symbol) :-
    emacs_symbol_kind(Symbol, function).

emacs_variable(Symbol) :-
    emacs_symbol_kind(Symbol, variable).

emacs_documentation(Symbol, Kind, Doc) :-
    emacs_doc(Symbol, Kind, Doc).

emacs_keys(Symbol, Keys) :-
    findall(Key, emacs_keybinding(Symbol, Key), Keys).

emacs_search(Needle, Symbol, Kind) :-
    downcase_atom(Needle, LowerNeedle),
    emacs_doc(Symbol, Kind, Doc),
    downcase_atom(Doc, LowerDoc),
    sub_atom(LowerDoc, _, _, _, LowerNeedle).
