# Formal model of the comPREssOR compressor

This manuscript states the engineering model behind comPREssOR as equations, registries, and plain-English claims. It formalizes the ship code in `engine/src/chat_compressor/`. It is not a proof that Cursor invoices shrink, not an optimality theorem, and not a substitute for the measured cards in [PERFORMANCE.md](PERFORMANCE.md).

**Audience:** readers who want the mathematical form of the packer, ranker, matrix merge, and graph quotas. **Voice:** Spec/math for equations; exposition for narrative. **Evidence authority:** code constants win over prose; PERFORMANCE locked numerals win over approximate marketing ratios.

---

## 1. Abstract / purpose

**Definition.** Let a Cursor Agent Chat session produce a growing transcript $H_t$ at turn $t$. comPREssOR maintains local dual state $S_t=(G_t,C_t)$ and emits a text pack $P_t$ into the `additional_context` channel under an estimated-token budget $B_t$.

**Claim.** The formal objects below match the executable operators `estimate_tokens`, `hashed_ngram_embed`, `rank_relevant_chunks`, `append_then_pool`, `adaptive_budget`, `pack_forward`, graph HOT_SET shares, and the hook hard character cap. Performance identities $\Delta$ and $\eta$ are defined only on the inject path under the estimator $\tau$.

**Assumptions.**

1. The model-facing channel is ordinary text; matrices and SQLite stay local.
2. Token accounting for packing and PERFORMANCE cards uses $\tau$, not a vendor tokenizer.
3. Heuristic salience, cosine floors, and priority order are surrogates for usefulness, not solutions of an optimization problem.

**Non-claims.** This document does not prove billing savings, answer-quality improvement, or uniqueness of the chosen constants. The ~6× / ~84% inject-path figures are corpus-scoped measurements from [PERFORMANCE.md](PERFORMANCE.md), not closed-form consequences of the equations.

**Plain English.** The math describes what the engine already does: keep local memory, pick a bounded text pack, and measure that pack with a simple character estimator. Reading this page should make the code easier to audit, not invent a stronger product claim.

**How to read this manuscript.** Each numbered section follows the same pattern: a definition (often with a display equation), a claim that ties the definition to ship code, assumptions that bound the claim, explicit non-claims, and a plain-English restatement. Tables collect symbols and constants so an auditor can grep the engine without re-deriving numerals from prose. When PERFORMANCE and this page disagree on a measured sum, PERFORMANCE wins for empirical claims; when this page and Python disagree on a constant, Python wins and this page should be patched.

**What “formal” means here.** Formal means the objects are named, the maps between them are written with standard notation, and every constant cites a module. It does not mean a machine-checked proof, a PAC-learning guarantee, or a complexity lower bound. The compressor is an engineering policy $\Pi$ with measurable inject-path volume under $\tau$. That is enough to make the behavior falsifiable: change a constant, re-run packing, and observe whether $\tau(P_t)$ and retention proxies move as the equations suggest.

**Pipeline sketch.** History and dual state feed the packer; the packer emits text under $\tau(P_t)\le B_t$:

```text
H_t --> G_t (graph) ----\
                         +--> Pi(S_t, q_t; B_t) --> P_t --> Agent Chat
H_t --> C_t (matrix) ---/
q_t --------------------/
```

$G_t$ and $C_t$ update locally on hook events. Only $P_t$ (after optional character truncate) crosses into Cursor’s `additional_context` channel.

---

## 2. Where theory lived before

Before this file, “theory” in the public tree was informal.

| Doc | Role |
| --- | --- |
| [WHY.md](WHY.md) | Utility-per-token exposition; explicitly says the idea can be stated without heavy math |
| [PERFORMANCE.md](PERFORMANCE.md) | Locked inject-corpus numerals and honesty lines |
| [SYSTEM.md](SYSTEM.md) | Architecture, pack recipe, settings |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Doc index |

There was no `.tex` appendix and no equation blocks under `docs/`. That was a product choice, not an accidental omission.

**Why math was deferred.**

1. **Audience.** Install and prompt-engineering docs lead with mechanism → outcome → scope.
2. **Honesty.** Formalizing the engine as “the math of 600%” would overclaim an empirical ratio.
3. **Evidence docs lead.** WHY and PERFORMANCE locked measured numerals; a formal model was never a ship gate for the VSIX.
4. **Code as source of truth.** The live model is `metrics.py`, `pack.py`, `rank.py`, `compress.py`, `producer.py`, `graph.py`, and `hook_cli.py`.

**Claim.** Adding `THEORY.md` is additive documentation: it explains the code; it does not unlock or strengthen the 84% / 6× inject-path figure.

**Plain English.** Earlier docs taught *why* and *how much* without writing LaTeX. This page adds *what equations the code implements*, with the same honesty bounds.

**Assumptions.** Readers may arrive from README, WHY, or PERFORMANCE. **Non-claims.** This manuscript does not imply a journal submission, a separate `MODEL.tex`, or parity with any lab CHAT-COMPRESSOR mirror.

**Relationship to other surfaces.** SYSTEM remains the utilization guide. ARCHITECTURE remains the index. THEORY is the equation form of the operators those pages describe in prose. If a setting name changes, update section 15; if a PERFORMANCE numeral is re-locked, update sections 11 and 16.

---

## 3. Notation registry

| Symbol | Meaning |
| --- | --- |
| $t$ | Turn index (1-based in narrative; compared as integer in `adaptive_budget`) |
| $q_t$ | Current user prompt (query) |
| $H_t$ | Full session history through turn $t$ |
| $G_t$ | Symbolic context graph (`ctx-graph/v1`) |
| $C_t \in \mathbb{R}^{k \times d}$ | Bounded matrix of live gist rows |
| $S_t=(G_t,C_t)$ | Dual local state |
| $P_t$ | Text pack injected as `additional_context` |
| $R_t$ | Replay arm text for turn $t$ (ingest dump on the inject corpus) |
| $B_t$ | Adaptive forward budget at turn $t$ (estimated tokens) |
| $B_{\max}$ | Cap / default forward budget |
| $\tau(\cdot)$ | Token estimator (`estimate_tokens`) |
| $\Pi$ | Packer (`pack_forward`) |
| $\varepsilon$ | Empty string |
| $L$ | Hard character cap on final injected context |
| $d$ | Embedding dimension |
| $K_{\max}$ | Maximum live rows in $C_t$ |
| $\theta$ | Minimum cosine rank score |
| $\mu$ | Marginal Jaccard skip threshold |
| $U(P;q)$ | Informal utility of pack $P$ for query $q$ (docs only) |

**Assumptions.** Symbols name engineering objects; they are not random variables unless stated. Indices $t$ align with hook-driven turn processing in the engine, not with Cursor’s internal billing meters. Sets of candidates $\mathcal{U}_t$ are finite lists produced by graph projection and ranking, not continuous function spaces.

**Non-claims.** The registry does not introduce probability measures, asymptotic complexity bounds, or a formal type system beyond ordinary mathematical notation for vectors and scalars. $U(P;q)$ appears only as a documentation placeholder in section 13.

**Plain English.** The table is a glossary so later sections can write short equations without redefining every letter. When in doubt, the Source map at the end points each symbol family to a Python file.

---

## 4. Token estimator ($\tau$)

**Definition.** For text $x$ with character length $|x|$,

$$
\tau(x)=\max\!\left(1,\ \left\lfloor\frac{|x|+3}{4}\right\rfloor\right)\quad\text{for }x\neq\varepsilon;\quad\tau(\varepsilon)=0.
$$

Code: `estimate_tokens` in `metrics.py` — integer division `(len(text)+3)//4` with floor 1 for nonempty text.

**Claim.** $\tau$ is the unit of packing (`pack_forward`), adaptive budget fill rates, payload stats, and the PERFORMANCE inject-corpus cards.

**Assumptions.** Character length is Unicode string length in Python (`len(text)`). Empty input is the only case returning 0.

**Non-claims.** $\tau$ is not tiktoken, not Anthropic/OpenAI tokenization, and not Cursor billing. Ratios under $\tau$ are estimator ratios unless a probe explicitly reports billed usage (see the separate SDK probe in WHY/PERFORMANCE).

**Plain English.** Four characters count as about one “token” for the compressor’s own accounting. That keeps measurements reproducible without depending on a vendor tokenizer. It is the wrong unit for reading a Cursor invoice.

**Worked micro-examples.** For ASCII `abcd` ($|x|=4$), $\tau=(4+3)//4=1$. For `abcde` ($|x|=5$), $\tau=2$. For the empty string, $\tau=0$ so an empty pack does not consume budget in rate calculations that divide by $\tau(P)$ only when $P\neq\varepsilon$. Whitespace-only strings are nonempty under Python `len`, so they receive at least one estimated token if packed. Pack truncation `_truncate_to_budget` targets roughly `budget * 4` characters because that is the inverse sketch of $\tau$.

**Why PERFORMANCE uses the same unit.** Cross-arm comparisons (replay vs pack) must share one estimator. Using vendor tokenizers would couple the cards to model choice and version drift. Using $\tau$ keeps the 199-prompt arithmetic stable across engine builds `0.1.1 / 0.1.2` as documented on the cards. Readers comparing a Cursor usage export to these cards must convert carefully or treat the series as incomparable.

---

## 5. Growth vs budget

**Definition.** Session history grows monotonically in content size:

$$
|H_t|\ \text{nondecreasing in }t,\qquad\tau(P_t)\le B_t\le B_{\max}.
$$

Defaults from code:

| Symbol | Value | Source |
| --- | ---: | --- |
| $B_{\max}$ | 1024 | `DEFAULT_FORWARD_BUDGET` in `pack.py` (override via `CHAT_COMPRESSOR_FORWARD_BUDGET` / settings `forwardBudget`) |
| $L$ | 8000 | `_MAX_CONTEXT_CHARS` in `hook_cli.py` |

After packing, the hook may truncate the final string so $|P_t^{\mathrm{out}}|\le L$. Truncation is character-based; packing itself is $\tau$-based.

**Claim.** The product constraint is bounded inject text, not unbounded replay of $H_t$ on the memory-inject channel.

**Assumptions.** Native Cursor chat history is still sent by the host and is outside $\tau(P_t)$. Fail-open hooks may yield $P_t=\varepsilon$.

**Non-claims.** $B_{\max}=1024$ is a default operating point, not a proven optimum for recall or cost.

**Plain English.** Chat history keeps growing. The compressor refuses to let its *extra* context grow without a cap. Cursor’s own thread is a separate channel; this page’s budgets apply to the gist inject.

**Two budgets, two units.** Packing enforces $\tau(P_t)\le B_t$ using estimated tokens. The hook then enforces $|P_t^{\mathrm{out}}|\le L$ using characters. These constraints are related by the sketch $\tau(x)\approx |x|/4$, but they are not identical: a pack that fits under $\tau$ can still lose a few characters to the hard cap, and truncation prefers the string tail. Operators that reason only about $B_{\max}$ without $L$ understate the final clip.

**Growth identity (informal).** If each turn appends text of size $\delta_t$ to history, then $|H_t|$ tracks $\sum_{i\le t}\delta_i$ while $\tau(P_t)$ stays in $[0,B_t]$. Continuity depends on useful entities migrating into $G_t$ (and thus $P_t$)—an empirical bet measured on PERFORMANCE’s corpus, not a theorem.

**Assumptions (continued).** $B_t$ may be smaller than $B_{\max}$ after warmup when novelty is low. Skip method can set $P_t=\varepsilon$ even when $B_t>0$. **Non-claims.** Bounding inject size does not bound total tokens Cursor sends on other channels.

---

## 6. Dual state

**Definition.**

$$
S_t=(G_t,\ C_t),\qquad P_t=\Pi(S_t,\ q_t;\ B_t).
$$

- $G_t$: typed nodes (Turn, Topic, Fact, OpenItem, Event) and edges; produces HOT_SET and typed lines.
- $C_t$: numeric digest rows used for local merge and ranking support; never shipped as tensors to the model.
- $\Pi$: packer assembling HOT_SET ≻ typed ≻ ranked text under $B_t$.

**Claim (text-only model boundary).** The Agent Chat model observes only text $P_t$ (plus native host context). It does not observe $C_t$, SQLite, or graph JSON.

**Assumptions.** Local persistence may store richer structures; projection into text is mandatory for model use.

**Non-claims.** Dual state is not hidden recurrence inside the foundation model. Absence from $P_t$ means comPREssOR did not supply that fact on the inject path.

**Plain English.** The engine keeps a notebook ($G_t$) and a compact numeric summary ($C_t$). The model only reads the short letter ($P_t$) the packer writes from that notebook.

**Update sketch.** On ingest, turn text updates $G_t$ via `ingest_turn` (insert, supersede, prune). Independently, producers may encode new text into rows and merge into $C_t$ via `append_then_pool`. At pack time, $\Pi$ reads projections of $G_t$ (HOT_SET, typed lines) and ranking over candidates; $C_t$ supports local digest metrics and optional probes but is not serialized into the inject string.

**Schema boundary.** $G_t$ uses schema id `ctx-graph/v1` with kinds Turn, Topic, Fact, OpenItem, Event. That schema is an engineering contract for local persistence and projection, not a claim that the foundation model understands the graph API.

**Assumptions (continued).** Persistence roots are configurable (`CHAT_COMPRESSOR_STATE_DIR`). **Non-claims.** Dual state does not imply cryptographic integrity, multi-user sync, or cross-IDE transfer.

---

## 7. Hashed n-gram embed

**Definition.** Offline default embedding `hashed_ngram_embed` maps text $x$ to $\hat{v}(x)\in\mathbb{R}^d$ by feature-hashing 1–3 grams:

$$
v(x)_j = \sum_{n=1}^{3} \sum_{g \in \mathcal{N}_n(x)} \sigma(g)\,\mathbf{1}[h(g)\equiv j \bmod d]
$$

$$
\hat{v}(x)=\frac{v(x)}{\|v(x)\|_2}
$$

(with a convention that an empty token list uses a sentinel token `"empty"`). Here $h$ and $\sigma\in\{+1,-1\}$ come from BLAKE2b over the payload `seed:n:gram` (`producer.py`).

| Const | Value | Source |
| --- | ---: | --- |
| $d$ | 256 | `DEFAULT_D` in `compress.py` / default arg in `hashed_ngram_embed` |
| seed $s$ | 0 | default |

Optional SentenceTransformer or HF gist producers may replace this map when env paths are set; pytest and the default offline path use hashed n-grams.

**Claim.** Ranking cosine is computed in this feature space unless a heavier embedder is explicitly enabled.

**Assumptions.** Tokenization for grams uses `[A-Za-z0-9_']+` on lowercased text. **Non-claims.** The hash embed is not a semantic encoder with training guarantees; collisions are expected and tolerated.

**Plain English.** The default “embedding” is a stable bag of character-ish word pieces hashed into a 256-dimensional unit vector. No model download is required for the default path.

**Construction detail.** For each $n\in\{1,2,3\}$ and each contiguous $n$-gram $g$ of tokens, the engine hashes the UTF-8 payload `f"{seed}:{n}:{gram}"` with BLAKE2b (`digest_size=8`). The first four digest bytes select index $j=h\bmod d$; a later byte selects sign $\sigma\in\{+1,-1\}$. Contributions accumulate, then L2-normalize. Empty token lists substitute the sentinel `"empty"` so the map remains total.

**Why hash embedding.** The default path must run offline and stay deterministic for tests. Feature hashing trades semantic precision for that constraint. Cosine in this space is cheap lexical-ish similarity, not a trained relevance model.

**Assumptions (continued).** Optional `EMBED_MODEL_PATH` / `GIST_MODEL_PATH` producers can change $d$ and geometry. **Non-claims.** BLAKE2b here is a stable mixer, not a cryptographic authenticator for security claims.

---

## 8. Ranking

**Definition.** For query $q$ and chunk $c$,

$$
\mathrm{score}(q,c)=\cos\!\big(\hat{v}(q),\hat{v}(c)\big)=\frac{\langle\hat{v}(q),\hat{v}(c)\rangle}{\|\hat{v}(q)\|_2\,\|\hat{v}(c)\|_2}
$$

`rank_relevant_chunks` keeps scores $\ge\theta$; if none survive, it falls back to the top $k_{\mathrm{fb}}$ chunks:

$$
\theta = 0.03
$$

$$
k_{\mathrm{fb}} = 3
$$

Constants: `MIN_RANK_SCORE` $=0.03$, `RANK_FALLBACK_TOP_K` $=3$. Candidates come from `collect_candidates` (window text chunks, recent turns, typed projection, durable facts, open items). Empty query yields an empty ranked list.

**Claim.** Ranking is extractive and wording-preserving: selected chunks are verbatim spans, not paraphrases.

**Assumptions.** Near-zero vectors yield cosine 0. Dedup is by lowercased full chunk text. **Non-claims.** Cosine $\ge\theta$ is not a calibrated probability of relevance.

**Plain English.** The packer asks: which past spans look most like the current prompt in the hash space? Weak matches are dropped unless *everything* is weak, in which case the top three still compete for budget.

**Ordering.** After scoring, chunks sort by descending score, then by descending length as a tie-break (`rank_chunks`). That prefers slightly longer supporting spans when cosine ties. Dedup keys are lowercased full chunk strings, so near-duplicates with different casing collapse before packing.

**Candidate construction.** `collect_candidates` unions window text chunks (structure-aware `chunk_text`), summaries from recent turns (last eight), typed projection lines, topics/events, durable facts with relevance or high-value hints, and open OpenItems. Query-term overlap (`_relevant`) biases which durable facts enter the pool. The ranked list is therefore not “all history”; it is a bounded extraction from $G_t$ plus window text.

**Assumptions (continued).** Floor $\theta=0.03$ is intentionally low so weakly related but still positive scores can survive; fallback $k_{\mathrm{fb}}=3$ prevents an empty ranked family when the whole pool sits below $\theta$. **Non-claims.** Neither $\theta$ nor $k_{\mathrm{fb}}$ was derived from a labeled ranking dataset in this manuscript; they are ship defaults subject to code change.

---

## 9. Append-then-pool

**Definition.** Given prior matrix $C_{t-1}$ and new row block $X_t$, stack then repeatedly merge while $k>K_{\max}$. Merge the adjacent pair with highest cosine via EMA:

$$
c'=\alpha\,c_i+(1-\alpha)\,c_{i+1},\qquad\alpha=0.7,\quad K_{\max}=32.
$$

Constants: `DEFAULT_EMA` $=0.7$, `DEFAULT_K_MAX` $=32$. Then L2-normalize rows (`append_then_pool` in `compress.py`).

**Claim.** This compresses *local numeric digests*, not the inject text $P_t$. Inject size is governed by $\Pi$ and $\tau$, not by $K_{\max}$ alone.

**Assumptions.** New rows come from chunked encodes of new input. If prior is empty, pooling starts from the new block only.

**Non-claims.** EMA merge is not information-theoretically optimal retention of past turns.

**Plain English.** The matrix is a fixed-size shelf of summary vectors. When the shelf overflows, the two most similar neighbors are blended so the shelf stays at most 32 rows.

**Algorithm steps.** (1) Ensure `new_rows` is 2-D. (2) Stack under prior $C_{t-1}$ or start from new rows alone. (3) While row count exceeds $K_{\max}$, scan adjacent pairs for maximum cosine, replace the pair with $\alpha c_i+(1-\alpha)c_{i+1}$. (4) L2-normalize all surviving rows with a small epsilon floor on norms. Adjacent-only merges preserve a rough temporal order while allowing similar neighbors to collapse.

**Interaction with pack.** Pooling limits local matrix growth for metrics and optional producers. Inject size still goes through $\Pi$ and $\tau$. A session can have a full $C_t$ and still emit a small $P_t$ if budget, skip, or fail-open dominate.

**Assumptions (continued).** Default $\alpha=0.7$ weights the earlier neighbor more heavily than the later one in each merge. **Non-claims.** Adjacent EMA is not equivalent to a learned attention pool, KV-cache compression, or lossless sketch of past tokens.

---

## 10. Adaptive budget

**Definition.** Let $r_t\in[0,1]$ be a novelty rate supplied to `adaptive_budget`. With cap $B_{\max}$:

$$
B_t = B_{\max}\quad\text{when } t \le T_w
$$

$$
B_t = \max\!\Big(T_{\mathrm{floor}},\,\min\big(B_{\max},\ \lfloor B_{\max}\cdot\max(\rho_{\min},\,r_t)\rfloor\big)\Big)\quad\text{when } t > T_w
$$

| Const | Value | Code name |
| --- | ---: | --- |
| $T_w$ | 3 | `WARMUP_TURNS` |
| $\rho_{\min}$ | 0.5 | `NOVELTY_BUDGET_FLOOR` |
| $T_{\mathrm{floor}}$ | 64 | `SKIP_FLOOR_TOKENS` (also used as scaled-budget floor) |

**Claim.** Early turns receive the full cap; later turns may shrink the budget toward novelty, never below 64 estimated tokens when scaling applies, and never above $B_{\max}$.

**Assumptions.** $r_t$ is clipped to $[0,1]$. Cap may be overridden by env/settings. **Non-claims.** Novelty scaling is a heuristic throttle, not a proof of optimal information rate.

**Plain English.** The first three turns get the full 1024-token room. After that, quiet/repetitive sessions get a smaller allowance so the inject stays lean.

**Floor dual-use.** The constant 64 (`SKIP_FLOOR_TOKENS`) appears both as the lower clamp on scaled $B_t$ and as the packed-size threshold for optional skip when open items are unchanged and supersede flags are quiet. That coupling means “very small packs” and “budget floors” share a numeral by design in `pack.py`.

**Novelty input.** Callers supply $r_t$; the manuscript does not redefine novelty measurement here. The equation only states how a clipped rate maps to $B_t$. If novelty is misestimated high, budgets stay large; if misestimated low, ranked chunks starve earlier.

**Assumptions (continued).** Env override of the cap applies before warmup branching. **Non-claims.** Warmup length $T_w=3$ is not proven optimal for all session lengths; it is a ship default matching early-session need for fuller context.

---

## 11. Pack assembly

**Definition.** Ordered candidate families $u_1\prec u_2\prec u_3$: HOT_SET block, typed lines, ranked chunks. The packer greedily concatenates while the prefix stays within budget under $\tau$:

$$
P_t=\mathrm{concat}\big(u\in\mathcal{U}_t:\ \tau(\mathrm{prefix})\le B_t\big).
$$

Cross-turn / marginal dedup uses keyword Jaccard:

$$
J(A,B)=\frac{|A\cap B|}{|A\cup B|},\qquad\text{skip if } J > \mu,\quad \mu = 0.8.
$$

Related constants: `MARGINAL_JACCARD` $=0.8$, `DEDUP_K=3` (last-K line-hash suppression window when enabled), cross-turn dedup default on (`CHAT_COMPRESSOR_CROSS_TURN_DEDUP`). Optional skip method returns empty pack when allowed and packed size is below the skip floor without open-item / supersede changes.

**Performance identity (inject corpus).** For replay texts $R_t$ and packs $P_t$,

$$
\Delta=\sum_t \tau(R_t)-\sum_t \tau(P_t),\qquad\eta=1-\frac{\sum_t\tau(P_t)}{\sum_t\tau(R_t)}.
$$

**Locked numerals** ([PERFORMANCE.md](PERFORMANCE.md), 199-prompt corpus, unit $\tau$ = `chars/4`):

| Quantity | Exact |
| --- | ---: |
| $\sum\tau(R)$ | 862201 |
| $\sum\tau(P)$ | 139465 |
| $\Delta$ | 722736 |
| $\eta$ | $\approx 0.838$ (display 84%) |
| Cap / median inject | 1024 / 783 |

Ratio illustration: $\sum\tau(R)/\sum\tau(P)\approx 6.18$ (~6×). Scope: memory-inject path only.

**Claim.** Pack order makes active HOT_SET material survive truncation before ranked prose.

**Assumptions.** Same ingested corpus for both arms; Pattern-1 vocab decode is off in this measurement. **Non-claims.** $\eta$ is not a Cursor billing cut; native history is outside $\Delta$.

**Plain English.** Fill the suitcase in priority order: active checklist first, labeled facts second, similar old paragraphs last. Stop when the estimated token budget is full. On the measured corpus, the suitcase held about one sixth of the replay pile.

---

## 12. HOT_SET shares and graph caps

**Definition.** HOT_SET slot shares (`graph.py`):

$$
s_{\mathrm{open}}=0.40,\quad s_{\mathrm{decision}}=0.40,\quad s_{\mathrm{path}}=0.20.
$$

Default HOT_SET assembly uses `max_chars=400`. Slot count is approximately $n_{\mathrm{slots}}=\max(5,\lfloor M/64\rfloor)$ where $M$ is `max_chars`, then per-bucket caps are $s\cdot n_{\mathrm{slots}}$ (at least 1). Ranking within buckets uses salience plus a Jaccard overlap term with the query when present:

$$
\mathrm{rank}(n)=\mathrm{salience}(n)+0.5\cdot J(\mathrm{keywords}(n),\mathrm{keywords}(q)).
$$

**Active graph caps** (prune):

| Cap | Value | Constant |
| --- | ---: | --- |
| Active turns | 32 | `MAX_ACTIVE_TURNS` |
| Non-durable facts | 48 | `MAX_ACTIVE_NON_DURABLE_FACTS` |
| Durable facts | 32 | `MAX_ACTIVE_DURABLE_FACTS` |
| Paths per turn | 8 | `PER_TURN_PATH_CAP` |

Salience is a heuristic weight from regex/boost rules in `graph.py` (decision cues, tradeoffs, paths, preamble penalties, etc.). It is not derived from $\tau$ or from an optimization dual.

**Claim.** Quotas bias HOT_SET toward open work and decisions over path/heading clutter.

**Assumptions.** Kind hints (`decision`, `path`, `heading`, …) affect bucket membership. **Non-claims.** Salience is not a calibrated importance probability.

**Plain English.** The hot list reserves roughly two-fifths of its slots for open items, two-fifths for decision-like facts, and one-fifth for paths/headings, then trims old turns and excess facts so the graph does not grow without bound.

**Salience as heuristic weight.** Sentence facts receive scores from regex boosts (decision language, tradeoffs, numeric claims, identifiers, definitions) and penalties (preamble cues, high overlap with the prior user turn). Paths and headings use separate salience schedules (mention counts, fence-only gating, scripts/figures boosts, SDLC-path penalties). Design/outcome facts may enter with elevated fixed salience (e.g. 2.0–2.5). Decision-bucket membership for HOT_SET uses kind hints or salience $\ge 2.0$ after excluding path/heading nodes. None of these weights solve for $U$; they are editable engineering knobs encoded in `graph.py`.

**Prune semantics.** Exceeding turn/fact caps marks oldest active nodes pruned with a reason attribute; durable facts prune by ascending salience then age. Prune reduces what future HOT_SET/typed projections can see; it does not rewrite Cursor’s native history.

**Assumptions (continued).** Default HOT_SET `max_chars=400` is independent of $B_{\max}$; packing may still truncate a long HOT_SET block if $\tau$ of the HOT_SET prefix exceeds $B_t$. **Non-claims.** Share ratios 0.40/0.40/0.20 are not derived from an information-theoretic allocation theorem.

---

## 13. Utility framing

**Definition (informal, documentation only).** WHY’s objective sketch:

$$
\max_{P:\ \tau(P)\le B}\ \frac{U(P;q)}{\tau(P)}\quad\text{s.t. recall of active entities}.
$$

**Claim.** Ship code does **not** optimize $U$. It uses fixed priority order, cosine ranking, Jaccard dedup, and salience heuristics as a surrogate policy $\Pi$.

**Assumptions.** $U$ is not instrumented as a scalar loss in production hooks. Fixture `entity_recall` in lab probes is a term-hit proxy, not $U$.

**Non-claims.** No theorem states that $\Pi$ maximizes utility per token. Smaller $\tau(P)$ can lower $U$ (legacy vocabulary-bag cautionary arm in WHY).

**Plain English.** The docs talk about “useful tokens.” The code implements a practical recipe that usually keeps useful-looking lines. That recipe is not a solver for a utility function.

**Bridge to WHY.** WHY states the same idea without heavy math: utility per token rises when noise falls faster than useful material. This section writes the informal program that WHY describes, then records that the implementation is a fixed policy $\Pi$, not an optimizer. For the equation form of budgets, ranking, and pack order, prefer sections 4–12; for product motivation and the SDK probe, prefer WHY.

**Assumptions (continued).** Lab proxies such as `entity_recall`, `design_precision`, and `hot_set_pollution` in `metrics.py` are diagnostic scores for fixtures and reports. They are not the production loss minimized each turn. **Non-claims.** Improving a proxy score does not automatically improve user-visible answer quality.

---

## 14. Operator table

| Operator | Inputs | Output | Primary code path |
| --- | --- | --- | --- |
| Extract / ingest | turn role, text, index | nodes/edges in $G_t$ with salience / `kind_hint` | `graph.CtxGraph.ingest_turn` |
| Embed | text | $\hat{v}\in\mathbb{R}^{d}$ (default $d=256$) | `producer.hashed_ngram_embed` |
| Rank | $q$, candidate chunks | ordered `RankedChunk` list | `rank.rank_chunks` / `rank_relevant_chunks` |
| Pool | prior $C$, new rows | $C_t$ with $\le K_{\max}$ rows | `compress.append_then_pool` |
| Pack | HOT_SET, typed lines, ranked chunks, $B_t$ | $P_t$ with $\tau(P_t)\le B_t$ | `pack.pack_forward` |
| Truncate | final context string | string with $\le L=8000$ chars | `hook_cli._truncate_context` |
| Estimate | text | $\tau(x)$ | `metrics.estimate_tokens` |
| Adaptive budget | turn $t$, novelty $r_t$, cap | $B_t$ | `pack.adaptive_budget` |
| HOT_SET project | graph, optional query | compact multi-line text | `graph.CtxGraph.hot_set` |
| Typed project | graph, optional query | `OpenItem:` / `Fact:` / `Path:` / `Event:` lines | `graph.CtxGraph.typed_projection` |

**Claim.** End-to-end inject assembly is the composition of extract → (embed/rank as needed) → pack → truncate, with pool updating local $C_t$ off the model channel.

**Composition note.** Operators are not one pure function; the hook CLI orchestrates ingest, ranking, packing, and truncation. The table is the mathematical interface: each row names a map with typed I/O and a primary file. Helpers (chunking, Jaccard sets, line hashes) support those maps without changing the product boundary (text out, matrices local).

**Plain English.** Six named moves build the product behavior: pull facts, embed, score, merge vectors, pack text, hard-cap characters. The hook wires those moves into Cursor events; the equations name the moves so audits can walk file-by-file.

---

## 15. Constant and parameter registry

### Code constants (not settings UI)

| Name | Value | Module |
| --- | ---: | --- |
| `DEFAULT_FORWARD_BUDGET` | 1024 | `pack.py` |
| `WARMUP_TURNS` | 3 | `pack.py` |
| `NOVELTY_BUDGET_FLOOR` | 0.5 | `pack.py` |
| `SKIP_FLOOR_TOKENS` | 64 | `pack.py` |
| `MARGINAL_JACCARD` | 0.8 | `pack.py` |
| `DEDUP_K` | 3 | `pack.py` |
| `MIN_RANK_SCORE` | 0.03 | `rank.py` |
| `RANK_FALLBACK_TOP_K` | 3 | `rank.py` |
| `DEFAULT_D` | 256 | `compress.py` |
| `DEFAULT_K_MAX` | 32 | `compress.py` |
| `DEFAULT_EMA` | 0.7 | `compress.py` |
| `_MAX_CONTEXT_CHARS` | 8000 | `hook_cli.py` |
| `HOT_SET_OPEN_SHARE` | 0.40 | `graph.py` |
| `HOT_SET_DECISION_SHARE` | 0.40 | `graph.py` |
| `HOT_SET_PATH_HEADING_SHARE` | 0.20 | `graph.py` |
| `MAX_ACTIVE_TURNS` | 32 | `graph.py` |
| `MAX_ACTIVE_NON_DURABLE_FACTS` | 48 | `graph.py` |
| `MAX_ACTIVE_DURABLE_FACTS` | 32 | `graph.py` |
| `PER_TURN_PATH_CAP` | 8 | `graph.py` |
| HOT_SET default `max_chars` | 400 | `graph.hot_set` |

### User-tunable settings / env (projection)

| Setting / env | Maps to | Notes |
| --- | --- | --- |
| `forwardBudget` / `CHAT_COMPRESSOR_FORWARD_BUDGET` | $B_{\max}$ | Must be ≥ 1 |
| `kMax` / `K_MAX` | $K_{\max}$ | Matrix row cap |
| `injectP1` / related flags | Pattern-1 debug vocab path | Off by default; not in PERFORMANCE inject cards |
| State directory / `CHAT_COMPRESSOR_STATE_DIR` | on-disk $S_t$ root | Default under `~/.cursor/context-graphs/` |
| `CHAT_COMPRESSOR_CROSS_TURN_DEDUP` | enable last-K hash suppress | Default on |
| `CHAT_COMPRESSOR_FACTS_PER_TURN` | sentence fact intake cap | Default 3, clamped 1–12 |
| `EMBED_MODEL_PATH` / `GIST_MODEL_PATH` | optional heavy producers | Default path stays hashed n-gram |

**Claim.** Ranking floor $\theta$ and Jaccard $\mu$ are code constants today; changing them requires a code change, not only a settings toggle.

**Plain English.** You can turn the budget dial and the matrix size. Many of the subtle thresholds are baked into the engine on purpose so measurements stay comparable.

---

## 16. Worked numerical example

**Setup.** 199-prompt inject corpus; unit $\tau$; cap 1024; builds referenced on PERFORMANCE cards (`0.1.1 / 0.1.2`).

**Replay vs pack sums.**

$$
\sum_t\tau(R_t)=862201,\qquad\sum_t\tau(P_t)=139465.
$$

**Delta and efficiency.**

$$
\Delta=862201-139465=722736,\qquad\eta=1-\frac{139465}{862201}\approx 0.838.
$$

**Multiple.**

$$
\frac{\sum\tau(R)}{\sum\tau(P)}=\frac{862201}{139465}\approx 6.18\quad(\text{display ~6×}).
$$

**Median.** Median packed inject on the corpus is 783 estimated tokens (≤ 1024).

**Dedup (inside inject stream, not added to $\Delta$).** On 147 metered turns, 65944 candidate tokens dropped as duplicates (46% yield). This filters re-sends inside the inject path; it does not enlarge the replay-minus-packed headline.

**Native history.** Cursor still forwards its own chat thread. That volume is outside $\Delta$ and outside the 6× ratio. Net spend drops only if the packed gist *replaces* a paste or post-compact replay of the corpus as `additional_context`.

**Claim.** The worked example is arithmetic on locked PERFORMANCE numerals under $\tau$, not a derivation from first principles.

**Plain English.** Same prompts, two ways to stuff the inject channel: dump everything, or pack under 1024. Pack used about 16% of the dump’s estimated tokens. That is the whole “6×” story—and it stops at the inject channel.

**Arithmetic check.** $139465/862201\approx 0.1617$ (display 16.2%). $1-0.1617\approx 0.8383$ (display 83.8% / 84%). $862201/139465\approx 6.182$. Dollar illustration on PERFORMANCE maps the same ratio to ~18¢ on a **1.00** replay-inject dollar under $\tau$ unit conversion—not a measured price.

**What the example does not compute.** It does not subtract native history, tool outputs Cursor already attached, or billed tokenizer counts. It does not attribute $\Delta$ to any single operator (HOT_SET vs typed vs ranked). Dedup yield is reported separately so readers do not double-count it into $\Delta$.

**Assumptions.** Corpus and build tags match PERFORMANCE’s card eyebrow. **Non-claims.** Re-running on a different corpus can move $\eta$ without any constant in this manuscript changing.

---

## 17. Predicted failure modes

The equations predict several observable failure modes.

1. **Budget starvation of chunks.** Because HOT_SET and typed lines precede ranked chunks, small $B_t$ drops supporting verbatim spans first. Active items may survive while prose disappears.
2. **Low cosine.** If $\mathrm{score}(q,c)<\theta$ for all $c$, only the fallback top-3 compete; weakly related history may still consume budget or be empty of true support.
3. **Fail-open empty pack.** Hook errors or skip method yield $P=\varepsilon$. The turn proceeds as ordinary chat with no compressor inject.
4. **Extraction miss → low $U$.** If salience/regex extraction never inserts the critical path or decision into $G_t$, then $\tau(P)$ can be small while utility is poor. Size metrics will look good; task continuity will not.
5. **Hash collision / weak embed.** Hashed n-grams can rank spuriously; optional ST/HF paths change the geometry but are not the default measurement path.
6. **Hard char truncate after pack.** Even if $\tau(P_t)\le B_t$, `_MAX_CONTEXT_CHARS=8000` can clip the final string, potentially cutting the tail (ranked region) again.
7. **Dedup over-suppression.** High Jaccard or last-K hash matches can drop novel-but-similar lines, reducing recall under tight budgets.

**Claim.** These modes follow from priority order, thresholds, and fail-open design; they are expected engineering tradeoffs.

**Observability.** Many modes leave fingerprints in hook stage logs (method=`skip`, packed_tokens, rate, rank_ms) or in empty `additional_context`. Extraction misses are harder: $\tau(P)$ can look healthy while the missing entity never entered $G_t$. Fixture probes (`entity_recall`, pollution scores) help in lab settings; production diagnosis starts with “was the fact ingested?” then “was it ranked/packed?” then “was it truncated?”.

**Mitigations (engineering, not theorems).** Raise `forwardBudget` when chunks starve; make decisions and open items explicit for extractors; keep Pattern-1 off unless debugging; treat fail-open as correct safety behavior. Changing $\theta$ or $\mu$ requires a code change and a fresh measurement if inject-path claims are at stake.

**Non-claims.** Listing failure modes is not a quantitative reliability model, MTBF estimate, or guarantee that mitigations restore $U$.

**Plain English.** When something important is missing from the inject, check budget, ranking floor, extraction, skip/fail-open, and whether Cursor’s native history already carried the fact.

---

## 18. Honesty ledger / non-claims

1. **No optimality theorem.** Priority packing + cosine + salience is a heuristic policy, not a proven $\arg\max U/\tau$.
2. **$\tau$ is not a billing tokenizer.** PERFORMANCE inject cards use `chars/4`. A separate lab/live SDK probe reports billed totals for that probe only; do not merge probes.
3. **Inject-path only.** 862201 / 139465 / ~83.8% / ~6× are scoped to packed inject vs full-corpus replay of ingested prompt text. Native chat history is outside $\Delta$.
4. **Not a Cursor invoice.** Dollar illustrations (e.g. ~18¢ on the replay dollar) are unit conversions of $\tau$ ratios, not measured dollars-per-token prices.
5. **Pattern-1 off by default.** Vocabulary decode is a debug path; it is not part of the 199-prompt inject measurement.
6. **No hidden model channel.** Only text $P_t$ is injected; $C_t$ stays local.
7. **No guarantee of better answers.** Bounded continuity is the mechanism; answer quality is out of scope for these equations.
8. **Constants may change.** If code drifts, this manuscript must be updated; code wins until docs catch up.

**Plain English.** Treat this page as a map of the machine. Treat PERFORMANCE as the scoreboard. Do not treat either as a billing forecast or a proof that the recipe is mathematically optimal.

---

## Related docs

- [WHY.md](WHY.md) — utility-per-token exposition and SDK probe
- [PERFORMANCE.md](PERFORMANCE.md) — locked inject-corpus numerals and cards
- [SYSTEM.md](SYSTEM.md) — architecture and utilization
- [ARCHITECTURE.md](ARCHITECTURE.md) — documentation index
- [HOOK_CONTRACT.md](HOOK_CONTRACT.md) — hook events and fail-open defaults

## Source map

| Formal object | Authoritative implementation |
| --- | --- |
| $\tau$ | `engine/src/chat_compressor/metrics.py` |
| $B_t$, $\Pi$, $\mu$ | `engine/src/chat_compressor/pack.py` |
| $\theta$, rank fallback | `engine/src/chat_compressor/rank.py` |
| $\hat{v}$ | `engine/src/chat_compressor/producer.py` |
| append-then-pool, $K_{\max}$, $\alpha$, $d$ | `engine/src/chat_compressor/compress.py` |
| HOT_SET shares, graph caps, salience | `engine/src/chat_compressor/graph.py` |
| $L=8000$ | `engine/src/chat_compressor/hook_cli.py` |
