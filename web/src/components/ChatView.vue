<script setup>
import { ref, computed, watch, reactive, onBeforeUnmount, onMounted } from 'vue'
import { useChat } from '@ai-sdk/vue'
import { DefaultChatTransport, isToolUIPart, getToolName } from 'ai'
import { marked } from 'marked'
import SalaryChart from './SalaryChart.vue'
import RentChart from './RentChart.vue'
import ThemeToggle from './ThemeToggle.vue'
import Sidebar from './Sidebar.vue'

// 回答模式：brief / standard / report
const mode = ref('standard')
const input = ref('')
const MODES = [
  { label: '简洁', value: 'brief', desc: '只给结论，快速回答', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>' },
  { label: '标准', value: 'standard', desc: '结论 + 简要说明', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>' },
  { label: '详细', value: 'report', desc: '完整报告，含计算过程', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>' },
]
const modeOpen = ref(false)
function modeLabel(v) {
  const m = MODES.find(x => x.value === v)
  return m ? m.label : '标准'
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
    body: () => ({
      mode: mode.value || null,
      // 临时会话 id 不传给后端，让后端创建真正的会话
      conversationId: convId.value && !convId.value.startsWith('temp-') ? convId.value : null,
    }),
  }),
  onFinish: async () => {
    // 记录最后一条 AI 消息的结束时间
    const lastAiMsg = [...messages.value].reverse().find(m => m.role === 'assistant')
    if (lastAiMsg?.id) msgEndTimes[lastAiMsg.id] = Date.now()
    // 新建会话首次发消息后，后端自动建了会话，刷新列表拿到 id
    await loadConvs()
    // 如果当前是临时会话 id，替换成后端真正的会话 id
    if (convId.value.startsWith('temp-') && conversations.value.length > 0) {
      convId.value = conversations.value[0].id
      localStorage.setItem('convId', convId.value)
    }
  },
})

// ---- 会话管理（SQLite 持久化）----
const convId = ref(localStorage.getItem('convId') || '')
const sidebarOpen = ref(true)
const conversations = ref([])
// 消息编辑状态
const editingId = ref(null)
const editText = ref('')
const editInputRef = ref(null)

async function loadConvs() {
  try {
    const r = await fetch('/api/conversations')
    conversations.value = await r.json()
  } catch { conversations.value = [] }
}
async function newConv() {
  // 只清空前端视图，不立即创建 DB 记录；发第一条消息时后端自动建会话
  convId.value = ''
  localStorage.removeItem('convId')
  messages.value = []
  // 不调 loadConvs()，避免异步覆盖掉 submit() 里插入的临时会话项
}
async function selectConv(id) {
  convId.value = id
  localStorage.setItem('convId', id)
  const r = await fetch(`/api/conversations/${id}/messages`)
  const msgs = await r.json()
  messages.value = msgs.map(m => ({ id: m.id, role: m.role, parts: m.parts }))
}
async function renameConv({ id, title }) {
  await fetch(`/api/conversations/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
  })
  loadConvs()
}
async function deleteConv(id) {
  try {
    const r = await fetch(`/api/conversations/${id}`, { method: 'DELETE' })
    if (!r.ok) console.error('delete failed:', r.status)
  } catch (e) { console.error('delete error:', e) }
  if (convId.value === id) {
    convId.value = ''
    localStorage.removeItem('convId')
    messages.value = []
  }
  await loadConvs()
}
onMounted(() => {
  loadConvs()
  // 上次未关闭的会话，自动载入历史
  if (convId.value) selectConv(convId.value)
})

const PRESETS = [
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/><path d="M3 7V5a2 2 0 0 1 2-2h11"/><circle cx="15" cy="13.5" r="1.3"/></svg>', text: '上海月薪 2 万，到手能拿多少？' },
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10 12 3l9 7"/><path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8"/><path d="M3 21h18"/></svg>', text: '上海社保公积金怎么缴？' },
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-8 9 8"/><path d="M5 9.5V20h14V9.5"/><path d="M10 20v-5h4v5"/></svg>', text: '上海月租 5000，租房要准备多少钱？' },
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M10 13h6M10 17h6"/></svg>', text: '帮我把测算结果整理成一份报告' },
]

function submit(text) {
  const q = (text ?? input.value).trim()
  if (!q) return

  // 新建会话时，先在侧边栏插入临时会话项，让用户立刻看到标题 + loading
  if (!convId.value) {
    const tempId = 'temp-' + Date.now()
    const tempTitle = q.length > 20 ? q.slice(0, 20) + '…' : q
    conversations.value.unshift({
      id: tempId,
      title: tempTitle,
      updated_at: Date.now() / 1000,
    })
    convId.value = tempId
    localStorage.setItem('convId', tempId)
  }

  sendMessage({ text: q })
  input.value = ''
  scrollToBottom(true)
}

// 多行输入框自动增高（上限 140px）
function autoGrow(e) {
  const t = e.target
  t.style.height = 'auto'
  t.style.height = Math.min(t.scrollHeight, 140) + 'px'
}

// 渲染前清理 markdown 源：把段落间的连续空行压缩成单个（使排版紧凑），
// 但完整保护 fenced code 块（``` 内部原样），不破坏列表 / 表格结构。
function cleanMd(src) {
  const lines = (src || '').split('\n')
  let inCode = false
  let blank = 0
  const out = []
  for (const line of lines) {
    if (/^```/.test(line)) {
      inCode = !inCode
      blank = 0
      out.push(line)
      continue
    }
    if (inCode) {
      out.push(line)
      continue
    }
    if (line.trim() === '') {
      blank++
      if (blank <= 1) out.push('')
      continue
    }
    blank = 0
    out.push(line)
  }
  return out.join('\n')
}

// Markdown → HTML 渲染（Agent 回答里的表格/标题/加粗）
function md(src) {
  return marked.parse(cleanMd(src))
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
      if (p.type === 'reasoning') return { key: i, kind: 'reasoning', text: p.text || '' }
      if (p.type === 'data-salary') return { key: i, kind: 'chart', data: p.data }
      if (p.type === 'data-rent') return { key: i, kind: 'chart', data: p.data }
      // 后端落库的 tool part 结构
      if (p.type === 'tool') {
        return {
          key: i,
          kind: 'tool',
          name: p.name || '',
          running: false,
          input: p.input,
          output: p.output,
          done: true,
        }
      }
      // AI SDK 流式输出的 tool UI part
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

// 把连续的 text 段合并成一段，避免流式分段导致 markdown 解析不完整
function groupedParts(m) {
  const parts = agentParts(m)
  const result = []
  let textBuffer = []
  let textStartKey = 0
  // chart 去重：相同城市+薪资的图表只保留最后一个
  const chartSeen = new Map()

  // 先收集所有 chart 的位置，标记需要去重的
  parts.forEach((p, idx) => {
    if (p.kind === 'chart') {
      const k = p.data?.monthly_salary != null
        ? `${p.data.city || ''}-s-${p.data.monthly_salary}`
        : p.data?.monthly_rent != null
          ? `${p.data.city || ''}-r-${p.data.monthly_rent}`
          : `c-${idx}`
      chartSeen.set(k, idx) // 记录最后出现的位置
    }
  })

  for (const p of parts) {
    if (p.kind === 'text') {
      if (textBuffer.length === 0) textStartKey = p.key
      textBuffer.push(p.text)
    } else {
      if (textBuffer.length > 0) {
        result.push({ key: 'text-' + textStartKey, kind: 'text', text: textBuffer.join('') })
        textBuffer = []
      }
      // chart 去重：如果不是最后一个相同 key 的 chart，跳过
      if (p.kind === 'chart') {
        const k = p.data?.monthly_salary != null
          ? `${p.data.city || ''}-s-${p.data.monthly_salary}`
          : p.data?.monthly_rent != null
            ? `${p.data.city || ''}-r-${p.data.monthly_rent}`
            : `c-${parts.indexOf(p)}`
        if (chartSeen.get(k) !== parts.indexOf(p)) continue // 不是最后一个，跳过
      }
      result.push(p)
    }
  }
  if (textBuffer.length > 0) {
    result.push({ key: 'text-' + textStartKey, kind: 'text', text: textBuffer.join('') })
  }
  return result
}

// 图表去重：相同城市 + 相同月薪只保留第一张
function uniqueCharts(m) {
  const seen = new Set()
  return agentParts(m).filter(x => x.kind === 'chart').filter(x => {
    const k =
      x.data.monthly_salary != null
        ? `${x.data.city || ''}-s-${x.data.monthly_salary}`
        : x.data.monthly_rent != null
          ? `${x.data.city || ''}-r-${x.data.monthly_rent}`
          : `c-${x.key}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

function toolsOf(m) {
  return agentParts(m).filter(x => x.kind === 'tool')
}

const busy = computed(() => status.value === 'streaming' || status.value === 'submitted')
const statusLabel = computed(() => {
  if (status.value === 'submitted') return '思考中'
  if (status.value === 'streaming') return '生成中'
  if (status.value === 'error') return '出错'
  return '就绪'
})
const statusTone = computed(() => {  if (status.value === 'streaming' || status.value === 'submitted') return 'busy'
  if (status.value === 'error') return 'err'
  return 'idle'
})

// 当前会话标题：从侧边栏列表里找，找不到就用第一条用户消息前 20 字
const currentTitle = computed(() => {
  const cv = conversations.value.find(c => c.id === convId.value)
  if (cv) return cv.title
  // 新建会话还没建 DB 记录时，用第一条用户消息当标题
  const firstUser = messages.value.find(m => m.role === 'user')
  if (firstUser) return userText(firstUser).slice(0, 20)
  return '新会话'
})

// 最后一条助手消息（可能还在生成）
const lastAssistant = computed(() => {
  const ms = messages.value
  for (let i = ms.length - 1; i >= 0; i--) {
    if (ms[i].role === 'assistant') return ms[i]
  }
  return null
})
// 是否已产出任何内容（文本 / 工具过程）
function hasOutput(m) {
  if (!m) return false
  return agentParts(m).some(x => (x.kind === 'text' && x.text) || x.kind === 'reasoning') || toolsOf(m).length > 0
}

// 判断是不是当前正在生成的最后一条 assistant 消息
function isLastAssistantMsg(m) {
  const msgs = messages.value
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'assistant') {
      return msgs[i].id === m.id
    }
  }
  return false
}

// 历史消息：把所有思考过程和工具调用合并成一个总的折叠面板
// text 和 chart 保持原始顺序穿插
function historyParts(m) {
  const parts = agentParts(m)
  const processes = parts.filter(p => p.kind === 'reasoning' || p.kind === 'tool')
  // text 和 chart 保持原始顺序
  const content = parts.filter(p => p.kind === 'text' || p.kind === 'chart')
  return { content, processes }
}
// 生成中但尚无内容 → 显示「思考中」友好提示
const showThinking = computed(() => {
  return busy.value && !hasOutput(lastAssistant.value)
})

// 消息时间戳与操作
const msgTimes = reactive({})
const msgEndTimes = reactive({})
watch(messages, (ms) => {
  for (const m of ms) {
    if (m.id && msgTimes[m.id] == null) msgTimes[m.id] = Date.now()
  }
}, { deep: true })

// 格式化用时
function fmtDuration(startTs, endTs) {
  if (!startTs || !endTs) return ''
  const sec = Math.round((endTs - startTs) / 1000)
  if (sec < 60) return `共用时 ${sec} 秒`
  const min = Math.floor(sec / 60)
  const restSec = sec % 60
  return `共用时 ${min} 分 ${restSec} 秒`
}
const copiedId = ref(null)
function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const now = new Date()
  const pad = n => String(n).padStart(2, '0')
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  const sameDay = d.toDateString() === now.toDateString()
  const yest = new Date(now)
  yest.setDate(now.getDate() - 1)
  if (sameDay) return `今天 ${hm}`
  if (d.toDateString() === yest.toDateString()) return `昨天 ${hm}`
  return `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}
function msgText(m) {
  if (m.role === 'user') return userText(m)
  return agentParts(m).filter(x => x.kind === 'text').map(x => x.text).join('')
}
async function copyMsg(m) {
  const t = msgText(m)
  if (!t) return
  try {
    await navigator.clipboard.writeText(t)
    copiedId.value = m.id
    setTimeout(() => { if (copiedId.value === m.id) copiedId.value = null }, 1500)
  } catch { /* 剪贴板不可用时静默降级 */ }
}
function regenerate(m) {
  const t = userText(m)
  if (!t) return
  // 把消息放到输入框里，让用户编辑后重新发送
  input.value = t
  // 聚焦输入框
  nextTick(() => {
    const ta = document.querySelector('.composer textarea')
    if (ta) ta.focus()
  })
}

// 开始编辑用户消息
function startEdit(m) {
  editingId.value = m.id
  editText.value = userText(m)
  // 自动调整输入框高度
  setTimeout(() => {
    const ta = document.querySelector('.edit-input')
    if (ta) {
      ta.style.height = 'auto'
      ta.style.height = ta.scrollHeight + 'px'
    }
  }, 50)
}

// 取消编辑
function cancelEdit() {
  editingId.value = null
  editText.value = ''
}

// 编辑输入框自动高度
function autoGrowEdit(e) {
  const ta = e.target
  ta.style.height = 'auto'
  ta.style.height = ta.scrollHeight + 'px'
}

// 确认编辑并重新发送
function confirmEdit(m) {
  const t = editText.value.trim()
  if (!t) return
  // 更新消息内容
  m.parts = [{ type: 'text', text: t }]
  cancelEdit()
  // 重新发送
  sendMessage({ text: t })
}

// 滚动条：仅滚动时浮现，停止后淡出隐藏
const msgScrolling = ref(false)
let scrollTimer = null

// 流式输出时自动滚到底部（仅当用户在底部时）
const messagesEl = ref(null)
const isAtBottom = ref(true)

function checkIfAtBottom() {
  const el = messagesEl.value
  if (!el) return
  isAtBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

function scrollToBottom(force = false) {
  requestAnimationFrame(() => {
    const el = messagesEl.value
    if (el && (force || isAtBottom.value)) {
      el.scrollTop = el.scrollHeight
    }
  })
}

function onMsgScroll() {
  msgScrolling.value = true
  clearTimeout(scrollTimer)
  scrollTimer = setTimeout(() => {
    msgScrolling.value = false
  }, 900)
  checkIfAtBottom()
}

// 深度监听消息内容变化，流式输出时持续滚动
watch(() => JSON.stringify(messages.value), () => {
  scrollToBottom()
})

// 切换会话时强制滚到底部
watch(() => convId.value, () => scrollToBottom(true))
onBeforeUnmount(() => clearTimeout(scrollTimer))
</script>

<template>
  <div class="app" @click="modeOpen = false">
    <Sidebar
      :conversations="conversations"
      :active-id="convId"
      :open="sidebarOpen"
      :status-tone="statusTone"
      :status-label="statusLabel"
      @close="sidebarOpen = false"
      @new="newConv"
      @select="selectConv"
      @rename="renameConv"
      @delete="deleteConv"
    />
    <div class="inner">
    <!-- 顶栏：收起时显示汉堡，展开时显示当前会话标题 -->
    <header class="topbar" :class="{ 'has-title': messages.length > 0 }">
      <button v-if="!sidebarOpen" class="hamburger" @click.stop="sidebarOpen = true" aria-label="展开侧栏" data-tip="展开侧栏">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="4"/><line x1="14" y1="4" x2="14" y2="20"/></svg>
      </button>
      <div v-if="messages.length > 0" class="topbar-title">{{ currentTitle }}
        <span class="topbar-disclaimer">AI 生成内容可能有误，关键数据请以官方来源为准</span>
      </div>
    </header>

    <!-- 消息区 -->
    <div ref="messagesEl" class="messages" :class="{ scrolling: msgScrolling }" @scroll="onMsgScroll">
      <!-- 初始态 -->
      <div v-if="messages.length === 0" class="welcome">
        <div class="w-title">城市生活的账，帮你算清楚</div>
        <div class="w-sub">工资到手、社保公积金、租房成本，先从这里问起</div>
        <div class="presets">
          <button
            v-for="p in PRESETS"
            :key="p.text"
            class="preset"
            @click="submit(p.text)"
            :disabled="status !== 'ready'"
          >
            <span class="p-icon" v-html="p.icon"></span>
            <span class="p-label">{{ p.text }}</span>
            <span class="p-arrow">→</span>
          </button>
        </div>
      </div>

      <!-- 对话 -->
      <template v-for="m in messages" :key="m.id">
        <div v-if="m.role === 'user'" class="row user-row">
          <!-- 编辑状态：显示输入框 -->
          <div v-if="editingId === m.id" class="bubble user edit-bubble">
            <textarea
              v-model="editText"
              class="edit-input"
              @input="autoGrowEdit"
              @keydown.enter.prevent="confirmEdit(m)"
              @keydown.esc="cancelEdit"
            ></textarea>
            <div class="edit-actions">
              <button class="edit-btn cancel" @click="cancelEdit">取消</button>
              <button class="edit-btn confirm" @click="confirmEdit(m)">发送</button>
            </div>
          </div>
          <!-- 正常状态：显示消息文本 -->
          <template v-else>
            <div class="bubble user">{{ userText(m) }}</div>
            <div class="msg-meta">
              <span class="m-time">{{ fmtTime(msgTimes[m.id]) }}</span>
              <span class="m-acts">
                <button class="m-act" :class="{ ok: copiedId === m.id }" @click="copyMsg(m)" data-tip="复制">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>
                </button>
                <button class="m-act" @click="startEdit(m)" data-tip="修改">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                </button>
              </span>
            </div>
          </template>
        </div>

        <div v-else class="row agent-row">
          <div class="avatar a">
            <img src="/ai-avatar.svg" alt="AI" style="width:100%;height:100%;border-radius:9px"/>
          </div>
          <div class="agent-body">
            <!-- 思考中占位：尚未产出任何内容时的友好提示 -->
            <div v-if="showThinking" class="thinking">让我算一算<span class="dots"><i></i><i></i><i></i></span></div>

            <!-- 当前正在生成的消息：穿插式展示 -->
            <template v-if="isLastAssistantMsg(m) && status === 'streaming'">
              <template v-for="p in groupedParts(m)" :key="p.key">
                <!-- 思考过程：生成中展开 -->
                <div v-if="p.kind === 'reasoning'" class="reasoning">
                  <details :open="true">
                    <summary>
                      <span class="r-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                          <path d="M9 18h6"/>
                          <path d="M10 22h4"/>
                          <path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0 0 12 2z"/>
                        </svg>
                      </span>
                      <span class="r-label">思考过程</span>
                      <span class="r-toggle">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                          <path d="M9 18l6-6-6-6"/>
                        </svg>
                      </span>
                      <span class="r-duration">{{ fmtDuration(msgTimes[m.id], msgEndTimes[m.id]) }}</span>
                    </summary>
                    <div class="r-body">{{ p.text }}</div>
                  </details>
                </div>

                <!-- 工具调用：每个单独一行 -->
                <div v-else-if="p.kind === 'tool'" class="process">
                  <div class="process-head" @click="toggleTool(p.key)">
                    <span class="p-icon">⚙</span>
                    <span class="p-text">
                      {{ p.running ? '正在调用工具…' : p.name }}
                    </span>
                    <span v-if="p.running" class="ti-state run">进行中…</span>
                    <span v-else class="ti-state ok">完成</span>
                    <span v-if="p.done" class="p-toggle chev" :class="{ open: expanded.has(p.key) }">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M9 18l6-6-6-6"/>
                      </svg>
                    </span>
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

                <!-- 图表 -->
                <div v-else-if="p.kind === 'chart'" class="chart-wrap">
                  <SalaryChart v-if="p.data && p.data.net != null" :data="p.data" />
                  <RentChart v-else-if="p.data && p.data.total != null" :data="p.data" />
                </div>

                <!-- 文本回复 -->
                <div v-else-if="p.kind === 'text'" class="markdown" v-html="md(p.text)"></div>
              </template>
            </template>

            <!-- 历史消息：思考过程折叠面板在最上面，然后分隔线，然后是最终回复 -->
            <template v-else>
              <!-- 总的思考过程折叠面板（在最上面） -->
              <details v-if="historyParts(m).processes.length > 0" class="reasoning history-reasoning">
                <summary>
                  <span class="r-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M9 18h6"/>
                      <path d="M10 22h4"/>
                      <path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0 0 12 2z"/>
                    </svg>
                  </span>
                  <span class="r-label">思考过程</span>
                  <span class="r-count">{{ historyParts(m).processes.length }}</span>
                  <span class="r-toggle">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M9 18l6-6-6-6"/>
                    </svg>
                  </span>
                  <span class="r-duration">{{ fmtDuration(msgTimes[m.id], msgEndTimes[m.id]) }}</span>
                </summary>
                <div class="r-body">
                  <div v-for="(proc, i) in historyParts(m).processes" :key="'proc-' + i" class="proc-item">
                    <template v-if="proc.kind === 'reasoning'">
                      <div class="proc-label">💭 思考</div>
                      <div class="proc-text">{{ proc.text }}</div>
                    </template>
                    <template v-else-if="proc.kind === 'tool'">
                      <details class="proc-tool">
                        <summary>
                          <span class="proc-label">⚙ {{ proc.name }}</span>
                          <span class="proc-status">完成</span>
                          <span class="proc-toggle">›</span>
                        </summary>
                        <div class="proc-detail">
                          <div v-if="proc.input && Object.keys(proc.input).length" class="td">
                            <span class="td-label">输入参数</span>
                            <pre class="td-pre">{{ fmt(proc.input) }}</pre>
                          </div>
                          <div v-if="proc.output" class="td">
                            <span class="td-label">返回结果</span>
                            <pre class="td-pre">{{ proc.output }}</pre>
                          </div>
                        </div>
                      </details>
                    </template>
                  </div>
                </div>
              </details>
              <!-- 分隔线 -->
              <div v-if="historyParts(m).processes.length > 0" class="history-divider"></div>
              <!-- 最终回复内容：text 和 chart 按原始顺序穿插 -->
              <template v-for="p in historyParts(m).content" :key="'content-' + p.key">
                <div v-if="p.kind === 'text'" class="markdown history-text" v-html="md(p.text)"></div>
                <div v-else-if="p.kind === 'chart'" class="chart-wrap">
                  <SalaryChart v-if="p.data && p.data.net != null" :data="p.data" />
                  <RentChart v-else-if="p.data && p.data.total != null" :data="p.data" />
                </div>
              </template>
            </template>
          </div>
          <div v-if="!isLastAssistantMsg(m) || status !== 'streaming'" class="msg-meta agent-meta">
            <span class="m-acts">
              <button class="m-act" :class="{ ok: copiedId === m.id }" @click="copyMsg(m)" data-tip="复制">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>
              </button>
              <button class="m-act" @click="regenerate(m)" data-tip="重新生成">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/></svg>
              </button>
              <button class="m-act" data-tip="收藏">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                </svg>
              </button>
            </span>
            <span class="m-time">{{ fmtTime(msgTimes[m.id]) }}</span>
          </div>
        </div>
      </template>
    </div>

    <!-- 错误条 -->
    <div v-if="error" class="errorbar">出错：{{ error.message || error }}</div>

    <!-- 输入区：大胶囊输入条 -->
    <div class="inputbar">
      <div class="composer">
        <textarea
          v-model="input"
          rows="1"
          placeholder="问我关于工资到手、社保公积金、租房成本的问题…"
          :disabled="status !== 'ready'"
          @input="autoGrow"
          @keydown.enter.exact.prevent="submit()"
        ></textarea>
        <div class="composer-bar">
          <div class="mode" @click.stop="modeOpen = !modeOpen" data-tip="回答风格">
            <svg class="m-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="8" y1="6" x2="21" y2="6"/>
              <line x1="8" y1="12" x2="21" y2="12"/>
              <line x1="8" y1="18" x2="21" y2="18"/>
              <line x1="3" y1="6" x2="3.01" y2="6"/>
              <line x1="3" y1="12" x2="3.01" y2="12"/>
              <line x1="3" y1="18" x2="3.01" y2="18"/>
            </svg>
            <span class="m-label">{{ modeLabel(mode) }}</span>
            <svg class="m-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M6 9l6 6 6-6"/>
            </svg>
            <div v-if="modeOpen" class="mode-menu">
              <div
                v-for="opt in MODES"
                :key="opt.value"
                class="mode-opt"
                :class="{ on: mode === opt.value }"
                @click.stop="pickMode(opt.value)"
              >
                <div class="opt-text">
                  <span class="opt-icon" v-html="opt.icon"></span>
                  <div class="opt-labels">
                    <div class="opt-label">{{ opt.label }}</div>
                    <div class="opt-desc">{{ opt.desc }}</div>
                  </div>
                </div>
                <span v-if="mode === opt.value" class="opt-check">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M20 6L9 17l-5-5"/>
                  </svg>
                </span>
              </div>
            </div>
          </div>
          <div class="bar-right">
            <button
              v-if="status !== 'streaming'"
              class="send"
              :disabled="status !== 'ready'"
              @click="submit()"
              aria-label="发送"
              data-tip="发送"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>
            </button>
            <button v-if="status === 'streaming'" class="stop" @click="stop" aria-label="停止" data-tip="停止生成">
              <svg viewBox="0 0 24 24" fill="currentColor"><rect x="4.5" y="4.5" width="15" height="15" rx="2.5"/></svg>
            </button>
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
  display: flex;
  overflow: hidden;
  background:
    radial-gradient(1200px 520px at 50% -8%, var(--glow), transparent 60%),
    radial-gradient(900px 460px at 88% 108%, var(--glow2), transparent 60%),
    linear-gradient(180deg, var(--bg-base) 0%, var(--bg-grad-end) 100%);
  color: var(--text);
}
.inner {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* 顶栏 */
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  border-bottom: none;
  min-height: 60px;
}
.topbar.has-title {
  border-bottom: 1px solid var(--border-soft);
}
.topbar-title {
  font-size: 14px;
  color: var(--text);
  font-weight: 500;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.topbar-disclaimer {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-faint);
}
.disclaimer {
  text-align: center;
  font-size: 11px;
  color: var(--text-faint);
  padding: 0 0 8px;
}
.hamburger {
  width: 38px; height: 38px; display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--border); border-radius: 10px; background: transparent;
  color: var(--text-2); cursor: pointer; transition: background .15s, color .15s;
}
.hamburger:hover { background: var(--border-line); color: var(--text); }
.hamburger svg { width: 24px; height: 24px; }
.hamburger:hover::after {
  bottom: auto;
  top: calc(100% + 6px);
}
.header-right {
  display: flex;
  align-items: center;
}
.logo {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  color: var(--text-on-accent);
  border-radius: 10px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  box-shadow: 0 4px 14px var(--accent-glow);
}
header h1 {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-strong);
}
.header-status {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--text-dim);
  padding: 5px 12px;
  border-radius: 999px;
  background: var(--panel-soft-trans);
  border: 1px solid var(--border);
}
.header-status .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.header-status.idle .dot { background: var(--ok); }
.header-status.busy .dot { background: var(--warn); animation: pulse 1.2s infinite; }
.header-status.err .dot { background: var(--err); }
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
  padding: 26px 28px 30px;
  scrollbar-width: thin;
  scrollbar-color: transparent transparent;
  transition: scrollbar-color 0.3s;
}
.messages > * {
  width: 100%;
  max-width: min(1080px, calc(100vw - 320px));
  margin-left: auto;
  margin-right: auto;
}
.messages.scrolling {
  scrollbar-color: var(--border-strong) transparent;
}
.messages::-webkit-scrollbar { width: 8px; }
.messages::-webkit-scrollbar-track { background: transparent; }
.messages::-webkit-scrollbar-thumb {
  background: transparent;
  border-radius: 4px;
  transition: background 0.3s;
}
.messages.scrolling::-webkit-scrollbar-thumb {
  background: var(--border-strong);
}

/* 初始态 */
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 6vh auto 0 auto;
  padding: 20px 0;
  text-align: center;
}
.w-title {
  font-size: 32px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--text-stronger);
}
.w-sub {
  font-size: 15px;
  color: var(--text-dim);
  margin-top: 12px;
}
.presets {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-top: 36px;
  max-width: 640px;
  width: 100%;
  text-align: left;
}
.preset {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 14px;
  background: var(--panel-trans);
  border: 1px solid var(--border-strong);
  color: var(--text-2);
  font-size: 14px;
  line-height: 1.4;
  cursor: pointer;
  transition: all 0.15s;
}
.preset:hover {
  background: var(--panel-hover);
  border-color: var(--accent);
  color: var(--text-strong);
  transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
}
.p-icon { font-size: 18px; flex-shrink: 0; }
.preset .p-icon {
  width: 18px;
  height: 18px;
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
}
.preset .p-icon :deep(svg) {
  width: 18px;
  height: 18px;
}
.p-label { flex: 1; }
.p-arrow { color: var(--text-faint); flex-shrink: 0; }
.preset:disabled { opacity: 0.5; cursor: not-allowed; }

/* 消息行 */
.row {
  position: relative;
  display: flex;
  gap: 12px;
  margin-bottom: 18px;
  align-items: flex-start;
}
.user-row { flex-direction: column; align-items: flex-end; }
.user-row .msg-meta { position: static; margin-top: 7px; }
.edit-bubble {
  padding: 12px 16px;
  background: linear-gradient(135deg, var(--accent), var(--accent-deep));
  color: #fff;
  border-radius: 14px;
  border-top-right-radius: 4px;
  display: inline-flex;
  flex-direction: column;
  width: 50%;
  max-width: 50%;
}
.edit-input {
  border: none;
  background: transparent;
  resize: none;
  outline: none;
  font-size: 16px;
  line-height: 1.7;
  color: #fff;
  padding: 0;
  width: 100%;
  min-width: 300px;
  font-family: inherit;
}
.edit-input::placeholder {
  color: rgba(255, 255, 255, 0.6);
}
.edit-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 8px;
}
.edit-btn {
  padding: 4px 12px;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  font-size: 13px;
}
.edit-btn.cancel {
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
}
.edit-btn.confirm {
  background: #fff;
  color: var(--accent, #4f6ef7);
}
.agent-row .msg-meta { left: 42px; right: auto; bottom: -30px; }
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
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  color: var(--text-on-accent);
  font-size: 14px;
}
.bubble {
  max-width: 76%;
  padding: 12px 16px;
  border-radius: 14px;
  font-size: 16px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubble.user {
  background: linear-gradient(135deg, var(--accent), var(--accent-deep));
  color: #fff;
  border-top-right-radius: 4px;
}
.bubble.agent {
  background: transparent;
  border: none;
  color: var(--text);
  max-width: 100%;
  padding: 0;
  box-shadow: none;
}
/* hover 操作栏：时间戳 + 功能 */
.msg-meta {
  position: absolute;
  right: 0;
  bottom: -20px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-faint);
  opacity: 0;
  transition: opacity 0.15s;
  z-index: 3;
}
.row:hover .msg-meta { opacity: 1; }
/* AI 消息的操作栏：始终显示 */
.agent-meta {
  opacity: 1;
}
.m-time { margin-right: 2px; font-size: 14px; }
.m-acts { display: flex; align-items: center; gap: 4px; }
.m-act {
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-dim);
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
}
.m-act svg { width: 16px; height: 16px; }
.m-act:hover { background: var(--panel-hover); color: var(--text-strong); }
.m-act.ok { color: var(--ok); }
.markdown { line-height: 1.5; }
.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3) {
  margin: 5px 0 1px;
  font-weight: 600;
  color: var(--text-strong);
}
.markdown :deep(h2) { font-size: 18px; }
.markdown :deep(p) { margin: 8px 0; }
.markdown :deep(strong) { color: var(--text-strong); }
.markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 15px;
}
.markdown :deep(th),
.markdown :deep(td) {
  border: 1px solid var(--border-line);
  padding: 4px 8px;
  text-align: left;
  vertical-align: top;
}
.markdown :deep(th) { background: var(--panel-th); color: var(--text-2); border-bottom: 1px solid var(--border-strong); }
.markdown :deep(tbody tr:nth-child(even) td) { background: var(--panel-zebra); }
.markdown :deep(code) {
  background: var(--panel-code);
  border: 1px solid var(--border);
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 16px;
  font-family: Consolas, Monaco, 'Courier New', monospace;
}
.markdown :deep(ul),
.markdown :deep(ol) { margin: 8px 0 8px 20px; padding-left: 0; }
.markdown :deep(li) { margin: 4px 0; }
.markdown :deep(a) { color: var(--text-link); text-decoration: underline; text-underline-offset: 3px; }
.markdown :deep(a:hover) { color: var(--accent-deep); }
.markdown :deep(h1) { font-size: 18px; }
.markdown :deep(pre) {
  background: var(--panel-code);
  border: 1px solid var(--border-line);
  border-radius: 8px;
  padding: 10px 12px;
  overflow-x: auto;
  margin: 6px 0;
  font-size: 14px;
  line-height: 1.5;
}
.markdown :deep(pre code) { background: transparent; padding: 0; }
/* 引用块：调轻，视觉退到辅助说明位置 */
.markdown :deep(blockquote) {
  border-left: 2px solid var(--accent-soft);
  padding: 4px 9px;
  margin: 3px 0;
  color: var(--text-muted);
  font-size: 16px;
  background: var(--panel-soft);
  border-radius: 0 8px 8px 0;
}
.agent-body { flex: 1; min-width: 0; }

/* 工具过程：折叠条 */
.process {
  margin-bottom: 10px;
  border-radius: 10px;
  overflow: hidden;
}
.process-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  margin: 0 -8px;
  font-size: 13px;
  cursor: pointer;
  border-radius: 8px;
  color: var(--text-3);
  transition: background 0.15s;
}
.process-head:hover { background: var(--panel-hover2); }
.process-head .p-icon { color: var(--warn); }
.p-text { color: var(--text-2); }
.p-toggle {
  color: var(--text-dim);
  width: 14px;
  height: 14px;
  display: inline-flex;
  transition: transform 0.15s;
}
.p-toggle svg { width: 100%; height: 100%; }
.chev.open { transform: rotate(90deg); }
.process-list { padding: 4px 0; }
.tool-item { border-bottom: 1px solid var(--border-line); }
.tool-item:last-child { border-bottom: none; }
.tool-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  font-size: 13px;
  cursor: pointer;
}
.tool-head:hover { background: var(--panel-hover2); }
.ti-name { color: var(--text); font-weight: 600; }
.ti-state.ok { color: var(--ok); }
.ti-state.run { color: var(--warn); }
.ti-toggle {
  color: var(--text-dim);
  width: 14px;
  height: 14px;
  display: inline-flex;
  transition: transform 0.15s;
}
.ti-toggle svg { width: 100%; height: 100%; }
.tool-detail { padding: 8px 12px 10px; }
.td { margin-bottom: 6px; }
.td:last-child { margin-bottom: 0; }
.td-label { color: var(--text-dim); font-size: 11px; display: block; margin-bottom: 2px; }
.td-pre {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-2);
  background: var(--panel-deep);
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 13px;
  margin: 0;
}

/* 图表 */
.chart-wrap {
  margin: 8px 0 12px;
  background: var(--panel-soft-trans);
  border: none;
  border-radius: 12px;
  padding: 10px;
}

/* 思考过程折叠区 */
.reasoning { margin-bottom: 4px; }
.reasoning summary {
  display: flex;
  align-items: center;
  gap: 6px;
  list-style: none;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-dim);
  padding: 5px 8px;
  margin: 0 -8px;
  border-radius: 8px;
  user-select: none;
}
.reasoning summary::-webkit-details-marker { display: none; }
.reasoning summary:hover { background: var(--panel-hover2); }
.reasoning .r-icon {
  width: 14px;
  height: 14px;
  color: var(--text-faint);
  display: inline-flex;
  flex-shrink: 0;
}
.reasoning .r-icon svg { width: 100%; height: 100%; }
.reasoning .r-label { color: var(--text-dim); }
.reasoning .r-duration {
  color: var(--text-faint);
  font-size: 12px;
  margin-left: auto;
  margin-right: 8px;
}
.reasoning .r-toggle {
  color: var(--text-faint);
  width: 14px;
  height: 14px;
  display: inline-flex;
  transition: transform 0.15s;
}
.reasoning .r-toggle svg { width: 100%; height: 100%; }
.reasoning details[open] .r-toggle { transform: rotate(90deg); }
.reasoning .r-body {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-muted);
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--panel-soft);
  border-radius: 8px;
  padding: 8px 12px;
  margin-top: 4px;
  max-height: 200px;
  overflow-y: auto;
}

/* 历史消息：总的思考过程折叠面板 */
.history-reasoning {
  margin-bottom: 8px;
}
.history-divider {
  height: 1px;
  background: var(--border-line, #e5e7eb);
  margin: 8px 0 12px;
}
.history-text {
  margin-bottom: 12px;
}
.history-text:last-child {
  margin-bottom: 0;
}
.history-text p {
  margin: 8px 0;
}
.history-text h1,
.history-text h2,
.history-text h3 {
  margin: 16px 0 8px;
}
.history-reasoning .r-count {
  color: var(--text-faint, #9ca3af);
  font-size: 12px;
  margin-left: 2px;
}
.history-reasoning .r-body {
  max-height: none;
  overflow-y: visible;
  background: transparent;
  padding: 4px 0 0 0;
  margin-top: 0;
}
.history-reasoning .proc-item {
  padding: 6px 0;
  border-bottom: 1px solid var(--border-line, #f0f0f0);
}
.history-reasoning .proc-item:last-child {
  border-bottom: none;
}
.history-reasoning .proc-label {
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 2px;
}
.history-reasoning .proc-text {
  font-size: 13px;
  color: var(--text-2);
  line-height: 1.5;
}
.proc-tool {
  margin: 4px 0;
}
.proc-tool summary {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 4px 0;
  list-style: none;
}
.proc-tool summary::-webkit-details-marker { display: none; }
.proc-status {
  color: var(--ok, #10b981);
  font-size: 12px;
}
.proc-toggle {
  color: var(--text-faint, #9ca3af);
  font-size: 14px;
  transition: transform 0.15s;
}
.proc-tool[open] .proc-toggle {
  transform: rotate(90deg);
}
.proc-detail {
  padding: 4px 0 8px 20px;
}
.proc-detail .td {
  margin-bottom: 8px;
}
.proc-detail .td-label {
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 2px;
}
.proc-detail .td-pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  color: var(--text-2);
  background: var(--panel-soft, #f5f5f5);
  padding: 6px 8px;
  border-radius: 6px;
  margin: 0;
}

/* 思考中提示 */
.thinking {
  display: flex;
  align-items: center;
  font-size: 14px;
  color: var(--text-dim);
  padding: 4px 0 8px;
}
.thinking .dots { display: inline-flex; gap: 3px; margin-left: 2px; align-items: center; }
.thinking .dots i {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: currentColor;
  animation: dot 1.2s infinite;
}
.thinking .dots i:nth-child(2) { animation-delay: 0.2s; }
.thinking .dots i:nth-child(3) { animation-delay: 0.4s; }
@keyframes dot {
  0%, 100% { opacity: 0.2; }
  50% { opacity: 1; }
}

/* 错误条 */
.errorbar {
  background: var(--err-bg);
  color: var(--err-text);
  padding: 10px 24px;
  font-size: 13px;
  border-top: 1px solid var(--err-border);
}

/* 输入区：大胶囊输入条 */
.inputbar {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 12px 24px 20px;
  background: transparent;
  border-top: none;
  width: 100%;
  max-width: min(1080px, calc(100vw - 320px));
  margin: 0 auto;
}
.mode {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 8px;
  background: transparent;
  border: none;
  font-size: 13px;
  color: var(--text-2);
  cursor: pointer;
  flex-shrink: 0;
  align-self: flex-end;
  user-select: none;
  transition: all 0.15s;
}
.mode:hover { color: var(--text); background: var(--panel-soft); box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15); }
.m-icon {
  width: 14px;
  height: 14px;
  color: var(--text-faint);
}
.m-caret {
  width: 12px;
  height: 12px;
  color: var(--text-faint);
}
.mode-menu {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  min-width: 200px;
  background: var(--panel);
  border: 1px solid var(--border-strong);
  border-radius: 12px;
  padding: 6px;
  box-shadow: 0 -8px 30px rgba(0, 0, 0, 0.5), 0 12px 32px rgba(0, 0, 0, 0.35);
  z-index: 10;
}
.mode-opt {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.opt-check {
  width: 16px;
  height: 16px;
  color: var(--accent);
  flex-shrink: 0;
  margin-top: 2px;
}
.opt-check svg { width: 100%; height: 100%; }
.opt-text {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  flex: 1;
}
.opt-icon {
  width: 16px;
  height: 16px;
  color: var(--text-dim);
  flex-shrink: 0;
  margin-top: 2px;
}
.opt-icon svg { width: 100%; height: 100%; }
.opt-labels { flex: 1; }
.opt-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 2px;
}
.opt-desc {
  font-size: 11px;
  color: var(--text-dim);
}
.mode-opt:hover { background: var(--panel-hover); color: var(--text-strong); }
.mode-opt.on .opt-label { color: var(--accent); }
.composer {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--border-strong);
  border-radius: 16px;
  padding: 14px 16px 12px;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}
.composer:hover {
  border-color: var(--accent-soft);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);
}
.composer:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-ring);
}
.composer textarea {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  color: var(--text);
  font-size: 16px;
  line-height: 1.5;
  min-height: 28px;
  max-height: 160px;
  font-family: inherit;
}
.composer textarea::placeholder { color: var(--text-faint); }
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
  background: var(--text);
  color: var(--bg-base);
  cursor: pointer;
  transition: opacity 0.15s, transform 0.15s;
}
.send svg { width: 16px; height: 16px; }
.send:hover:not(:disabled) { opacity: .85; transform: translateY(-1px); }
.send:disabled { background: var(--border); color: var(--text-faint); cursor: not-allowed; }
.stop {
  position: relative;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-strong);
  border-radius: 50%;
  background: var(--panel);
  color: var(--text-dim);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s, color 0.15s;
}
.stop svg {
  width: 20px;
  height: 20px;
  transition: transform 0.2s;
}
.stop:hover svg { transform: scale(1.12); }
.stop::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 2px solid var(--accent);
  opacity: 0.55;
  animation: stopPulse 1.8s ease-out infinite;
  pointer-events: none;
}
.stop:hover::before { opacity: 0; }
.stop:hover { color: var(--err); border-color: var(--err); background: var(--err-bg); }
@keyframes stopPulse {
  0% { transform: scale(1); opacity: 0.55; }
  100% { transform: scale(1.4); opacity: 0; }
}
</style>
