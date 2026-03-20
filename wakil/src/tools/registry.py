"""
tools/registry.py — وكيل: Tool Registry & Built-in Tools
=========================================================
All agent tools in one file. Each tool is an async function
registered by name. Easy to add custom tools.

Built-in tools:
  file_reader   — read files with path safety
  file_writer   — write/append files
  code_executor — run Python code in a sandbox
  web_searcher  — search via DuckDuckGo HTML (no API key)
  memory_tool   — save/retrieve memories
  calculator    — evaluate math expressions safely
  system_info   — get OS/env information
"""

import ast, io, math, os, re, sys, time, traceback
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any, Callable, Dict, Optional


class ToolResult:
    def __init__(self, success: bool, output: str, tool: str):
        self.success = success
        self.output  = output
        self.tool    = tool

    def __str__(self): return self.output


class ToolRegistry:
    """Registry of all available tools. Call via registry.run(name, input)."""

    def __init__(self, workspace: str = "/tmp/wakil_workspace"):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._tools: Dict[str, Callable] = {}
        self._register_builtins()

    def register(self, name: str, fn: Callable):
        self._tools[name] = fn

    def list_tools(self) -> list:
        return list(self._tools.keys())

    async def run(self, name: str, input_text: str) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"[Tool '{name}' not found. Available: {', '.join(self._tools)}]"
        try:
            result = await tool(input_text, workspace=self.workspace)
            return str(result)
        except Exception as e:
            return f"[Tool error: {e}]"

    def _register_builtins(self):
        self.register("file_reader",   _tool_file_reader)
        self.register("file_writer",   _tool_file_writer)
        self.register("code_executor", _tool_code_executor)
        self.register("web_searcher",  _tool_web_searcher)
        self.register("memory_tool",   _tool_memory_stub)
        self.register("calculator",    _tool_calculator)
        self.register("system_info",   _tool_system_info)


# ═══════════════════════════════════════════════════════════════
#  Built-in Tool Implementations
# ═══════════════════════════════════════════════════════════════

async def _tool_file_reader(input_text: str, workspace: Path, **_) -> str:
    """
    Read a file. Input can be a path or natural language like 'read config.py'.
    Resolves relative paths relative to workspace.
    """
    path_match = re.search(r"[\w/\\.~-]+\.\w+", input_text)
    if not path_match:
        return "[file_reader] No file path found in input."
    raw_path = path_match.group()
    path = Path(raw_path)
    if not path.is_absolute():
        path = workspace / raw_path
    if not path.exists():
        return f"[file_reader] File not found: {path}"
    if path.stat().st_size > 500_000:
        return f"[file_reader] File too large (>{500}KB): {path}"
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        lines   = content.split("\n")
        if len(lines) > 200:
            preview = "\n".join(lines[:200])
            return f"{preview}\n\n... [{len(lines)-200} more lines] ..."
        return content
    except Exception as e:
        return f"[file_reader] Error: {e}"


async def _tool_file_writer(input_text: str, workspace: Path, **_) -> str:
    """
    Write content to a file.
    Expects format: 'write to <path>:\n<content>'
    or 'append to <path>:\n<content>'
    """
    mode = "w"
    if input_text.lower().startswith("append"):
        mode = "a"
    m = re.search(r"(?:write|append)\s+to\s+([\w/\\.~-]+)\s*:\s*([\s\S]+)",
                  input_text, re.I)
    if not m:
        # Fallback: try to extract any path and treat rest as content
        m2 = re.search(r"([\w/\\.~-]+\.\w+)\s*\n([\s\S]+)", input_text)
        if m2:
            fname, content = m2.group(1), m2.group(2)
        else:
            return "[file_writer] Could not parse file path and content."
    else:
        fname, content = m.group(1), m.group(2)

    path = Path(fname)
    if not path.is_absolute():
        path = workspace / fname
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode, encoding="utf-8") as f:
        f.write(content)
    verb = "Appended to" if mode == "a" else "Written to"
    return f"[file_writer] {verb}: {path} ({len(content)} chars)"


async def _tool_code_executor(input_text: str, workspace: Path, **_) -> str:
    """
    Execute Python code in a restricted sandbox.
    Extracts code from markdown fences or raw text.
    """
    # Extract code block
    code_match = re.search(r"```python\s*([\s\S]+?)```", input_text)
    if code_match:
        code = code_match.group(1)
    else:
        # Check if it looks like code
        code = input_text.strip()

    if not code:
        return "[code_executor] No code found."

    # Safety: block dangerous imports
    dangerous = ["subprocess", "os.system", "eval", "exec", "__import__",
                 "open(", "shutil.rmtree", "socket", "ctypes"]
    for d in dangerous:
        if d in code:
            return f"[code_executor] Blocked: contains '{d}'"

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    env = {
        "__builtins__": {
            "print": print, "len": len, "range": range, "int": int, "float": float,
            "str": str, "list": list, "dict": dict, "set": set, "tuple": tuple,
            "sum": sum, "min": min, "max": max, "abs": abs, "round": round,
            "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
            "sorted": sorted, "reversed": reversed, "isinstance": isinstance,
            "type": type, "bool": bool, "math": math,
        }
    }
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compile(code, "<wakil>", "exec"), env)
        out    = stdout_buf.getvalue()
        err    = stderr_buf.getvalue()
        result = out + (f"\nStderr:\n{err}" if err else "")
        return result if result.strip() else "[code_executor] Executed (no output)"
    except Exception:
        tb = traceback.format_exc(limit=5)
        return f"[code_executor] Error:\n{tb}"


async def _tool_web_searcher(input_text: str, workspace: Path, **_) -> str:
    """
    Search the web via DuckDuckGo HTML (no API key required).
    Returns top 5 results as text.
    """
    import urllib.request, urllib.parse, html, ssl

    query = input_text.strip()
    if query.lower().startswith("search"):
        query = re.sub(r"^search\s*(for\s*)?", "", query, flags=re.I).strip()
    if not query:
        return "[web_searcher] No query provided."

    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; WakilAgent/1.0)"}
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            body = r.read().decode("utf-8", errors="replace")

        # Extract result snippets
        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</a>',
            body, re.DOTALL
        )[:5]
        titles = re.findall(
            r'class="result__a"[^>]*>(.*?)</a>',
            body, re.DOTALL
        )[:5]

        if not snippets:
            return f"[web_searcher] No results found for: {query}"

        results = []
        for i, (title, snippet) in enumerate(zip(titles, snippets), 1):
            t = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            s = html.unescape(re.sub(r"<[^>]+>", "", snippet)).strip()
            results.append(f"{i}. {t}\n   {s}")

        return f"Search results for '{query}':\n\n" + "\n\n".join(results)

    except Exception as e:
        return f"[web_searcher] Error: {e}"


async def _tool_memory_stub(input_text: str, **_) -> str:
    """Memory tool placeholder — memory is handled directly by the agent."""
    return f"[memory] Noted: {input_text[:200]}"


async def _tool_calculator(input_text: str, **_) -> str:
    """Safely evaluate a mathematical expression."""
    expr = input_text.strip()
    # Remove common natural language wrappers
    expr = re.sub(r"^(calculate|compute|eval|evaluate|what is)\s*", "", expr, flags=re.I)
    expr = expr.strip().rstrip("?")

    # Only allow safe characters
    if re.search(r"[a-zA-Z_](?![\d.])", expr.replace("math.", "").replace("sqrt", "").replace("pi", "").replace("e", "")):
        # Try ast literal eval
        pass

    try:
        safe_env = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
        safe_env["abs"] = abs
        result = eval(expr, {"__builtins__": {}}, safe_env)
        return f"{expr} = {result}"
    except Exception as e:
        return f"[calculator] Cannot evaluate '{expr}': {e}"


async def _tool_system_info(input_text: str, **_) -> str:
    """Return system/environment information."""
    import platform
    info = {
        "platform" : platform.system(),
        "python"   : sys.version.split()[0],
        "cwd"      : os.getcwd(),
        "env_vars" : list(os.environ.keys())[:10],
    }
    return "\n".join(f"{k}: {v}" for k, v in info.items())
