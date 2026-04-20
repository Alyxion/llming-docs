# Validation

Every `DocumentSessionStore.create()` and `.update()` call runs `validators.validate_document(type, data)` before persisting. Validation is mandatory on any code path the LLM can reach — no exceptions.

## The contract

```python
result = store.create(type="table", name="Q1", data=payload)
if isinstance(result, list):
    # Structural problems — caller must surface them.
    errors: list[ValidationError] = result
else:
    doc: Document = result
```

A validator returns a list of `ValidationError`s (empty list = valid). The store only persists if the list is empty.

## ValidationError fields

```python
@dataclass
class ValidationError:
    code: str       # machine-readable, stable across releases
    message: str    # human-readable summary
    hint: str       # concrete fix instruction for an LLM
    path: str = ""  # slash-separated location in the data, "" = root
```

All four fields matter. An LLM presented with `code`, `message`, `hint`, and `path` can fix most issues in a single retry. Without `hint` and `path` it tends to re-emit the same broken payload.

Example:

```json
{
  "code": "missing_required_field",
  "message": "Table column is missing 'name'",
  "hint": "Add a 'name' field (string) to each object in 'columns'",
  "path": "columns/2"
}
```

## MCP tool pattern

Every MCP tool in this package follows the same shape when wrapping a store call:

```python
result = self._store.create(type=doc_type, name=name, data=data)
if isinstance(result, list):
    return json.dumps({
        "error": "validation_failed",
        "errors": [{"code": e.code, "message": e.message,
                    "hint": e.hint, "path": e.path} for e in result],
    })
doc = result
return json.dumps({"status": "created", "document_id": doc.id, ...})
```

The LLM sees the structured error and can retry with a corrected payload. Frontends render `validation_failed` results as a distinct error state instead of a generic "tool failed" message.

## Bypassing validation

Pass `skip_validation=True` only from:

- Tests (where you're testing behavior adjacent to validation).
- `restore_from_list` (the incoming payload is already-validated historical data).
- Internal migrations that intentionally insert legacy-shape data.

Never from MCP tools or any API reachable by an LLM.

## Registering a validator for a new type

```python
# validators.py
def _validate_foo(data: Any) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not isinstance(data, dict):
        errors.append(_err(
            code="invalid_root",
            message="foo data must be an object",
            hint="Wrap the payload in a JSON object",
        ))
        return errors
    if "name" not in data:
        errors.append(_err(
            code="missing_required_field",
            message="foo is missing 'name'",
            hint="Add a 'name' field (string)",
            path="name",
        ))
    return errors

_VALIDATORS["foo"] = _validate_foo
```

Guidelines:

- **Fail fast on root-level shape mismatches** (wrong JSON type) before descending — a wrong-root error is more useful than a cascade of field errors.
- **Describe the fix, not the rule.** `hint="Add a 'name' field (string)"` beats `hint="'name' is required"`.
- **Use paths consistently** — slash-separated, array indices as strings, matches `UnifiedDocumentMCP`'s path language.
- **Keep codes stable.** Tests and client UI may switch on them.
