# Research provenance — 2026-09-17

The exact 250 phrase patterns are newly authored engineering heuristics, not
copied from a benchmark, not empirically calibrated and not endorsed by the
sources below. Sources motivate categories and design safeguards.

| Source ID | Primary source | Design consequence |
|---|---|---|
| `anthropic_sycophancy` | Anthropic, *Towards understanding sycophancy in language models*, 2023-10-23. https://www.anthropic.com/research/towards-understanding-sycophancy-in-language-models | Review reflexive agreement/flattery; preserve independently supported agreement. |
| `openai_hallucinations` | OpenAI, *Why language models hallucinate*, 2025-09-05. https://openai.com/index/why-language-models-hallucinate/ | Do not punish uncertainty or replace it with unsupported certainty. Lexical signals cannot establish truth. |
| `xstest` | Röttger et al., *XSTest: A Test Suite for Identifying Exaggerated Safety Behaviours in Large Language Models*, NAACL 2024. https://aclanthology.org/2024.naacl-long.301/ | Distinguish over-refusal from justified refusal. Broad-refusal review is opt-in; ordinary refusal words are not banned. |
| `local_operations` | Operator requirements and Zara repository contracts, not empirical research. | Review unsupported completion, verification, persistence, access and asynchronous-work claims. Keep claims supported by actual evidence. |
| `local_style` | Optional local editorial preferences, not reliability science. | Keep stylistic signals outside the default balanced profile. |
| `local` | Operator-authored extension. | The operator owns and reviews executable extensions. |

The bounded feedback design draws on Madaan et al., *Self-Refine: Iterative
Refinement with Self-Feedback*, 2023, https://arxiv.org/abs/2303.17651.
That paper motivates an architecture; it does not validate this plugin or
provide a guarantee that a second model call improves a particular response.

Runtime references:
- https://www.swi-prolog.org/pldoc/doc_for?object=call_with_time_limit/2
- https://www.swi-prolog.org/pldoc/doc_for?object=call_with_inference_limit/3
- https://www.swi-prolog.org/pldoc/doc_for?object=findnsols/4

Evaluation still needed: labelled realistic conversations, false positive and
negative rates by rule, evidence-preservation and refusal-preservation rates,
latency and token-cost measurements, and tests with real model providers.
Native unit tests verify deterministic mechanics, not semantic accuracy.
