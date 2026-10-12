import asyncio
import json
from common import PLAN, TOOLS, connection, emit
from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

class ScriptedModel(BaseLlm):
    model: str = 'offline-stub'
    async def generate_content_async(self, llm_request, stream=False):
        responses = [p.function_response for c in llm_request.contents for p in c.parts or [] if p.function_response]
        if len(responses) < len(PLAN):
            name, args = PLAN[len(responses)]
            part = types.Part(function_call=types.FunctionCall(name=name, args=args))
        else:
            part = types.Part(text=json.dumps(responses[-1].response))
        yield LlmResponse(content=types.Content(role='model', parts=[part]))

async def main():
    toolset = McpToolset(connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(**connection())), tool_filter=TOOLS)
    sessions = InMemorySessionService()
    await sessions.create_session(app_name='spike', user_id='fixture', session_id='fresh')
    agent = LlmAgent(name='memory_agent', model=ScriptedModel(), tools=[toolset])
    runner = Runner(app_name='spike', agent=agent, session_service=sessions)
    results, final = [], ''
    try:
        async for event in runner.run_async(user_id='fixture', session_id='fresh',
                new_message=types.Content(role='user', parts=[types.Part(text='Resume MEM-1 from saved memory.')])):
            for part in event.content.parts if event.content else []:
                if part.function_response:
                    response = part.function_response
                    assert not response.response.get('isError'), response
                    results.append({'name': response.name, 'output': response.response})
                if part.text:
                    final = part.text
        emit('adk', results, final)
    finally:
        await runner.close()

asyncio.run(main())
