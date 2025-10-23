import os
import json
import unittest
import pytest
from unittest.mock import patch, Mock
from pydantic import BaseModel
from mcpuniverse.llm.claude_gateway import ClaudeGatewayModel
from mcpuniverse.common.context import Context


class Response(BaseModel):
    code: str
    explanation: str


class TestClaudeGateway(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        model = ClaudeGatewayModel()
        system_message = ""
        user_message = """
        hi
        """
        response = model.get_response(system_message, user_message, response_format=None)
        print(response)

    def test_list_undefined_env_vars(self):
        os.environ["SALESFORCE_GATEWAY_KEY"] = ""
        model = ClaudeGatewayModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, ["SALESFORCE_GATEWAY_KEY"])

        context = Context(env={"SALESFORCE_GATEWAY_KEY": "xxx"})
        model = ClaudeGatewayModel()
        model.set_context(context)
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, [])

    # def test_convert_openai_messages_to_claude(self):
    #     """Test conversion of OpenAI messages format to Claude format"""
    #     model = ClaudeGatewayModel()

    #     # Test multi-turn function call messages
    #     openai_messages = [
    #         {"role": "system", "content": "You are a helpful assistant."},
    #         {"role": "user", "content": "What's the weather?"},
    #         {
    #             "role": "assistant",
    #             "content": None,
    #             "tool_calls": [
    #                 {
    #                     "id": "call_123",
    #                     "type": "function",
    #                     "function": {
    #                         "name": "get_weather",
    #                         "arguments": '{"location": "San Francisco"}'
    #                     }
    #                 }
    #             ]
    #         },
    #         {
    #             "role": "tool",
    #             "tool_call_id": "call_123",
    #             "content": "It's sunny and 72°F"
    #         },
    #         {"role": "user", "content": "Thanks!"}
    #     ]

    #     system_messages = []
    #     claude_messages = model._convert_openai_messages_to_claude(
    #           openai_messages, system_messages)

    #     # Check system message was extracted
    #     self.assertEqual(system_messages, ["You are a helpful assistant."])

    #     # Check Claude format conversion
    #     self.assertEqual(len(claude_messages), 4)

    #     # User message
    #     self.assertEqual(claude_messages[0]["role"], "user")
    #     self.assertEqual(claude_messages[0]["content"], "What's the weather?")

    #     # Assistant with tool call
    #     self.assertEqual(claude_messages[1]["role"], "assistant")
    #     self.assertEqual(len(claude_messages[1]["content"]), 1)
    #     tool_use = claude_messages[1]["content"][0]
    #     self.assertEqual(tool_use["type"], "tool_use")
    #     self.assertEqual(tool_use["id"], "call_123")
    #     self.assertEqual(tool_use["name"], "get_weather")
    #     self.assertEqual(tool_use["input"], {"location": "San Francisco"})

    #     # Tool result
    #     self.assertEqual(claude_messages[2]["role"], "user")
    #     tool_result = claude_messages[2]["content"][0]
    #     self.assertEqual(tool_result["type"], "tool_result")
    #     self.assertEqual(tool_result["tool_use_id"], "call_123")
    #     self.assertEqual(tool_result["content"], "It's sunny and 72°F")

    #     # Final user message
    #     self.assertEqual(claude_messages[3]["role"], "user")
    #     self.assertEqual(claude_messages[3]["content"], "Thanks!")

    # def test_convert_openai_tools_to_claude(self):
    #     """Test conversion of OpenAI tools format to Claude format"""
    #     model = ClaudeGatewayModel()

    #     # OpenAI format tools
    #     openai_tools = [
    #         {
    #             "type": "function",
    #             "function": {
    #                 "name": "get_weather",
    #                 "description": "Get current weather for a location",
    #                 "parameters": {
    #                     "type": "object",
    #                     "properties": {
    #                         "location": {"type": "string", "description": "City name"},
    #                         "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
    #                     },
    #                     "required": ["location"]
    #                 }
    #             }
    #         },
    #         {
    #             "type": "function",
    #             "function": {
    #                 "name": "calculate_sum",
    #                 "description": "Calculate sum of two numbers",
    #                 "parameters": {
    #                     "type": "object",
    #                     "properties": {
    #                         "a": {"type": "number"},
    #                         "b": {"type": "number"}
    #                     },
    #                     "required": ["a", "b"]
    #                 }
    #             }
    #         }
    #     ]

    #     claude_tools = model._convert_openai_tools_to_claude(openai_tools)

    #     # Check conversion
    #     self.assertEqual(len(claude_tools), 2)

    #     # First tool
    #     self.assertEqual(claude_tools[0]["name"], "get_weather")
    #     self.assertEqual(claude_tools[0]["description"], "Get current weather for a location")
    #     self.assertEqual(claude_tools[0]["input_schema"]["type"], "object")
    #     self.assertIn("location", claude_tools[0]["input_schema"]["properties"])

    #     # Second tool
    #     self.assertEqual(claude_tools[1]["name"], "calculate_sum")
    #     self.assertEqual(claude_tools[1]["description"], "Calculate sum of two numbers")
    #     self.assertIn("a", claude_tools[1]["input_schema"]["properties"])
    #     self.assertIn("b", claude_tools[1]["input_schema"]["properties"])

    # def test_create_openai_style_response_with_tool_calls(self):
    #     """Test creation of OpenAI-style response from Claude response with tool calls"""
    #     model = ClaudeGatewayModel()

    #     # Mock Claude response with tool use
    #     claude_response = {
    #         "result": [{
    #             "text": "",
    #             "content": [
    #                 {
    #                     "type": "text",
    #                     "text": "I'll help you get the weather."
    #                 },
    #                 {
    #                     "type": "tool_use",
    #                     "id": "toolu_123",
    #                     "name": "get_weather",
    #                     "input": {"location": "San Francisco", "unit": "celsius"}
    #                 }
    #             ]
    #         }]
    #     }

    #     response = model._create_openai_style_response(claude_response)

    #     # Check response structure
    #     self.assertEqual(len(response.choices), 1)
    #     self.assertEqual(response.model, model.config.model_name)

    #     # Check message content
    #     message = response.choices[0].message
    #     self.assertEqual(message.content, "I'll help you get the weather.")

    #     # Check tool calls
    #     self.assertIsNotNone(message.tool_calls)
    #     self.assertEqual(len(message.tool_calls), 1)

    #     tool_call = message.tool_calls[0]
    #     self.assertEqual(tool_call.id, "toolu_123")
    #     self.assertEqual(tool_call.type, "function")
    #     self.assertEqual(tool_call.function.name, "get_weather")

    #     # Check arguments are JSON string
    #     args = json.loads(tool_call.function.arguments)
    #     self.assertEqual(args["location"], "San Francisco")
    #     self.assertEqual(args["unit"], "celsius")

    # def test_create_openai_style_response_text_only(self):
    #     """Test creation of OpenAI-style response from Claude response without tools"""
    #     model = ClaudeGatewayModel()

    #     # Mock Claude response with text only
    #     claude_response = {
    #         "result": [{
    #             "text": "Hello! How can I help you today?",
    #             "content": []
    #         }]
    #     }

    #     response = model._create_openai_style_response(claude_response)

    #     # Check response structure
    #     self.assertEqual(len(response.choices), 1)
    #     message = response.choices[0].message
    #     self.assertEqual(message.content, "Hello! How can I help you today?")
    #     self.assertIsNone(message.tool_calls)

    # def test_support_tool_call(self):
    #     """Test that Claude Gateway reports tool call support"""
    #     model = ClaudeGatewayModel()
    #     self.assertTrue(model.support_tool_call())

    # @patch('mcpuniverse.llm.claude_gateway.requests.post')
    # def test_generate_with_retry_success(self, mock_post):
    #     """Test successful generation with retry mechanism"""
    #     model = ClaudeGatewayModel()

    #     # Mock successful response
    #     mock_response = Mock()
    #     mock_response.raise_for_status.return_value = None
    #     mock_response.text = json.dumps({
    #         "result": [{"text": "Hello, world!"}]
    #     })
    #     mock_post.return_value = mock_response

    #     messages = [{"role": "user", "content": "Hello"}]
    #     result = model._generate(messages)

    #     self.assertEqual(result, "Hello, world!")
    #     self.assertEqual(mock_post.call_count, 1)

    # @patch('mcpuniverse.llm.claude_gateway.requests.post')
    # def test_generate_with_tools(self, mock_post):
    #     """Test generation with tools parameter"""
    #     model = ClaudeGatewayModel()

    #     # Mock response with tool use
    #     mock_response = Mock()
    #     mock_response.raise_for_status.return_value = None
    #     mock_response.text = json.dumps({
    #         "result": [{
    #             "text": "",
    #             "content": [
    #                 {
    #                     "type": "tool_use",
    #                     "id": "call_123",
    #                     "name": "get_weather",
    #                     "input": {"location": "NYC"}
    #                 }
    #             ]
    #         }]
    #     })
    #     mock_post.return_value = mock_response

    #     messages = [{"role": "user", "content": "What's the weather?"}]
    #     tools = [
    #         {
    #             "type": "function",
    #             "function": {
    #                 "name": "get_weather",
    #                 "description": "Get weather",
    #                 "parameters": {
    # "type": "object", "properties": {"location": {"type": "string"}}}
    #             }
    #         }
    #     ]

    #     result = model._generate(messages, tools=tools)

    #     # Should return OpenAI-style response object
    #     self.assertTrue(hasattr(result, 'choices'))
    #     self.assertTrue(hasattr(result.choices[0], 'message'))
    #     self.assertTrue(hasattr(result.choices[0].message, 'tool_calls'))

    #     # Check that Claude tools format was sent in request
    #     call_args = mock_post.call_args
    #     sent_data = call_args[1]['json']
    #     self.assertIn('tools', sent_data)
    #     self.assertEqual(sent_data['tools'][0]['name'], 'get_weather')
    #     self.assertEqual(sent_data['tools'][0]['input_schema']['type'], 'object')

    # def test_thinking_parameter_handling(self):
    #     """Test thinking parameter configuration"""
    #     # Test default thinking disabled
    #     model = ClaudeGatewayModel()
    #     self.assertFalse(model.config.thinking_enabled)

    #     # Test custom thinking config
    #     config = {"thinking_enabled": True, "thinking_budget_tokens": 2000}
    #     model_with_thinking = ClaudeGatewayModel(config)
    #     self.assertTrue(model_with_thinking.config.thinking_enabled)
    #     self.assertEqual(model_with_thinking.config.thinking_budget_tokens, 2000)

    # @patch('mcpuniverse.llm.claude_gateway.requests.post')
    # def test_thinking_parameter_in_request(self, mock_post):
    #     """Test that thinking parameter is included in request when enabled"""
    #     model = ClaudeGatewayModel()

    #     mock_response = Mock()
    #     mock_response.raise_for_status.return_value = None
    #     mock_response.text = json.dumps({"result": [{"text": "Response"}]})
    #     mock_post.return_value = mock_response

    #     messages = [{"role": "user", "content": "Hello"}]

    #     # Test with thinking enabled via kwargs
    #     model._generate(messages, thinking_enabled=True, thinking_budget_tokens=3000)

    #     call_args = mock_post.call_args
    #     sent_data = call_args[1]['json']

    #     self.assertIn('thinking', sent_data)
    #     self.assertEqual(sent_data['thinking']['type'], 'enabled')
    #     self.assertEqual(sent_data['thinking']['budget_tokens'], 3000)

    # def test_complex_multi_turn_conversation(self):
    #     """Test complex multi-turn conversation with multiple tool calls and results"""
    #     model = ClaudeGatewayModel()

    #     complex_messages = [
    #         {"role": "system", "content": "You are a helpful assistant with access to tools."},
    #         {"role": "user", "content": "What's the weather in NYC and calculate 15 + 25?"},
    #         {
    #             "role": "assistant",
    #             "content": "I'll help you with both requests.",
    #             "tool_calls": [
    #                 {
    #                     "id": "call_weather",
    #                     "type": "function",
    #                     "function": {
    #                         "name": "get_weather",
    #                         "arguments": '{"location": "NYC", "unit": "celsius"}'
    #                     }
    #                 },
    #                 {
    #                     "id": "call_calc",
    #                     "type": "function",
    #                     "function": {
    #                         "name": "calculate",
    #                         "arguments": '{"operation": "add", "a": 15, "b": 25}'
    #                     }
    #                 }
    #             ]
    #         },
    #         {
    #             "role": "tool",
    #             "tool_call_id": "call_weather",
    #             "content": "Weather in NYC: 22°C, sunny"
    #         },
    #         {
    #             "role": "tool",
    #             "tool_call_id": "call_calc",
    #             "content": "15 + 25 = 40"
    #         },
    #         {"role": "user", "content": "Thanks! Now what about London weather?"}
    #     ]

    #     system_messages = []
    #     claude_messages = model._convert_openai_messages_to_claude(
    # complex_messages, system_messages)

    #     # Check system message extraction
    #     self.assertEqual(system_messages, ["You are a helpful assistant with access to tools."])

    #     # Check total messages (excluding system)
    #     self.assertEqual(len(claude_messages), 5)

    #     # Check assistant message with multiple tool calls
    #     assistant_msg = claude_messages[1]
    #     self.assertEqual(assistant_msg["role"], "assistant")
    #     self.assertEqual(len(assistant_msg["content"]), 3)  # 1 text + 2 tool_use

    #     # Check text content
    #     self.assertEqual(assistant_msg["content"][0]["type"], "text")
    #     self.assertEqual(assistant_msg["content"][0]["text"], "I'll help you with both requests.")

    #     # Check first tool use
    #     tool_use_1 = assistant_msg["content"][1]
    #     self.assertEqual(tool_use_1["type"], "tool_use")
    #     self.assertEqual(tool_use_1["id"], "call_weather")
    #     self.assertEqual(tool_use_1["name"], "get_weather")
    #     self.assertEqual(tool_use_1["input"]["location"], "NYC")

    #     # Check second tool use
    #     tool_use_2 = assistant_msg["content"][2]
    #     self.assertEqual(tool_use_2["type"], "tool_use")
    #     self.assertEqual(tool_use_2["id"], "call_calc")
    #     self.assertEqual(tool_use_2["name"], "calculate")
    #     self.assertEqual(tool_use_2["input"]["operation"], "add")

    #     # Check tool results
    #     tool_result_1 = claude_messages[2]
    #     self.assertEqual(tool_result_1["role"], "user")
    #     self.assertEqual(tool_result_1["content"][0]["type"], "tool_result")
    #     self.assertEqual(tool_result_1["content"][0]["tool_use_id"], "call_weather")

    #     tool_result_2 = claude_messages[3]
    #     self.assertEqual(tool_result_2["role"], "user")
    #     self.assertEqual(tool_result_2["content"][0]["tool_use_id"], "call_calc")

    # def test_empty_messages_handling(self):
    #     """Test handling of empty messages list"""
    #     model = ClaudeGatewayModel()

    #     system_messages = []
    #     claude_messages = model._convert_openai_messages_to_claude([], system_messages)

    #     self.assertEqual(len(system_messages), 0)
    #     self.assertEqual(len(claude_messages), 0)

    # def test_malformed_tool_call_arguments(self):
    #     """Test handling of malformed tool call arguments"""
    #     model = ClaudeGatewayModel()

    #     messages = [
    #         {
    #             "role": "assistant",
    #             "tool_calls": [
    #                 {
    #                     "id": "call_123",
    #                     "type": "function",
    #                     "function": {
    #                         "name": "test_function",
    #                         "arguments": "invalid json {"  # Malformed JSON
    #                     }
    #                 }
    #             ]
    #         }
    #     ]

    #     system_messages = []
    #     claude_messages = model._convert_openai_messages_to_claude(messages, system_messages)

    #     # Should handle gracefully with empty arguments
    #     self.assertEqual(len(claude_messages), 1)
    #     tool_use = claude_messages[0]["content"][0]
    #     self.assertEqual(tool_use["type"], "tool_use")
    #     self.assertEqual(tool_use["input"], {})  # Should default to empty dict

    # def test_missing_tool_fields(self):
    #     """Test handling of tools with missing fields"""
    #     model = ClaudeGatewayModel()

    #     # Tool missing description and parameters
    #     openai_tools = [
    #         {
    #             "type": "function",
    #             "function": {
    #                 "name": "incomplete_tool"
    #                 # Missing description and parameters
    #             }
    #         }
    #     ]

    #     claude_tools = model._convert_openai_tools_to_claude(openai_tools)

    #     self.assertEqual(len(claude_tools), 1)
    #     self.assertEqual(claude_tools[0]["name"], "incomplete_tool")
    #     self.assertEqual(claude_tools[0]["description"], "")  # Default empty string
    #     self.assertEqual(claude_tools[0]["input_schema"], {})  # Default empty dict

    # def test_mixed_message_types(self):
    #     """Test handling of mixed valid and invalid message types"""
    #     model = ClaudeGatewayModel()

    #     messages = [
    #         {"role": "system", "content": "System prompt"},
    #         {"role": "user", "content": "User message"},
    #         {"role": "unknown_role", "content": "This should be ignored"},  # Invalid role
    #         {"role": "assistant", "content": "Assistant response"}
    #     ]

    #     system_messages = []
    #     claude_messages = model._convert_openai_messages_to_claude(messages, system_messages)

    #     # Should process valid messages and ignore invalid ones
    #     self.assertEqual(len(system_messages), 1)
    #     self.assertEqual(len(claude_messages), 2)  # user + assistant only
    #     self.assertEqual(claude_messages[0]["role"], "user")
    #     self.assertEqual(claude_messages[1]["role"], "assistant")

    # def test_claude_response_edge_cases(self):
    #     """Test handling of various Claude response formats"""
    #     model = ClaudeGatewayModel()

    #     # Test response with empty result
    #     empty_response = {"result": []}
    #     with self.assertRaises(IndexError):
    #         model._create_openai_style_response(empty_response)

    #     # Test response with missing content field
    #     minimal_response = {
    #         "result": [{
    #             "text": "Just text, no content field"
    #         }]
    #     }

    #     response = model._create_openai_style_response(minimal_response)
    #     self.assertEqual(response.choices[0].message.content, "Just text, no content field")
    #     self.assertIsNone(response.choices[0].message.tool_calls)

if __name__ == "__main__":
    unittest.main()
