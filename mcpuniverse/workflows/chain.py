"""
Agent workflow pattern: Prompt chaining

This module implements the Chain workflow, which allows for sequential execution of multiple agents.
Each agent in the chain processes the output of the previous agent, creating a pipeline of operations.

For more information on prompt chaining, see:
https://www.anthropic.com/engineering/building-effective-agents
"""
from typing import List, Dict, Optional
from mcpuniverse.agent.base import BaseAgent
from mcpuniverse.workflows.base import BaseWorkflow
from mcpuniverse.agent.types import AgentResponse
from mcpuniverse.tracer import Tracer


class Chain(BaseWorkflow):
    """
    A workflow that executes a chain of agents sequentially.

    Each agent in the chain processes the output of the previous agent,
    allowing for complex, multi-step operations. The final output is the
    result of the last agent in the chain.

    Attributes:
        alias (List[str]): Alternative names for the Chain workflow.
        _name (str): The name of the workflow.
        _agents (List[BaseAgent]): The list of agents in the chain.
    """
    alias = ["chain"]

    def __init__(self, agents: List[BaseAgent]):
        """
        Initialize a Chain workflow with a list of agents.

        Args:
            agents (List[BaseAgent]): A list of initialized agents to be executed in sequence.
        """
        super().__init__()
        self._name = "chain"
        self._agents = agents

    async def execute(
            self,
            message: str | List[str],
            output_format: Optional[str | Dict] = None,
            **kwargs
    ) -> AgentResponse:
        """
        Execute the chain of agents sequentially.

        This method processes the input message through each agent in the chain.
        The output of each agent becomes the input for the next agent.

        Args:
            message (str | List[str]): The initial input message or list of messages.
            output_format (Optional[str | Dict]): The desired output format for the final agent.
            **kwargs: Additional keyword arguments to be passed to each agent.

        Returns:
            AgentResponse: The response from the final agent in the chain.

        Raises:
            AssertionError: If the agents are not initialized.
            ValueError: If an agent's response is not of type AgentResponse.
            Exception: For any other errors that occur during execution.

        Note:
            This method uses a tracer to log the execution process. If a tracer is provided
            in kwargs, it will be used; otherwise, a new Tracer instance will be created.
        """
        assert len(self._agents) > 0 and self._agents[0].initialized, "The agents are not initialized."
        with kwargs.get("tracer", Tracer()).sprout() as tracer:
            if "tracer" in kwargs:
                kwargs.pop("tracer")
            trace_data = self.dump_config()
            input_message = message
            try:
                for i, agent in enumerate(self._agents):
                    if i == len(self._agents) - 1:
                        response = await agent.execute(
                            input_message, output_format=output_format, tracer=tracer, **kwargs)
                    else:
                        response = await agent.execute(input_message, tracer=tracer, **kwargs)
                    if isinstance(response, AgentResponse):
                        input_message = response.get_response_str()
                    else:
                        raise ValueError(f"Agent response has a wrong type: {type(response)}")

                response = AgentResponse(
                    name=self._name,
                    class_name=self.__class__.__name__,
                    response=response.response,
                    trace_id=tracer.trace_id
                )
                trace_data.update({
                    "messages": [message] if not isinstance(message, str) else message,
                    "response": response.get_response(),
                    "response_type": response.get_response_type(),
                    "error": ""
                })
                tracer.add(trace_data)
                return response

            except Exception as e:
                trace_data.update({
                    "messages": [message] if not isinstance(message, str) else message,
                    "response": "",
                    "response_type": "str",
                    "error": str(e)
                })
                tracer.add(trace_data)
                raise e

    def dump_config(self) -> dict:
        """
        Dump the workflow configuration as a dictionary.

        This method creates a dictionary representation of the Chain workflow,
        including its type, class name, and the configurations of all agents in the chain.

        Returns:
            dict: A dictionary containing the workflow configuration.
        """
        return {
            "type": "workflow",
            "class": self.__class__.__name__,
            "agents": [agent.dump_config() for agent in self._agents]
        }
