:- module(zara_stock_trading,
          [ stock_trade_decision/2,
            stock_trade_explain/2,
            stock_required_tools/1
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
