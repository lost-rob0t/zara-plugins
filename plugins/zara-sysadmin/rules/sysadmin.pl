:- dynamic fact/2.

hypothesis(service_failed) :-
    fact(service_active, false),
    fact(service_result, Result),
    Result \= success.

next_diagnostic(service_failed, inspect_recent_journal).
verification(service_failed, service_status_after_remediation).

hypothesis(running_without_listener) :-
    fact(service_active, true),
    fact(port_listening, false).

next_diagnostic(running_without_listener, inspect_socket_or_service_config).
verification(running_without_listener, listener_and_service_status_after_remediation).

hypothesis(dns_upstream_failure) :-
    fact(resolver_configured, true),
    fact(default_route_present, true),
    fact(dns_upstream_reachable, false).

next_diagnostic(dns_upstream_failure, inspect_resolver_and_upstream).
verification(dns_upstream_failure, repeat_dns_resolution_and_route_observation).

hypothesis(nix_activation_failure) :-
    fact(nix_operation, switch),
    fact(generation_advanced, false).

next_diagnostic(nix_activation_failure, inspect_build_activation_evidence).
verification(nix_activation_failure, generation_and_activation_state_after_remediation).
