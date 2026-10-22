# Microsoft Agent Framework Python API確認記録

確認日: 2026-10-22

このプロジェクトの仮想環境で確認したバージョンは次のとおりです。

- `agent-framework-core==1.17.0`
- `agent-framework-openai==1.14.2`
- `agent-framework-orchestrations==1.1.1`
- Python 3.11.16

実際のインストール環境で、次のシグネチャとコンストラクタ生成を確認しています。

- `Agent(..., tools=..., context_providers=..., middleware=...)`
- `agent.create_session()` / `agent.run(..., session=..., stream=True)`
- `@tool(name=..., approval_mode="never_require")`
- Toolへの `FunctionInvocationContext` 注入
- `FunctionMiddleware.process(context, call_next)`
- `SkillsProvider.from_paths(..., disable_caching=True)`
- `ToolApprovalMiddleware(auto_approval_rules=...)`
- `AgentExecutor(agent, session=session)`
- `GroupChatBuilder(...).build()`

採用した公式情報:

- [Adding Middleware to Agents](https://learn.microsoft.com/en-us/agent-framework/concepts/agents/middleware/defining-middleware)
- [Agent Pipeline Architecture](https://learn.microsoft.com/en-us/agent-framework/agents/agent-pipeline)
- [Agent Hooks](https://learn.microsoft.com/en-us/agent-framework/agents/agent-hooks)
- [Microsoft Agent Framework repository](https://github.com/microsoft/agent-framework)
- [Python package status](https://github.com/microsoft/agent-framework/blob/main/python/PACKAGE_STATUS.md)

Python版Agent Hooksは追加SDKを伴う実験的機能であるため、この用途では
`commit_navigation` Toolに限定したFunction Middlewareを使っています。

将来パッケージを更新する場合は、先にテストを実行し、特にTool context注入、
`AgentSession.state`、ストリーミング更新型、GroupChatのイベント形式を再確認してください。

