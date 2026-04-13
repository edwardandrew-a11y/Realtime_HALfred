import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import supervisor


class AsyncEventStream:
    def __init__(self, events):
        self._events = list(events)

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self):
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event


class FakeResponsesAPI:
    def __init__(self, streams):
        self._streams = list(streams)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._streams:
            raise AssertionError("No fake response stream configured")
        return self._streams.pop(0)


class SupervisorProcessStreamTests(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, streams):
        responses_api = FakeResponsesAPI(streams)
        agent = supervisor.SupervisorAgent.__new__(supervisor.SupervisorAgent)
        agent.client = SimpleNamespace(responses=responses_api)
        agent.model = "test-model"
        agent.last_response_id = None
        agent.INSTRUCTIONS = supervisor.SupervisorAgent.INSTRUCTIONS
        agent._tools_cache = None
        agent.mcp_servers = []
        agent.native_tools = []

        async def build_tools():
            return []

        agent._build_tools = build_tools
        agent._find_native_tool = lambda name: object() if name == "native_tool" else None
        agent._execute_tool = AsyncMock()
        return agent, responses_api

    async def collect_chunks(self, agent):
        context = supervisor.ConversationContext()
        return [chunk async for chunk in agent.process("test message", context)]

    async def test_stream_error_does_not_emit_complete(self):
        agent, responses_api = self.make_agent([
            AsyncEventStream([
                SimpleNamespace(type="error", error="boom"),
            ])
        ])

        chunks = await self.collect_chunks(agent)

        self.assertEqual([chunk.type for chunk in chunks], ["error"])
        self.assertEqual(chunks[0].content, "boom")
        self.assertEqual(len(responses_api.calls), 1)
        self.assertIn("instructions", responses_api.calls[0])

    async def test_invalid_tool_json_with_call_id_becomes_tool_scoped_failure(self):
        agent, responses_api = self.make_agent([
            AsyncEventStream([
                SimpleNamespace(
                    type="response.output_item.added",
                    item=SimpleNamespace(
                        type="function_call",
                        id="item_1",
                        name="native_tool",
                        call_id="call_1",
                    ),
                ),
                SimpleNamespace(
                    type="response.function_call_arguments.done",
                    item_id="item_1",
                    arguments='{"broken":',
                ),
            ]),
            AsyncEventStream([
                SimpleNamespace(type="response.output_text.delta", delta="ok"),
                SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(id="resp_2"),
                ),
            ]),
        ])

        chunks = await self.collect_chunks(agent)

        self.assertEqual(
            [chunk.type for chunk in chunks],
            ["tool_start", "tool_end", "text_delta", "complete"],
        )
        self.assertEqual(chunks[0].metadata, {"raw_args": '{"broken":'})
        self.assertFalse(chunks[1].metadata["success"])
        self.assertEqual(chunks[2].content, "ok")
        self.assertEqual(chunks[3].metadata["response_id"], "resp_2")
        self.assertEqual(len(responses_api.calls), 2)
        self.assertIn("instructions", responses_api.calls[0])
        self.assertNotIn("instructions", responses_api.calls[1])
        self.assertEqual(
            responses_api.calls[1]["input"],
            [
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": unittest.mock.ANY,
                }
            ],
        )
        self.assertIn("Invalid tool arguments for native_tool", responses_api.calls[1]["input"][0]["output"])
        agent._execute_tool.assert_not_awaited()

    async def test_invalid_tool_json_without_call_id_emits_terminal_error(self):
        agent, _ = self.make_agent([
            AsyncEventStream([
                SimpleNamespace(
                    type="response.function_call_arguments.done",
                    name="native_tool",
                    arguments='{"broken":',
                ),
            ])
        ])

        chunks = await self.collect_chunks(agent)

        self.assertEqual([chunk.type for chunk in chunks], ["error"])
        self.assertIn("Invalid tool arguments for native_tool", chunks[0].content)
        agent._execute_tool.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
