"""
planner.py — وكيل: التخطيط السيادي (Planning First Engine)
===========================================================
Before executing ANY tool, Wakil generates a structured TODO plan.
This prevents random tool-calling and ensures strategic thinking.

Author: github.com/swordenkisk/wakil
"""

import json, re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PlanStep:
    id               : int
    title            : str
    description      : str
    tool_hint        : str  = "none"
    requires_approval: bool = False
    sub_agent        : bool = False
    status           : str  = "pending"   # pending|running|done|failed|skipped
    result           : str  = ""

    def to_dict(self): return self.__dict__.copy()


@dataclass
class Plan:
    task     : str
    steps    : List[PlanStep] = field(default_factory=list)
    analysis : str = ""
    complexity: str = "simple"

    @property
    def done_steps(self):  return [s for s in self.steps if s.status == "done"]
    @property
    def progress_pct(self):
        return int(100 * len(self.done_steps) / len(self.steps)) if self.steps else 0
    def next_step(self) -> Optional[PlanStep]:
        return next((s for s in self.steps if s.status == "pending"), None)
    def to_dict(self):
        return {"task": self.task, "analysis": self.analysis,
                "complexity": self.complexity,
                "steps": [s.to_dict() for s in self.steps],
                "progress": self.progress_pct}


class Planner:
    SYSTEM = """You are a strategic planning agent. Analyse the task then produce a JSON plan.

Output ONLY valid JSON — no markdown fences, no preamble:
{
  "analysis": "2-sentence problem analysis",
  "complexity": "simple|medium|complex",
  "steps": [
    {
      "id": 1,
      "title": "short title",
      "description": "specific action",
      "tool_hint": "file_read|file_write|code_exec|web_search|memory|sub_agent|none",
      "requires_approval": false,
      "sub_agent": false
    }
  ]
}

Rules:
- 2-4 steps for simple, 5-8 for medium, 8-12 for complex tasks
- requires_approval=true for: file deletion, running code, external API calls
- sub_agent=true when step is itself a multi-step research or coding task
- Each step must be independently verifiable"""

    def __init__(self, provider):
        self.provider = provider

    async def plan(self, task: str, context: str = "") -> Plan:
        from ..providers.base import ChatMessage
        msg = f"Task: {task}" + (f"\n\nContext:\n{context}" if context else "")
        resp = await self.provider.chat(
            [ChatMessage(role="user", content=msg)],
            system_prompt=self.SYSTEM, temperature=0.2, max_tokens=2000,
        )
        return self._parse(task, resp.content)

    def _parse(self, task: str, raw: str) -> Plan:
        raw = re.sub(r"```json\s*|```", "", raw).strip()
        try:
            data = json.loads(raw)
        except Exception:
            m = re.search(r"\{[\s\S]+\}", raw)
            data = json.loads(m.group()) if m else {}

        plan = Plan(task=task,
                    analysis=data.get("analysis", ""),
                    complexity=data.get("complexity", "simple"))
        for i, s in enumerate(data.get("steps", []), 1):
            plan.steps.append(PlanStep(
                id=s.get("id", i), title=s.get("title", f"Step {i}"),
                description=s.get("description", ""),
                tool_hint=s.get("tool_hint", "none"),
                requires_approval=s.get("requires_approval", False),
                sub_agent=s.get("sub_agent", False),
            ))
        if not plan.steps:
            plan.steps = [PlanStep(id=1, title="Execute", description=task)]
        return plan
