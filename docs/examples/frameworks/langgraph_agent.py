import asyncio
from common import PLAN, TOOLS, connection, emit
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode

async def main():
    client = MultiServerMCPClient({'memory': {'transport': 'stdio', **connection()}})
    tools = [tool for tool in await client.get_tools() if tool.name in TOOLS]
    assert {tool.name for tool in tools} == set(TOOLS)
    def stub(state):
        responses = [m for m in state['messages'] if isinstance(m, ToolMessage)]
        if len(responses) < len(PLAN):
            name, args = PLAN[len(responses)]
            message = AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': str(len(responses))}])
        else:
            message = AIMessage(content=str(responses[-1].content))
        return {'messages': [message]}
    graph = StateGraph(MessagesState)
    graph.add_node('agent', stub)
    graph.add_node('tools', ToolNode(tools))
    graph.add_edge(START, 'agent')
    graph.add_conditional_edges('agent', lambda s: 'tools' if s['messages'][-1].tool_calls else END)
    graph.add_edge('tools', 'agent')
    result = await graph.compile().ainvoke({'messages': [HumanMessage(content='Resume MEM-1 from saved memory.')]})
    responses = [m for m in result['messages'] if isinstance(m, ToolMessage)]
    assert all(m.status == 'success' for m in responses), responses
    emit('langgraph', [{'name': m.name, 'output': m.content} for m in responses], result['messages'][-1].content)

asyncio.run(main())
