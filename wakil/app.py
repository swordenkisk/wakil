"""
app.py — وكيل: Wakil Agent Web Application
==========================================
Full-featured AI agent web interface.

Routes:
  GET  /                → Main agent UI
  POST /api/run         → Run agent task (full pipeline)
  GET  /api/stream      → SSE streaming execution
  POST /api/chat        → Simple chat mode
  POST /api/approve     → Approve/reject a pending step
  GET  /api/memories    → List all memories
  POST /api/memories    → Save a memory
  DELETE /api/memories  → Clear all memories
  GET  /api/tools       → List available tools
  GET  /api/providers   → List supported LLM providers
  POST /api/run_tool    → Run a single tool directly
  GET  /health          → Health check

Author: github.com/swordenkisk/wakil
"""

import asyncio, json, os, time
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from src.core.agent    import WakilAgent, WakilConfig
from src.providers.base import create_provider, PROVIDERS, MockProvider
from src.memory.store   import MemoryStore
from src.tools.registry import ToolRegistry

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "wakil-dev-2026")

_loop    = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

def _run(coro): return _loop.run_until_complete(coro)

def _build_agent(data: dict) -> WakilAgent:
    ptype    = data.get("provider",  "mock")
    api_key  = data.get("api_key",   "")
    model    = data.get("model",     "")
    base_url = data.get("base_url",  "")
    provider = create_provider(ptype, api_key, model, base_url)
    config   = WakilConfig(
        workspace     = data.get("workspace",    "/tmp/wakil_workspace"),
        memory_path   = data.get("memory_path",  "memories/default"),
        auto_approve  = data.get("auto_approve", True),
        session_id    = data.get("session_id",   ""),
    )
    return WakilAgent(provider, config)


# ── Pages ────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html",
                           providers=PROVIDERS,
                           tools=ToolRegistry().list_tools())

# ── SSE streaming run ────────────────────────────────────────
@app.route("/api/stream")
def api_stream():
    task = request.args.get("task", "").strip()
    if not task:
        def err():
            yield f"data: {json.dumps({'event':'error','message':'No task provided'})}\n\n"
        return Response(stream_with_context(err()), mimetype="text/event-stream")

    config = {
        "provider"    : request.args.get("provider",     "mock"),
        "api_key"     : request.args.get("api_key",      ""),
        "model"       : request.args.get("model",        ""),
        "auto_approve": request.args.get("auto_approve", "true") == "true",
        "memory_path" : request.args.get("memory_path",  "memories/default"),
    }
    agent = _build_agent(config)

    def generate():
        async def run():
            async for ev in agent.run(task):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        g = run()
        while True:
            try:
                chunk = _loop.run_until_complete(g.__anext__())
                yield chunk
            except StopAsyncIteration:
                break
            except Exception as e:
                yield f"data: {json.dumps({'event':'error','message':str(e)})}\n\n"
                break

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── Chat mode ────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(silent=True) or {}
    msg  = data.get("message", "").strip()
    if not msg:
        return jsonify({"error": "No message"}), 400
    agent = _build_agent(data)
    events = _run(_collect_events(agent.chat(msg, data.get("history", []))))
    answer = next((e.get("text","") for e in events if e.get("event") in ("answer","synthesis")), "")
    plan   = next((e.get("plan",{}) for e in events if e.get("event")=="plan_ready"), None)
    return jsonify({"answer": answer, "plan": plan, "events": events})

async def _collect_events(gen):
    events = []
    async for ev in gen:
        events.append(ev)
    return events

# ── Direct run (non-streaming) ────────────────────────────────
@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(silent=True) or {}
    task = data.get("task", "").strip()
    if not task:
        return jsonify({"error": "No task"}), 400
    agent  = _build_agent(data)
    events = _run(_collect_events(agent.run(task)))
    done   = next((e for e in events if e.get("event")=="done"), {})
    return jsonify({"result": done.get("result",{}), "events": events})

# ── Approval ─────────────────────────────────────────────────
@app.route("/api/approve", methods=["POST"])
def api_approve():
    data    = request.get_json(silent=True) or {}
    step_id = int(data.get("step_id", 0))
    approved= bool(data.get("approved", True))
    # In a real session we'd look up the agent by session_id
    # For now return ack
    return jsonify({"step_id": step_id, "approved": approved, "status": "ok"})

# ── Memories ─────────────────────────────────────────────────
@app.route("/api/memories", methods=["GET"])
def api_memories_get():
    path  = request.args.get("path", "memories/default")
    store = MemoryStore(path)
    mems  = _run(store.list_all())
    stats = _run(store.summary_stats())
    return jsonify({"memories": mems, "stats": stats})

@app.route("/api/memories", methods=["POST"])
def api_memories_save():
    data  = request.get_json(silent=True) or {}
    path  = data.get("path", "memories/default")
    store = MemoryStore(path)
    _run(store.save(data.get("key","manual"), data.get("content",""),
                    data.get("tags",["manual"])))
    return jsonify({"status": "saved"})

@app.route("/api/memories", methods=["DELETE"])
def api_memories_clear():
    path  = request.args.get("path", "memories/default")
    store = MemoryStore(path)
    _run(store.clear())
    return jsonify({"status": "cleared"})

# ── Tools ─────────────────────────────────────────────────────
@app.route("/api/tools")
def api_tools():
    registry = ToolRegistry()
    return jsonify({"tools": registry.list_tools()})

@app.route("/api/run_tool", methods=["POST"])
def api_run_tool():
    data   = request.get_json(silent=True) or {}
    tool   = data.get("tool", "")
    inp    = data.get("input", "")
    workspace = data.get("workspace", "/tmp/wakil_workspace")
    registry  = ToolRegistry(workspace)
    result    = _run(registry.run(tool, inp))
    return jsonify({"tool": tool, "output": result})

# ── Providers ────────────────────────────────────────────────
@app.route("/api/providers")
def api_providers():
    return jsonify(PROVIDERS)

@app.route("/api/validate_key", methods=["POST"])
def api_validate():
    data = request.get_json(silent=True) or {}
    try:
        from src.providers.base import ChatMessage
        p = create_provider(data.get("provider","mock"), data.get("api_key",""),
                            data.get("model",""), data.get("base_url",""))
        r = _run(p.chat([ChatMessage(role="user",content="Reply: OK")], max_tokens=5, temperature=0))
        return jsonify({"valid": True, "model": r.model, "preview": r.content[:20]})
    except Exception as e:
        return jsonify({"valid": False, "error": str(e)})

@app.route("/health")
def health():
    return jsonify({"status": "ok", "app": "Wakil", "version": "2.0.0",
                    "tools": ToolRegistry().list_tools()})

if __name__ == "__main__":
    host  = os.environ.get("HOST", "127.0.0.1")
    port  = int(os.environ.get("PORT", 7072))
    debug = os.environ.get("DEBUG","false").lower()=="true"
    print(f"\n{'='*52}\n  وكيل — Wakil AI Agent v2.0\n  http://{host}:{port}\n{'='*52}\n")
    app.run(host=host, port=port, debug=debug, threaded=True)
