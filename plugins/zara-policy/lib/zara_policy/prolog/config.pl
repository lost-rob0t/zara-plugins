% Shipped defaults. Operator config is loaded afterwards in each fresh process.
% This is trusted Prolog code, not a sandbox or a model-editable configuration.
:- multifile zara_policy:option/2.
zara_policy:option(mode, advice).
zara_policy:option(max_findings, 8).
zara_policy:option(disabled_categories, [style]).
