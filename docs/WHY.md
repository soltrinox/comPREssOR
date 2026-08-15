# Why bounded forward context beats raw replay

comPREssOR exists for a specific prompt-engineering problem: long Agent Chat sessions accumulate useful decisions, paths, open items, and constraints, but replaying the full transcript is a blunt way to carry that material forward. Raw replay preserves the most text, yet it also carries repeated logs, abandoned hypotheses, old tool output, social framing, and stale branches of work. The model receives more tokens, but not necessarily a cleaner view of what matters now.

The mechanism is local state plus budgeted text projection. comPREssOR watches Cursor Agent Chat hook events, stores compressed state on disk, and emits a bounded text payload back into later turns. Cursor still receives ordinary text. The extension does not send matrices, hidden state, SQLite rows, safetensors blobs, or private sidecars to the model. Those local artifacts only help decide which text should be forwarded.

The observable outcome is a forward payload ordered for prompt use:

- `HOT_SET` first: active open items, durable paths, current decisions, and recent facts.
- Typed graph lines second: compact lines such as `OpenItem:`, `Fact:`, `Path:`, and `Event:`.
- Query-ranked chunks third: verbatim spans selected against the current prompt.

The scope boundary is equally important. comPREssOR is not a guarantee of better answers. It is not a codebase retrieval system. It is not model fine-tuning. It does not create a hidden context channel. It is a local memory and prompt-construction layer for Cursor, designed to make long-session memory bounded, typed, and inspectable.

## The problem: context grows, budgets do not

A prompt engineer usually wants continuity. If a session has already established the target file, the accepted design, a failing test, and two open decisions, the next prompt should not start from zero. The simplest way to preserve continuity is to paste or replay everything. That works until the transcript becomes large enough that replay competes with the actual task for token budget, latency, and attention.

The growth pattern is structural. A raw transcript grows with each turn:

```text
H_t = all turns up to turn t
```

If each new turn adds text, then the raw history increases as the session progresses. Sending that history again means the prompt cost tracks the accumulated session, not just the new request. A short conversation can tolerate that. A long implementation session, debugging loop, or release-prep pass often cannot.

Compression alone is not the answer. A tiny summary that drops the relevant file path or open item may be cheaper but less useful. A vocabulary bag may be very small and still fail to tell the model what was decided. The target is not "smallest text." The target is bounded text that retains enough relevant material to guide the next turn.

In plain terms:

```text
forward_payload <= budget
```

and the payload should still carry the entities, files, decisions, and open items the next prompt depends on. That second condition is why comPREssOR combines symbolic graph memory with ranked verbatim spans instead of forwarding only a generic summary.

## Text-only by design

Cursor Agent Chat consumes text. comPREssOR respects that surface. Its local engine can maintain richer data structures, but the model-facing channel remains ordinary prompt text. That makes the behavior easier to reason about: anything the model can use must be present in the injected context.

The local state has two memory tracks:

- A bounded matrix state, stored locally, that gives the engine a compact numeric digest of previous turns.
- A symbolic graph, stored locally, that records extractable material such as turns, facts, open items, events, paths, headings, and status changes.

The matrix helps with compact state and ranking support. The graph helps preserve human-readable durable material. The forward pack then projects selected graph and span content into text.

This matters because it prevents a category mistake. comPREssOR does not claim to extend the model's native context window with hidden recurrence. It does not rely on the model reading local files. It does not transmit safetensors or SQLite state to Cursor. The model sees a bounded text pack. If a fact is absent from that pack and not otherwise in the prompt, comPREssOR has not supplied that fact to the model.

That boundary is useful for prompt engineers. You can inspect the shape of the injected context, tune the budget, and write turns in a way that improves extraction. Clear paths, explicit open items, durable decisions, and stable headings are easier for the system to carry than ambiguous prose.

## Why ordering matters

The forward pack is not just a shorter transcript. It is ordered text with explicit priority.

`HOT_SET` is first because active items should survive budget pressure. If the system knows there is an open item, a path, or a recent durable fact, that line should not compete equally with low-value historical prose. Prompt budget pressure should remove tail material first, not the active work list.

Typed graph lines come next. The model receives labels that distinguish kinds of memory. A line that starts with `OpenItem:` carries a different instruction value than a random sentence containing the same words. A line that starts with `Path:` tells the model that a file path is durable context, not an incidental example. A line that starts with `Fact:` says the item was extracted as a fact-like statement. The labels are simple, but they reduce ambiguity.

Ranked chunks come after the typed material. These are verbatim spans selected against the current prompt. They help preserve phrasing and nearby context when the graph alone is too sparse. Because they are last, they are the first region to shrink when the budget is tight.

This order creates a predictable failure mode. Under a small budget, comPREssOR may lose supporting prose before it loses the current open items and typed facts. That is not always enough for a task, but it is easier to debug than a summary that silently drops the active decision and keeps a polished paragraph.

## Why smaller is not automatically better

The main measurement lesson behind comPREssOR is that token count and usefulness must be measured separately. A forward payload can be extremely small because it preserved only generic words. That payload may look successful on a size chart while failing the task.

The lab comparison used three arms:

- Raw replay: forward the full accumulated context.
- Legacy vocabulary bag: forward a very small decoded vocabulary representation.
- comPREssOR pack: forward `HOT_SET`, typed lines, and ranked chunks.

Raw replay is the upper bound on retained text. It is expensive, but it carries the source material. The legacy vocabulary bag is the lower bound on size. It is cheap, but it can remove the structure that makes the text useful. The comPREssOR pack sits between them: larger than the vocabulary bag, far smaller than raw replay, and structured around active memory.

That comparison is useful because it exposes the wrong objective. If the only metric is "fewest forwarded tokens," the vocabulary bag wins. If the metric also asks whether relevant fixture terms survived into the forward payload, the vocabulary bag fails. comPREssOR is designed for the second objective: bounded context with retained relevance.

The prompt-engineering implication is practical. Do not tune a memory layer only by making it shorter. Tune it by asking what the next turn needs to see: current paths, accepted decisions, open blockers, named entities, recent errors, and constraints. A memory pack that keeps those items is more valuable than a smaller one that drops them.

## Two public measurements

Public numbers come from two separate probes. Do not merge them.

The 199-prompt inject corpus (14–15 Aug 2026) compares full-corpus replay of ingested prompt text against packed inject under a 1,024-token cap. Packed inject forwarded about **one sixth** the estimated tokens of replay (**84% fewer**). Unit is `chars/4`. That path is the memory-inject channel, not a Cursor billing export. As a ratio illustration only: if replay inject volume = $1.00, packed inject ≈ $0.18 (~**6×** as far for the same inject-path budget); see [PERFORMANCE.md](PERFORMANCE.md). Card sequence, locked numerals, and honesty lines: [PERFORMANCE.md](PERFORMANCE.md).

The lab/live SDK probe in the next section remains the live billed comparison (184 vs 19,938 estimated forward tokens; about 34% fewer billed tokens than raw replay on that probe). It is a different corpus, a different arm set, and a different unit of reporting.

## Measurement design

The lab/live SDK numbers below come from one press-release-style probe. The fixture started from about 78,876 inbound characters, or about 19,719 estimated tokens under the report's characters-divided-by-four estimator. Five turns were replayed through each arm. The final turn compared raw replay, a legacy vocabulary-bag replica, and the current comPREssOR pack.

The measurement separated three quantities:

- Estimated forward tokens: approximate size of the text payload each arm supplied at the final turn.
- `entity_recall`: a fixture term-hit proxy over a six-term set in the probe.
- Live billed totals: usage reported by the SDK call for one context-only probe per arm.

Those are different measurements. Estimated forward tokens are not live billed input tokens. `entity_recall` is not answer correctness. Billed totals include the SDK envelope, so they are larger than the gist-only payload sizes and should be read as live usage for that probe, not as a pure measurement of the injected pack.

The scoped result:

| Arm | Final-turn estimated forward tokens | `entity_recall` | Live billed total |
| --- | ---: | ---: | ---: |
| Raw replay | 19938 | 1.00 | 31971 |
| Legacy vocabulary bag | 27 | 0.00 | 22352 |
| comPREssOR pack | 184 | 0.33 | 21050 |

The inbound baseline was about 78,876 chars / 19,719 estimated tokens. At the final turn, raw replay had grown to 19,938 estimated forward tokens. The legacy vocabulary bag forwarded 27 estimated tokens and hit none of the fixture recall terms. The comPREssOR pack forwarded 184 estimated tokens and hit 0.33 of the fixture term set.

The billed totals were raw 31971, legacy 22352, and comPREssOR pack 21050. On that probe, the comPREssOR pack used about 34 percent fewer billed tokens than raw replay. That percentage is scoped to the live SDK probe. It should not be generalized to every Cursor Agent Chat session, every model, or every workload.

## What the metrics mean

The forward-token result means the projection was bounded and much smaller than raw replay on the final turn. It does not mean the projection retained every useful detail. In fact, the recall figure says it did not.

The `entity_recall` result means a fixed term set was checked against the forwarded text. It is a fixture term-hit proxy. A recall value of 0.33 means some target terms appeared in the pack; it does not mean one third of the task was solved, one third of the document was understood, or one third of the answer quality was preserved.

The legacy vocabulary bag is the cautionary arm. It forwarded only 27 estimated tokens, so it looked excellent on size. Its recall was 0.00. That is an observable example of why a smaller forward payload can be worse than a larger one. The missing structure forced the downstream reply to infer rather than cite supplied context.

The comPREssOR pack is also not a complete solution. In the probe, its recalled terms came through active-item fragments rather than full exposition. That is useful continuity, but it is not the same as carrying the entire source. A larger budget, stronger extraction, or better ranking could improve recall. A task that requires exact wording may still need raw source text or explicit file references.

The billed totals mean the live SDK call returned lower total token usage for the comPREssOR arm than for raw replay on the same context-only probe. The totals include system/tool/request overhead from the SDK envelope. The projection's estimated size is therefore not equal to the billed input. The useful comparison is relative within the same probe and setup.

## The working claim

The defensible claim is conditional:

```text
When a long-running Cursor session depends on extractable paths, open items,
facts, decisions, and ranked spans, a bounded typed projection can improve
utility per forwarded token compared with raw replay.
```

This claim has three parts.

First, the payload is bounded by configuration. Raw replay grows with the session. The comPREssOR pack is assembled under a forward budget, so it has a stable upper bound.

Second, the local state is bounded and local. The engine stores matrix state and graph metadata on disk, then uses those structures to assemble text. That avoids paying model-facing tokens for every previous turn, while also avoiding an unbounded prompt-side replay.

Third, relevance must be retained. If extraction misses the task-critical material, the pack may be cheap and insufficient. This is why the measured evidence reports recall alongside token size and why the documentation does not claim universal answer-quality improvement.

In a short session, raw replay may be better. If the transcript is small, the cost of replay is low and it retains everything. In a task requiring exact source wording, raw text or explicit file attachment may be necessary. In a session where the important facts are not written clearly, comPREssOR may fail to extract them. The system is most useful when prior work can be represented as durable facts, paths, decisions, open items, and selected spans.

## Practical prompt-engineering implications

Use comPREssOR as a continuity layer, not as a replacement for clear prompting. It helps most when the conversation itself contains durable signals.

Write file paths explicitly. A path such as `docs/SYSTEM.md` is easier to carry forward than "the system doc." If a later prompt asks about system behavior, a durable path line gives the model a concrete anchor.

Name open items directly. "Open item: verify the hook merge keeps non-compressor entries" is easier to preserve than "we still need to check that thing." The graph can represent an open item, and the forward pack can place it in `HOT_SET`.

Mark completion explicitly. When an item is completed, say so with stable language. Completion cues allow the graph to supersede or close prior open items instead of carrying stale work forward.

Keep related work in one Agent conversation when continuity matters. comPREssOR maintains state by conversation or workspace-derived agent identity. Starting many unrelated conversations can split the memory that would otherwise support a workstream.

Tune the forward budget to the task. The default exists to keep injected text bounded. For broad recall over long source material, a higher budget may give ranked chunks room to carry more evidence. For narrow task loops, a smaller budget may be enough.

Prefer packed memory over pasting an entire transcript. If the purpose is continuity, let the pack carry active state and use the prompt for the current request. Paste raw history only when exact wording is required.

Use project hooks when cloud parity matters. User hooks support local Cursor Agent Chat. Project hook templates help carry the same hook command into project-level environments where that is appropriate and explicitly installed.

## A prompt-engineer's mental model

Treat the pack as a working note that the system writes for the next turn. The note is generated mechanically, but it rewards the same habits that make human handoff notes useful: name the target, write the decision, mark the unresolved question, and cite the file path.

Raw replay answers a different need. It gives the model everything that still fits. That is valuable when exact phrasing, full argument structure, or complete source detail matters. It is less valuable when the next turn only needs the active task state. A transcript can contain the right answer and still make it harder to find because the useful lines are surrounded by old tool output, failed commands, repeated context, and completed branches.

comPREssOR's local graph gives the system a way to distinguish some of those roles. It can carry an open item as an open item, not merely as a phrase that appeared somewhere. It can carry a path as a path. It can carry a completed item with a status transition rather than letting an old task remain active forever. The forward pack is therefore closer to a typed status brief than to a generic summary.

That distinction changes how you should write prompts in long sessions. Instead of assuming the system will infer what mattered from a large transcript, write the durable facts in forms that can survive extraction. Examples:

- "Decision: keep activation fail-closed on non-Cursor hosts."
- "Open item: validate links from README to the new docs."
- "Path: `docs/SYSTEM.md` is the system guide."
- "Completed: README metrics table updated with scoped Layer B values."

Those lines are useful even without comPREssOR. They are also easier for comPREssOR to carry into future turns. The system does not need prose to be stiff, but it benefits from explicit labels and concrete nouns.

## Budget as an engineering control

The forward budget is not a quality knob in the abstract. It controls how much text the pack may inject. Raising it gives typed lines and ranked chunks more room. Lowering it keeps the additional context smaller. The right value depends on the workstream.

For narrow implementation loops, the active path, current failure, and next step may fit in a small pack. A large budget may add old context that does not help. For broad documentation work, release planning, or multi-file refactors, ranked chunks may need more room because the current prompt can depend on several earlier decisions. A higher budget can improve recall, but it can also make each prompt heavier.

The default budget is a conservative starting point. It is designed to prevent accidental transcript-scale growth, not to prove an optimal recall point. The measured probe is a useful example: the comPREssOR pack used 184 estimated forward tokens, well below the default cap. That means the binding limit in that run was not simply the configured maximum; selection and ranking determined what entered the pack. If a future run needs broader recall, the fix may be better candidate extraction, better query terms, a larger budget, or clearer durable statements in the conversation.

This is why prompt engineers should evaluate the injected pack qualitatively when tuning. Ask whether it contains the active file, the current constraint, the accepted decision, and the unresolved item. If it does not, making the pack shorter is not progress. If it does, the next question is whether the remaining ranked context is worth its token cost.

## Workloads where bounded context helps

comPREssOR is most aligned with long-running workstreams where the important memory can be written as durable state. Examples include:

- Multi-turn debugging, where the current hypothesis, failing command, and ruled-out causes matter more than every previous log line.
- Release preparation, where checklists, documentation paths, version constraints, and human blockers need to survive across turns.
- Documentation writing, where voice constraints, measured values, and source boundaries need to remain visible.
- Refactor planning, where accepted design decisions and open migration steps are more useful than repeated discussion.
- Agent handoff, where the next prompt needs a compact view of what was done, what remains, and where evidence lives.

These workloads benefit from a memory layer because raw conversation history contains both state and noise. comPREssOR tries to carry state first.

The mechanism is less aligned with tasks that require complete source fidelity. If the next turn asks the model to quote exact paragraphs, compare every sentence in a long document, or preserve the full structure of a legal or research text, a bounded pack is the wrong primary source. In those cases, attach or reference the source directly. comPREssOR can still carry the fact that the source matters, but it should not be treated as the source.

Short sessions are also less compelling. If the raw transcript is smaller than the budget, replaying or relying on the visible context may be simpler. The benefit of bounded forwarding increases when the history grows and when prior turns would otherwise be resent or reintroduced repeatedly.

## What local state buys

The local state lets comPREssOR do two things that a one-shot summary cannot do as reliably.

First, it updates continuously. Each observed prompt and response can create a new state node. The system does not wait for a human to ask for a summary at the end of a session. It accumulates a lineage of compact state as the conversation proceeds.

Second, it separates numeric digest from symbolic memory. The matrix track gives the engine a bounded representation that can support ranking and compact persistence. The graph track keeps human-readable structure: facts, events, paths, headings, open items, and supersession. That combination is useful because prompt continuity needs both selection and labels. Ranking can find candidate spans, while typed graph lines tell the model what role a line plays.

The local state also creates a clean privacy and debugging boundary. Files under the state root are local artifacts. They can be inspected, purged, or ignored. The model-facing boundary is the text pack. When debugging, you can ask: did the hook fire, did it update state, did the graph record the right item, did the pack include it, and did the final prompt contain it? That is more observable than a hidden memory claim.

The cost is that local state can be wrong or incomplete. Extraction may miss a decision. A vague prompt may not create a useful open item. A completed task may remain active if it was never clearly closed. A ranked chunk may match a keyword but not the user's intent. The system is designed to degrade into ordinary text prompting, not to remove the need for prompt discipline.

## Reading the three arms

The raw arm answers the question: what happens if we forward everything? It is expected to have high term recall because the source text is present. Its weakness is cost and size.

The legacy vocabulary-bag arm answers the question: what happens if we make the payload extremely small without enough structure? It shows that compression can win a size contest while losing the useful-context contest. The bag contained real words derived from local state, but it did not preserve the target terms in the probe. That is why its `entity_recall` was 0.00.

The comPREssOR pack answers the question: what happens if the payload is still small but ordered around active graph state and ranked spans? It did not match raw recall, but it retained a non-zero share of the target terms while staying far below raw replay size. That is the intended operating region: not maximal retention, not minimal size, but bounded relevance.

This is also why the measured pack should not be oversold. A recall proxy of 0.33 is informative because it beats the vocabulary bag and passes the scoped gate. It is not a strong answer-quality score. The pack missed several target terms. A careful reader should see both facts at once: the mechanism worked enough to carry some relevant state, and the evaluation shows room for better extraction and ranking.

## Interpreting "utility per token"

The theory behind comPREssOR can be stated without heavy math. A prompt has utility when it supplies information that helps the model do the task. A prompt has token cost because every forwarded token competes with budget, latency, and sometimes billing. Utility per token asks whether the prompt is spending its tokens on useful material.

Raw replay often has high total utility because it contains everything. But as the session grows, its utility per token can decline. Many tokens are old, repeated, or irrelevant to the current turn. A bounded pack can have lower total utility and still higher utility per token if it keeps the active material and removes enough noise.

The condition is not automatic. The pack must retain relevant entities and relations. If it drops the current file path, the accepted decision, or the blocker, then token savings may not help. That is why recall appears as a constraint, not an afterthought. A good compressor should not optimize only for fewer tokens; it should optimize for useful retained context inside a budget.

For prompt engineers, the practical version is:

```text
Do not ask "how short is the memory?"
Ask "does the memory carry the next turn's needed state?"
```

If the answer is yes, then the smaller prompt is valuable. If the answer is no, the prompt may be cheap but unhelpful.

## Honesty ledger

The current evidence supports bounded context assembly and scoped token-use reduction on one lab/live SDK probe. It does not prove broad task success. It does not compare against every alternative, such as last-N truncation, summary-only memory, vector retrieval, or human-written session notes. It does not prove a universal advantage over raw replay.

The recall number is a fixture term-hit proxy. It is useful because it catches the vocabulary-bag failure, but it is not a semantic correctness metric. A future evaluation should include graded tasks, repeated trials, variance, matched-budget baselines, and real Agent Chat UI validation.

The live billed totals include the SDK envelope. They are useful for comparing the three arms in the same probe, but they should not be read as the exact size of the comPREssOR payload.

The measured pack missed several target terms. That is a real limitation. It shows where ranking, budget selection, and extraction can improve. It also shows why comPREssOR documentation should avoid unsupported claims about complete recall.

The system is therefore best described as a bounded forward-context mechanism. It changes what is carried into later prompts: active memory first, typed durable facts second, ranked spans third, all inside a configured text budget. For prompt engineers working in long Cursor sessions, that mechanism can make continuity cheaper and more explicit than raw replay, while preserving a clear boundary around what has and has not been measured.
