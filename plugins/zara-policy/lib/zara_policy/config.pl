% User-owned executable Prolog. This file is created only when absent.
% The bundled default KB is loaded automatically before this file.
% Extensions belong here or in files explicitly loaded with ensure_loaded/1.
% No model output is ever consulted as code. Operator config is trusted code.
:- multifile zara_policy:setting/2, zara_policy:rule/6, zara_policy:pattern/2,
             zara_policy:disabled/1, zara_policy:override/3.

zara_policy:setting(mode, advise).
zara_policy:setting(max_repairs, 1).
zara_policy:setting(timeout_seconds, 20).
zara_policy:setting(max_text_chars, 65536).
zara_policy:setting(profile, balanced).
zara_policy:setting(review_refusals, false).

% Add a rule without editing bundled defaults:
% zara_policy:rule(local_hype, style, info, always,
%                 "Replace hype with a concrete description.", local).
% zara_policy:pattern(local_hype, "magic pixie dust").
% zara_policy:disabled(flattery).
% zara_policy:override(test_claim, severity, info).
% zara_policy:override(test_claim, advice, "Report the command and result.").
