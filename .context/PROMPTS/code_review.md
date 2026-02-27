# Prompt: Code Review

Read for context before reviewing:
1. `.context/CONVENTIONS.md` — coding standards (Python style, naming, error handling, async patterns)
2. `.context/ARCHITECTURE.md` — system design (to check integration fit)

## Instructions

Review the following code against our project standards.

```python
[paste code here]
```

Check for:
1. Follows naming conventions from CONVENTIONS.md? (snake_case functions, PascalCase classes, UPPER for constants)
2. Has required type annotations? (no bare `Any`)
3. Error handling follows our patterns? (custom exceptions, log before re-raise)
4. Async correctness? (all I/O-bound operations are `async def`, no blocking calls in async context)
5. Security issues? (no hardcoded secrets, no shell injection, no unsafe deserialization)
6. Integration fit with ARCHITECTURE.md? (writes to correct storage targets, uses correct MCP client)
7. Test coverage adequate? (happy path + error path covered)
8. Docstrings/comments where logic isn't self-evident?

Provide:
- Issues found (severity: critical / warning / nit)
- Suggested fixes with code examples
- Any positive observations worth noting
