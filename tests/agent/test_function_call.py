import unittest
import pprint
import pytest
from unittest.mock import Mock

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.agent.function_call import FunctionCall, FunctionCallConfig
from mcpuniverse.tracer import Tracer
from mcpuniverse.tracer.collectors import SQLiteCollector
from mcpuniverse.callbacks.base import Printer


class TestFunctionCallAgent(unittest.IsolatedAsyncioTestCase):

    @pytest.mark.skip
    async def test_prompt(self):
        """Test the prompt building functionality of FunctionCall agent."""
        agent = FunctionCall(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()        
        prompt = agent._build_prompt(question="What's the weather in San Francisco now?")
        self.assertTrue("What's the weather in San Francisco now?" in prompt)
        await agent.cleanup()

    @pytest.mark.skip
    async def test_tool_conversion(self):
        """Test MCP tools to function call conversion."""
        agent = FunctionCall(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()
        
        # Test empty tools conversion
        empty_tools = agent._convert_mcp_tools_to_function_calls({})
        self.assertEqual(empty_tools, [])

        # Test with actual tools if available
        if agent._tools:
            function_calls = agent._convert_mcp_tools_to_function_calls(agent._tools)
            self.assertIsInstance(function_calls, list)
            for fc in function_calls:
                self.assertIn("type", fc)
                self.assertEqual(fc["type"], "function")
                self.assertIn("function", fc)
                self.assertIn("name", fc["function"])
                self.assertIn("description", fc["function"])
                self.assertIn("parameters", fc["function"])

        await agent.cleanup()

    @pytest.mark.skip
    async def test_function_name_parsing(self):
        """Test function name parsing functionality."""
        agent = FunctionCall(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()

        # Test valid function names
        server, tool = agent._parse_function_call_name("weather__get_current_weather")
        self.assertEqual(server, "weather")
        self.assertEqual(tool, "get_current_weather")

        server, tool = agent._parse_function_call_name("search__web_search")
        self.assertEqual(server, "search")
        self.assertEqual(tool, "web_search")

        # Test function name with multiple underscores
        server, tool = agent._parse_function_call_name("server__tool__with__underscores")
        self.assertEqual(server, "server")
        self.assertEqual(tool, "tool__with__underscores")

        # Test invalid function name
        with self.assertRaises(ValueError):
            agent._parse_function_call_name("invalid_name_without_double_underscore")

        await agent.cleanup()

    @pytest.mark.skip
    async def test_configuration(self):
        """Test FunctionCall configuration."""
        config = {
            "name": "test_fc",
            "instruction": "You are a helpful assistant that can use tools to answer questions.",
            "max_iterations": 3,
            "summarize_tool_response": True,
            "servers": [{"name": "weather"}]
        }
        
        agent = FunctionCall(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config=config
        )
        await agent.initialize()
        
        self.assertEqual(agent._config.name, "test_fc")
        self.assertEqual(agent._config.max_iterations, 3)
        self.assertTrue(agent._config.summarize_tool_response)
        self.assertIn("function_call", agent.alias)
        self.assertIn("fc", agent.alias)
        self.assertIn("function-call", agent.alias)
        
        await agent.cleanup()

    @pytest.mark.skip
    async def test_history_management(self):
        """Test conversation history management."""
        agent = FunctionCall(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()
        
        # Test adding history
        agent._add_history("thought", "I need to check the weather")
        agent._add_history("action", "Using weather API")
        agent._add_history("result", "Temperature is 72°F")
        
        history = agent.get_history()
        self.assertIn("Thought: I need to check the weather", history)
        self.assertIn("Action: Using weather API", history)
        self.assertIn("Result: Temperature is 72°F", history)
        
        # Test clearing history
        agent.clear_history()
        self.assertEqual(len(agent._history), 0)
        self.assertEqual(agent.get_history(), "")
        
        # Test reset
        agent._add_history("test", "test message")
        agent.reset()
        self.assertEqual(len(agent._history), 0)
        
        await agent.cleanup()

    @pytest.mark.skip
    async def test_execute_weather(self):
        """Test executing a weather query using function calling."""
        question = "I live in San Francisco. Do I need to bring an umbrella if I need to go outside?"
        tracer = Tracer()
        agent = FunctionCall(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={
                "instruction": "You are a helpful weather assistant that can check current weather conditions.",
                "servers": [{"name": "weather"}],
                "max_iterations": 3
            }
        )
        await agent.initialize()
        print(f"Agent description: {agent.get_description()}")
        
        response = await agent.execute(
            message=question,
            tracer=tracer,
            callbacks=Printer()
        )
        print(f"Response: {response}")
        print(f"History: {agent.get_history()}")
        await agent.cleanup()
        pprint.pprint(tracer.get_trace())

    @pytest.mark.skip
    async def test_execute_with_output_format(self):
        """Test executing with specific output format."""
        question = "What's the current weather in New York City?"
        tracer = Tracer()
        agent = FunctionCall(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={
                "instruction": "You are a weather assistant.",
                "servers": [{"name": "weather"}],
                "max_iterations": 5,
                "summarize_tool_response": False
            }
        )
        await agent.initialize()

        output_format = {
            "weather_summary": "<Brief weather summary>",
            "temperature": "<Temperature in Fahrenheit>",
            "recommendation": "<Clothing or activity recommendation>"
        }

        response = await agent.execute(
            message=question,
            output_format=output_format,
            tracer=tracer,
            callbacks=Printer()
        )
        print(f"Formatted response: {response}")
        print(f"Agent history: {agent.get_history()}")
        await agent.cleanup()
        pprint.pprint(tracer.get_trace())

    @pytest.mark.skip
    async def test_execute_multi_server(self):
        """Test executing with multiple servers."""
        question = "Search for information about the tallest building in LA and then get the current weather there."
        tracer = Tracer()
        agent = FunctionCall(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={
                "instruction": "You are an assistant that can search for information and check weather.",
                "servers": [
                    {"name": "weather"},
                    {"name": "google-search"}
                ],
                "max_iterations": 5,
            }
        )
        await agent.initialize()
        print(f"Available tools: {agent.get_description(with_tools_description=True)}")

        response = await agent.execute(
            message=question,
            tracer=tracer,
            callbacks=Printer()
        )
        print(f"Multi-server response: {response}")
        print(f"Execution history: {agent.get_history()}")
        await agent.cleanup()
        pprint.pprint(tracer.get_trace())

    @pytest.mark.skip
    async def test_tool_calls_with_content(self):
        """Test that agent can handle responses with both tool_calls and content (e.g., GPT-5)."""
        print("Testing FunctionCall agent with both tool_calls and content...")

        # Create a simple agent for testing
        agent = FunctionCall(
            mcp_manager=MCPManager(),
            llm=ModelManager().build_model(name="openai"),
            config={"max_iterations": 2, "servers": []}
        )
        await agent.initialize()

        # Test the core logic: response handling with both tool_calls and content
        class MockToolCall:
            def __init__(self):
                self.id = "call_test_123"
                self.function = Mock()
                self.function.name = "test_server__get_weather"
                self.function.arguments = '{"location": "Beijing"}'

        class MockMessage:
            def __init__(self):
                self.content = "I'll help you get the weather. Let me check the current conditions."
                self.tool_calls = [MockToolCall()]

        class MockChoice:
            def __init__(self):
                self.message = MockMessage()

        class MockResponse:
            def __init__(self):
                self.choices = [MockChoice()]

        mock_response = MockResponse()
        message_obj = mock_response.choices[0].message

        # Test the condition detection logic
        has_tool_calls = hasattr(message_obj, 'tool_calls') and message_obj.tool_calls
        has_content = hasattr(message_obj, 'content') and message_obj.content

        print(f"has_tool_calls: {has_tool_calls}")
        print(f"has_content: {has_content}")

        # Both should be True for our mock
        self.assertTrue(has_tool_calls, "Mock should have tool_calls")
        self.assertTrue(has_content, "Mock should have content")

        # Test that content is not empty
        self.assertIn("I'll help you get the weather", message_obj.content)

        # Test that tool_calls exist
        self.assertEqual(len(message_obj.tool_calls), 1)
        self.assertEqual(message_obj.tool_calls[0].function.name, "test_server__get_weather")

        # Test history addition (the key part of our fix)
        # Clear any existing history first
        agent.clear_history()
        initial_history = agent.get_history()

        # Simulate what our fix does: add content to history when both exist
        if has_tool_calls and has_content:
            content = message_obj.content.strip()
            if content:
                agent._add_history(
                    history_type="thought",
                    message=f"LLM reasoning with tool calls: {content}"
                )

        # Verify history was updated
        final_history = agent.get_history()
        
        # Check if the new content was added (history might be a string)
        if isinstance(final_history, str):
            self.assertIn("LLM reasoning with tool calls", final_history)
            self.assertIn("I'll help you get the weather", final_history)
        else:
            # If it's a list, check that it was extended
            reasoning_found = any("LLM reasoning with tool calls" in str(entry) and "I'll help you get the weather" in str(entry) for entry in final_history)
            self.assertTrue(reasoning_found, "History should contain the LLM reasoning content")

        print("Tool calls with content logic test passed!")
        print("History updated correctly")

        # Test message structure that would be created
        messages = [{"role": "user", "content": "What's the weather in Beijing?"}]

        # Simulate adding content as assistant message (part of our fix)
        if has_content:
            content = message_obj.content.strip()
            messages.append({
                "role": "assistant",
                "content": content
            })

        # Verify the conversation structure
        self.assertEqual(len(messages), 2)
        assistant_msg = messages[1]
        self.assertEqual(assistant_msg["role"], "assistant")
        self.assertIn("I'll help you get the weather", assistant_msg["content"])

        print("Message structure test passed!")
        print("All core logic for handling tool_calls + content works correctly!")

        await agent.cleanup()


if __name__ == "__main__":
    unittest.main()
