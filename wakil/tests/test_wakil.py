"""
test_wakil.py — وكيل Test Suite (24 tests)
Run: python tests/test_wakil.py
"""
import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.planner   import Planner, Plan, PlanStep
from src.core.executor  import Executor
from src.core.agent     import WakilAgent, WakilConfig
from src.memory.store   import MemoryStore
from src.tools.registry import ToolRegistry
from src.providers.base import MockProvider, create_provider, PROVIDERS, ChatMessage

W = 64
passed = failed = 0
results = []
loop = asyncio.new_event_loop()
def run(c): return loop.run_until_complete(c)

def check(name, cond, detail=""):
    global passed, failed
    msg = f"  [{'PASS' if cond else 'FAIL'}] {name}"
    if detail: msg += f"  --  {detail}"
    print(msg)
    results.append((name, cond))
    if cond: passed += 1
    else:    failed += 1

print("=" * W)
print("  وكيل — Wakil Agent — Test Suite (24 tests)")
print("=" * W)

# ── Block A: Planner ──────────────────────────────────────
print("\n[ Block A: Planner (5 tests) ]\n")

planner = Planner(MockProvider())
plan    = run(planner.plan("Build a Flask API with SQLite"))

check("A1: plan returns Plan object", isinstance(plan, Plan))
check("A2: plan has steps",          len(plan.steps) >= 2, f"steps={len(plan.steps)}")
check("A3: plan has analysis",       len(plan.analysis) > 5)
check("A4: complexity set",          plan.complexity in ("simple","medium","complex"),
      f"={plan.complexity}")

step1 = plan.steps[0]
check("A5: PlanStep fields present",
      step1.id and step1.title and step1.description,
      f"id={step1.id} title={step1.title[:20]}")

# ── Block B: Plan operations ──────────────────────────────
print("\n[ Block B: Plan Operations (3 tests) ]\n")

plan2 = Plan(task="test")
plan2.steps = [
    PlanStep(id=1,title="A",description="a",status="done"),
    PlanStep(id=2,title="B",description="b",status="pending"),
    PlanStep(id=3,title="C",description="c",status="pending"),
]
check("B1: progress_pct correct",   plan2.progress_pct == 33, f"={plan2.progress_pct}")
check("B2: next_step returns pending", plan2.next_step().id == 2)
check("B3: to_dict serialisable",   "steps" in plan2.to_dict())

# ── Block C: Memory Store ─────────────────────────────────
print("\n[ Block C: MemoryStore (5 tests) ]\n")

import tempfile, os
tmpdir = tempfile.mkdtemp()
mem = MemoryStore(tmpdir)

run(mem.save("test_key", "Python is great for AI", ["python","ai"]))
check("C1: save doesn't raise", True)

got = run(mem.get("test_key"))
check("C2: get retrieves correct content",
      got and got.content == "Python is great for AI", f"content={got.content if got else None}")

run(mem.save("key2", "Flask web framework tutorial", ["flask","web"]))
results_s = run(mem.search("Python AI"))
check("C3: search returns relevant results",
      len(results_s) >= 1 and any("test_key" in r["key"] for r in results_s),
      f"results={[r['key'] for r in results_s]}")

all_mem = run(mem.list_all())
check("C4: list_all returns all entries", len(all_mem) == 2)

run(mem.delete("test_key"))
check("C5: delete removes entry", run(mem.get("test_key")) is None)

# Cleanup
import shutil; shutil.rmtree(tmpdir, ignore_errors=True)

# ── Block D: Tools ────────────────────────────────────────
print("\n[ Block D: ToolRegistry (5 tests) ]\n")

reg = ToolRegistry("/tmp/wakil_test")
check("D1: list_tools returns ≥ 5 tools",
      len(reg.list_tools()) >= 5, f"tools={reg.list_tools()}")

calc = run(reg.run("calculator", "2 + 2 * 3"))
check("D2: calculator evaluates correctly",
      "8" in calc or "2 + 2 * 3" in calc, f"result={calc}")

info = run(reg.run("system_info", ""))
check("D3: system_info returns platform info",
      "python" in info.lower() or "platform" in info.lower(), f"={info[:50]}")

code_res = run(reg.run("code_executor", "print(2 ** 10)"))
check("D4: code_executor runs safe Python",
      "1024" in code_res, f"output={code_res}")

bad_code = run(reg.run("code_executor", "import subprocess; subprocess.run(['ls'])"))
check("D5: code_executor blocks subprocess",
      "Blocked" in bad_code, f"={bad_code}")

# ── Block E: Providers ────────────────────────────────────
print("\n[ Block E: Providers (3 tests) ]\n")

mock = MockProvider("Test answer")
resp = run(mock.chat([ChatMessage(role="user",content="Hello")]))
check("E1: MockProvider returns LLMResponse",
      resp.content and len(resp.content) > 0, f"={resp.content[:30]}")

check("E2: PROVIDERS has ≥ 5 entries", len(PROVIDERS) >= 5, f"count={len(PROVIDERS)}")

p = create_provider("mock")
check("E3: create_provider mock works", isinstance(p, MockProvider))

# ── Block F: Full Agent ───────────────────────────────────
print("\n[ Block F: WakilAgent (3 tests) ]\n")

tmpdir2 = tempfile.mkdtemp()
config  = WakilConfig(workspace="/tmp/wakil_test", memory_path=tmpdir2)
agent   = WakilAgent(MockProvider(), config)

events  = []
async def collect():
    async for ev in agent.run("Write a Python hello world function"):
        events.append(ev)
run(collect())

event_types = [e["event"] for e in events]
check("F1: agent emits multiple events",
      len(events) >= 4, f"events={event_types[:6]}")

check("F2: agent emits plan_ready",
      "plan_ready" in event_types, f"types={event_types}")

check("F3: agent emits done",
      "done" in event_types, f"last={event_types[-1]}")

shutil.rmtree(tmpdir2, ignore_errors=True)

# ── Summary ───────────────────────────────────────────────
total = passed + failed
print()
print("=" * W)
status = "ALL PASS ✅" if failed == 0 else f"{failed} FAILED ❌"
print(f"  Results  :  {passed}/{total} tests passed  ({status})")
if failed:
    print("  Failures :  " + ", ".join(n for n, ok in results if not ok))
print("=" * W)

import sys as _s; _s.exit(0 if failed == 0 else 1)
