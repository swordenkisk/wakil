"""
agent.py — وكيل: Main Agent Orchestrator
==========================================
Top-level agent that combines Planning + Execution + Memory.
Exposes a clean async interface for the web layer.
"""

import asyncio, json, time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from .planner  import Planner, Plan
from .executor import Executor, ExecutionResult
from ..memory.store    import MemoryStore
from ..tools.registry  import ToolRegistry
from ..providers.base  import BaseLLMProvider


@dataclass
class WakilConfig:
    """Runtime configuration for a Wakil agent session."""
    workspace        : str   = "/tmp/wakil_workspace"
    memory_path      : str   = "memories/default"
    auto_approve     : bool  = True    # False = pause for human on flagged steps
    max_steps        : int   = 12
    context_offload  : bool  = True    # move large results to files
    session_id       : str   = ""      # for checkpointing
    language         : str   = "auto"  # auto|arabic|english


class WakilAgent:
    """
    Wakil — وكيل ذكي

    The main entry point. Usage:
        agent = WakilAgent(provider, config)
        async for event in agent.run("بناء API Flask لإدارة المهام"):
            print(event)
    """

    def __init__(self, provider: BaseLLMProvider,
                 config: Optional[WakilConfig] = None):
        self.provider = provider
        self.config   = config or WakilConfig()
        self.memory   = MemoryStore(self.config.memory_path)
        self.tools    = ToolRegistry(self.config.workspace)
        self.planner  = Planner(provider)
        self.executor = Executor(provider, self.tools, self.memory,
                                 self.config.workspace)
        if not self.config.auto_approve:
            self.executor.set_approval_callback(self._approval_gate)
        self._pending_approvals: dict = {}

    async def run(self, task: str) -> AsyncIterator[dict]:
        """
        Full agent pipeline: plan → execute → synthesise.

        Yields SSE-compatible event dicts throughout.
        """
        t0 = time.monotonic()

        # ── Load relevant memories ────────────────────────────
        yield {"event": "loading_memories"}
        memories = await self.memory.search(task, top_k=5)
        mem_text = "\n".join(f"- {m['content'][:200]}" for m in memories) if memories else ""

        # ── Planning phase ────────────────────────────────────
        yield {"event": "planning", "task": task}
        plan = await self.planner.plan(task, context=mem_text)
        yield {"event": "plan_ready", "plan": plan.to_dict()}

        # ── Execution phase ───────────────────────────────────
        async for event in self.executor.execute(plan):
            yield event

        # ── Save session to memory ────────────────────────────
        await self.memory.save(
            key=f"session_{int(time.time())}",
            content=f"Task: {task}\nPlan complexity: {plan.complexity}\n"
                    f"Steps: {len(plan.steps)} | Status: completed",
            tags=["session", "completed"],
        )

        total_ms = int((time.monotonic() - t0) * 1000)
        yield {"event": "session_saved", "total_ms": total_ms}

    async def run_task(self, task: str) -> ExecutionResult:
        """Blocking version — runs full pipeline and returns result."""
        result = None
        async for event in self.run(task):
            if event.get("event") == "done":
                # Reconstruct minimal ExecutionResult
                plan = Plan(task=task)
                result = ExecutionResult(
                    plan=plan,
                    synthesis=event["result"].get("synthesis", ""),
                    total_ms=event["result"].get("total_ms", 0),
                )
        return result

    async def chat(self, message: str, history: list = None) -> AsyncIterator[dict]:
        """
        Conversational mode — for simple questions that don't need a plan.
        Falls back to full planning for complex tasks.
        """
        from ..providers.base import ChatMessage
        complexity_check = await self._check_complexity(message)
        if complexity_check == "simple":
            # Direct answer without planning
            yield {"event": "thinking"}
            memories = await self.memory.search(message, top_k=3)
            mem_ctx = "\n".join(f"- {m['content'][:150]}" for m in memories)
            sys = "You are Wakil (وكيل), a helpful AI assistant. Answer directly and clearly."
            if mem_ctx:
                sys += f"\n\nUser memories:\n{mem_ctx}"
            messages = [ChatMessage(role="user", content=message)]
            if history:
                messages = [ChatMessage(**m) for m in history[-6:]] + messages
            resp = await self.provider.chat(messages, system_prompt=sys, temperature=0.6)
            yield {"event": "answer", "text": resp.content}
        else:
            # Complex task → full planning pipeline
            async for event in self.run(message):
                yield event

    async def _check_complexity(self, task: str) -> str:
        """Quickly determine if a task needs planning or direct answering."""
        from ..providers.base import ChatMessage
        resp = await self.provider.chat(
            [ChatMessage(role="user", content=f"Is this task simple (single answer) or complex (multiple steps)? Reply ONE word: simple|complex\n\nTask: {task}")],
            temperature=0, max_tokens=5,
        )
        return "simple" if "simple" in resp.content.lower() else "complex"

    async def _approval_gate(self, step) -> bool:
        """Called when a step requires human approval. Returns True=proceed."""
        step_id = step.id
        self._pending_approvals[step_id] = asyncio.Event()
        await self._pending_approvals[step_id].wait()
        approved = self._pending_approvals.pop(step_id, True)
        return approved if isinstance(approved, bool) else True

    def approve_step(self, step_id: int, approved: bool = True):
        """External call to approve or reject a pending step."""
        evt = self._pending_approvals.get(step_id)
        if evt:
            self._pending_approvals[step_id] = approved
            evt.set()

    async def get_memories(self) -> list:
        return await self.memory.list_all()

    async def clear_memories(self):
        await self.memory.clear()
