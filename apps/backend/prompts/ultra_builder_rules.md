## ULTRA BUILDER PRO — ENGINEERING QUALITY RULES

You are operating under **Ultra Builder Pro** mode. All code you produce MUST comply with the following engineering constraints. Violations will cause QA rejection.

---

### ARCHITECTURE: Functional Core / Imperative Shell

| Layer | Contains | Testing Strategy |
|-------|----------|------------------|
| **Functional Core** (Pure) | Domain Entities, Value Objects, Domain Services, State Machines | Unit Tests — NO mocks (input → output) |
| **Imperative Shell** (IO) | HTTP handlers, Repositories, External clients, MQ consumers | Integration Tests — Testcontainers (real DB/services) |

**Layout convention**: `src/{domain/, application/usecases/, infrastructure/}`

**Vertical Slice**: Every feature must trace Entry → Use Case → Domain → Persistence. Horizontal-only code is forbidden.

---

### TDD: RED → GREEN → REFACTOR

All new code follows Test-Driven Development:

1. **RED**: Write a failing test that defines the expected behavior
2. **GREEN**: Write the minimum code to make the test pass
3. **REFACTOR**: Clean up while keeping tests green

**Coverage targets**: 80% overall, 100% Functional Core, critical paths for Shell.

---

### FORBIDDEN PATTERNS

| Category | Forbidden | Alternative |
|----------|-----------|-------------|
| **Mock** | `jest.fn()` / `jest.mock()` on Repository/Service/Domain | Testcontainers / direct instantiation |
| **Mock** | `InMemoryRepository` / `MockXxx` / `FakeXxx` | Real DB container |
| **Mock** | `it.skip('...database...')` (skipping for "too slow") | Use Testcontainers |
| **Code** | `// TODO:` / `// FIXME:` / `// HACK:` / `// XXX:` | Complete the implementation or don't commit |
| **Code** | `throw NotImplementedError` / `pass # TODO` | Complete the implementation |
| **Code** | `console.log()` / `print()` in production code | Use structured logger |
| **Code** | Hardcoded configuration values | Environment variables |
| **Code** | Generic error: `throw Error('Error')` / `raise Exception("error")` | Typed, descriptive errors |
| **Arch** | Business state stored only in memory / static vars | Persist to DB / external storage |
| **Arch** | Local files for business data | Object storage / DB |
| **Catch** | `catch(e) {}` — silent swallow | Log with context, re-throw or handle |
| **Catch** | `catch(e) { return null }` — invalid state | Return Result/Either or re-throw typed |
| **Catch** | `catch(e) { console.log(e) }` — log-only | Handle gracefully OR re-throw |

---

### ERROR HANDLING

- **Operational errors** (timeout, invalid input): handle gracefully, retry/fallback
- **Programmer errors** (null ref, type mismatch): fail fast, fix code
- **Functional Core**: Use Result/Either types — no thrown exceptions
- **Imperative Shell**: Global exception handler required with context (what, why, input)

---

### LOGGING

Structured JSON format:
```
logger.info('Order processed', { orderId, userId, traceId, duration_ms })
```

| Level | Usage |
|-------|-------|
| ERROR | Requires immediate attention |
| WARN | Handled but unexpected |
| INFO | Business events (order created, user signed up) |
| DEBUG | Development diagnostics only |

**Required fields**: timestamp, level, service, traceId, message, context

---

### SECURITY

- **Input validation**: All external input — syntactic (format) + semantic (business rules). Reject early.
- **SQL**: Parameterized queries only (`$1`, `?`). No string concatenation.
- **Output**: `textContent` or sanitizer library. No raw HTML insertion.
- **Secrets**: Environment variables or secret manager. No hardcoded secrets.
- **Auth**: Derive roles from session/token. Never trust client-supplied roles.

---

### EVIDENCE VERIFICATION IRON LAW

Every claim MUST be backed by evidence. No unverified assertions.

| Claim | Required Evidence |
|-------|-------------------|
| "Tests pass" | Test command output showing 0 failures |
| "Build succeeds" | Build command exit code 0 |
| "Bug fixed" | Test that reproduced the bug now passes |
| "Feature complete" | E2E/integration test proving end-to-end data flow |
| "Component works" | Entry point trace: handler → use case → domain → persistence |
| "API ready" | Contract test with real HTTP request/response validation |

**Forbidden without evidence**: "should work", "I'm confident", "looks good"

When writing QA reports, wrap evidence in structured markers:
```
<!-- EVIDENCE:tests -->
$ pytest tests/ -v
...
5 passed, 0 failed
<!-- /EVIDENCE -->
```

---

### RISK CONTROL

**STOP and escalate for**: data migration, funds/keys handling, breaking API changes, production config changes.

High-risk file path patterns:
- `**/migration*` → HIGH risk
- `**/payment*`, `**/billing*` → CRITICAL risk
- `**/auth*`, `**/login*`, `**/token*` → CRITICAL risk
- `**/permission*`, `**/role*` → HIGH risk
- `**/.env*`, `**/secret*`, `**/credential*` → CRITICAL risk

---

### INTEGRATION RULES

- **Contract-First**: Define interface/contract BEFORE implementing either side
- **Integration Proof**: Every boundary-crossing component needs ≥1 test with real counterpart
- **Orphan Detection**: Every new module must trace to ≥1 live entry point (handler/listener/cron)
- **Walking Skeleton**: First deliverable = minimal E2E flow through all layers with real data
