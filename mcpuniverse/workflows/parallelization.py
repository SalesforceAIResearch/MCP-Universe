"""
Agent workflow pattern: Parallelization workflow

This module implements the Parallelization workflow as described in
https://www.anthropic.com/engineering/building-effective-agents

The Parallelization workflow allows multiple agents to work on tasks
concurrently and then aggregates their results.
"""
import asyncio
from typing import List, Optional, Dict
from mcpuniverse.agent.base import BaseAgent
from mcpuniverse.workflows.base import BaseWorkflow
from mcpuniverse.agent.types import AgentResponse
from mcpuniverse.tracer import Tracer


class Parallelization(BaseWorkflow):
    """
    Implements a Parallelization workflow for concurrent agent execution.

    This workflow allows multiple agents to work on tasks in parallel
    and then aggregates their results using a designated aggregator agent.
    """
    alias = ["parallelization"]

    def __init__(self, agents: List[BaseAgent], aggregator: BaseAgent):
        """
        Initialize a Parallelization workflow.

        Args:
            agents (List[BaseAgent]): A list of agents to execute tasks in parallel.
            aggregator (BaseAgent): An agent responsible for aggregating results from parallel agents.
        """
        super().__init__()
        self._name = "parallelization"
        self._agents = agents + [aggregator]
        self._parallel_agents = agents
        self._aggregator = aggregator

    async def execute(
            self,
            message: str | List[str],
            output_format: Optional[str | Dict] = None,
            **kwargs
    ) -> AgentResponse:
        """
        Execute the parallelization workflow.

        This method runs the parallel agents concurrently, collects their responses,
        and then uses the aggregator to combine the results.

        Args:
            message (str | List[str]): Input message or list of messages for the agents.
            output_format (Optional[str | Dict]): Desired format for the aggregated output.
            **kwargs: Additional keyword arguments to pass to the agents.

        Returns:
            AgentResponse: The aggregated response from all agents.

        Raises:
            Exception: If the agents are not initialized or if an error occurs during execution.
        """
        assert len(self._agents) > 0 and self._agents[0].initialized, "The agents are not initialized."
        with kwargs.get("tracer", Tracer()).sprout() as tracer:
            if "tracer" in kwargs:
                kwargs.pop("tracer")
            trace_data = self.dump_config()
            try:
                results = await asyncio.gather(
                    *[agent.execute(message, tracer=tracer, **kwargs) for agent in self._parallel_agents]
                )
                responses = [
                    (f"{agent.get_description(with_tools_description=False)}\n"
                     f"Agent response: {res.get_response_str()}".strip())
                    for agent, res in zip(self._parallel_agents, results)
                ]
                input_message = "\n\n".join(responses)
                response = await self._aggregator.execute(
                    input_message, output_format=output_format, tracer=tracer, **kwargs)
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
        Dump the workflow configuration.

        Returns:
            dict: A dictionary containing the workflow configuration, including
                  the class name, parallel agents' configs, and aggregator config.
        """
        return {
            "type": "workflow",
            "class": self.__class__.__name__,
            "agents": [agent.dump_config() for agent in self._parallel_agents],
            "aggregator": self._aggregator.dump_config()
        }
