:- module(zara_stock_trading,
          [ stock_trade_decision/2,
            stock_trade_explain/2,
            stock_required_tools/1,
            stock_daily_investor_authorized/1,
            stock_daily_investor_plan/2,
            stock_daily_investor_explain/2
          ]).

stock_required_tools(['stock.history', 'stock.money', 'stock.evaluate']).

stock_trade_decision(Assessment, Decision) :-
    stock_trade_explain(Assessment, explanation(Decision, _)).

stock_trade_explain(assessment(paper, []),
                   explanation(paper_candidate, [risk_checks_passed, strategy_not_evaluated, no_execution])).
stock_trade_explain(assessment(paper, [Reason|Reasons]),
                   explanation(blocked, [Reason|Reasons])) :-
    ground([Reason|Reasons]),
    is_list(Reasons).
stock_trade_explain(assessment(live, Reasons),
                   explanation(blocked, [live_execution_unavailable|Reasons])) :-
    ground(Reasons),
    is_list(Reasons).

% The unattended daily investor is explicitly a research-only capability.
% Its caller is restricted to the operator-configured market-data allowlist.
% Live/broker execution is deliberately not an authorized mode here.
stock_daily_investor_authorized(research).

stock_daily_investor_plan(research,
    plan([fetch_configured_market_evidence,
          persist_market_evidence,
          inspect_recent_history,
          forecast_registered_models,
          persist_daily_research_note],
         [arbitrary_instrument,
          broker_order,
          live_execution])).

stock_daily_investor_explain(research,
    explanation(authorized,
                [operator_configured_instruments,
                 research_only,
                 persistent_kb,
                 neural_forecasts_non_executable,
                 no_broker_orders])).
stock_daily_investor_explain(live,
    explanation(blocked, [live_execution_unavailable])).
