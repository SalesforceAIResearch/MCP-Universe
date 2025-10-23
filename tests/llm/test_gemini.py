import os
import json
import unittest
import pytest
from unittest.mock import patch, Mock
from pydantic import BaseModel
from google.genai import types
from mcpuniverse.llm.gemini import GeminiModel
from mcpuniverse.common.context import Context


class Response(BaseModel):
    code: str
    explanation: str


class TestGemini(unittest.TestCase):

    @pytest.mark.skip
    def test(self):
        model = GeminiModel()
        system_message = "As a professional python developer"
        user_message = "please write a program to generate a fibonacci sequence"
        response = model.get_response(system_message, user_message)
        print(response)

    def test_list_undefined_env_vars(self):
        os.environ["GEMINI_API_KEY"] = ""
        model = GeminiModel()
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, ["GEMINI_API_KEY"])

        context = Context(env={"GEMINI_API_KEY": "xxx"})
        model = GeminiModel()
        model.set_context(context)
        r = model.list_undefined_env_vars()
        self.assertListEqual(r, [])

    # def test_support_tool_call(self):
    #     """Test that Gemini model reports tool call support"""
    #     model = GeminiModel()
    #     self.assertTrue(model.support_tool_call())

    # def test_convert_openai_tools_to_gemini(self):
    #     """Test conversion of OpenAI tools format to Gemini format"""
    #     model = GeminiModel()

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

    #     gemini_tools = model._convert_openai_tools_to_gemini(openai_tools)

    #     # Check conversion
    #     self.assertEqual(len(gemini_tools), 1)  # All functions in one Tool object
    #     self.assertEqual(len(gemini_tools[0].function_declarations), 2)

    #     # First function
    #     func1 = gemini_tools[0].function_declarations[0]
    #     self.assertEqual(func1.name, "get_weather")
    #     self.assertEqual(func1.description, "Get current weather for a location")
    #     self.assertTrue(str(func1.parameters.type).endswith("OBJECT"))
    #     self.assertIn("location", func1.parameters.properties)

    #     # Second function
    #     func2 = gemini_tools[0].function_declarations[1]
    #     self.assertEqual(func2.name, "calculate_sum")
    #     self.assertEqual(func2.description, "Calculate sum of two numbers")
    #     self.assertIn("a", func2.parameters.properties)
    #     self.assertIn("b", func2.parameters.properties)

    # def test_convert_openai_schema_to_gemini(self):
    #     """Test conversion of OpenAI JSON schema to Gemini Schema format"""
    #     model = GeminiModel()

    #     # Test basic object schema
    #     openai_schema = {
    #         "type": "object",
    #         "properties": {
    #             "name": {"type": "string", "description": "Person's name"},
    #             "age": {"type": "integer", "description": "Person's age"},
    #             "hobbies": {
    #                 "type": "array",
    #                 "items": {"type": "string"},
    #                 "description": "List of hobbies"
    #             }
    #         },
    #         "required": ["name"]
    #     }

    #     gemini_schema = model._convert_openai_schema_to_gemini(openai_schema)

    #     # Check basic properties
    #     self.assertTrue(str(gemini_schema.type).endswith("OBJECT"))
    #     self.assertIn("name", gemini_schema.properties)
    #     self.assertIn("age", gemini_schema.properties)
    #     self.assertIn("hobbies", gemini_schema.properties)
    #     self.assertEqual(gemini_schema.required, ["name"])

    #     # Check nested properties
    #     name_prop = gemini_schema.properties["name"]
    #     self.assertTrue(str(name_prop.type).endswith("STRING"))
    #     self.assertEqual(name_prop.description, "Person's name")

    #     age_prop = gemini_schema.properties["age"]
    #     self.assertTrue(str(age_prop.type).endswith("INTEGER"))

    #     hobbies_prop = gemini_schema.properties["hobbies"]
    #     self.assertTrue(str(hobbies_prop.type).endswith("ARRAY"))
    #     self.assertTrue(str(hobbies_prop.items.type).endswith("STRING"))

    # def test_convert_openai_schema_empty(self):
    #     """Test conversion of empty schema"""
    #     model = GeminiModel()
        
    #     # Empty schema should default to object
    #     empty_schema = {}
    #     gemini_schema = model._convert_openai_schema_to_gemini(empty_schema)
    #     self.assertTrue(str(gemini_schema.type).endswith("OBJECT"))

    #     # None schema should also default to object
    #     gemini_schema_none = model._convert_openai_schema_to_gemini(None)
    #     self.assertTrue(str(gemini_schema_none.type).endswith("OBJECT"))

    # def test_create_openai_style_response_text_only(self):
    #     """Test creation of OpenAI-style response from Gemini response without tools"""
    #     model = GeminiModel()

    #     # Mock Gemini response with text only
    #     mock_candidate = Mock()
    #     mock_content = Mock()
    #     mock_part = Mock()
    #     mock_part.text = "Hello! How can I help you today?"
    #     mock_part.function_call = None
    #     mock_content.parts = [mock_part]
    #     mock_candidate.content = mock_content
        
    #     mock_gemini_response = Mock()
    #     mock_gemini_response.candidates = [mock_candidate]

    #     response = model._create_openai_style_response(mock_gemini_response)

    #     # Check response structure
    #     self.assertEqual(len(response.choices), 1)
    #     message = response.choices[0].message
    #     self.assertEqual(message.content, "Hello! How can I help you today?")
    #     self.assertIsNone(message.tool_calls)
    #     self.assertEqual(response.model, model.config.model_name)

    # def test_create_openai_style_response_with_tool_calls(self):
    #     """Test creation of OpenAI-style response from Gemini response with tool calls"""
    #     model = GeminiModel()

    #     # Mock Gemini response with tool call
    #     mock_candidate = Mock()
    #     mock_content = Mock()
        
    #     # Text part
    #     mock_text_part = Mock()
    #     mock_text_part.text = "I'll help you get the weather."
    #     mock_text_part.function_call = None
        
    #     # Function call part
    #     mock_func_part = Mock()
    #     mock_func_part.text = None
    #     mock_func_call = Mock()
    #     mock_func_call.name = "get_weather"
    #     mock_func_call.args = {"location": "San Francisco", "unit": "celsius"}
    #     mock_func_part.function_call = mock_func_call
        
    #     mock_content.parts = [mock_text_part, mock_func_part]
    #     mock_candidate.content = mock_content
        
    #     mock_gemini_response = Mock()
    #     mock_gemini_response.candidates = [mock_candidate]

    #     response = model._create_openai_style_response(mock_gemini_response)

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
    #     self.assertEqual(tool_call["type"], "function")
    #     self.assertEqual(tool_call["function"]["name"], "get_weather")

    #     # Check arguments are JSON string
    #     args = json.loads(tool_call["function"]["arguments"])
    #     self.assertEqual(args["location"], "San Francisco")
    #     self.assertEqual(args["unit"], "celsius")

    # def test_create_openai_style_response_no_candidates(self):
    #     """Test handling of Gemini response with no candidates"""
    #     model = GeminiModel()

    #     # Mock empty response
    #     mock_gemini_response = Mock()
    #     mock_gemini_response.candidates = []

    #     response = model._create_openai_style_response(mock_gemini_response)

    #     # Should create response with empty content
    #     self.assertEqual(len(response.choices), 1)
    #     message = response.choices[0].message
    #     self.assertIsNone(message.content)
    #     self.assertIsNone(message.tool_calls)

    # def test_missing_tool_fields(self):
    #     """Test handling of tools with missing fields"""
    #     model = GeminiModel()

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

    #     gemini_tools = model._convert_openai_tools_to_gemini(openai_tools)

    #     self.assertEqual(len(gemini_tools), 1)
    #     func_decl = gemini_tools[0].function_declarations[0]
    #     self.assertEqual(func_decl.name, "incomplete_tool")
    #     self.assertEqual(func_decl.description, "")  # Default empty string
    #     self.assertTrue(str(func_decl.parameters.type).endswith("OBJECT"))  # Default object

    # def test_complex_nested_schema(self):
    #     """Test conversion of complex nested schemas"""
    #     model = GeminiModel()

    #     complex_schema = {
    #         "type": "object",
    #         "properties": {
    #             "user": {
    #                 "type": "object",
    #                 "properties": {
    #                     "name": {"type": "string"},
    #                     "contacts": {
    #                         "type": "array",
    #                         "items": {
    #                             "type": "object",
    #                             "properties": {
    #                                 "type": {"type": "string"},
    #                                 "value": {"type": "string"}
    #                             }
    #                         }
    #                     }
    #                 },
    #                 "required": ["name"]
    #             },
    #             "preferences": {
    #                 "type": "array",
    #                 "items": {"type": "string"}
    #             }
    #         },
    #         "required": ["user"]
    #     }

    #     gemini_schema = model._convert_openai_schema_to_gemini(complex_schema)

    #     # Check top level
    #     self.assertTrue(str(gemini_schema.type).endswith("OBJECT"))
    #     self.assertEqual(gemini_schema.required, ["user"])

    #     # Check nested user object
    #     user_prop = gemini_schema.properties["user"]
    #     self.assertTrue(str(user_prop.type).endswith("OBJECT"))
    #     self.assertEqual(user_prop.required, ["name"])
    #     self.assertIn("name", user_prop.properties)
    #     self.assertIn("contacts", user_prop.properties)

    #     # Check contacts array
    #     contacts_prop = user_prop.properties["contacts"]
    #     self.assertTrue(str(contacts_prop.type).endswith("ARRAY"))
    #     self.assertTrue(str(contacts_prop.items.type).endswith("OBJECT"))
    #     self.assertIn("type", contacts_prop.items.properties)
    #     self.assertIn("value", contacts_prop.items.properties)

    #     # Check preferences array
    #     prefs_prop = gemini_schema.properties["preferences"]
    #     self.assertTrue(str(prefs_prop.type).endswith("ARRAY"))
    #     self.assertTrue(str(prefs_prop.items.type).endswith("STRING"))

    # def test_system_message_handling(self):
    #     """Test that system messages are properly extracted and formatted"""
    #     model = GeminiModel()

    #     # Mock to test message processing
    #     with patch.object(model, '_convert_openai_tools_to_gemini') as mock_convert:
    #         with patch('google.genai.Client') as mock_client_class:
    #             mock_client = Mock()
    #             mock_client_class.return_value = mock_client
    #             mock_response = Mock()
    #             mock_response.text = "Response"
    #             mock_client.models.generate_content.return_value = mock_response

    #             messages = [
    #                 {"role": "system", "content": "You are a helpful assistant."},
    #                 {"role": "system", "content": "Be concise."},
    #                 {"role": "user", "content": "Hello"}
    #             ]

    #             model._generate(messages)

    #             # Check that system messages were combined
    #             call_args = mock_client.models.generate_content.call_args
    #             config = call_args[1]['config']
    #             expected_system = "You are a helpful assistant.\n\nBe concise."
    #             self.assertEqual(config.system_instruction, expected_system)

    #             # Check that only user message was included in contents
    #             contents = call_args[1]['contents']
    #             self.assertEqual(contents, "Hello")

if __name__ == "__main__":
    unittest.main()
