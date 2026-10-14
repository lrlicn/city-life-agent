<script setup>
import { ref, computed } from 'vue'
import { useChat } from '@ai-sdk/vue'
import { DefaultChatTransport, isToolUIPart, getToolName } from 'ai'
import { marked } from 'marked'
import SalaryChart from './SalaryChart.vue'

// 回答模式：空 = 后端 .env 的 REPLY_MODE；或 brief / standard / report
const mode = ref('')
const input = ref('')
const MODES = [
  { label: '自动', value: '' },
  { label: '简洁', value: 'brief' },
  { label: '标准', value: 'standard' },
  { label: '报告', value: 'report' },
]
const modeOpen = ref(false)
function modeLabel(v) {
  const m = MODES.find(x => x.value === v)
  return m ? m.label : '自动'
}
function pickMode(v) {
  mode.value = v
  modeOpen.value = false
}

// 已展开的工具明细（存 part.key）
const expanded = ref(new Set())
function toggleTool(k) {
  const s = new Set(expanded.value)
  if (s.has(k)) s.delete(k)
  else s.add(k)
  expanded.value = s
}
// 已展开的「工具过程」区（存消息 id）
const openMsgs = ref(new Set())
function toggleMsg(k) {
  const s = new Set(openMsgs.value)
  if (s.has(k)) s.delete(k)
  else s.add(k)
  openMsgs.value = s
}
function fmt(v) {
  if (v == null) return ''
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

const { messages, sendMessage, status, error, stop } = useChat({
  transport: new DefaultChatTransport({
    api: '/chat-ai',
    body: () => ({ mode: mode.value || null }),
  }),
})

const PRESETS = [
  { icon: '💼', text: '上海月薪 2 万，到手能拿多少？' },
  { icon: '🏦', text: '上海社保公积金怎么缴？' },
  { icon: '📊', text: '深圳月薪 3 万，到手能拿多少？' },
  { icon: '📄', text: '帮我把测算结果整理成一份报告' },
]

function submit(text) {
  const q = (text ?? input.value).trim()
  if (!q) return
  sendMessage({ text: q })
  input.value = ''
}

// 多行输入框自动增高（上限 140px）
function autoGrow(e) {
  const t = e.target
  t.style.height = 'auto'
  t.style.height = Math.min(t.scrollHeight, 140) + 'px'
}

// Markdown → HTML 渲染（Agent 回答里的表格/标题/加粗）
function md(src) {
  return marked.parse(src || '')
}

function userText(m) {
  if (m.content) return m.content
  return (m.parts || [])
    .filter(p => p.type === 'text')
    .map(p => p.text)
    .join('')
}

// 助手消息：拆成「文本 / 工具 / 图表」三类渲染单元
function agentParts(m) {
  return (m.parts || [])
    .map((p, i) => {
      if (p.type === 'text') return { key: i, kind: 'text', text: p.text || '' }
      if (p.type === 'data-salary') return { key: i, kind: 'chart', data: p.data }
      if (isToolUIPart(p)) {
        return {
          key: i,
          kind: 'tool',
          name: getToolName(p),
          running: p.state === 'input-streaming',
          input: p.input,
          output: p.output,
          done: p.state !== 'input-streaming',
        }
      }
      return null
    })
    .filter(Boolean)
}

// 图表去重：相同城市 + 相同月薪只保留第一张
function uniqueCharts(m) {
  const seen = new Set()
  return agentParts(m).filter(x => x.kind === 'chart').filter(x => {
    const k =
      x.data.city && x.data.monthly_salary != null
        ? `${x.data.city}-${x.data.monthly_salary}`
        : `c-${x.key}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

function toolsOf(m) {
  return agentParts(m).filter(x => x.kind === 'tool')
}

// 最后一条助手消息仍在上 / 生成中 → 显示活动光标
function isLastAssistant(m) {
  return m.role === 'assistant' && m === messages.value[messages.value.length - 1]
}

const busy = computed(() => status.value === 'streaming' || status.value === 'submitted')
const statusLabel = computed(() => {
  if (status.value === 'submitted') return '思考中'
  if (status.value === 'streaming') return '生成中'
  if (status.value === 'error') return '出错'
  return '就绪'
})
const statusTone = computed(() => {
  if (status.value === 'streaming' || status.value === 'submitted') return 'busy'
  if (status.value === 'error') return 'err'
  return 'idle'
})
</script>

<template>
  <div class="app" @click="modeOpen = false">
    <div class="inner">
    <!-- 顶栏：只留产品名 + 一个状态点 -->
    <header>
      <div class="brand">
        <div class="logo">◈</div>
        <h1>城市生活计算管家</h1>
      </div>
      <div class="header-status" :class="statusTone">
        <span class="dot"></span>
        <span>{{ statusLabel }}</span>
      </div>
    </header>

    <!-- 消息区 -->
    <div class="messages">
      <!-- 初始态 -->
      <div v-if="messages.length === 0" class="welcome">
        <div class="w-title">问点什么，我来帮你算</div>
        <div class="w-sub">社保公积金、到手工资，帮你算清楚</div>
        <div class="presets">
          <button
            v-for="p in PRESETS"
            :key="p.text"
            class="preset"
            @click="submit(p.text)"
            :disabled="status !== 'ready'"
          >
            <span class="p-icon">{{ p.icon }}</span>
            <span class="p-label">{{ p.text }}</span>
            <span class="p-arrow">→</span>
          </button>
        </div>
      </div>

      <!-- 对话 -->
      <template v-for="m in messages" :key="m.id">
        <div v-if="m.role === 'user'" class="row user-row">
          <div class="bubble user">{{ userText(m) }}</div>
        </div>

        <div v-else class="row agent-row">
          <div class="avatar a">◈</div>
          <div class="agent-body">
            <!-- 工具过程：默认折叠成一条 -->
            <div v-if="toolsOf(m).length" class="process">
              <div class="process-head" @click="toggleMsg(m.id)">
                <span class="p-icon">⚙</span>
                <span class="p-text">
                  {{ toolsOf(m).some(t => t.running) ? '正在调用工具…' : `已调用工具 ${toolsOf(m).length} 次` }}
                </span>
                <span class="p-toggle">{{ openMsgs.has(m.id) ? '▴' : '▾' }}</span>
              </div>
              <div v-if="openMsgs.has(m.id)" class="process-list">
                <div v-for="p in toolsOf(m)" :key="p.key" class="tool-item">
                  <div class="tool-head" @click="toggleTool(p.key)">
                    <span class="ti-name">{{ p.name }}</span>
                    <span v-if="p.running" class="ti-state run">进行中…</span>
                    <span v-else class="ti-state ok">完成</span>
                    <span v-if="p.done" class="ti-toggle">{{ expanded.has(p.key) ? '▴' : '▾' }}</span>
                  </div>
                  <div v-if="expanded.has(p.key)" class="tool-detail">
                    <div v-if="p.input && Object.keys(p.input).length" class="td">
                      <span class="td-label">输入参数</span>
                      <pre class="td-pre">{{ fmt(p.input) }}</pre>
                    </div>
                    <div v-if="p.output" class="td">
                      <span class="td-label">返回结果</span>
                      <pre class="td-pre">{{ fmt(p.output) }}</pre>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 图表（去重后） -->
            <div v-for="p in uniqueCharts(m)" :key="p.key" class="chart-wrap">
              <SalaryChart :data="p.data" />
            </div>

            <!-- 回答文本 -->
            <div class="bubble agent">
              <template v-for="p in agentParts(m).filter(x => x.kind === 'text')" :key="p.key">
                <div class="text markdown" v-html="md(p.text)"></div>
              </template>
              <span v-if="isLastAssistant(m) && busy" class="cursor"></span>
            </div>
          </div>
        </div>
      </template>
    </div>

    <div v-if="messages.length" class="fade"></div>

    <!-- 错误条 -->
    <div v-if="error" class="errorbar">出错：{{ error.message || error }}</div>

    <!-- 输入区：大胶囊输入条 -->
    <div class="inputbar">
      <div class="composer">
        <textarea
          v-model="input"
          rows="1"
          placeholder="问我关于社保、公积金、到手工资的问题…"
          :disabled="status !== 'ready'"
          @input="autoGrow"
          @keydown.enter.exact.prevent="submit()"
        ></textarea>
        <div class="composer-bar">
          <div class="mode" @click.stop="modeOpen = !modeOpen" title="回答模式">
            <span class="m-label">{{ modeLabel(mode) }}</span>
            <span class="m-caret">▾</span>
            <div v-if="modeOpen" class="mode-menu">
              <div
                v-for="opt in MODES"
                :key="opt.value"
                class="mode-opt"
                :class="{ on: mode === opt.value }"
                @click.stop="pickMode(opt.value)"
              >{{ opt.label }}</div>
            </div>
          </div>
          <div class="bar-right">
            <button
              v-if="status !== 'streaming'"
              class="send"
              :disabled="status !== 'ready'"
              @click="submit()"
              aria-label="发送"
            >➤</button>
            <button v-if="status === 'streaming'" class="stop" @click="stop" aria-label="停止">■</button>
          </div>
        </div>
      </div>
    </div>
    </div>
  </div>
</template>

<style scoped>
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}
.app {
  font-family: -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  height: 100vh;
  width: 100%;
  background:
    radial-gradient(1200px 520px at 50% -8%, rgba(37, 99, 235, 0.16), transparent 60%),
    radial-gradient(900px 460px at 88% 108%, rgba(56, 189, 248, 0.10), transparent 60%),
    linear-gradient(180deg, #0c1220 0%, #121a2e 100%);
  color: #e5eaf1;
}
.inner {
  max-width: 880px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* 顶栏 */
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid rgba(42, 58, 85, 0.5);
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.logo {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  color: #dbeafe;
  border-radius: 10px;
  background: linear-gradient(135deg, #2563eb, #38bdf8);
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4);
}
header h1 {
  font-size: 17px;
  font-weight: 600;
  color: #f1f5fb;
}
.header-status {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: #8aa0bd;
  padding: 5px 12px;
  border-radius: 999px;
  background: rgba(14, 23, 40, 0.7);
  border: 1px solid #22304a;
}
.header-status .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.header-status.idle .dot { background: #34d399; }
.header-status.busy .dot { background: #fbbf24; animation: pulse 1.2s infinite; }
.header-status.err .dot { background: #f87171; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

/* 消息区 */
.messages {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: 26px 28px 8px;
  scrollbar-width: thin;
  scrollbar-color: #2a3a55 transparent;
}
/* 消息区底部渐隐：仅在有消息时显示，内容滚到输入条上方时自然淡出 */
.fade {
  height: 40px;
  margin-top: -40px;
  background: linear-gradient(to bottom, transparent, rgba(12, 18, 32, 0.85));
  pointer-events: none;
  position: relative;
  z-index: 2;
}

/* 初始态 */
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: auto;
  padding: 40px 0;
  text-align: center;
}
.w-title {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: #f4f7fc;
}
.w-sub {
  font-size: 14px;
  color: #8aa0bd;
  margin-top: 10px;
}
.presets {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-top: 34px;
  max-width: 600px;
  width: 100%;
  text-align: left;
}
.preset {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(22, 34, 58, 0.8);
  border: 1px solid #2a3a55;
  color: #c4d4ec;
  font-size: 13px;
  line-height: 1.4;
  cursor: pointer;
  transition: all 0.15s;
}
.preset:hover {
  background: #1d2b47;
  border-color: #3b82c4;
  color: #dbeafe;
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
}
.p-icon { font-size: 18px; flex-shrink: 0; }
.p-label { flex: 1; }
.p-arrow { color: #5f7aa0; flex-shrink: 0; }
.preset:disabled { opacity: 0.5; cursor: not-allowed; }

/* 消息行 */
.row {
  display: flex;
  gap: 12px;
  margin-bottom: 18px;
  align-items: flex-start;
}
.user-row { justify-content: flex-end; }
.avatar {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  flex-shrink: 0;
}
.avatar.a {
  background: linear-gradient(135deg, #2563eb, #38bdf8);
  color: #dbeafe;
  font-size: 14px;
}
.bubble {
  max-width: 76%;
  padding: 12px 16px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubble.user {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  border-top-right-radius: 4px;
}
.bubble.agent {
  background: rgba(22, 34, 58, 0.85);
  border: 1px solid #22304a;
  color: #e5eaf1;
  border-top-left-radius: 4px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
}
.markdown { line-height: 1.7; }
.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3) {
  margin: 12px 0 6px;
  font-weight: 600;
  color: #f1f5fb;
}
.markdown :deep(h2) { font-size: 16px; }
.markdown :deep(p) { margin: 6px 0; }
.markdown :deep(strong) { color: #dbeafe; }
.markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 8px 0;
  font-size: 13px;
}
.markdown :deep(th),
.markdown :deep(td) {
  border: 1px solid #2a3a55;
  padding: 6px 10px;
  text-align: left;
  vertical-align: top;
}
.markdown :deep(th) { background: #1d2b47; color: #c4d4ec; }
.markdown :deep(tbody tr:nth-child(even) td) { background: #182440; }
.markdown :deep(code) {
  background: #0e1728;
  padding: 1px 6px;
  border-radius: 6px;
  font-size: 12px;
}
.markdown :deep(ul),
.markdown :deep(ol) { margin: 6px 0 6px 18px; }
.markdown :deep(li) { margin: 3px 0; }
.markdown :deep(a) { color: #60a5fa; }
/* 引用块：调轻，视觉退到辅助说明位置 */
.markdown :deep(blockquote) {
  border-left: 2px solid rgba(59, 130, 196, 0.45);
  padding: 6px 12px;
  margin: 8px 0;
  color: #93a7c4;
  font-size: 13px;
  background: rgba(30, 41, 66, 0.35);
  border-radius: 0 8px 8px 0;
}
.agent-body { flex: 1; min-width: 0; }

/* 工具过程：折叠条 */
.process {
  margin-bottom: 8px;
  border-radius: 10px;
  background: rgba(14, 23, 40, 0.8);
  border: 1px solid #22304a;
  overflow: hidden;
}
.process-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  font-size: 12px;
  cursor: pointer;
  color: #9fb4d4;
}
.process-head:hover { background: #111c31; }
.p-icon { color: #fbbf24; }
.p-text { color: #c4d4ec; }
.p-toggle { margin-left: auto; color: #8aa0bd; font-size: 10px; }
.process-list { border-top: 1px solid #22304a; padding: 4px 0; }
.tool-item { border-bottom: 1px solid #1c2a42; }
.tool-item:last-child { border-bottom: none; }
.tool-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  font-size: 12px;
  cursor: pointer;
}
.tool-head:hover { background: #111c31; }
.ti-name { color: #e5eaf1; font-weight: 600; }
.ti-state.ok { color: #34d399; }
.ti-state.run { color: #fbbf24; }
.ti-toggle { margin-left: auto; color: #8aa0bd; font-size: 10px; }
.tool-detail { padding: 8px 12px 10px; }
.td { margin-bottom: 6px; }
.td:last-child { margin-bottom: 0; }
.td-label { color: #8aa0bd; font-size: 11px; display: block; margin-bottom: 2px; }
.td-pre {
  white-space: pre-wrap;
  word-break: break-word;
  color: #c4d4ec;
  background: #101a2d;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 12px;
  margin: 0;
}

/* 图表 */
.chart-wrap {
  margin: 10px 0;
  background: rgba(14, 23, 40, 0.8);
  border: 1px solid #22304a;
  border-radius: 12px;
  padding: 10px;
}

/* 打字光标 */
.cursor {
  display: inline-block;
  width: 2px;
  height: 15px;
  background: #38bdf8;
  vertical-align: text-bottom;
  margin-left: 2px;
  animation: caret 0.9s infinite;
}
@keyframes caret { 50% { opacity: 0; } }

/* 错误条 */
.errorbar {
  background: #45181b;
  color: #fca5a5;
  padding: 10px 24px;
  font-size: 13px;
  border-top: 1px solid #5b2a2e;
}

/* 输入区：大胶囊输入条 */
.inputbar {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 10px 24px 18px;
  background: transparent;
  border-top: none;
}
.mode {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 9px;
  border-radius: 8px;
  background: rgba(14, 23, 40, 0.7);
  border: 1px solid #2a3a55;
  font-size: 11px;
  color: #9fb4d4;
  cursor: pointer;
  flex-shrink: 0;
  align-self: flex-end;
  user-select: none;
  transition: border-color 0.15s;
}
.mode:hover { border-color: #3b82c4; }
.m-caret { color: #5f7aa0; font-size: 10px; }
.mode-menu {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  min-width: 120px;
  background: #16223a;
  border: 1px solid #2a3a55;
  border-radius: 12px;
  padding: 4px;
  box-shadow: 0 -6px 20px rgba(0, 0, 0, 0.4), 0 8px 24px rgba(0, 0, 0, 0.25);
  z-index: 10;
}
.mode-opt {
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
  color: #c4d4ec;
  cursor: pointer;
}
.mode-opt:hover { background: #1d2b47; color: #dbeafe; }
.mode-opt.on { color: #60a5fa; font-weight: 600; }
.composer {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #16223a;
  border: 1px solid #2a3a55;
  border-radius: 16px;
  padding: 12px 14px 10px;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}
.composer:hover {
  border-color: rgba(59, 130, 196, 0.6);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);
}
.composer:focus-within {
  border-color: #3b82c4;
  box-shadow: 0 0 0 3px rgba(59, 130, 196, 0.15);
}
.composer textarea {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  color: #e5eaf1;
  font-size: 14px;
  line-height: 1.5;
  max-height: 140px;
  font-family: inherit;
}
.composer textarea::placeholder { color: #5f7aa0; }
.composer textarea:disabled { cursor: not-allowed; }
.composer-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}
.bar-right { margin-left: auto; display: flex; gap: 8px; }
.send {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: linear-gradient(135deg, #2563eb, #3b82c4);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
}
.send:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4);
}
.send:disabled { background: #22304a; color: #5f7aa0; cursor: not-allowed; }
.stop {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border: none;
  border-radius: 50%;
  background: #7f1d1d;
  color: #fca5a5;
  font-size: 13px;
  cursor: pointer;
}
</style>
