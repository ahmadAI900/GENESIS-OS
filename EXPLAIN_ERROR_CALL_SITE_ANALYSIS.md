# explain_error() Call Site Analysis

**Date:** 2026-09-09  
**Purpose:** Verify all callers of `explain_error()` are compatible with the return type change from `str` to `FriendlyError`.

---

## All Call Sites Found

### 1. `genesis_os/action_executor.py:303`

```python
friendly = explain_error(
    error,
    context={
        "operation": plan.operation,
        "target": plan.target,
        "application": plan.application,
    },
)
return ActionResult.failure_result(
    ...
    message=friendly.user_message,      # Line 315
    error=friendly.original_error,      # Line 317
    ...
)
```

**Analysis:** Accesses `.user_message` and `.original_error` → expects `FriendlyError` object → **COMPATIBLE** ✓

---

### 2. `genesis_os/action_executor.py:569`

```python
friendly = explain_error(
    error,
    context={
        "operation": plan.operation,
        "target": plan.target,
        "application": plan.application,
    },
)
return ActionResult.failure_result(
    ...
    message=friendly.user_message,                 # Line 581
    error=friendly.original_error,                 # Line 583
    ...
    metadata={
        ...
        "friendly_error": {
            "user_message": friendly.user_message,         # Line 594
            "suggested_actions": friendly.suggested_actions, # Line 595
            "recovery_hint": friendly.recovery_hint,       # Line 596
        },
    },
)
```

**Analysis:** Accesses `.user_message`, `.original_error`, `.suggested_actions`, `.recovery_hint` → expects `FriendlyError` object → **COMPATIBLE** ✓

---

### 3. `genesis_os/error_handler.py:280`

```python
def explain_error(error: Exception, context: Optional[Dict[str, Any]] = None) -> FriendlyError:
    """Quick function to get a user-friendly error explanation."""
    handler = ErrorHandler()
    return handler.handle(error, context)
```

**Analysis:** This is the function definition itself → **NOT A CALL SITE**

---

### 4. `test_phase2_deferred_items.py` (multiple lines)

```python
from genesis_os.error_handler import explain_error, FriendlyError

# Multiple test functions calling explain_error() and asserting:
# - isinstance(result, FriendlyError)
# - hasattr(result, "user_message")
# - etc.
```

**Analysis:** Test file that verifies the new behavior → expects `FriendlyError` object → **COMPATIBLE** ✓

---

## Summary

| Call Site | File | Line | Expects | Status |
|-----------|------|------|---------|--------|
| 1 | action_executor.py | 303 | FriendlyError | ✓ Compatible |
| 2 | action_executor.py | 569 | FriendlyError | ✓ Compatible |
| 3 | error_handler.py | 280 | (definition) | N/A |
| 4 | test_phase2_deferred_items.py | multiple | FriendlyError | ✓ Compatible |

---

## Conclusion

**ALL production callers of `explain_error()` already expect a `FriendlyError` object** (they access `.user_message`, `.original_error`, `.suggested_actions`, `.recovery_hint`). The return type change from `str` to `FriendlyError` is fully compatible with all existing call sites.

**No silent downgrades detected.** There are no callers that do `str(explain_error(...))` or log the result directly expecting a formatted string.

**No fixes needed.** The change is safe and complete.
