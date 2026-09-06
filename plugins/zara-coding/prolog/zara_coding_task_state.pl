:- module(zara_coding_task_state, [serve/0]).

:- use_module(library(http/json)).
:- use_module(library(readutil)).

:- dynamic task_state/2.
:- dynamic task_evidence/2.

max_tasks(64).
max_evidence_per_task(64).

serve :-
    read_line_to_string(user_input, Line),
    serve_line(Line).

serve_line(end_of_file) :- !.
serve_line(Line) :-
    response_for_line(Line, Response),
    json_write_dict(current_output, Response, [width(0)]),
    nl,
    flush_output,
    serve.

response_for_line(Line, Response) :-
    catch(
        ( atom_string(Atom, Line),
          atom_json_dict(Atom, Command, []),
          dispatch(Command, Response)
        ),
        _,
        Response = _{status:"rejected", reason:"malformed-command"}
    ).

dispatch(Command, Response) :-
    get_dict(op, Command, Op),
    dispatch_op(Op, Command, Response), !.
dispatch(_, _{status:"rejected", reason:"unsupported-operation"}).

dispatch_op("status", _, _{status:"ok", state:"ready"}).

dispatch_op("create", Command, Response) :-
    get_dict(task_id, Command, Id),
    ( task_state(Id, _) ->
        Response = _{status:"rejected", reason:"task-already-exists"}
    ; task_limit_reached ->
        Response = _{status:"rejected", reason:"task-limit-reached"}
    ; get_dict(goal, Command, Goal),
      get_dict(constraints, Command, Constraints),
      get_dict(dependencies, Command, Dependencies),
      get_dict(completion_criteria, Command, Criteria),
      Task = _{
          id:Id,
          goal:Goal,
          constraints:Constraints,
          dependencies:Dependencies,
          completion_criteria:Criteria,
          state:"open"
      },
      assertz(task_state(Id, Task)),
      Response = _{status:"ok", task:Task}
    ).

dispatch_op("get", Command, Response) :-
    get_dict(task_id, Command, Id),
    ( task_state(Id, Task) ->
        findall(Evidence, task_evidence(Id, Evidence), EvidenceList),
        put_dict(evidence, Task, EvidenceList, Expanded),
        Response = _{status:"ok", task:Expanded}
    ; Response = _{status:"rejected", reason:"task-not-found"}
    ).

dispatch_op("record_evidence", Command, Response) :-
    get_dict(task_id, Command, Id),
    ( task_state(Id, _) ->
        ( evidence_limit_reached(Id) ->
            Response = _{status:"rejected", reason:"evidence-limit-reached"}
        ; get_dict(kind, Command, Kind),
          get_dict(status, Command, Status),
          get_dict(detail, Command, Detail),
          Evidence = _{kind:Kind, status:Status, detail:Detail},
          assertz(task_evidence(Id, Evidence)),
          Response = _{status:"ok", evidence:Evidence}
        )
    ; Response = _{status:"rejected", reason:"task-not-found"}
    ).

dispatch_op("complete", Command, Response) :-
    get_dict(task_id, Command, Id),
    ( task_state(Id, Task) ->
        ( task_evidence(Id, _) ->
            put_dict(state, Task, "completed", Completed),
            retractall(task_state(Id, _)),
            assertz(task_state(Id, Completed)),
            Response = _{status:"ok", task:Completed}
        ; Response = _{status:"rejected", reason:"verification-evidence-required"}
        )
    ; Response = _{status:"rejected", reason:"task-not-found"}
    ).

task_limit_reached :-
    max_tasks(Max),
    findall(Id, task_state(Id, _), Tasks),
    length(Tasks, Count),
    Count >= Max.

evidence_limit_reached(Id) :-
    max_evidence_per_task(Max),
    findall(Evidence, task_evidence(Id, Evidence), EvidenceList),
    length(EvidenceList, Count),
    Count >= Max.
