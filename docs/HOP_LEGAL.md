# Hop legality (`hop_legal`)

CC-7 exposes `PersistentAgentHandle.hop_legal()` as a scheduling constraint for
model hops (comPASS Tier 4).

## Rules

- **Legal** only at turn boundaries with **no pending tool state**.
- Returns **False** when:
  - `handle.set_pending_tool(True)` was called and not cleared, or
  - latest `StateNode.meta["pending_tool"]` is `true`, or
  - `meta["tool_status"]` is one of `pending`, `in_flight`, `awaiting`, `tool_pending`.
- Returns **True** when tool state is unknown/`stub` and no pending flag is set
  (preserves 0.2.0 hop permissiveness).

## Usage

```python
if handle.hop_legal():
    # safe to change recipient_id on the next step
    ...
else:
    # defer hop until tools settle; clear with handle.clear_pending_tool()
    ...
```

See also `docs/HOOK_CONTRACT.md` and prototype §14.2 CC-7.
