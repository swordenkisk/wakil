/* وكيل — Wakil Agent App.js */
'use strict';

const $ = id => document.getElementById(id);
let MODE = 'agent', running = false, eventSrc = null;
let pendingApproval = null, selectedTool = '';

// ── Config ──────────────────────────────────────────────────
function getConfig() {
  return {
    provider    : $('cfg-provider').value,
    model       : $('cfg-model').value,
    api_key     : $('cfg-key').value,
    auto_approve: !$('cfg-approve').checked,
  };
}

function saveConfig() {
  localStorage.setItem('wakil_cfg', JSON.stringify(getConfig()));
}

function loadConfig() {
  try {
    const c = JSON.parse(localStorage.getItem('wakil_cfg') || '{}');
    if (c.provider) { $('cfg-provider').value = c.provider; onProviderChange(); }
    if (c.model)    $('cfg-model').value = c.model;
    if (c.api_key)  $('cfg-key').value   = c.api_key;
    if (c.auto_approve !== undefined)
      $('cfg-approve').checked = !c.auto_approve;
  } catch {}
}

function onProviderChange() {
  const p = $('cfg-provider').value;
  const sel = $('cfg-model');
  const pdata = window.PROVIDERS_DATA[p];
  sel.innerHTML = '';
  if (pdata) {
    pdata.models.forEach(m => {
      const o = document.createElement('option');
      o.value = m; o.textContent = m;
      if (m === pdata.default) o.selected = true;
      sel.appendChild(o);
    });
  }
  saveConfig();
}

// ── Mode ─────────────────────────────────────────────────────
const MODE_TITLES = {
  agent : '🎯 وضع الوكيل الكامل',
  chat  : '💬 وضع المحادثة',
  tools : '🔧 تشغيل الأدوات',
  memory: '🧠 إدارة الذاكرة',
};
function setMode(m) {
  MODE = m;
  document.querySelectorAll('.mode-tab').forEach(t =>
    t.classList.toggle('active', t.dataset.mode === m));
  document.querySelectorAll('.panel').forEach(p =>
    p.classList.toggle('active', p.id === 'panel-' + m));
  $('mode-title').textContent = MODE_TITLES[m] || '';
  if (m === 'memory') loadMemories();
}

// ── Sidebar ──────────────────────────────────────────────────
function toggleSidebar() {
  document.querySelector('.sidebar').classList.toggle('collapsed');
}

// ── Status badge ─────────────────────────────────────────────
function setBadge(type, text) {
  const b = $('status-badge');
  b.className = 'badge-' + type;
  b.textContent = text;
}

// ── Toast ────────────────────────────────────────────────────
function toast(msg, dur=2200) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('show'), dur);
}

// ── Simple Markdown renderer ─────────────────────────────────
function md(text) {
  const codes = [];
  text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, l, c) => {
    const i = codes.length;
    codes.push(`<pre><code>${esc(c.trim())}</code></pre>`);
    return `\x00C${i}\x00`;
  });
  text = esc(text)
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,'<em>$1</em>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/^### (.+)$/gm,'<h3>$1</h3>')
    .replace(/^## (.+)$/gm,'<h2>$1</h2>')
    .replace(/^# (.+)$/gm,'<h1>$1</h1>')
    .replace(/^\s*[-*] (.+)$/gm,'<li>$1</li>')
    .split('\n\n').map(p => {
      p = p.trim();
      if (!p) return '';
      if (/^<(h[1-3]|ul|li|pre)/.test(p)) return p;
      return `<p>${p.replace(/\n/g,'<br/>')}</p>`;
    }).join('\n')
    .replace(/(<li>[\s\S]+?<\/li>)+/g, m => `<ul>${m}</ul>`);
  text = text.replace(/\x00C(\d+)\x00/g, (_, i) => codes[+i]);
  return text;
}
function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// ═══════════════════════════════════════════════════════════
//  AGENT MODE
// ═══════════════════════════════════════════════════════════

function runAgent() {
  if (running) {
    if (eventSrc) { eventSrc.close(); eventSrc = null; }
    running = false; setBadge('idle','جاهز');
    $('run-label').textContent = '▶ تشغيل الوكيل';
    return;
  }
  const task = $('task-input').value.trim();
  if (!task) return;

  running = true;
  $('run-label').textContent = '⏹ إيقاف';
  setBadge('running', 'يعمل...');
  clearTerminal();
  $('synthesis-panel').classList.add('hidden');
  $('plan-panel').classList.add('hidden');
  $('plan-steps').innerHTML = '';

  const cfg    = getConfig();
  const params = new URLSearchParams({
    task        : task,
    provider    : cfg.provider,
    api_key     : cfg.api_key,
    model       : cfg.model,
    auto_approve: String(cfg.auto_approve),
  });

  const es = new EventSource('/api/stream?' + params);
  eventSrc = es;

  es.onmessage = e => {
    const data = JSON.parse(e.data);
    handleAgentEvent(data);
  };
  es.onerror = () => {
    addTermLine('Disconnected.', 'tline-error');
    running = false; setBadge('error','خطأ');
    $('run-label').textContent = '▶ تشغيل الوكيل';
    es.close(); eventSrc = null;
  };
}

function handleAgentEvent(ev) {
  const event = ev.event;

  if (event === 'loading_memories') {
    addTermLine('📚 جاري تحميل الذاكرة...', 'tline-event');
  }
  else if (event === 'planning') {
    addTermLine(`📋 التخطيط للمهمة: ${ev.task.slice(0,80)}...`, 'tline-plan');
  }
  else if (event === 'plan_ready') {
    const plan = ev.plan;
    $('plan-panel').classList.remove('hidden');
    $('plan-complexity').textContent  = plan.complexity;
    $('plan-complexity').classList.remove('hidden');
    $('plan-analysis').textContent    = plan.analysis;
    $('plan-analysis').classList.remove('hidden');
    renderPlanSteps(plan.steps);
    addTermLine(`✅ الخطة جاهزة: ${plan.steps.length} خطوة`, 'tline-plan');
  }
  else if (event === 'step_start') {
    const s = ev.step;
    updateStepStatus(s.id, 'running', '⟳');
    addTermLine(`▶ الخطوة ${s.id}: ${s.title}`, 'tline-step');
    if (s.requires_approval) {
      addTermLine(`  ⚠ تتطلب موافقة`, 'tline-event');
    }
  }
  else if (event === 'step_approval') {
    const s = ev.step;
    showApproval(s);
  }
  else if (event === 'step_done') {
    const s = ev.step;
    updateStepStatus(s.id, 'done', '✓');
    if (ev.output && ev.output.length < 300) {
      addTermLine(`  ↳ ${ev.output.slice(0,200)}`, 'tline-output');
    }
    updateProgress(ev.step);
  }
  else if (event === 'step_skipped') {
    updateStepStatus(ev.step.id, 'skipped', '↷');
    addTermLine(`  ↷ تم تخطي الخطوة ${ev.step.id}`, 'tline-event');
  }
  else if (event === 'step_failed') {
    updateStepStatus(ev.step.id, 'failed', '✗');
    addTermLine(`  ✗ فشلت الخطوة: ${ev.error||''}`, 'tline-error');
  }
  else if (event === 'synthesising') {
    addTermLine('🔄 جاري تجميع النتائج النهائية...', 'tline-synth');
  }
  else if (event === 'synthesis') {
    addTermLine('✅ اكتمل التوليف', 'tline-synth');
    $('synthesis-panel').classList.remove('hidden');
    $('syn-content').innerHTML = md(ev.text);
  }
  else if (event === 'done') {
    const r = ev.result;
    $('timing-row').classList.remove('hidden');
    $('t-total').textContent = `⏱ الإجمالي: ${r.total_ms}ms`;
    $('t-steps').textContent = `📋 الخطوات: ${r.plan?.steps?.length || '?'}`;
    running = false;
    setBadge('done', 'اكتمل');
    $('run-label').textContent = '▶ تشغيل الوكيل';
    if (eventSrc) { eventSrc.close(); eventSrc = null; }
    toast('✅ اكتملت المهمة!');
  }
  else if (event === 'error') {
    addTermLine(`✗ خطأ: ${ev.message}`, 'tline-error');
    running = false; setBadge('error','خطأ');
    $('run-label').textContent = '▶ تشغيل الوكيل';
  }
  else if (event === 'session_saved') {
    addTermLine('💾 تم حفظ الجلسة في الذاكرة', 'tline-mem');
  }
}

// ── Plan rendering ────────────────────────────────────────────
function renderPlanSteps(steps) {
  $('plan-steps').innerHTML = steps.map(s => `
    <div class="plan-step" id="pstep-${s.id}">
      <div class="step-num">${s.id}</div>
      <div class="step-content">
        <div class="step-title">${esc(s.title)}
          ${s.tool_hint && s.tool_hint!=='none' ? `<span class="step-badge">${s.tool_hint}</span>` : ''}
          ${s.requires_approval ? '<span class="step-badge step-approval-badge">⚠ موافقة</span>' : ''}
          ${s.sub_agent ? '<span class="step-badge step-sub-badge">🤖 وكيل فرعي</span>' : ''}
        </div>
        <div class="step-desc">${esc(s.description.slice(0,120))}</div>
      </div>
      <div class="step-status-icon" id="pstep-icon-${s.id}">○</div>
    </div>`
  ).join('');
}

function updateStepStatus(id, cls, icon) {
  const el   = $(`pstep-${id}`);
  const icon_el = $(`pstep-icon-${id}`);
  if (el) {
    el.className = `plan-step ps-${cls}`;
  }
  if (icon_el) icon_el.textContent = icon;
}

function updateProgress(step) {
  // Count done steps
  const all  = document.querySelectorAll('.plan-step').length;
  const done = document.querySelectorAll('.plan-step.ps-done').length;
  $('plan-progress').style.width = all ? (100 * done / all) + '%' : '0%';
}

// ── Terminal helpers ──────────────────────────────────────────
function addTermLine(text, cls) {
  const t = $('terminal');
  const d = document.createElement('div');
  d.className = 'tline ' + (cls || '');
  d.textContent = text;
  t.appendChild(d);
  t.scrollTop = t.scrollHeight;
}

function clearTerminal() {
  $('terminal').innerHTML = '';
}

function copySynthesis() {
  navigator.clipboard.writeText($('syn-content').innerText)
    .then(() => toast('✓ تم نسخ النتيجة'));
}

// ── Approval ─────────────────────────────────────────────────
function showApproval(step) {
  pendingApproval = step;
  $('apv-desc').innerHTML =
    `<strong>الخطوة ${step.id}:</strong> ${esc(step.title)}<br/>
     <em>${esc(step.description.slice(0,200))}</em>`;
  $('approval-dialog').classList.remove('hidden');
}

async function approveStep(approved) {
  $('approval-dialog').classList.add('hidden');
  if (!pendingApproval) return;
  await fetch('/api/approve', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({step_id: pendingApproval.id, approved}),
  });
  pendingApproval = null;
  toast(approved ? '✅ تمت الموافقة' : '❌ تم الرفض');
}

// ═══════════════════════════════════════════════════════════
//  CHAT MODE
// ═══════════════════════════════════════════════════════════

const chatHistory = [];

async function sendChat() {
  const inp = $('chat-input');
  const msg = inp.value.trim();
  if (!msg) return;
  inp.value = '';
  addChatMsg(msg, 'user');
  chatHistory.push({role:'user', content:msg});

  const cfg = getConfig();
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({message:msg, history:chatHistory.slice(-6), ...cfg}),
    });
    const data = await res.json();
    const answer = data.answer || 'لا يوجد رد';
    addChatMsg(answer, 'agent');
    chatHistory.push({role:'assistant', content:answer});
  } catch (e) {
    addChatMsg(`خطأ: ${e.message}`, 'agent');
  }
}

function addChatMsg(text, role) {
  const d = document.createElement('div');
  d.className = role === 'user' ? 'msg-user' : 'msg-agent';
  if (role === 'agent') {
    d.innerHTML = md(text);
  } else {
    d.textContent = text;
  }
  $('chat-messages').appendChild(d);
  $('chat-messages').scrollTop = 9999;
}

// ═══════════════════════════════════════════════════════════
//  TOOLS MODE
// ═══════════════════════════════════════════════════════════

function selectTool(name) {
  selectedTool = name;
  $('tr-name').textContent = name;
  $('tool-runner').classList.remove('hidden');
  $('tr-output').classList.add('hidden');
  $('tr-output').textContent = '';
}

async function runTool() {
  const inp = $('tr-input').value;
  if (!selectedTool || !inp) return;
  const btn = document.querySelector('.btn-run-tool');
  btn.textContent = '⟳ جاري...'; btn.disabled = true;
  try {
    const res = await fetch('/api/run_tool', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({tool: selectedTool, input: inp}),
    });
    const data = await res.json();
    $('tr-output').textContent = data.output || 'لا يوجد مخرجات';
    $('tr-output').classList.remove('hidden');
  } catch (e) {
    $('tr-output').textContent = `خطأ: ${e.message}`;
    $('tr-output').classList.remove('hidden');
  } finally {
    btn.textContent = '▶ تشغيل'; btn.disabled = false;
  }
}

// ═══════════════════════════════════════════════════════════
//  MEMORY MODE
// ═══════════════════════════════════════════════════════════

async function loadMemories() {
  const res   = await fetch('/api/memories');
  const data  = await res.json();
  const stats = data.stats;
  $('mem-stats').textContent =
    `الإجمالي: ${stats.total} ذاكرة | تاغات: ${Object.keys(stats.tags||{}).length}`;
  renderMemories(data.memories);
}

function renderMemories(mems) {
  const el = $('memory-list');
  if (!mems || !mems.length) {
    el.innerHTML = '<div class="mem-empty">لا توجد ذكريات بعد</div>';
    return;
  }
  el.innerHTML = mems.map(m => `
    <div class="mem-card">
      <div class="mc-key">${esc(m.key)}</div>
      <div class="mc-content">${esc(m.content.slice(0,200))}</div>
      <div class="mc-tags">${(m.tags||[]).map(t=>`<span class="mc-tag">${esc(t)}</span>`).join('')}</div>
      <div class="mc-time">${new Date(m.updated_at*1000).toLocaleString('ar')}</div>
    </div>`).join('');
}

async function addMemory() {
  const key     = $('mem-key').value.trim();
  const content = $('mem-content').value.trim();
  const tags    = $('mem-tags').value.split(',').map(t=>t.trim()).filter(Boolean);
  if (!key || !content) return;
  await fetch('/api/memories', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({key, content, tags}),
  });
  $('mem-key').value = ''; $('mem-content').value = ''; $('mem-tags').value = '';
  toast('💾 تم حفظ الذاكرة');
  loadMemories();
}

async function clearMemories() {
  if (!confirm('هل تريد مسح جميع الذكريات؟')) return;
  await fetch('/api/memories', {method:'DELETE'});
  toast('🗑 تم مسح الذاكرة');
  loadMemories();
}

// Memory search
$('mem-search')?.addEventListener('input', async e => {
  const q = e.target.value.trim();
  if (!q) { loadMemories(); return; }
  const res  = await fetch('/api/memories');
  const data = await res.json();
  const ql   = q.toLowerCase();
  const filtered = data.memories.filter(m =>
    m.key.toLowerCase().includes(ql) ||
    m.content.toLowerCase().includes(ql) ||
    (m.tags||[]).some(t=>t.toLowerCase().includes(ql))
  );
  renderMemories(filtered);
});

// ── Task input auto-resize ────────────────────────────────────
$('task-input')?.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 180) + 'px';
});
$('task-input')?.addEventListener('keydown', e => {
  if ((e.ctrlKey||e.metaKey) && e.key==='Enter') { e.preventDefault(); runAgent(); }
});
$('chat-input')?.addEventListener('keydown', e => {
  if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

// ── Init ──────────────────────────────────────────────────────
loadConfig();
onProviderChange();

// Auto-save config on change
['cfg-provider','cfg-model','cfg-key','cfg-approve'].forEach(id => {
  $(id)?.addEventListener('change', saveConfig);
});
