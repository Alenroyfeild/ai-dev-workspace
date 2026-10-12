# MCP protocol compatibility

Run `python3 mcp/server.py --root /path/to/workspace` over newline-delimited stdio. Only protocol messages go to stdout. CLI and MCP share the same task files, path checks and write safeguards.

| Era | Connection | Result behavior |
|---|---|---|
| 2025-11-25, 2025-06-18 | `initialize`, then ordinary requests; notifications receive no reply | Legacy envelopes and `ping`; unknown proposed versions negotiate 2025-11-25 |
| 2026-07-28 | No initialize; metadata on **every** request; optional `server/discover` | `resultType: complete`; cacheable discovery/list/resource reads use `ttlMs: 0`, `cacheScope: private` |

Modern example (a fresh process can also call a tool directly):

```json
{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}
```

Missing/malformed metadata is rejected before tool dispatch. An unsupported modern version returns `-32022` with `data.requested` and `data.supported`; old versions inside modern metadata must use legacy initialize instead. Modern requests never inherit metadata from a prior request. Modern `ping` and legacy subscription methods are unavailable, and missing resources use `-32602` (legacy `-32002`). No subscriptions, client-input capabilities, HTTP or OAuth are advertised. `ws doctor --mcp` remains a legacy compatibility check.

Proof on 2026-10-11: seven protocol tests use real stdio subprocesses, including cross-era writes/reads and rejected metadata leaving records unchanged. The already-installed Python MCP SDK **2.3.0**, Python **3.14.7**, connected in auto-discovery, direct-modern and legacy modes; fresh processes recovered a saved decision, and tool/prompt/resource calls validated. [Recorded result](examples/mcp-protocol-proof.json). This is SDK protocol interoperability, **not** a live assistant/model or every client version. No install, credentials or model calls were needed; network connections were denied. Core remains Python 3.9+ standard library only.

Contract sources: [base fields and errors](https://modelcontextprotocol.io/specification/2026-07-28/basic), [discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover), [versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning), [schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/schema.ts). Actual assistant wire versions must be checked separately; an SDK dependency or transport listing is not proof.
