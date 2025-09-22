"""Tool permission management for MCP operations."""

import re
from typing import Dict, Literal, Any, Optional
from pydantic import BaseModel, Field


class ToolPermission(BaseModel):
    """Defines permission rules for MCP tool execution.
    
    Attributes:
        tool: Tool name or regex pattern with wildcards.
        arguments: Tool argument constraints as key-value pairs.
        action: Permission action (allow, reject, or human_review).
    """
    tool: str
    arguments: Dict[str, str] = Field(default_factory=dict)
    action: Literal["allow", "reject", "human_review"] = "allow"

    @staticmethod
    def _match(pattern: str, text: str):
        """Matches text against pattern with regex support.
        
        Args:
            pattern: Pattern string with optional wildcards.
            text: Text to match against pattern.
            
        Returns:
            Match object or boolean indicating match result.
        """
        if "*" in pattern or "+" in pattern or "?" in pattern:
            return re.match(pattern, text)
        return pattern == text

    def match(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Checks if tool execution matches this permission rule.
        
        Args:
            tool_name: Name of the tool to check.
            arguments: Tool arguments to validate.
            
        Returns:
            Permission action if matched, None otherwise.
        """
        if not ToolPermission._match(self.tool, tool_name):
            return None
        if arguments is None:
            arguments = {}
        match = True
        for key, value in self.arguments.items():
            if key not in arguments or not ToolPermission._match(value, arguments[key]):
                match = False
                break
        if not match:
            return None
        return self.action
