"""
This module implements the Orchestrator-workers workflow pattern for agent-based task execution
as described in https://www.anthropic.com/engineering/building-effective-agents.

It provides an Orchestrator class that can generate and execute plans using multiple specialized agents.
The workflow supports both full and iterative planning strategies.

The prompts used in this implementation are inspired by:
https://github.com/lastmile-ai/mcp-agent/blob/main/src/mcp_agent/workflows/orchestrator/orchestrator_prompts.py
"""
import copy
from typing import List, Literal, Dict, Optional
from pydantic import BaseModel, Field, ValidationError
from pydantic_core import from_json

from mcpuniverse.llm.base import BaseLLM
from mcpuniverse.agent.base import BaseAgent
from mcpuniverse.workflows.base import BaseWorkflow
from mcpuniverse.agent.types import AgentResponse
from mcpuniverse.agent.basic import BasicAgent
from mcpuniverse.agent.utils import render_prompt_template
from mcpuniverse.tracer import Tracer

PLANNER_PROMPT = """
You are an expert planner. Given an objective task and a list of agents (which are collections of tools and capabilities), 
your job is to break down the objective into a series of steps, which can be performed by these agents.
"""

ITERATIVE_PLAN_PROMPT_TEMPLATE = """
You are tasked with determining only the next step in a plan
needed to complete an objective. You must analyze the current state and progress from previous steps 
to decide what to do next.

A Step must be sequential in the plan, but can have independent parallel subtasks. Only return a single Step.

Objective: {{OBJECTIVE}}

{{PLAN_RESULTS}}

If the previous results achieve the objective, return is_complete=True.
Otherwise, generate the next Step.

You have access to the following agents:

### Agents Description ###

{{AGENTS_DESCRIPTION}}

### End of Agents Description ###

Generate the next step, by specifying a description of the step and independent subtasks that can run in parallel:
For each subtask specify:
    1. Clear description of the task that an LLM can execute  
    2. Name of one agent to use for the task

Return your response in the following JSON structure:
{
    "description": "Description of step 1",
    "tasks": [
        {
            "description": "Description of task 1",
            "agent": "agent-1-name"
        },
        {
            "description": "Description of task 2", 
            "agent": "agent-2-name"
        }, ...
    ],
    "is_complete": false
}

You must respond with valid JSON only, with no triple backticks. No markdown formatting.
No extra text. Do not wrap in ```json code fences.
"""

FULL_PLAN_PROMPT_TEMPLATE = """
You are tasked with orchestrating a plan to complete an objective.
You can analyze results from the previous steps already executed to decide if the objective is complete.
Your plan must be structured in sequential steps, with each step containing independent parallel subtasks.

Objective: {{OBJECTIVE}}

{{PLAN_RESULTS}}

If the previous results achieve the objective, return is_complete=True.
Otherwise, generate remaining steps needed.

You have access to the following agents:

### Agents Description ###

{{AGENTS_DESCRIPTION}}

### End of Agents Description ###

Generate a plan with all remaining steps needed.
Steps are sequential, but each Step can have parallel subtasks.
For each Step, specify a description of the step and independent subtasks that can run in parallel.
For each subtask specify:
    1. Clear description of the task that an LLM can execute  
    2. Name of one agent to use for the task

Return your response in the following JSON structure:
{
    "steps": [
        {
            "description": "Description of step 1",
            "tasks": [
                {
                    "description": "Description of task 1",
                    "agent": "agent-1-name"
                },
                {
                    "description": "Description of task 2", 
                    "agent": "agent-2-name"
                }, ...
            ]
        }
    ],
    "is_complete": false
}

You must respond with valid JSON only, with no triple backticks. No markdown formatting.
No extra text. Do not wrap in ```json code fences.
"""

TASK_PROMPT_TEMPLATE = """
You are part of a larger workflow to achieve the objective: {{OBJECTIVE}}.
Your job is to accomplish only the following task: {{TASK}}.

Results so far that may provide helpful context:
{{CONTEXT}}
"""

AGGREGATE_PLAN_PROMPT_TEMPLATE = """
Merge the results of the following executed steps in the plan and return a summarized result:
{{PLAN_RESULTS}}
"""


class Task(BaseModel):
    """
    Represents a single task within a plan step.

    Attributes:
        description (str): A detailed description of the task.
        agent (str): The name of the agent assigned to execute this task.
        result (str): The result of the task execution (initially empty).
    """
    description: str
    agent: str
    result: str = ""


class Step(BaseModel):
    """
    Represents a step in the execution plan.

    Attributes:
        description (str): A description of the step.
        tasks (List[Task]): A list of tasks to be executed in this step.
        is_complete (bool): Indicates whether this step has been completed.
    """
    description: str
    tasks: List[Task] = Field(default_factory=list)
    is_complete: bool = False


class Plan(BaseModel):
    """
    Represents the full execution plan.

    A plan consists of a series of steps to be executed sequentially.

    Attributes:
        steps (List[Step]): A list of steps in the plan.
        is_complete (bool): Indicates whether the entire plan has been completed.
    """
    steps: List[Step] = Field(default_factory=list)
    is_complete: bool = False

    def add_step(self, step: Step):
        """Add one step."""
        self.steps.append(step)


class Orchestrator(BaseWorkflow):
    """
    Implements the orchestrator-workers workflow for task execution.

    This class manages the generation and execution of plans using multiple specialized agents.
    It supports both full and iterative planning strategies.

    The orchestrator breaks down a given objective into steps and tasks, assigns them to
    appropriate agents, and aggregates the results to achieve the overall objective.
    """
    alias = ["orchestrator"]

    def __init__(
            self,
            llm: BaseLLM,
            agents: List[BaseAgent],
            plan_type: Literal["full", "iterative"] = "full",
            max_iterations: int = 10
    ):
        """
        Create a routing workflow.

        Args:
            llm: A LLM.
            agents: A list of agents to route.
            plan_type: "full" generates a full plan with one LLM call.
            "iterative" generates plan steps iteratively.
            max_iterations: The maximum number of iterations for plan step generation.
        """
        super().__init__()
        assert plan_type in ["full", "iterative"], "`plan_type` can only be `full` or `iterative`"
        self._name = "orchestrator"
        self._agents = agents
        self._llm = llm
        self._plan_type = plan_type
        self._max_iterations = max_iterations

        self._planner = BasicAgent(
            llm=self._llm,
            config={
                "name": "Orchestration Planner",
                "instruction": PLANNER_PROMPT.strip()
            }
        )
        self._name2agent = {agent.name: agent for agent in self._agents}

    async def execute(
            self,
            message: str | List[str],
            output_format: Optional[str | Dict] = None,
            **kwargs
    ) -> AgentResponse:
        """
        Execute the orchestrator workflow to achieve the given objective.

        This method generates a plan, executes it step by step using the available agents,
        and aggregates the results.

        Args:
            message (str | List[str]): The input message or objective to be achieved.
            output_format (Optional[str | Dict]): Desired format for the final output.
            **kwargs: Additional keyword arguments.

        Returns:
            AgentResponse: An object containing the final response and execution metadata.

        Raises:
            ValueError: If an invalid agent is specified or if the planner output is invalid.
            RuntimeError: If the task fails to complete within the maximum number of iterations.
        """
        for agent in self._agents:
            assert agent.initialized, f"Agent {agent.name} is not initialized"
        with kwargs.get("tracer", Tracer()).sprout() as tracer:
            if "tracer" in kwargs:
                kwargs.pop("tracer")
            trace_data = self.dump_config()
            await self._planner.initialize()
            if isinstance(message, (list, tuple)):
                message = "\n".join(message)

            try:
                plan = Plan()
                for _ in range(self._max_iterations):
                    if self._plan_type == "full":
                        plan = await self._generate_full_plan(message, plan=plan, tracer=tracer)
                    else:
                        plan = await self._generate_step(message, plan=plan, tracer=tracer)

                    for step in plan.steps:
                        for task in step.tasks:
                            if task.result:
                                continue
                            if task.agent not in self._name2agent:
                                raise ValueError(f"No agent found matching {task.agent}")
                            agent = self._name2agent[task.agent]
                            prompt_input = render_prompt_template(TASK_PROMPT_TEMPLATE, **{
                                "OBJECTIVE": message,
                                "TASK": task.description,
                                "CONTEXT": self._get_plan_results(plan)
                            })
                            response = await agent.execute(prompt_input, tracer=tracer)
                            task.result = response.get_response_str()

                    if plan.is_complete:
                        prompt_input = render_prompt_template(AGGREGATE_PLAN_PROMPT_TEMPLATE, **{
                            "PLAN_RESULTS": self._get_plan_results(plan)
                        })
                        response = await self._planner.execute(
                            message=prompt_input, output_format=output_format, tracer=tracer)
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

                raise RuntimeError(f"Task failed to complete in {self._max_iterations} iterations")
            except ValidationError as e:
                trace_data.update({
                    "messages": [message] if not isinstance(message, str) else message,
                    "response": "",
                    "response_type": "str",
                    "error": str(e)
                })
                raise ValueError("Failed to parse the planner output") from e
            except Exception as e:
                trace_data.update({
                    "messages": [message] if not isinstance(message, str) else message,
                    "response": "",
                    "response_type": "str",
                    "error": str(e)
                })
                raise e
            finally:
                await self._planner.cleanup()

    async def _generate_full_plan(self, message: str, plan: Plan, tracer: Tracer) -> Plan:
        """
        Generate a full plan by the planner.

        Args:
            message: Input message/question.
            plan: The current plan.
        """
        plan = copy.deepcopy(plan)
        agent_descriptions = "\n\n".join(agent.get_description() for agent in self._agents)
        params = {
            "OBJECTIVE": message,
            "AGENTS_DESCRIPTION": agent_descriptions,
            "PLAN_RESULTS": self._get_plan_results(plan)
        }
        prompt_input = render_prompt_template(FULL_PLAN_PROMPT_TEMPLATE, **params)
        output = await self._planner.execute(message=prompt_input, tracer=tracer)
        new_plan = Plan.model_validate(from_json(output.get_response_str()))
        # Append new steps
        plan.is_complete = new_plan.is_complete
        for step in new_plan.steps:
            plan.add_step(step)
        return plan

    async def _generate_step(self, message: str, plan: Plan, tracer: Tracer) -> Plan:
        """
        Generate a single step by the planner.

        Args:
            message: Input message/question.
            plan: The current plan.
        """
        plan = copy.deepcopy(plan)
        agent_descriptions = "\n\n".join(agent.get_description() for agent in self._agents)
        params = {
            "OBJECTIVE": message,
            "AGENTS_DESCRIPTION": agent_descriptions,
            "PLAN_RESULTS": self._get_plan_results(plan)
        }
        prompt_input = render_prompt_template(ITERATIVE_PLAN_PROMPT_TEMPLATE, **params)
        output = await self._planner.execute(message=prompt_input, tracer=tracer)
        step = Step.model_validate(from_json(output.get_response_str()))
        plan.is_complete = step.is_complete
        plan.add_step(step)
        return plan

    @staticmethod
    def _get_plan_results(plan: Plan) -> str:
        """
        Return the plan results and descriptions.

        Args:
            plan: The current plan.

        Returns:
            str: Previous step results.
        """
        index, steps = 0, []
        for step in plan.steps:
            task_description = []
            for task in step.tasks:
                if task.result:
                    task_description.append(f"  - Task: {task.description}\n    Result: {task.result}")
            if task_description:
                step_description = f"Step {index + 1}: {step.description}\nStep Subtasks:\n"
                step_description += "\n".join(task_description)
                steps.append(step_description)
                index += 1
        r = "\n\n".join(steps) if steps else "No steps executed"
        return f"Progress So Far (steps completed):\n{r}"

    def dump_config(self) -> dict:
        """
        Dump the workflow configuration as a dictionary.

        This method creates a dictionary representation of the Orchestrator workflow,
        including its type, class name, and the configurations of all agents.

        Returns:
            dict: A dictionary containing the workflow configuration.
        """
        return {
            "type": "workflow",
            "class": self.__class__.__name__,
            "agents": [agent.dump_config() for agent in self._agents],
            "llm": self._llm.dump_config(),
            "plan_type": self._plan_type,
            "max_iterations": self._max_iterations
        }
