# Research and provenance

Reviewed 2026-09-17. The 75 rule definitions and 291 phrase alternatives are
project-authored heuristics. The research supports the *failure families*, not
these exact phrases, thresholds or classifier accuracy. No precision/recall
claim is made. A match requests contextual review; an empty result does not
establish truth, safety or task completion. This is an English-language starter KB.

| Source ID | Primary source | Design consequence |
|---|---|---|
| `sycophancy` | Anthropic, *Towards Understanding Sycophancy in Language Models* (2023-10-23), https://www.anthropic.com/research/towards-understanding-sycophancy-in-language-models | Ask for independent assessment rather than rewarding agreement. |
| `hallucinations` | OpenAI, *Why language models hallucinate* (2025-09-05), https://openai.com/index/why-language-models-hallucinate/ | Reward honest uncertainty; seek evidence for confident factual claims. |
| `self_refine` | Madaan et al., *Self-Refine: Iterative Refinement with Self-Feedback* (2023), https://arxiv.org/abs/2303.17651 | Specific feedback may improve results on studied tasks; it is not a guarantee. |
| `self_correction` | Huang et al., *Large Language Models Cannot Self-Correct Reasoning Yet* (2023), https://arxiv.org/abs/2310.01798 | Intrinsic self-correction can fail or degrade performance; keep checks external and retries bounded. |
| `self_debug` | Chen et al., *Teaching Large Language Models to Self-Debug* (2023), https://arxiv.org/abs/2304.05128 | Execution evidence is more useful than unsupported claims that code works. |
| `xstest` | Röttger et al., *XSTest: A Test Suite for Identifying Exaggerated Safety Behaviours in Large Language Models* (2023), https://arxiv.org/abs/2308.01263 | Consider context and safe/unsafe contrasts; neither blanket refusal nor blanket compliance is the goal. |
| `engineering` | Original Zara policy design in issue #811 | Execution, authorization, completeness, freshness and style checks are project judgments, not research-validated lexical detectors. |
| `local` | Operator-supplied extension | The operator owns the rule and its provenance. |

Transport references: SWI-Prolog `json_read_dict/2` documentation,
https://www.swi-prolog.org/pldoc/man?predicate=json_read_dict/2 and command-line
documentation, https://www.swi-prolog.org/pldoc/man?section=cmdline.

A phrase such as “all tests pass” is often correct. Its rule asks for the test
command, candidate revision and observed result; it does not accuse the model of
lying. “I do not know” and legitimate refusal language are not default failure
patterns. Style rules are disabled by default. Calibrate additions with positive,
negative, quoted, negated and adversarial examples from the intended workflow.
