# NEXUS — Threat Model (STRIDE-oriented)

| Threat | Vector | Mitigation |
|---|---|---|
| Data exfiltration via SQL | Malicious/compromised prompt → write or multi-statement SQL | AST SELECT-only enforcement, single statement, row/timeout caps, audit |
| RCE via generated Python | LLM emits hostile code | Separate process, AST import allowlist, restricted builtins, timeout, memory cap, no shell |
| SSRF via HTTP tool | Tool fetches internal URLs | Hostname allowlist from env; deny-by-default; no redirects to disallowed hosts |
| Prompt injection | Document contains "ignore previous instructions…" | Delimited untrusted blocks, instruction hierarchy, validator flags embedded instructions |
| Hallucinated citations | LLM invents sources | Citations bound to actual chunk IDs from retrieval; validator checks claim↔evidence support |
| Infinite agent loop | Router cycles forever | `MAX_AGENT_ITERATIONS` + `MAX_RETRIES` hard caps; step timeouts |
| Resource exhaustion | Huge uploads / many tasks | File size cap, rate limiting, per-task timeouts, row caps |
| Secret leakage | Keys in code/logs/responses | Env-only secrets, redaction filter, no key fields in API schemas, .gitignore |
| Privilege escalation | Viewer runs admin ops | Role dependency checks on mutating endpoints |
| Approval bypass | Agent executes HIGH risk silently | Tool executor requires approval token for HIGH/CRITICAL |
| Path traversal | Upload filename tricks | Stored under UUID dirs; original filename sanitized and metadata-only |
| DoS via slow LLM | Provider hang | Per-call and per-step timeouts; provider failure → classified correction or task failure |

Residual risks (documented): local heuristic provider is not a substitute for a frontier model on hard reasoning; sandbox is process-level not kernel-level (for stronger isolation run backend in Docker with seccomp); pgvector/memory store is single-node.
