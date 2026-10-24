"""START → plan → verify → END；图中没有执行节点。"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.llm import Planner, PlannerOutputError, PlannerUnavailable, Proposal
from app.agent.plan import PlanError, PlanningContext, PlanResult, validate


class AgentState(TypedDict):
    goal: str
    context: PlanningContext
    proposal: Proposal
    trace: list[str]
    failure: str
    failure_kind: str
    result: PlanResult


def build_graph(planner: Planner):
    async def plan(state: AgentState) -> dict:
        try:
            proposal = await planner.propose(state["goal"], state["context"])
            return {"proposal": proposal, "trace": ["plan"]}
        except PlannerUnavailable as exc:
            return {"failure": str(exc), "failure_kind": "unavailable", "trace": ["plan"]}
        except PlannerOutputError as exc:
            return {"failure": str(exc), "failure_kind": "invalid", "trace": ["plan"]}

    def verify(state: AgentState) -> dict:
        trace = [*state["trace"], "verify"]
        source = planner.source
        if state.get("failure"):
            kind = state["failure_kind"]
            return {
                "result": PlanResult(
                    status=kind,
                    message=state["failure"],
                    error_code="model_" + kind,
                    trace=trace,
                    planner_source=source,
                )
            }
        try:
            steps = validate(state["proposal"].calls, state["context"])
        except PlanError as exc:
            return {
                "result": PlanResult(
                    status="invalid",
                    message=str(exc),
                    error_code=exc.code,
                    trace=trace,
                    planner_source=source,
                )
            }
        if not steps:
            return {
                "result": PlanResult(
                    status="clarification",
                    message="模型分析已返回，本轮没有可执行步骤，画布未修改。"
                    if state["proposal"].analysis
                    else "模型未提出可执行的工具计划，请补充目标或要求；本轮未执行。",
                    analysis=state["proposal"].analysis,
                    trace=trace,
                    planner_source=source,
                )
            }
        status = "needs_confirmation" if len(steps) > 1 else "ready"
        return {
            "result": PlanResult(
                status=status,
                message=f"已校验 {len(steps)} 步计划，尚未保存或执行。",
                analysis=state["proposal"].analysis,
                steps=steps,
                trace=trace,
                planner_source=source,
            )
        }

    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("verify", verify)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "verify")
    graph.add_edge("verify", END)
    return graph.compile()


async def run(goal: str, context: PlanningContext, planner: Planner) -> PlanResult:
    state = await build_graph(planner).ainvoke(
        {"goal": goal, "context": context, "trace": [], "failure": "", "failure_kind": ""}
    )
    return state["result"]
