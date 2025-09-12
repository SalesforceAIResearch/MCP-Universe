# pylint: disable=protected-access
import unittest
import pprint
import pytest

from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.agent.openai_agent_sdk import OpenAIAgentSDK
from mcpuniverse.tracer import Tracer
from mcpuniverse.callbacks.base import Printer


class TestOpenAIAgentSDK(unittest.IsolatedAsyncioTestCase):

    async def test_configuration(self):
        """Test OpenAI Agent SDK configuration."""
        config = {
            "name": "test_openai_agent",
            "instructions": "You are a helpful AI assistant that can use tools to answer questions.",
            "model": "gpt-4.1",
            "max_turns": 5,
            "temperature": 0.7,
            "output_type": "str",
            "servers": [{"name": "weather"}]
        }
        
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,  # OpenAI Agent SDK handles its own LLM
            config=config
        )
        await agent.initialize()
        
        self.assertEqual(agent._config.name, "test_openai_agent")
        self.assertEqual(agent._config.instructions, "You are a helpful AI assistant that can use tools to answer questions.")
        self.assertEqual(agent._config.model, "gpt-4.1")
        self.assertEqual(agent._config.max_turns, 5)
        self.assertEqual(agent._config.temperature, 0.7)
        self.assertEqual(agent._config.output_type, "str")
        
        await agent.cleanup()

    async def test_default_configuration(self):
        """Test OpenAI Agent SDK with default configuration."""
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()
        
        # Test default values
        self.assertEqual(agent._config.instructions, "You are a helpful AI assistant.")
        self.assertEqual(agent._config.model, "gpt-4.1")
        self.assertEqual(agent._config.max_turns, 20)
        self.assertIsNone(agent._config.temperature)
        self.assertEqual(agent._config.output_type, "str")
        
        await agent.cleanup()

    async def test_mcp_tools_conversion(self):
        """Test MCP tools to OpenAI Agent SDK tools conversion with real weather server."""
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()
        
        # Test that real tools were loaded
        self.assertGreater(len(agent._mcp_tools), 0)
        
        # Check weather tools are properly converted
        tool_names = [tool.name for tool in agent._mcp_tools]
        self.assertIn("weather_get_forecast", tool_names)
        self.assertIn("weather_get_alerts", tool_names)
        
        # Test tool properties
        forecast_tool = next(tool for tool in agent._mcp_tools if tool.name == "weather_get_forecast")
        self.assertIsNotNone(forecast_tool)
        self.assertTrue(hasattr(forecast_tool, 'name'))
        self.assertTrue(hasattr(forecast_tool, 'description'))
        self.assertTrue(hasattr(forecast_tool, 'params_json_schema'))
        self.assertTrue(hasattr(forecast_tool, 'on_invoke_tool'))
        self.assertTrue(callable(forecast_tool.on_invoke_tool))
        
        # Test schema is correctly preserved
        schema = forecast_tool.params_json_schema
        self.assertEqual(schema['type'], 'object')
        self.assertIn('latitude', schema['properties'])
        self.assertIn('longitude', schema['properties'])
        self.assertIn('latitude', schema['required'])
        self.assertIn('longitude', schema['required'])
        
        await agent.cleanup()

    async def test_description_generation(self):
        """Test agent description generation."""
        config = {
            "name": "weather_assistant",
            "instructions": "I help with weather information.",
            "servers": [{"name": "weather"}]
        }
        
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config=config
        )
        await agent.initialize()
        
        # Test basic description
        description = agent.get_description(with_tools_description=False)
        self.assertIn("weather_assistant", description)
        self.assertIn("I help with weather information.", description)
        self.assertIn("OpenAI Agent SDK", description)
        
        # Test description with tools (when no tools are available)
        description_with_tools = agent.get_description(with_tools_description=True)
        self.assertIn("weather_assistant", description_with_tools)
        
        await agent.cleanup()

    async def test_openai_agent_access(self):
        """Test access to underlying OpenAI Agent instance."""
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()
        
        # Test property access
        openai_agent = agent.openai_agent_sdk
        self.assertIsNotNone(openai_agent)
        
        # Test method access
        openai_agent_method = agent.get_openai_agent_sdk()
        self.assertEqual(openai_agent, openai_agent_method)
        
        await agent.cleanup()

    async def test_cleanup(self):
        """Test cleanup functionality."""
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config={"servers": [{"name": "weather"}]}
        )
        await agent.initialize()
        
        # Verify initialization
        self.assertIsNotNone(agent._openai_agent_sdk)
        self.assertIsInstance(agent._mcp_tools, list)
        
        # Test cleanup
        await agent.cleanup()
        self.assertIsNone(agent._openai_agent_sdk)
        self.assertEqual(len(agent._mcp_tools), 0)

    # Integration tests (commented out by default due to external dependencies)
    @pytest.mark.skip(reason="Requires OpenAI API key and external dependencies")
    async def test_execute_weather_integration(self):
        """Integration test with actual weather API."""
        question = "What's the weather in San Francisco now?"
        tracer = Tracer()
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config={
                "name": "weather_assistant",
                "instructions": "You are a helpful weather assistant that provides current weather information.",
                "servers": [{"name": "weather"}],
                "max_turns": 3,
                "temperature": 0.1
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
        await agent.cleanup()
        pprint.pprint(tracer.get_trace())

    @pytest.mark.skip(reason="Requires OpenAI API key and external dependencies")
    async def test_execute_multi_server_integration(self):
        """Integration test with multiple servers."""
        question = "Search for the tallest building in LA and then tell me the current weather there."
        tracer = Tracer()
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config={
                "name": "research_assistant",
                "instructions": "You are an assistant that can search for information and check weather conditions.",
                "servers": [
                    {"name": "weather"},
                    {"name": "google-search"}
                ],
                "max_turns": 5,
                "temperature": 0.2
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
        await agent.cleanup()
        pprint.pprint(tracer.get_trace())

    async def test_model_settings_regular_model(self):
        """Test ModelSettings creation for regular models."""
        agent = OpenAIAgentSDK(
            mcp_manager=None,
            llm=None,
            config={
                "name": "gpt4_agent",
                "model": "gpt-4.1",
                "temperature": 0.7
            }
        )
        
        settings = agent._create_model_settings()
        self.assertIsNotNone(settings)
        self.assertEqual(settings.temperature, 0.7)
        self.assertIsNone(settings.reasoning)
        self.assertIsNone(settings.verbosity)

    async def test_model_settings_reasoning_model(self):
        """Test ModelSettings creation for reasoning models."""
        agent = OpenAIAgentSDK(
            mcp_manager=None,
            llm=None,
            config={
                "name": "gpt5_agent",
                "model": "gpt-5",
                "reasoning_effort": "high",
                "verbosity": "medium"
            }
        )
        
        settings = agent._create_model_settings()
        self.assertIsNotNone(settings)
        self.assertIsNone(settings.temperature)
        self.assertIsNotNone(settings.reasoning)
        self.assertEqual(settings.reasoning.effort, "high")
        self.assertEqual(settings.verbosity, "medium")

    async def test_model_settings_o3_model(self):
        """Test ModelSettings creation for O3 models."""
        agent = OpenAIAgentSDK(
            mcp_manager=None,
            llm=None,
            config={
                "name": "o3_agent",
                "model": "o3-mini",
                "reasoning_effort": "minimal",
                "verbosity": "low"
            }
        )
        
        settings = agent._create_model_settings()
        self.assertIsNotNone(settings)
        self.assertIsNone(settings.temperature)
        self.assertIsNotNone(settings.reasoning)
        self.assertEqual(settings.reasoning.effort, "minimal")
        self.assertEqual(settings.verbosity, "low")

    async def test_model_settings_default_reasoning(self):
        """Test default reasoning settings for reasoning models."""
        agent = OpenAIAgentSDK(
            mcp_manager=None,
            llm=None,
            config={
                "name": "gpt5_default",
                "model": "gpt-5"
            }
        )
        
        settings = agent._create_model_settings()
        self.assertIsNotNone(settings)
        self.assertIsNone(settings.temperature)
        self.assertIsNotNone(settings.reasoning)
        self.assertEqual(settings.reasoning.effort, "low")
        self.assertEqual(settings.verbosity, "low")

    async def test_reasoning_model_detection(self):
        """Test reasoning model detection logic."""
        agent = OpenAIAgentSDK(mcp_manager=None, llm=None, config={"name": "test"})
        
        # Test reasoning models
        self.assertTrue(agent._is_reasoning_model("gpt-5"))
        self.assertTrue(agent._is_reasoning_model("gpt-5-mini"))
        self.assertTrue(agent._is_reasoning_model("gpt-5-nano"))
        self.assertTrue(agent._is_reasoning_model("gpt-5-chat"))
        self.assertTrue(agent._is_reasoning_model("o3"))
        self.assertTrue(agent._is_reasoning_model("o3-mini"))
        self.assertTrue(agent._is_reasoning_model("o4-mini"))
        
        # Test non-reasoning models
        self.assertFalse(agent._is_reasoning_model("gpt-4.1"))
        self.assertFalse(agent._is_reasoning_model("gpt-4o"))
        self.assertFalse(agent._is_reasoning_model("gpt-3.5-turbo"))

    async def test_config_with_reasoning_parameters(self):
        """Test configuration with reasoning-specific parameters."""
        config = {
            "name": "reasoning_agent",
            "instructions": "You are a reasoning assistant.",
            "model": "gpt-5",
            "reasoning_effort": "high",
            "verbosity": "medium",
            "max_turns": 5,
            "servers": [{"name": "weather"}]
        }
        
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config=config
        )
        await agent.initialize()
        
        self.assertEqual(agent._config.model, "gpt-5")
        self.assertEqual(agent._config.reasoning_effort, "high")
        self.assertEqual(agent._config.verbosity, "medium")
        self.assertEqual(agent._config.max_turns, 5)
        
        await agent.cleanup()

    async def test_multiple_servers(self):
        """Test initialization with multiple MCP servers."""
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config={
                "name": "multi_server_agent",
                "servers": [
                    {"name": "weather"},
                    {"name": "echo"}
                ]
            }
        )
        await agent.initialize()
        
        # Should have tools from both servers
        self.assertGreater(len(agent._mcp_tools), 2)
        
        tool_names = [tool.name for tool in agent._mcp_tools]
        # Weather tools
        self.assertIn("weather_get_forecast", tool_names)
        # Echo tools
        self.assertIn("echo_echo_tool", tool_names)
        
        await agent.cleanup()

    async def test_agent_without_servers(self):
        """Test agent initialization without any MCP servers."""
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config={
                "name": "no_server_agent",
                "servers": []
            }
        )
        await agent.initialize()
        
        # Should have no MCP tools
        self.assertEqual(len(agent._mcp_tools), 0)
        
        # Should still have valid OpenAI agent
        self.assertIsNotNone(agent._openai_agent_sdk)
        
        await agent.cleanup()

    async def test_max_tokens_parameter(self):
        """Test max_tokens parameter for both regular and reasoning models."""
        # Test regular model with max_tokens
        agent1 = OpenAIAgentSDK(
            mcp_manager=None,
            llm=None,
            config={
                "name": "regular_model",
                "model": "gpt-4.1",
                "temperature": 0.5,
                "max_tokens": 500
            }
        )
        
        settings1 = agent1._create_model_settings()
        self.assertIsNotNone(settings1)
        self.assertEqual(settings1.temperature, 0.5)
        self.assertEqual(settings1.max_tokens, 500)
        self.assertIsNone(settings1.reasoning)
        
        # Test reasoning model with max_tokens
        agent2 = OpenAIAgentSDK(
            mcp_manager=None,
            llm=None,
            config={
                "name": "reasoning_model",
                "model": "gpt-5",
                "reasoning_effort": "high",
                "verbosity": "medium",
                "max_tokens": 1000
            }
        )
        
        settings2 = agent2._create_model_settings()
        self.assertIsNotNone(settings2)
        self.assertIsNone(settings2.temperature)
        self.assertEqual(settings2.max_tokens, 1000)
        self.assertEqual(settings2.reasoning.effort, "high")
        self.assertEqual(settings2.verbosity, "medium")

    async def test_model_settings_combinations(self):
        """Test various combinations of model settings."""
        # Test with only max_tokens (no other settings)
        agent1 = OpenAIAgentSDK(
            mcp_manager=None,
            llm=None,
            config={
                "name": "max_tokens_only",
                "model": "gpt-4.1",
                "max_tokens": 300
            }
        )
        
        settings1 = agent1._create_model_settings()
        self.assertIsNotNone(settings1)
        self.assertEqual(settings1.max_tokens, 300)
        self.assertIsNone(settings1.temperature)
        
        # Test O3 model with minimal settings and token limit
        agent2 = OpenAIAgentSDK(
            mcp_manager=None,
            llm=None,
            config={
                "name": "o3_fast",
                "model": "o3-mini",
                "reasoning_effort": "minimal",
                "max_tokens": 150  # Short responses for speed
            }
        )
        
        settings2 = agent2._create_model_settings()
        self.assertIsNotNone(settings2)
        self.assertEqual(settings2.max_tokens, 150)
        self.assertEqual(settings2.reasoning.effort, "minimal")
        self.assertEqual(settings2.verbosity, "low")  # Default

    async def test_callback_integration(self):
        """Test callback integration with OpenAI Agent SDK."""
        from mcpuniverse.callbacks.base import BaseCallback, CallbackMessage
        
        # Create a test callback
        class TestCallback(BaseCallback):
            def __init__(self):
                super().__init__()
                self.messages = []
            
            async def call_async(self, message: CallbackMessage, **kwargs):
                self.messages.append(message)
        
        callback = TestCallback()
        
        # Create agent with no servers
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config={
                "name": "callback_test_agent",
                "model": "gpt-4.1",
                "max_tokens": 50,
                "servers": []
            }
        )
        
        try:
            await agent.initialize()
            
            # Execute with callback - will likely fail due to no OpenAI key but callbacks should work
            try:
                await agent._execute("test message", callbacks=[callback])
            except Exception:
                pass  # Expected to fail due to OpenAI API
            
            # Should have received callback messages
            self.assertGreater(len(callback.messages), 0)
            
            # Check for start message
            start_messages = [msg for msg in callback.messages 
                            if msg.metadata.get("event") == "agent_start"]
            self.assertGreater(len(start_messages), 0)
            
            # Check message content
            start_msg = start_messages[0]
            self.assertIn("callback_test_agent", start_msg.metadata.get("data", ""))
            
        finally:
            await agent.cleanup()

    async def test_output_format_support(self):
        """Test output format support in OpenAI Agent SDK."""
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config={
                "name": "output_format_test_agent",
                "model": "gpt-4.1",
                "servers": []
            }
        )
        
        # Test string output format
        string_format = "Please respond in uppercase letters only."
        string_prompt = agent._get_output_format_prompt(string_format)
        self.assertEqual(string_prompt, string_format)
        
        # Test dict output format
        dict_format = {
            "answer": "string",
            "confidence": "number between 0 and 1",
            "reasoning": "string explaining the logic"
        }
        dict_prompt = agent._get_output_format_prompt(dict_format)
        self.assertIn("The final answer should follow this JSON format:", dict_prompt)
        self.assertIn('"answer": "string"', dict_prompt)
        self.assertIn('"confidence": "number between 0 and 1"', dict_prompt)
        self.assertIn('"reasoning": "string explaining the logic"', dict_prompt)
        
        # Test None output format
        none_prompt = agent._get_output_format_prompt(None)
        self.assertEqual(none_prompt, "")
        
        try:
            await agent.initialize()
            
            # Test _execute with output format (will fail at OpenAI API but format should be added)
            test_message = "What is 2+2?"
            
            # Mock the message processing to verify format is added
            # We can't actually run the agent without OpenAI API key, but we can test the format logic
            original_message = test_message
            
            # Simulate the format addition logic from _execute
            if dict_format is not None:
                output_format_prompt = agent._get_output_format_prompt(dict_format)
                if output_format_prompt:
                    formatted_message = f"{original_message}\n\n{output_format_prompt}"
                    self.assertIn(original_message, formatted_message)
                    self.assertIn("JSON format", formatted_message)
                    
        finally:
            await agent.cleanup()

    async def test_response_parsing(self):
        """Test response parsing functionality."""
        agent = OpenAIAgentSDK(
            mcp_manager=None,
            llm=None,
            config={
                "name": "parsing_test_agent",
                "model": "gpt-4.1",
                "servers": []
            }
        )
        
        # Test JSON extraction
        test_json = '{"answer": "The result is 42", "confidence": 0.9}'
        extracted = agent._extract_json_from_text(test_json)
        self.assertEqual(extracted, test_json)
        
        # Test JSON in text
        text_with_json = 'Here is the answer: {"answer": "Yes", "reasoning": "Based on data"}'
        extracted = agent._extract_json_from_text(text_with_json)
        import json
        parsed = json.loads(extracted)
        self.assertEqual(parsed["answer"], "Yes")
        
        # Test response parsing with JSON format
        json_format = {"answer": "string", "confidence": "number"}
        response_text = '{"answer": "Paris", "confidence": 0.95}'
        parsed_response = agent._parse_response(response_text, json_format)
        self.assertEqual(parsed_response, "Paris")
        
        # Test response parsing with string format
        string_format = "Please be concise"
        simple_response = "This is a simple answer."
        parsed_simple = agent._parse_response(simple_response, string_format)
        self.assertEqual(parsed_simple, simple_response)
        
        # Test response parsing with malformed JSON (should fallback gracefully)
        malformed_json = "This is not valid JSON: {invalid}"
        parsed_malformed = agent._parse_response(malformed_json, json_format)
        self.assertEqual(parsed_malformed, malformed_json)  # Should return original text

    async def test_openrouter_model_detection(self):
        """Test OpenRouter model detection and configuration."""
        agent = OpenAIAgentSDK(mcp_manager=None, llm=None, config={"name": "test"})
        
        # Test OpenRouter model detection
        self.assertTrue(agent._is_openrouter_model("GPTOSS120B_OR"))
        self.assertTrue(agent._is_openrouter_model("KimiK2_OR"))
        self.assertTrue(agent._is_openrouter_model("DeepSeekV3_1_OR"))
        self.assertTrue(agent._is_openrouter_model("CustomModel_OR"))  # Any model ending with _OR
        
        # Test non-OpenRouter models
        self.assertFalse(agent._is_openrouter_model("gpt-4.1"))
        self.assertFalse(agent._is_openrouter_model("gpt-5"))
        self.assertFalse(agent._is_openrouter_model("claude-3"))
        
        # Test model name mapping
        self.assertEqual(agent._get_openrouter_model_name("GPTOSS120B_OR"), "openai/gpt-oss-120b")
        self.assertEqual(agent._get_openrouter_model_name("KimiK2_OR"), "moonshotai/kimi-k2")
        self.assertEqual(agent._get_openrouter_model_name("DeepSeekV3_1_OR"), "deepseek/deepseek-chat-v3.1")
        # Unknown models should return as-is
        self.assertEqual(agent._get_openrouter_model_name("UnknownModel_OR"), "UnknownModel_OR")
        self.assertEqual(agent._get_openrouter_model_name("gpt-4.1"), "gpt-4.1")

    async def test_openrouter_model_settings(self):
        """Test model settings for OpenRouter models."""
        # Test regular OpenRouter model (non-reasoning)
        agent1 = OpenAIAgentSDK(
            mcp_manager=None,
            llm=None,
            config={
                "name": "openrouter_regular",
                "model": "GPTOSS120B_OR",  # Maps to openai/gpt-oss-120b
                "temperature": 0.8,
                "max_tokens": 500
            }
        )
        
        settings1 = agent1._create_model_settings()
        self.assertIsNotNone(settings1)
        self.assertEqual(settings1.temperature, 0.8)
        self.assertEqual(settings1.max_tokens, 500)
        self.assertIsNone(settings1.reasoning)  # Not a reasoning model
        
        # Test if OpenRouter model happens to be a reasoning model (hypothetical)
        # This tests the logic where we check the mapped name for reasoning detection
        agent2 = OpenAIAgentSDK(
            mcp_manager=None,
            llm=None,
            config={
                "name": "openrouter_reasoning",
                "model": "GPT5_OR",  # Hypothetical mapping to gpt-5
                "reasoning_effort": "medium",
                "verbosity": "high"
            }
        )
        
        # Mock the mapping for this test
        original_get_name = agent2._get_openrouter_model_name
        def mock_get_name(model):
            if model == "GPT5_OR":
                return "gpt-5"
            return original_get_name(model)
        agent2._get_openrouter_model_name = mock_get_name
        
        settings2 = agent2._create_model_settings()
        self.assertIsNotNone(settings2)
        self.assertIsNone(settings2.temperature)
        self.assertIsNotNone(settings2.reasoning)
        self.assertEqual(settings2.reasoning.effort, "medium")
        self.assertEqual(settings2.verbosity, "high")

    @pytest.mark.skip(reason="Requires OPENROUTER_API_KEY environment variable")
    async def test_openrouter_integration_with_api_key(self):
        """Integration test for OpenRouter models (requires API key)."""
        import os
        if not os.getenv("OPENROUTER_API_KEY"):
            self.skipTest("OPENROUTER_API_KEY not set")
            
        agent = OpenAIAgentSDK(
            mcp_manager=MCPManager(),
            llm=None,
            config={
                "name": "openrouter_integration_test",
                "model": "GPTOSS120B_OR",
                "instructions": "You are a helpful assistant.",
                "max_turns": 3,
                "temperature": 0.7,
                "servers": []
            }
        )
        
        await agent.initialize()
        self.assertIsNotNone(agent._openai_agent_sdk)
        
        # Test that the model was configured correctly
        # (We won't actually call execute to avoid API costs)
        
        await agent.cleanup()


if __name__ == "__main__":
    unittest.main()
