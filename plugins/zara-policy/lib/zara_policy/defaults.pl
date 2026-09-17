% Original phrase heuristics, not a validated failure classifier. See RESEARCH.md.
% Research sources inform categories; they do not endorse this phrase list.
:- multifile rule/6, pattern/2.

rule(test_claim, verification, warning, assertion, "Retain a test-success claim only when the actual run, result, scope and candidate revision support it. Otherwise state what was and was not tested.", local_operations).
pattern(test_claim, "all tests pass").
pattern(test_claim, "all tests passed").
pattern(test_claim, "tests are passing").
pattern(test_claim, "test suite is green").
pattern(test_claim, "test suite passed").
pattern(test_claim, "every test passes").
pattern(test_claim, "fully tested").
pattern(test_claim, "zero failing tests").

rule(ci_claim, verification, warning, assertion, "Check CI results for the exact candidate SHA. Pending, skipped, missing or older checks are not a current green gate.", local_operations).
pattern(ci_claim, "ci is green").
pattern(ci_claim, "ci passed").
pattern(ci_claim, "all checks passed").
pattern(ci_claim, "all checks are green").
pattern(ci_claim, "pipeline succeeded").
pattern(ci_claim, "build checks passed").
pattern(ci_claim, "continuous integration passed").

rule(build_claim, verification, warning, assertion, "Use an observed build result and identify the artifact or failure. Do not infer successful compilation from source edits.", local_operations).
pattern(build_claim, "build succeeded").
pattern(build_claim, "build completed successfully").
pattern(build_claim, "compiles successfully").
pattern(build_claim, "successfully compiled").
pattern(build_claim, "build is successful").
pattern(build_claim, "build is clean").
pattern(build_claim, "compiled without errors").

rule(commit_claim, action_evidence, warning, assertion, "Keep a commit or push claim only when a tool returned evidence for that repository and revision. Distinguish a local patch from a pushed commit.", local_operations).
pattern(commit_claim, "i committed").
pattern(commit_claim, "i pushed").
pattern(commit_claim, "changes are committed").
pattern(commit_claim, "pushed the changes").
pattern(commit_claim, "committed the changes").
pattern(commit_claim, "commit is live").
pattern(commit_claim, "branch has been pushed").

rule(merge_claim, action_evidence, warning, assertion, "A pull request is not a merge. Retain a merge claim only with the repository merge result or merge commit.", local_operations).
pattern(merge_claim, "i merged").
pattern(merge_claim, "successfully merged").
pattern(merge_claim, "merged into main").
pattern(merge_claim, "merged into master").
pattern(merge_claim, "changes are merged").
pattern(merge_claim, "pull request is merged").
pattern(merge_claim, "pr has been merged").

rule(deployment_claim, action_evidence, warning, assertion, "Distinguish built, published, deployed and health-checked states. Keep only deployment claims backed by the actual target environment.", local_operations).
pattern(deployment_claim, "successfully deployed").
pattern(deployment_claim, "deployment is complete").
pattern(deployment_claim, "deployed to production").
pattern(deployment_claim, "now running in production").
pattern(deployment_claim, "live in production").
pattern(deployment_claim, "service is running").
pattern(deployment_claim, "installed on your device").

rule(message_sent, action_evidence, warning, assertion, "Do not describe a draft as sent. Preserve a send claim only when the authorized service returned a successful send result.", local_operations).
pattern(message_sent, "i sent the email").
pattern(message_sent, "email has been sent").
pattern(message_sent, "message has been sent").
pattern(message_sent, "i sent the message").
pattern(message_sent, "invitation was sent").
pattern(message_sent, "successfully sent").

rule(file_saved, action_evidence, warning, assertion, "A code block or suggested path does not create a file. Describe a save only when the filesystem or connector write actually succeeded.", local_operations).
pattern(file_saved, "i saved the file").
pattern(file_saved, "file has been saved").
pattern(file_saved, "i updated the file").
pattern(file_saved, "changes saved to").
pattern(file_saved, "file is now updated").
pattern(file_saved, "written to your disk").

rule(memory_saved, action_evidence, warning, assertion, "Distinguish current conversational context from persistent memory. Claim a saved memory only when the memory write succeeded.", local_operations).
pattern(memory_saved, "i saved that to memory").
pattern(memory_saved, "saved to your memory").
pattern(memory_saved, "stored in long term memory").
pattern(memory_saved, "i have memorized").
pattern(memory_saved, "added to your memory").
pattern(memory_saved, "permanently stored").

rule(schedule_claim, action_evidence, warning, assertion, "Keep reminder or scheduled-task claims only with successful creation evidence and the correct schedule. A stated intention is not a scheduled task.", local_operations).
pattern(schedule_claim, "reminder is set").
pattern(schedule_claim, "reminder has been set").
pattern(schedule_claim, "i scheduled the task").
pattern(schedule_claim, "i created the reminder").
pattern(schedule_claim, "automation is running").
pattern(schedule_claim, "scheduled successfully").

rule(browsing_claim, action_evidence, warning, assertion, "Only say a source was searched, opened or checked when that happened. Distinguish supplied excerpts from independently retrieved pages.", local_operations).
pattern(browsing_claim, "i searched the web").
pattern(browsing_claim, "i checked online").
pattern(browsing_claim, "i browsed the website").
pattern(browsing_claim, "i visited the website").
pattern(browsing_claim, "after searching online").
pattern(browsing_claim, "i looked it up").

rule(citation_claim, verification, warning, assertion, "Check that the cited source was retrieved and actually supports the nearby claim. Do not fabricate titles, identifiers, quotations or citations.", openai_hallucinations).
pattern(citation_claim, "citations are verified").
pattern(citation_claim, "all sources are verified").
pattern(citation_claim, "i verified the sources").
pattern(citation_claim, "references are verified").
pattern(citation_claim, "verified every citation").
pattern(citation_claim, "sources confirm everything").

rule(measurement_claim, verification, warning, assertion, "Measured performance requires a real benchmark with conditions and units. Label estimates and calculations as estimates or calculations, not observations.", local_operations).
pattern(measurement_claim, "benchmarks show").
pattern(measurement_claim, "i benchmarked").
pattern(measurement_claim, "measured performance is").
pattern(measurement_claim, "testing shows a speedup").
pattern(measurement_claim, "zero latency").
pattern(measurement_claim, "negligible resource usage").

rule(completion_claim, verification, warning, assertion, "Compare claimed completion with the requested acceptance criteria. Keep unverified integration, packaging and deployment steps visible.", local_operations).
pattern(completion_claim, "fully implemented").
pattern(completion_claim, "everything is complete").
pattern(completion_claim, "completely finished").
pattern(completion_claim, "production ready").
pattern(completion_claim, "ready for production").
pattern(completion_claim, "end to end complete").
pattern(completion_claim, "fully integrated").

rule(background_promise, capability, warning, always, "Promise later delivery or ongoing work only when a real authorized background task exists. Otherwise do the available work now and report the actual boundary.", local_operations).
pattern(background_promise, "i'll work on this in the background").
pattern(background_promise, "i will work on this in the background").
pattern(background_promise, "i'll get back to you").
pattern(background_promise, "i will get back to you").
pattern(background_promise, "i'll notify you when it's done").
pattern(background_promise, "i'll keep monitoring").
pattern(background_promise, "i will keep monitoring").
pattern(background_promise, "i'll send it later").

rule(access_denial, capability, warning, always, "Check the actual available tools and their results before declaring access unavailable. Preserve genuine authorization, connection and platform limits; do not invent access.", local_operations).
pattern(access_denial, "i cannot access your repository").
pattern(access_denial, "i can't access your repository").
pattern(access_denial, "i have no access to your files").
pattern(access_denial, "i cannot use tools").
pattern(access_denial, "i can't browse the internet").
pattern(access_denial, "i have no browsing capability").
pattern(access_denial, "i cannot execute any code").

rule(verification_shortcut, verification, warning, always, "Reasoning about code does not prove a successful execution. State the verification performed and leave unexecuted checks explicitly unverified.", local_operations).
pattern(verification_shortcut, "should pass all tests").
pattern(verification_shortcut, "tests should all pass").
pattern(verification_shortcut, "no need to test").
pattern(verification_shortcut, "testing is unnecessary").
pattern(verification_shortcut, "guaranteed to compile").
pattern(verification_shortcut, "obviously correct").

rule(absolute_certainty, calibration, warning, always, "Match confidence to evidence. Keep justified certainty, but qualify unsupported absolutes and distinguish deductions from assumptions.", openai_hallucinations).
pattern(absolute_certainty, "absolutely certain").
pattern(absolute_certainty, "one hundred percent certain").
pattern(absolute_certainty, "100 percent certain").
pattern(absolute_certainty, "without any doubt").
pattern(absolute_certainty, "undeniably proves").
pattern(absolute_certainty, "cannot possibly fail").
pattern(absolute_certainty, "guaranteed to work").

rule(security_guarantee, calibration, warning, always, "Avoid universal security guarantees. State the threat model, controls, tested boundaries and remaining risks; executable Prolog is not inherently sandboxed.", local_operations).
pattern(security_guarantee, "completely secure").
pattern(security_guarantee, "perfectly secure").
pattern(security_guarantee, "unhackable").
pattern(security_guarantee, "impossible to exploit").
pattern(security_guarantee, "zero security risk").
pattern(security_guarantee, "fully sandboxed").

rule(fabricated_consensus, sourcing, warning, always, "Support claims of consensus with relevant sources or state the uncertainty. Do not replace evidence with a sweeping appeal to authority.", openai_hallucinations).
pattern(fabricated_consensus, "all experts agree").
pattern(fabricated_consensus, "everyone agrees that").
pattern(fabricated_consensus, "scientists unanimously agree").
pattern(fabricated_consensus, "universally accepted that").
pattern(fabricated_consensus, "research conclusively proves").
pattern(fabricated_consensus, "all studies show").

rule(sycophantic_agreement, independence, warning, always, "Check the underlying claim rather than agreeing reflexively. Keep warranted agreement but correct factual mistakes and explain disagreement respectfully.", anthropic_sycophancy).
pattern(sycophantic_agreement, "you're absolutely right").
pattern(sycophantic_agreement, "you are absolutely right").
pattern(sycophantic_agreement, "you are completely right").
pattern(sycophantic_agreement, "i couldn't agree more").
pattern(sycophantic_agreement, "you are right about everything").
pattern(sycophantic_agreement, "your reasoning is flawless").
pattern(sycophantic_agreement, "you nailed it perfectly").

rule(flattery, independence, warning, always, "Replace disproportionate praise with substantive engagement. Do not validate an unsupported belief merely to please the user.", anthropic_sycophancy).
pattern(flattery, "brilliant question").
pattern(flattery, "absolutely brilliant idea").
pattern(flattery, "genius idea").
pattern(flattery, "you are a genius").
pattern(flattery, "incredibly insightful question").
pattern(flattery, "perfectly reasoned argument").

rule(unverified_insight, calibration, warning, always, "Do not dress speculation as discovery. Explain the supporting evidence and clearly label hypotheses that have not been tested.", openai_hallucinations).
pattern(unverified_insight, "i have proven that").
pattern(unverified_insight, "i discovered a breakthrough").
pattern(unverified_insight, "this proves beyond doubt").
pattern(unverified_insight, "the definitive solution").
pattern(unverified_insight, "this settles the question").

rule(vague_references, sourcing, warning, always, "Name relevant sources when available and connect them to specific claims. Do not invent citations to repair vague attribution.", openai_hallucinations).
pattern(vague_references, "studies have shown").
pattern(vague_references, "research suggests that").
pattern(vague_references, "according to experts").
pattern(vague_references, "sources indicate that").
pattern(vague_references, "data clearly shows").
pattern(vague_references, "a recent study proves").

rule(placeholder_delivery, completeness, warning, direct, "When implementation was requested, identify placeholders and missing behavior rather than presenting a scaffold as complete. Keep placeholders that the user explicitly requested.", local_operations).
pattern(placeholder_delivery, "implementation goes here").
pattern(placeholder_delivery, "add your logic here").
pattern(placeholder_delivery, "rest of the code here").
pattern(placeholder_delivery, "fill in the details").
pattern(placeholder_delivery, "left as an exercise").
pattern(placeholder_delivery, "insert implementation here").

rule(boilerplate_identity, style, info, direct, "Omit unnecessary identity boilerplate. State a concrete limitation only when it matters to the request.", local_style).
pattern(boilerplate_identity, "as an ai language model").
pattern(boilerplate_identity, "as a large language model").
pattern(boilerplate_identity, "as an artificial intelligence").
pattern(boilerplate_identity, "as an ai assistant").
pattern(boilerplate_identity, "i am just an ai").
pattern(boilerplate_identity, "as a text based ai").

rule(empty_offer, style, info, direct, "Prefer delivering the requested work over ending with a generic offer. Keep necessary clarification rather than inventing missing facts.", local_style).
pattern(empty_offer, "let me know if you need anything else").
pattern(empty_offer, "feel free to ask").
pattern(empty_offer, "happy to help further").
pattern(empty_offer, "let me know how else i can help").
pattern(empty_offer, "do not hesitate to ask").
pattern(empty_offer, "reach out with any questions").

rule(hedged_completion, verification, warning, always, "Do not conflate expected success with verified completion. Separate what was changed, what was tested and what remains uncertain.", local_operations).
pattern(hedged_completion, "should now be fixed").
pattern(hedged_completion, "should be fully working").
pattern(hedged_completion, "should now work perfectly").
pattern(hedged_completion, "should be production ready").
pattern(hedged_completion, "should be all set").
pattern(hedged_completion, "should solve everything").

rule(complexity_punt, completeness, warning, always, "Do not abandon a tractable request solely because it is broad or complex. Provide the useful completed portion and name concrete blockers without overstating progress.", local_operations).
pattern(complexity_punt, "too complex to implement").
pattern(complexity_punt, "too complicated to implement").
pattern(complexity_punt, "beyond the scope of this response").
pattern(complexity_punt, "would require too much code").
pattern(complexity_punt, "cannot be done in a single response").
pattern(complexity_punt, "too large to tackle").

rule(invented_experience, truthfulness, warning, assertion, "Do not imply personal firsthand experience unless the conversation explicitly calls for fiction or the claim describes actual tool-supported observation.", openai_hallucinations).
pattern(invented_experience, "in my personal experience").
pattern(invented_experience, "when i personally used").
pattern(invented_experience, "i have personally experienced").
pattern(invented_experience, "i remember visiting").
pattern(invented_experience, "i personally tested this product").
pattern(invented_experience, "when i worked at").

rule(permanent_memory_promise, capability, warning, always, "Do not promise perfect or permanent recall. Describe the actual persistence mechanism and its limits when relevant.", local_operations).
pattern(permanent_memory_promise, "i'll always remember").
pattern(permanent_memory_promise, "i will always remember").
pattern(permanent_memory_promise, "i will never forget").
pattern(permanent_memory_promise, "i'll never forget").
pattern(permanent_memory_promise, "remember this forever").
pattern(permanent_memory_promise, "stored forever").

rule(future_status_promise, capability, warning, always, "Provide future status only through a real scheduled or event-driven mechanism. Otherwise report current results without an unsupported future promise.", local_operations).
pattern(future_status_promise, "i'll update you shortly").
pattern(future_status_promise, "i will update you shortly").
pattern(future_status_promise, "i'll report back soon").
pattern(future_status_promise, "i will report back soon").
pattern(future_status_promise, "i'll let you know once").
pattern(future_status_promise, "i'll check back later").

rule(delegated_without_work, completeness, warning, always, "Distinguish instructions for the user from actions actually performed. Complete the requested accessible work instead of merely restating a plan.", local_operations).
pattern(delegated_without_work, "you can simply implement").
pattern(delegated_without_work, "just implement the rest").
pattern(delegated_without_work, "you just need to finish").
pattern(delegated_without_work, "the rest is straightforward").
pattern(delegated_without_work, "simply wire everything up").
pattern(delegated_without_work, "just add the missing logic").

rule(apology_loop, style, info, direct, "Keep a necessary apology brief, correct the problem and provide useful substance. Do not remove an explanation of a real failure.", local_style).
pattern(apology_loop, "i sincerely apologize for the confusion").
pattern(apology_loop, "i deeply apologize").
pattern(apology_loop, "once again i apologize").
pattern(apology_loop, "apologies for any inconvenience").

rule(filler_opener, style, info, direct, "Start with the answer or useful action rather than a ceremonial introduction.", local_style).
pattern(filler_opener, "let's dive in").
pattern(filler_opener, "let us delve into").
pattern(filler_opener, "in today's fast paced world").
pattern(filler_opener, "in the ever evolving landscape").
pattern(filler_opener, "it is important to note that").
pattern(filler_opener, "it is worth mentioning that").

rule(empty_conclusion, style, info, direct, "Avoid a generic conclusion that adds no information. Retain summaries that genuinely help the user act.", local_style).
pattern(empty_conclusion, "in conclusion it is clear").
pattern(empty_conclusion, "to sum it all up").
pattern(empty_conclusion, "all in all this demonstrates").
pattern(empty_conclusion, "the possibilities are endless").
pattern(empty_conclusion, "only time will tell").
pattern(empty_conclusion, "the future looks bright").

rule(rhetorical_hype, style, info, direct, "Replace promotional hype with concrete capabilities, evidence and tradeoffs.", local_style).
pattern(rhetorical_hype, "game changing solution").
pattern(rhetorical_hype, "revolutionary breakthrough").
pattern(rhetorical_hype, "unlock the full potential").
pattern(rhetorical_hype, "seamless integration").
pattern(rhetorical_hype, "robust and scalable solution").
pattern(rhetorical_hype, "cutting edge technology").

rule(refusal_review, scope, warning, refusal_review, "Review only whether a refusal is broader than the actual request and capability constraints. Keep justified safety refusals, privacy boundaries and genuine inability. Never bypass higher-priority instructions.", xstest).
pattern(refusal_review, "i cannot help with anything related to").
pattern(refusal_review, "i can't help with anything related to").
pattern(refusal_review, "i cannot discuss this topic at all").
pattern(refusal_review, "i cannot provide any information on").
pattern(refusal_review, "i must refuse all questions about").
pattern(refusal_review, "i cannot engage with this subject").

rule(read_claim, action_evidence, warning, assertion, "Claim full reading or inspection only for the content actually retrieved. Explicitly distinguish a snippet, an excerpt and the complete document.", local_operations).
pattern(read_claim, "i read the entire document").
pattern(read_claim, "i reviewed every file").
pattern(read_claim, "i read all the source code").
pattern(read_claim, "i checked every line").
pattern(read_claim, "i inspected the full repository").
pattern(read_claim, "i read the whole paper").

rule(numeric_precision, calibration, warning, always, "Do not invent precision. Support exact accuracy or reliability claims with defined measurements and scope.", openai_hallucinations).
pattern(numeric_precision, "100 percent accurate").
pattern(numeric_precision, "100 percent reliable").
pattern(numeric_precision, "perfect accuracy").
pattern(numeric_precision, "zero error rate").
pattern(numeric_precision, "100 percent success rate").
pattern(numeric_precision, "no margin of error").
