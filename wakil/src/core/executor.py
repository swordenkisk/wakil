"""
executor.py — وكيل: Step Executor & Approval Gate
===================================================
Executes plan steps, routes to tools, handles approval gates,
offloads large results to files (context window relief), and
coordinates sub-agents.
"""

import asyncio, json, time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Dict, List, Optional

from ..core.planner import Plan, PlanStep
from ..tools.registry import ToolRegistry
from ..memory.store import MemoryStore


@dataclass
class StepResult:
    step_id   : int
    status    : str   # done|failed|awaiting_approval|skipped
    output    : str   = ""
    file_path : str   = ""   # if result was offloaded to file
    error     : str   = ""
    duration_ms: int  = 0


@dataclass
class ExecutionResult:
    plan     : Plan
    steps    : List[StepResult] = field(default_factory=list)
    synthesis: str = ""
    total_ms : int = 0

    @property
    def success(self): return all(s.status in ("done","skipped") for s in self.steps)


class Executor:
    """
    Executes a Plan step by step.

    Features:
    - Approval gate: pauses for user confirmation on flagged steps
    - Context offloading: results >2000 chars go to /memories/offload/
    - Sub-agent delegation: spawns isolated child executors
    - Streaming events via async generator
    """

    SYNTHESIS_SYSTEM = """You are a synthesis agent. Given the task and the results of each step,
write a clear, complete final answer. Be concise but thorough.
If steps produced code, include the final code. If steps produced research, summarise key findings.
Respond in the same language as the original task."""

    OFFLOAD_THRESHOLD = 2000   # chars

    def __init__(self, provider, tools: ToolRegistry,
                 memory: MemoryStore, workspace: str = "/tmp/wakil_workspace"):
        self.provider  = provider
        self.tools     = tools
        self.memory    = memory
        self.workspace = workspace
        self._approval_cb: Optional[Callable] = None

    def set_approval_callback(self, cb: Callable):
        """Register async callback for approval gates: cb(step) -> bool"""
        self._approval_cb = cb

    async def execute(self, plan: Plan) -> AsyncIterator[dict]:
        """
        Execute plan steps, yielding SSE-style event dicts:
          {"event": "step_start",    "step": {...}}
          {"event": "step_done",     "step": {...}, "output": "..."}
          {"event": "step_approval", "step": {...}}
          {"event": "step_failed",   "step": {...}, "error": "..."}
          {"event": "synthesis",     "text": "..."}
          {"event": "done",          "result": {...}}
        """
        t_start = time.monotonic()
        step_results = []

        for step in plan.steps:
            step.status = "running"
            yield {"event": "step_start", "step": step.to_dict()}

            # ── Approval gate ─────────────────────────────────
            if step.requires_approval:
                step.status = "awaiting_approval"
                yield {"event": "step_approval", "step": step.to_dict()}
                # In streaming mode, approval response comes via separate endpoint
                # For now we yield and pause; approval resumes via /api/approve
                # We'll continue optimistically in mock mode
                approved = await self._request_approval(step)
                if not approved:
                    step.status = "skipped"
                    step_results.append(StepResult(
                        step_id=step.id, status="skipped",
                        output="Skipped by user"))
                    yield {"event": "step_skipped", "step": step.to_dict()}
                    continue

            # ── Sub-agent delegation ──────────────────────────
            if step.sub_agent:
                output = await self._run_sub_agent(step)
            else:
                output = await self._run_step(step)

            # ── Context offloading ────────────────────────────
            file_path = ""
            if len(output) > self.OFFLOAD_THRESHOLD:
                file_path = await self._offload(step.id, output)
                display   = f"[Result offloaded → {file_path}]\n\n" + output[:500] + "..."
            else:
                display = output

            step.status = "done"
            step.result = display
            sr = StepResult(step_id=step.id, status="done",
                            output=display, file_path=file_path)
            step_results.append(sr)
            yield {"event": "step_done", "step": step.to_dict(), "output": display}

        # ── Synthesis ─────────────────────────────────────────
        yield {"event": "synthesising"}
        synthesis = await self._synthesise(plan, step_results)
        plan_dict = plan.to_dict()

        total_ms = int((time.monotonic() - t_start) * 1000)
        result = ExecutionResult(plan=plan, steps=step_results,
                                 synthesis=synthesis, total_ms=total_ms)
        yield {"event": "synthesis", "text": synthesis}
        yield {"event": "done", "result": {
            "plan"      : plan_dict,
            "synthesis" : synthesis,
            "total_ms"  : total_ms,
            "success"   : result.success,
        }}

    async def _run_step(self, step: PlanStep) -> str:
        """Execute a single step using the appropriate tool."""
        from ..providers.base import ChatMessage

        # Build context from memory
        memories = await self.memory.search(step.title + " " + step.description, top_k=3)
        mem_context = "\n".join(f"- {m['content']}" for m in memories) if memories else ""

        # Tool routing based on hint
        if step.tool_hint == "code_exec":
            result = await self.tools.run("code_executor", step.description)
        elif step.tool_hint == "file_read":
            result = await self.tools.run("file_reader", step.description)
        elif step.tool_hint == "file_write":
            result = await self.tools.run("file_writer", step.description)
        elif step.tool_hint == "web_search":
            result = await self.tools.run("web_searcher", step.description)
        elif step.tool_hint == "memory":
            result = await self.tools.run("memory_tool", step.description)
        else:
            # Ask LLM to execute this step directly
            sys = "You are an expert assistant. Execute the given step precisely and return the result."
            if mem_context:
                sys += f"\n\nRelevant memories:\n{mem_context}"
            resp = await self.provider.chat(
                [ChatMessage(role="user", content=step.description)],
                system_prompt=sys, temperature=0.4, max_tokens=3000,
            )
            result = resp.content

        # Save to memory if valuable
        if len(result) > 50:
            await self.memory.save(
                key=f"step_{step.id}_{step.title[:30]}",
                content=result[:1000],
                tags=[step.tool_hint, "step_result"],
            )
        return result

    async def _run_sub_agent(self, step: PlanStep) -> str:
        """Spawn an isolated sub-agent for complex steps."""
        from ..core.planner import Planner
        sub_planner = Planner(self.provider)
        sub_plan    = await sub_planner.plan(step.description)

        outputs = []
        async for event in self.execute(sub_plan):
            if event.get("event") == "step_done":
                outputs.append(f"[Sub-step {event['step']['id']}] {event['output'][:300]}")
            elif event.get("event") == "synthesis":
                outputs.append(f"[Sub-agent synthesis]\n{event['text']}")
                break

        return "\n\n".join(outputs) or "Sub-agent completed."

    async def _request_approval(self, step: PlanStep) -> bool:
        if self._approval_cb:
            return await self._approval_cb(step)
        return True   # auto-approve in headless mode

    async def _offload(self, step_id: int, content: str) -> str:
        import os
        path = f"{self.workspace}/offload_step_{step_id}_{int(time.time())}.txt"
        os.makedirs(self.workspace, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    async def _synthesise(self, plan: Plan, results: List[StepResult]) -> str:
        from ..providers.base import ChatMessage
        context = f"Task: {plan.task}\n\n"
        for sr in results:
            context += f"Step {sr.step_id} ({sr.status}):\n{sr.output[:600]}\n\n"

        resp = await self.provider.chat(
            [ChatMessage(role="user", content=context)],
            system_prompt=self.SYNTHESIS_SYSTEM,
            temperature=0.5, max_tokens=4000,
        )
        return resp.content
