"""
providers/base.py — وكيل: Multi-Provider LLM Interface
========================================================
Supports: Anthropic, OpenAI, DeepSeek, Qwen, Gemini, Ollama, Mock
All via Python stdlib (urllib) — zero extra dependencies.
"""

import json, ssl, urllib.request, urllib.error
from abc import ABC, abstractmethod
from asyncio import get_event_loop
from dataclasses import dataclass
from functools import partial
from typing import AsyncIterator, List


@dataclass
class ChatMessage:
    role   : str
    content: str
    def to_dict(self): return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    content      : str
    model        : str  = ""
    input_tokens : int  = 0
    output_tokens: int  = 0
    provider     : str  = ""


class BaseLLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages: List[ChatMessage], system_prompt="",
                   temperature=0.7, max_tokens=4096) -> LLMResponse: ...
    @abstractmethod
    async def stream(self, messages: List[ChatMessage], system_prompt="",
                     temperature=0.7, max_tokens=4096) -> AsyncIterator[str]: ...

    def _run(self, fn, *a, **k):
        return get_event_loop().run_in_executor(None, partial(fn, *a, **k))

    @staticmethod
    def _post(url, headers, body, timeout=120):
        data = json.dumps(body).encode()
        req  = urllib.request.Request(url, data=data, headers=headers, method="POST")
        ctx  = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode())

    @staticmethod
    def _stream_post(url, headers, body, timeout=180):
        data = json.dumps(body).encode()
        req  = urllib.request.Request(url, data=data, headers=headers, method="POST")
        ctx  = ssl.create_default_context()
        chunks = []
        resp   = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        buf    = b""
        while True:
            part = resp.read(512)
            if not part: break
            buf += part
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.decode("utf-8", errors="replace").strip()
                if line.startswith("data: "):
                    chunks.append(line[6:])
        resp.close()
        return chunks


class AnthropicProvider(BaseLLMProvider):
    API = "https://api.anthropic.com/v1/messages"
    VER = "2023-06-01"
    def __init__(self, api_key, model="claude-sonnet-4-6"):
        self.key = api_key; self.model = model
    def _h(self):
        return {"x-api-key": self.key, "anthropic-version": self.VER,
                "content-type": "application/json"}
    def _b(self, msgs, sys, t, max_t, stream=False):
        b = {"model": self.model, "max_tokens": max_t, "messages": [m.to_dict() for m in msgs],
             "temperature": t, "stream": stream}
        if sys: b["system"] = sys
        return b
    def _sync_chat(self, msgs, sys, t, max_t):
        d = self._post(self.API, self._h(), self._b(msgs, sys, t, max_t))
        text = "".join(b.get("text","") for b in d.get("content",[]) if b.get("type")=="text")
        u = d.get("usage",{})
        return LLMResponse(content=text, model=self.model, provider="anthropic",
                           input_tokens=u.get("input_tokens",0), output_tokens=u.get("output_tokens",0))
    async def chat(self, msgs, system_prompt="", temperature=0.7, max_tokens=4096):
        return await self._run(self._sync_chat, msgs, system_prompt, temperature, max_tokens)
    def _sync_stream(self, msgs, sys, t, max_t):
        raw = self._stream_post(self.API, self._h(), self._b(msgs, sys, t, max_t, True))
        out = []
        for p in raw:
            if p == "[DONE]": continue
            try:
                ev = json.loads(p)
                if ev.get("type") == "content_block_delta":
                    d = ev.get("delta",{})
                    if d.get("type") == "text_delta": out.append(d.get("text",""))
            except: pass
        return out
    async def stream(self, msgs, system_prompt="", temperature=0.7, max_tokens=4096):
        chunks = await self._run(self._sync_stream, msgs, system_prompt, temperature, max_tokens)
        for c in chunks: yield c


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, api_key, model="gpt-4o", base_url="https://api.openai.com"):
        self.key = api_key; self.model = model; self.base = base_url.rstrip("/")
    def _h(self): return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
    def _msgs(self, msgs, sys):
        m = []
        if sys: m.append({"role":"system","content":sys})
        m.extend(x.to_dict() for x in msgs)
        return m
    def _sync_chat(self, msgs, sys, t, max_t):
        d = self._post(f"{self.base}/v1/chat/completions", self._h(),
                       {"model":self.model,"messages":self._msgs(msgs,sys),"temperature":t,"max_tokens":max_t})
        text = d["choices"][0]["message"]["content"]
        u = d.get("usage",{})
        return LLMResponse(content=text, model=self.model, provider="openai",
                           input_tokens=u.get("prompt_tokens",0), output_tokens=u.get("completion_tokens",0))
    async def chat(self, msgs, system_prompt="", temperature=0.7, max_tokens=4096):
        return await self._run(self._sync_chat, msgs, system_prompt, temperature, max_tokens)
    def _sync_stream(self, msgs, sys, t, max_t):
        raw = self._stream_post(f"{self.base}/v1/chat/completions", self._h(),
                                {"model":self.model,"messages":self._msgs(msgs,sys),
                                 "temperature":t,"max_tokens":max_t,"stream":True})
        out = []
        for p in raw:
            if p=="[DONE]": continue
            try:
                ev = json.loads(p)
                d = ev["choices"][0].get("delta",{})
                if d.get("content"): out.append(d["content"])
            except: pass
        return out
    async def stream(self, msgs, system_prompt="", temperature=0.7, max_tokens=4096):
        chunks = await self._run(self._sync_stream, msgs, system_prompt, temperature, max_tokens)
        for c in chunks: yield c


class MockProvider(BaseLLMProvider):
    """Deterministic mock for testing."""
    def __init__(self, resp="Mock response from Wakil agent."):
        self._resp = resp
    async def chat(self, msgs, system_prompt="", temperature=0.7, max_tokens=4096):
        q = msgs[-1].content if msgs else ""
        # Return valid JSON plan for planning requests
        if "planning" in system_prompt.lower() or "TODO" in system_prompt or "steps" in system_prompt.lower():
            content = json.dumps({
                "analysis": f"Analysing: {q[:80]}",
                "complexity": "medium",
                "steps": [
                    {"id":1,"title":"Research","description":f"Gather information about: {q[:50]}","tool_hint":"web_search","requires_approval":False,"sub_agent":False},
                    {"id":2,"title":"Plan","description":"Design solution structure","tool_hint":"none","requires_approval":False,"sub_agent":False},
                    {"id":3,"title":"Execute","description":"Implement the solution","tool_hint":"code_exec","requires_approval":True,"sub_agent":False},
                    {"id":4,"title":"Verify","description":"Test and validate output","tool_hint":"none","requires_approval":False,"sub_agent":False},
                ]
            })
        elif "simple" in system_prompt.lower() or "complex" in system_prompt.lower():
            content = "complex"
        else:
            content = f"{self._resp}\n\nProcessed: {q[:60]}"
        return LLMResponse(content=content, model="mock", provider="mock",
                           input_tokens=len(q)//4, output_tokens=50)
    async def stream(self, msgs, system_prompt="", temperature=0.7, max_tokens=4096):
        r = await self.chat(msgs, system_prompt)
        for w in r.content.split(): yield w + " "


def create_provider(ptype, api_key="", model="", base_url="") -> BaseLLMProvider:
    t = ptype.lower()
    if t in ("anthropic","claude"):
        return AnthropicProvider(api_key, model or "claude-sonnet-4-6")
    if t in ("openai","gpt"):
        return OpenAIProvider(api_key, model or "gpt-4o")
    if t == "deepseek":
        return OpenAIProvider(api_key, model or "deepseek-reasoner",
                              base_url or "https://api.deepseek.com")
    if t in ("qwen","tongyi"):
        return OpenAIProvider(api_key, model or "qwen-max",
                              base_url or "https://dashscope.aliyuncs.com/compatible-mode")
    if t == "gemini":
        return OpenAIProvider(api_key, model or "gemini-1.5-pro",
                              base_url or "https://generativelanguage.googleapis.com/v1beta/openai")
    if t in ("ollama","local"):
        return OpenAIProvider(api_key or "ollama", model or "llama3",
                              base_url or "http://localhost:11434")
    if t in ("mock","test"):
        return MockProvider()
    raise ValueError(f"Unknown provider: {ptype}")

PROVIDERS = {
    "anthropic": {"name":"Anthropic Claude","models":["claude-opus-4-6","claude-sonnet-4-6","claude-haiku-4-5-20251001"],"default":"claude-sonnet-4-6"},
    "openai"   : {"name":"OpenAI","models":["gpt-4o","gpt-4o-mini","o1","o3-mini"],"default":"gpt-4o"},
    "deepseek" : {"name":"DeepSeek","models":["deepseek-reasoner","deepseek-chat"],"default":"deepseek-reasoner"},
    "qwen"     : {"name":"Qwen / Tongyi","models":["qwen-max","qwen-turbo","qwen-plus"],"default":"qwen-max"},
    "gemini"   : {"name":"Google Gemini","models":["gemini-2.0-flash","gemini-1.5-pro"],"default":"gemini-2.0-flash"},
    "ollama"   : {"name":"Ollama (Local)","models":["llama3","mistral","codestral","phi3"],"default":"llama3"},
}
