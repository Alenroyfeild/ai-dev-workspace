# Optional ADK / LangGraph recipes — stub-model-tested

For people already using these frameworks. The kit does not depend on either one. These standalone examples use native MCP adapters and expose only `find_task`, `brief`, `checkpoint`, `add_lesson`. Filtering limits tool choices; it is not a server authorization boundary or a measured token saving.

| Recipe | Tested packages (Python 3.14.7) | Native adapter |
|---|---|---|
| [ADK](adk_agent.py) | google-adk 2.11.0, mcp 2.3.0 | McpToolset / LlmAgent / Runner |
| [LangGraph](langgraph_agent.py) | langgraph 1.2.14, langchain-mcp-adapters 0.3.2, langchain-core 1.6.9, mcp 1.30.0 | MultiServerMCPClient / ToolNode / StateGraph |

Use separate existing virtual environments with these versions; the optional requirements files pin the directly used packages, not every transitive dependency. Nothing installs automatically. Core packaging stays standard-library-only. The current [ADK MCP guide](https://adk.dev/tools-custom/mcp-tools/) and [LangChain MCP guide](https://docs.langchain.com/oss/python/langchain/mcp) describe the native integrations; the latest beta LangChain MCP API is **not tested** by this pinned recipe.

From a kit clone, this POSIX example creates only disposable memory and home directories. Set the two interpreter paths to your existing environments:

```sh
KIT="$PWD"
DEMO="$(mktemp -d)"
ADK_PY=/absolute/path/to/adk-venv/bin/python
GRAPH_PY=/absolute/path/to/langgraph-venv/bin/python
mkdir "$DEMO/home"
demo() { env -i PATH=/usr/bin:/bin HOME="$DEMO/home" PYTHONDONTWRITEBYTECODE=1 \
  WS_OFFLINE=1 LANGSMITH_TRACING=false LANGGRAPH_CLI_NO_ANALYTICS=1 OTEL_SDK_DISABLED=true "$@"; }
demo python3 "$KIT/bin/ws" init "$DEMO/memory" --name Fixture
demo python3 "$KIT/bin/ws" --workspace "$DEMO/memory" task new MEM-1 "Migration fixture"
demo python3 "$KIT/bin/ws" --workspace "$DEMO/memory" claim MEM-1 --worker fixture
demo "$ADK_PY" "$KIT/docs/examples/frameworks/adk_agent.py" "$DEMO/memory" write \
  --decision "Keep the old index; verify rollback marker violet before retrying."
demo "$GRAPH_PY" "$KIT/docs/examples/frameworks/langgraph_agent.py" "$DEMO/memory" resume
```

The writer checkpoints the supplied decision and adds a lesson. The fresh reader receives no decision argument and recovers it via `brief`. Reverse the frameworks in a new disposable workspace to try the other direction. Both scripts are scripted stubs: they do not select a hosted model, need credentials, or evaluate model reasoning. Their Python audit hook rejects IP connections; it is not an OS sandbox. The server receives an allowlisted environment. The full launch environment above also disables tracing and excludes credentials from the framework process.

[Recorded proof](proof.json): both write flows and fresh cross-framework reads pass against the dual-era server, with random rollback markers absent from each pre-checkpoint brief and supplied only to the writer. Zero external model calls; dollar inference cost is zero. The original adapter experiment used legacy 2025-11-25 on the wire; an SDK package version alone does not establish a modern wire revision. See [separate protocol evidence](../../MCP.md). Windows framework execution, hosted model behavior and other dependency versions remain unverified.

ADK sessions and LangGraph execution state control the current run. The workspace's Markdown task record is the shared durable memory across processes/frameworks; it does not restore a graph's internal execution checkpoint. Replacing the stub with a paid model is a separate, untested integration, including its credentials, permissions and tracing decisions.
