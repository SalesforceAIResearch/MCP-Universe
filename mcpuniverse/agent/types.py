"""
Agent related types, e.g., class for responses
"""
import json
from dataclasses import dataclass
from pydantic import BaseModel
from mcp.types import CallToolResult, TextContent, ImageContent


@dataclass
class AgentResponse:
    """
    Represents a response from an agent.

    This class encapsulates various types of responses (BaseModel, dict, or str)
    along with metadata such as the agent's name and class name.

    Attributes:
        name (str): The name of the agent.
        class_name (str): The class name of the agent.
        response (Union[BaseModel, dict, str]): The actual response content.
        trace_id (str): An optional trace ID for debugging or tracking purposes.
    """
    name: str
    class_name: str
    response: BaseModel | dict | str
    trace_id: str = ""

    def get_response_type(self) -> str:
        """
        Determines and returns the type of the response.

        Returns:
            str: The type of the response. 'str' for string responses,
                 or the class name for other types.
        """
        if isinstance(self.response, str):
            return "str"
        return self.response.__class__.__name__

    def get_response_str(self) -> str:
        """
        Converts the response to a string representation.

        This method handles different response types:
        - For CallToolResult, it extracts text or image data, or returns an error message.
        - For dictionaries, it returns a JSON string.
        - For other types, it returns the string representation.

        Returns:
            str: The string representation of the response.
        """
        if isinstance(self.response, CallToolResult):
            if self.response.isError:
                return "Error occurred in the call tool result"
            content = self.response.content[0]
            if isinstance(content, TextContent):
                return content.text
            if isinstance(content, ImageContent):
                return content.data
            return json.dumps(self.response.model_dump(mode="json"))
        if isinstance(self.response, dict):
            return json.dumps(self.response)
        return str(self.response)

    def get_response(self) -> dict | str:
        """
        Retrieves the response in its most appropriate form.

        - For Pydantic BaseModel instances, it returns a JSON-compatible dictionary.
        - For dictionaries, it returns the dictionary as-is.
        - For other types, it returns the string representation.

        Returns:
            Union[dict, str]: The response as a dictionary or string.
        """
        if isinstance(self.response, BaseModel):
            return self.response.model_dump(mode="json")
        if isinstance(self.response, dict):
            return self.response
        return str(self.response)

    def has_image(self) -> bool:
        """
        Checks if the response contains an image.

        This method specifically looks for ImageContent within CallToolResult responses.

        Returns:
            bool: True if the response contains an image, False otherwise.
        """
        if isinstance(self.response, CallToolResult):
            if self.response.isError:
                return False
            content = self.response.content[0]
            if isinstance(content, ImageContent):
                return True
        return False
