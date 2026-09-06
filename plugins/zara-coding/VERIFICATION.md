# Verification trust boundary

`zara-coding` treats task completion evidence as observed verifier output, not caller assertion.

The public `coding.task.record-evidence` tool may retain bounded `failed` observations, but it rejects caller-authored `passed` status. Authorization to invoke a Zara tool is not verification evidence. A passing record must be produced by plugin-owned verifier/adapter code from observed execution or repository results before it can satisfy Prolog-owned task completion.

Until such a verifier records passing evidence, `coding.task.complete` must continue to fail closed with `passing-verification-required`.
