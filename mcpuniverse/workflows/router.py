"""
Agent workflow pattern: Routing

This module implements a routing workflow for directing user requests to appropriate agents.
It is inspired by the Anthropic engineering blog post on building effective agents and
the MCP Agent project.

References:
- https://www.anthropic.com/engineering/building-effective-agents
- https://github.com/lastmile-ai/mcp-agent/blob/main/src/mcp_agent/workflows/router/router_llm.py

The module contains classes for routing logic, agent selection, and workflow execution.
"""
import asyncio
from typing import List
from pydantic import BaseModel, Field, ValidationError
from pydantic_core import from_json

from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.agent.base import BaseAgent
from mcpuniverse.workflows.base import BaseWorkflow
from mcpuniverse.agent.types import AgentResponse
from mcpuniverse.agent.basic import BasicAgent
from mcpuniverse.tracer import Tracer

DEFAULT_ROUTING_PROMPT = """
You are a highly reliable and accurate request router that directs incoming user's requests to the most appropriate agent.
Below are the available agents, each with their descriptions:

### Agents Description ###

{{AGENTS_DESCRIPTION}}

### End of Agents Description ###

Your task is to analyze the user's request and determine the most appropriate agent from the options above. You must consider:
- The specific capabilities and tools each agent offers
- How well the request matches the agent's description
- Whether the request might benefit from multiple agents (up to {{TOP_K}})

You must ONLY respond with the exact JSON object format below, nothing else:
{
    "agents": [
        {
            "name": "agent-1-name",
            "confidence": "high, medium or low",
            "reason": "brief explanation about why you chose agent-1"
        },
        {
            "name": "agent-2-name",
            "confidence": "high, medium or low",
            "reason": "brief explanation about why you chose agent-2"
        }, ...
    ]
}

Only include agents that are truly relevant. You may return fewer than {{TOP_K}} if appropriate.
If none of the agents are relevant, return an empty list.
"""


class SelectedAgent(BaseModel):
    """
    Represents an agent selected by the router.

    Attributes:
        name (str): The name of the selected agent.
        confidence (str): The confidence level of the selection (high, medium, or low).
        reason (str): A brief explanation for why this agent was selected.
    """
    name: str = ""
    confidence: str = ""
    reason: str = ""


class RouterSelection(BaseModel):
    """
    Represents the collection of agents selected by the router.

    Attributes:
        agents (List[SelectedAgent]): A list of selected agents.
    """
    agents: List[SelectedAgent] = Field(default_factory=list)


class Router(BaseWorkflow):
    """
    Implements the routing workflow for directing user requests to appropriate agents.

    This class manages the process of analyzing user input, selecting relevant agents,
    and executing the chosen agents' tasks.
    """
    alias = ["router"]

    def __init__(self, llm: BaseLLM, agents: List[BaseAgent], top_k: int = 1):
        """
        Initialize a routing workflow.

        Args:
            llm (BaseLLM): The language model used for routing decisions.
            agents (List[BaseAgent]): A list of available agents to route requests to.
            top_k (int, optional): The maximum number of agents to select for each request. Defaults to 1.
        """
        super().__init__()
        self._name = "router"
        self._agents = agents
        self._prompt = DEFAULT_ROUTING_PROMPT
        self._llm = llm
        self._top_k = top_k

    async def execute(self, message: str | List[str], **kwargs) -> AgentResponse:
        """
        Execute the routing workflow for a given input message.

        This method analyzes the input, selects appropriate agents, and executes their tasks.

        Args:
            message (str | List[str]): The input message or list of messages to process.
            **kwargs: Additional keyword arguments to pass to the agents.

        Returns:
            AgentResponse: An object containing the responses from the selected agents.

        Raises:
            RuntimeError: If no suitable agents are found for the task.
            ValueError: If there's an error parsing the router's output.
        """
        for agent in self._agents:
            assert agent.initialized, f"Agent {agent.name} is not initialized"
        with kwargs.get("tracer", Tracer()).sprout() as tracer:
            if "tracer" in kwargs:
                kwargs.pop("tracer")
            trace_data = self.dump_config()
            try:
                descriptions = [agent.get_description() for agent in self._agents]
                router = BasicAgent(
                    llm=self._llm,
                    config={
                        "system_prompt": self._prompt,
                        "template_vars": {
                            "TOP_K": self._top_k,
                            "AGENTS_DESCRIPTION": "\n\n".join(descriptions)
                        }
                    }
                )
                await router.initialize()
                response = await router.execute(message=message, tracer=tracer)
                trace_data.update({
                    "messages": [message] if not isinstance(message, str) else message,
                    "response": response.get_response(),
                    "response_type": response.get_response_type(),
                    "error": ""
                })
                tracer.add(trace_data)
                await router.cleanup()

                llm_response = response.get_response_str()
                llm_response = llm_response.strip().strip('`').strip()
                if llm_response.startswith("json"):
                    llm_response = llm_response[4:].strip()
                output = RouterSelection.model_validate(from_json(llm_response))

                agents = []
                for info in self._sort_by_confidence(output.agents)[:self._top_k]:
                    for agent in self._agents:
                        if agent.name == info.name:
                            agents.append({
                                "name": agent.name,
                                "agent": agent,
                                "reason": info.reason,
                                "confidence": info.confidence
                            })
                            break
                if len(agents) == 0:
                    raise RuntimeError("Router cannot find proper agents for this task")

                results = await asyncio.gather(
                    *[agent["agent"].execute(message, tracer=tracer, **kwargs) for agent in agents]
                )
                responses = [{
                    "name": agent["name"],
                    "confidence": agent["confidence"],
                    "response": res.get_response()
                } for agent, res in zip(agents, results)]
                return AgentResponse(
                    name=self._name,
                    class_name=self.__class__.__name__,
                    response={"agents": responses},
                    trace_id=tracer.trace_id
                )

            except ValidationError as e:
                raise ValueError("Failed to parse the router output") from e
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

        Returns:
            dict: A dictionary containing the configuration of the router and its agents.
        """
        return {
            "type": "workflow",
            "class": self.__class__.__name__,
            "agents": [agent.dump_config() for agent in self._agents],
            "llm": self._llm.dump_config(),
            "top_k": self._top_k
        }

    @staticmethod
    def _sort_by_confidence(agents: List[SelectedAgent]) -> List[SelectedAgent]:
        """
        Sort the selected agents by their confidence levels.

        Args:
            agents (List[SelectedAgent]): The list of selected agents to sort.

        Returns:
            List[SelectedAgent]: A new list of agents sorted by confidence (high, medium, low, other).
        """
        sorted_agents = []
        confidence2agents = {"high": [], "medium": [], "low": [], "other": []}
        for info in agents:
            confidence = info.confidence.lower()
            if confidence not in confidence2agents:
                confidence = "other"
            confidence2agents[confidence].append(info)
        for key in ["high", "medium", "low", "other"]:
            sorted_agents.extend(confidence2agents[key])
        return sorted_agents
