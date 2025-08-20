# Custom Agent Implementation Guide

This guide explains how to implement custom agents in the MCPUniverse framework, building upon the existing agent architecture to create specialized AI agents.

## Overview

MCPUniverse provides a flexible agent framework that allows you to create custom agents with different reasoning patterns, tool usage, and behaviors. The framework is built around the Model Control Protocol (MCP) and supports various LLM providers.

## Architecture

### Core Components

1. **BaseAgent**: Abstract base class that all agents inherit from
2. **BaseAgentConfig**: Configuration class for agent parameters
3. **AgentResponse**: Standardized response format
4. **MCPManager**: Manages connections to MCP servers
5. **Tracer**: Handles execution tracing and debugging

### Agent Types

The framework includes several built-in agent types:

- **BasicAgent**: Simple LLM interaction agent
- **ReAct**: Reasoning and Acting agent implementation
- **FunctionCallAgent**: Uses LLM native tool calling APIs
- **ReflectionAgent**: Self-reflective agent with memory

## Creating a Custom Agent

### Step 1: Define Your Agent Configuration

Create a configuration class that extends `BaseAgentConfig`:

```python
from dataclasses import dataclass
from mcpuniverse.agent.base import BaseAgentConfig

@dataclass
class MyCustomAgentConfig(BaseAgentConfig):
    """Configuration for your custom agent."""
    
    # Add custom configuration parameters
    max_retries: int = 3
    temperature: float = 0.7
    enable_memory: bool = True
    custom_prompt_path: str = "custom_prompt.j2"
    
    # You can override default values
    system_prompt: str = "path/to/your/custom_system_prompt.j2"
    max_iterations: int = 10
```

### Step 2: Implement Your Custom Agent Class

Create your agent class by inheriting from `BaseAgent`:

```python
from typing import Optional, Union, Dict, List
from mcpuniverse.agent.base import BaseAgent
from mcpuniverse.agent.types import AgentResponse
from mcpuniverse.mcp.manager import MCPManager
from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.tracer import Tracer
from mcpuniverse.agent.utils import build_system_prompt

class MyCustomAgent(BaseAgent):
    """A custom agent implementation."""
    
    # Required class attributes
    config_class = MyCustomAgentConfig
    alias = ["custom", "my-agent"]  # Alternative names for agent registration
    
    def __init__(
        self,
        mcp_manager: Optional[MCPManager] = None,
        llm: BaseLLM = None,
        config: Optional[Union[Dict, str]] = None,
        **kwargs
    ):
        """Initialize your custom agent."""
        super().__init__(mcp_manager=mcp_manager, llm=llm, config=config)
        
        # Initialize any custom attributes
        self._custom_memory = []
        self._retry_count = 0
    
    async def _initialize(self):
        """Optional: Initialize custom resources."""
        # This method is called after MCP clients are set up
        # Add any custom initialization logic here
        pass
    
    async def _execute(
        self,
        message: Union[str, List[str]],
        **kwargs
    ) -> AgentResponse:
        """Main execution method - implement your agent logic here."""
        
        # Get tracer for debugging
        tracer = kwargs.get("tracer", Tracer())
        callbacks = kwargs.get("callbacks", [])
        
        # Build system prompt with tools
        params = {"INSTRUCTION": self._config.instruction}
        params.update(self._config.template_vars)
        
        # Build system prompt using available tools
        system_prompt = build_system_prompt(
            system_prompt_template=self._config.system_prompt,
            tool_prompt_template=self._config.tools_prompt,
            tools=self._tools,
            **params
        )
        
        # Process input message
        if isinstance(message, (list, tuple)):
            message = "\n".join(message)
        
        # Implement your custom agent logic here
        response = await self._custom_reasoning_loop(
            system_prompt, message, tracer, callbacks
        )
        
        return AgentResponse(
            name=self._name,
            class_name=self.__class__.__name__,
            response=response,
            trace_id=tracer.trace_id
        )
    
    async def _custom_reasoning_loop(
        self,
        system_prompt: str,
        user_message: str,
        tracer: Tracer,
        callbacks: List
    ) -> str:
        """Implement your custom reasoning logic."""
        
        # Example: Multi-step reasoning with tool calls
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        for iteration in range(self._config.max_iterations):
            # Generate LLM response
            llm_response = await self._llm.generate_async(
                messages=messages,
                tracer=tracer,
                callbacks=callbacks,
                remote_mcp=self.get_remote_mcp_list()
            )
            
            # Check if tool calling is needed
            if self._should_call_tool(llm_response):
                try:
                    tool_result = await self.call_tool(
                        llm_response, tracer=tracer, callbacks=callbacks
                    )
                    
                    # Add tool result to conversation
                    messages.append({"role": "assistant", "content": llm_response})
                    messages.append({"role": "user", "content": f"Tool result: {tool_result}"})
                    
                except Exception as e:
                    # Handle tool call errors
                    error_msg = f"Tool call failed: {str(e)}"
                    messages.append({"role": "user", "content": error_msg})
            else:
                # Return final response
                return llm_response
        
        return "Maximum iterations reached"
    
    def _should_call_tool(self, response: str) -> bool:
        """Determine if the response contains a tool call."""
        # Implement your logic to detect tool calls
        # This is a simple example - you might want more sophisticated parsing
        try:
            import json
            parsed = json.loads(response.strip())
            return "server" in parsed and "tool" in parsed and "arguments" in parsed
        except:
            return False
    
    async def _cleanup(self):
        """Optional: Cleanup custom resources."""
        # Clean up any resources your agent created
        self._custom_memory.clear()
```

### Step 3: Create Custom Prompt Templates

Create Jinja2 templates for your agent's prompts:

**custom_system_prompt.j2:**
```jinja2
You are a specialized AI agent designed for {{INSTRUCTION}}.

{% if TOOLS_PROMPT is defined and TOOLS_PROMPT|length %}
{{TOOLS_PROMPT}}

When you need to use tools, respond with this JSON format:
{
    "server": "server-name",
    "tool": "tool-name", 
    "arguments": {"key": "value"}
}
{% endif %}

Follow these guidelines:
1. Be thorough in your analysis
2. Use tools when additional information is needed
3. Provide clear, actionable responses
4. If uncertain, ask clarifying questions
```

### Step 4: Register Your Agent

Create an `__init__.py` file or add to existing agent module:

```python
from .my_custom_agent import MyCustomAgent

# The agent will be automatically registered due to the metaclass
__all__ = [..., "MyCustomAgent"]
```

## Testing Your Custom Agent

Create tests for your agent:

```python
import pytest
from mcpuniverse.agent.my_custom_agent import MyCustomAgent
from mcpuniverse.llm.manager import ModelManager
from mcpuniverse.mcp.manager import MCPManager

@pytest.mark.asyncio
async def test_custom_agent():
    # Setup    
    agent = MyCustomAgent(
        mcp_manager=MCPManager(),
        llm=ModelManager().build_model(name="openai"),
        config={"name": "test-agent", "instruction": "Test agent"}
    )
    
    # Test initialization
    await agent.initialize()
    # Test execution
    response = await agent.execute(message="Hello, world!")
    assert response.name == "test-agent"
    assert isinstance(response.response, str)
    # Cleanup
    await agent.cleanup()
```

## Best Practices

1. **Configuration Management**: Use YAML files for configuration and support environment variable substitution
2. **Error Handling**: Implement comprehensive error handling with meaningful error messages
3. **Logging**: Use the framework's logging system for debugging and monitoring
4. **Resource Cleanup**: Always implement proper cleanup in the `_cleanup` method
6. **Memory Management**: Consider memory usage for long-running agents
7. **Testing**: Write comprehensive tests for your agent's functionality
8. **Documentation**: Document your agent's capabilities, configuration options, and usage examples

## Troubleshooting

### Common Issues

1. **Agent Not Registered**: Ensure your agent class has the correct metaclass and is imported
2. **Tool Not Found**: Check that MCP servers are properly configured and tools are available
3. **Configuration Errors**: Validate YAML configuration files and required environment variables

### Debugging

Use the built-in tracing system:

```python
from mcpuniverse.tracer import Tracer

tracer = Tracer()
response = await agent.execute("test message", tracer=tracer)

# Examine trace data
trace_data = tracer.get_trace()
print(json.dumps(trace_data, indent=2))
```

## Conclusion

The MCPUniverse framework provides a powerful foundation for building custom AI agents. By following this guide, you can create sophisticated agents that leverage MCP tools, implement custom reasoning patterns, and integrate seamlessly with the broader MCPUniverse ecosystem.

For more examples and advanced patterns, refer to the existing agent implementations in the `mcpuniverse/agent/` directory.