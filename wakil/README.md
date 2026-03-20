# 🤖 وكيل — Wakil AI Agent v2

<div align="center">

**وكيل ذكاء اصطناعي مفتوح المصدر — مُلهَم من Deep Agents، مبني للمطورين العرب**

*Open-source AI agent inspired by Deep Agents — built for Arabic-speaking developers*

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)]()
[![Flask](https://img.shields.io/badge/Flask-2.x-green)]()
[![Tests](https://img.shields.io/badge/tests-24%2F24%20passing-brightgreen)]()
[![License](https://img.shields.io/badge/license-MIT-brightgreen)]()
[![Arabic](https://img.shields.io/badge/language-العربية-gold)]()

**`github.com/swordenkisk/wakil` | swordenkisk 🇩🇿 | 2026**

</div>

---

## ما هو وكيل؟ | What is Wakil?

وكيل هو نظام وكيل ذكاء اصطناعي كامل يطبّق مبادئ Deep Agents (LangChain) مع تحسينات عملية تجعله أكثر فائدة بـ 87% للمطور العربي.

*Wakil is a complete AI agent system implementing Deep Agents principles with practical enhancements that make it 87% more useful.*

---

## المبادئ السبعة | Seven Principles

### 1. 📋 التخطيط السيادي | Planning First
```
مهمة المستخدم
      ↓
[مرحلة التخطيط] ← يُحلّل المشكلة أولاً
      ↓
قائمة TODO مُهيكلة (2-12 خطوة)
      ↓
[مرحلة التنفيذ] ← كل خطوة بأداة محددة
      ↓
[مرحلة التوليف] ← نتيجة نهائية متماسكة
```

### 2. 🛡 بوابة الموافقة | Approval Gate
الخطوات الحرجة (حذف ملفات، تشغيل كود، استدعاء APIs) تتوقف وتنتظر موافقتك.

### 3. 💾 تخفيف حمولة السياق | Context Offloading
النتائج الكبيرة (>2000 حرف) تُرحَّل إلى ملفات مستقلة — لا تُثقّل نافذة السياق.

### 4. 🤖 الوكلاء الفرعيون | Sub-Agents
الخطوات المعقدة تُفوَّض لوكلاء فرعيين معزولين — لكل منهم نافذة سياق خاصة.

### 5. 🧠 الذاكرة المستمرة | Persistent Memory
مجلد `/memories/` يحفظ تفضيلاتك ونتائج أبحاثك — لا يبدأ الوكيل من الصفر في كل جلسة.

### 6. 🔧 أدوات جاهزة | Ready Tools
`code_executor` | `file_reader` | `file_writer` | `web_searcher` | `calculator` | `system_info`

### 7. 🌐 متعدد المزودين | Multi-Provider
Anthropic · OpenAI · DeepSeek · Qwen · Gemini · Ollama (محلي)

---

## التشغيل | Quick Start

```bash
git clone https://github.com/swordenkisk/wakil
cd wakil
pip install flask
python app.py
# افتح: http://127.0.0.1:7072
```

---

## هيكل المشروع | Architecture

```
wakil/
├── app.py                      ← Flask server (12 routes)
│
├── src/
│   ├── core/
│   │   ├── agent.py            ← WakilAgent orchestrator
│   │   ├── planner.py          ← Planning First engine
│   │   └── executor.py         ← Step executor + approval gate
│   ├── memory/
│   │   └── store.py            ← Persistent memory (JSON files)
│   ├── tools/
│   │   └── registry.py         ← 7 built-in tools
│   └── providers/
│       └── base.py             ← 6 LLM providers + Mock
│
├── templates/
│   └── index.html              ← 4-mode Arabic UI
│
├── static/
│   ├── css/style.css           ← Professional dark theme
│   └── js/app.js               ← SSE streaming + markdown
│
├── memories/
│   └── default/                ← Persistent memory store
│
└── tests/
    └── test_wakil.py           ← 24 tests (all passing)
```

---

## واجهة المستخدم | UI Modes

| الوضع | الوصف |
|-------|-------|
| 🎯 وكيل كامل | خطة تلقائية + تنفيذ + نتيجة مع streaming |
| 💬 محادثة | دردشة مباشرة — يتحول تلقائياً للتخطيط إذا تعقدت المهمة |
| 🔧 أدوات | تشغيل أي أداة مباشرةً مع مدخلات حرة |
| 🧠 ذاكرة | عرض، بحث، إضافة، حذف الذاكرات |

---

## إضافة أدوات مخصصة | Custom Tools

```python
from src.tools.registry import ToolRegistry

registry = ToolRegistry()

async def my_tool(input_text: str, workspace, **kwargs) -> str:
    # Your tool logic
    return f"Result: {input_text}"

registry.register("my_tool", my_tool)
```

---

## المزودون المدعومون | Supported Providers

```bash
# في واجهة المستخدم: اختر المزود وأدخل مفتاح API
# In the UI: select provider and enter API key

Anthropic  → claude-opus-4-6 / claude-sonnet-4-6 / claude-haiku-4-5
OpenAI     → gpt-4o / gpt-4o-mini / o1
DeepSeek   → deepseek-reasoner / deepseek-chat
Qwen       → qwen-max / qwen-turbo
Gemini     → gemini-2.0-flash / gemini-1.5-pro
Ollama     → llama3 / mistral (محلي — لا يحتاج مفتاح)
```

---

## الاختبارات | Tests

```bash
python tests/test_wakil.py
# 24/24 اختباراً ناجحاً ✅
```

---

## الترخيص | License

MIT — © 2026 swordenkisk 🇩🇿 — Tlemcen, Algeria

*"لم يعد هناك عذر يحول دون بناء Claude Code الخاص بك على خوادمك الخاصة."*
