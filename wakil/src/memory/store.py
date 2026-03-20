"""
memory/store.py — وكيل: Persistent Memory Store
=================================================
Agent memory with semantic search, tagging, and session persistence.
Stored in /memories/ as JSON files — no external DB required.
"""

import json, os, time, re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Memory:
    key       : str
    content   : str
    tags      : List[str] = field(default_factory=list)
    created_at: float     = field(default_factory=time.time)
    updated_at: float     = field(default_factory=time.time)
    access_count: int     = 0

    def to_dict(self): return self.__dict__.copy()

    @staticmethod
    def from_dict(d: dict) -> "Memory":
        return Memory(
            key=d["key"], content=d["content"],
            tags=d.get("tags", []),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
            access_count=d.get("access_count", 0),
        )


class MemoryStore:
    """
    File-based persistent memory store.

    Features:
    - Keyword-based semantic search
    - Tag filtering
    - Auto-consolidation (merge related memories)
    - Session summaries
    """

    def __init__(self, path: str = "memories/default"):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._index_file = self.path / "_index.json"
        self._memories: dict = {}
        self._load_index()

    def _load_index(self):
        if self._index_file.exists():
            try:
                data = json.loads(self._index_file.read_text(encoding="utf-8"))
                self._memories = {k: Memory.from_dict(v) for k, v in data.items()}
            except Exception:
                self._memories = {}

    def _save_index(self):
        self._index_file.write_text(
            json.dumps({k: v.to_dict() for k, v in self._memories.items()},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def save(self, key: str, content: str, tags: List[str] = None):
        """Save or update a memory entry."""
        safe_key = re.sub(r"[^\w\-]", "_", key)[:80]
        now = time.time()
        if safe_key in self._memories:
            m = self._memories[safe_key]
            m.content     = content
            m.tags        = list(set((m.tags or []) + (tags or [])))
            m.updated_at  = now
        else:
            self._memories[safe_key] = Memory(
                key=safe_key, content=content,
                tags=tags or [], created_at=now, updated_at=now,
            )
        self._save_index()

    async def get(self, key: str) -> Optional[Memory]:
        safe_key = re.sub(r"[^\w\-]", "_", key)[:80]
        m = self._memories.get(safe_key)
        if m:
            m.access_count += 1
            self._save_index()
        return m

    async def search(self, query: str, top_k: int = 5,
                     tags: List[str] = None) -> List[dict]:
        """
        Keyword-based search (TF-IDF-lite: term frequency in content).
        Returns top_k memories as dicts, sorted by relevance.
        """
        query_terms = set(re.findall(r"\w+", query.lower()))
        if not query_terms:
            return []

        scored = []
        for m in self._memories.values():
            if tags and not any(t in m.tags for t in tags):
                continue
            text   = (m.content + " " + " ".join(m.tags)).lower()
            score  = sum(1 for t in query_terms if t in text)
            score += m.access_count * 0.1   # boost frequently accessed
            if score > 0:
                scored.append((score, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"key": m.key, "content": m.content,
                 "tags": m.tags, "score": s}
                for s, m in scored[:top_k]]

    async def list_all(self) -> List[dict]:
        return sorted(
            [m.to_dict() for m in self._memories.values()],
            key=lambda x: x["updated_at"], reverse=True,
        )

    async def delete(self, key: str):
        safe_key = re.sub(r"[^\w\-]", "_", key)[:80]
        self._memories.pop(safe_key, None)
        self._save_index()

    async def clear(self):
        self._memories = {}
        self._save_index()

    async def summary_stats(self) -> dict:
        total = len(self._memories)
        if not total:
            return {"total": 0, "tags": {}, "newest": None, "oldest": None}
        all_tags: dict = {}
        for m in self._memories.values():
            for t in m.tags:
                all_tags[t] = all_tags.get(t, 0) + 1
        times = [m.created_at for m in self._memories.values()]
        return {
            "total" : total,
            "tags"  : all_tags,
            "newest": max(times),
            "oldest": min(times),
        }
