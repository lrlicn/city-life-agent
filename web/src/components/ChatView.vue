<script setup>
import { ref, computed, watch, reactive, onBeforeUnmount, onMounted, nextTick } from 'vue'
import { useChat } from '@ai-sdk/vue'
import { DefaultChatTransport, isToolUIPart, getToolName } from 'ai'
import { marked } from 'marked'
import SalaryChart from './SalaryChart.vue'
import RentChart from './RentChart.vue'
import CommuteChart from './CommuteChart.vue'
import MortgageChart from './MortgageChart.vue'
import CostIndexChart from './CostIndexChart.vue'
import ThemeToggle from './ThemeToggle.vue'
import Sidebar from './Sidebar.vue'
import BookmarksPanel from './BookmarksPanel.vue'
import { useSettings } from '../composables/useSettings.js'

// 回答模式：brief / standard / report
const mode = ref('standard')
// 全局审批开关：状态提到共享 composable（与 Sidebar 设置面板绑定同一份，存 localStorage 跨会话生效）。
// 输入条上的 chip 作为快捷开关，与设置里的权威开关双向同步。
const { requireApproval, toggleApproval } = useSettings()
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

// 工具输入/输出格式化（JSON 美化）
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
      require_approval: requireApproval.value,
      // 临时会话 id 不传给后端，让后端创建真正的会话
      conversationId: convId.value && !convId.value.startsWith('temp-') ? convId.value : null,
    }),
  }),
  onFinish: async () => {
    // 记录最后一条 AI 消息的结束时间
    const lastAiMsg = [...messages.value].reverse().find(m => m.role === 'assistant')
    if (lastAiMsg?.id) msgEndTimes[lastAiMsg.id] = Date.now()
    // 新建会话首次发消息后，后端自动建了会话，刷新列表拿到 id
    // （正常已由 watchNewConv 在生成期间提前对账，这里作为兜底：若仍为 temp 则按最新会话纠正）
    const wasNew = convId.value.startsWith('temp-')
    await loadConvs()
    if (wasNew && conversations.value.length > 0) {
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
  messages.value = msgs.map(m => ({ id: m.id, role: m.role, parts: m.parts, _durMs: m.duration_ms }))
  // 历史消息：用落库的真实创建时间回填时间戳（否则 m-time 会显示成“加载时刻”）
  for (const m of msgs) {
    if (m.created_at) msgTimes[m.id] = m.created_at * 1000
  }
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
  loadBookmarks()
  // 上次未关闭的会话，自动载入历史
  if (convId.value) selectConv(convId.value)
})

// ---- 收藏笔记本 ----
const bookmarksOpen = ref(false)
const bookmarkList = ref([])

async function loadBookmarks() {
  try {
    const r = await fetch('/api/bookmarks')
    bookmarkList.value = await r.json()
  } catch { bookmarkList.value = [] }
}

// 助手消息所属的轮次（往前找 user 消息，与轮次导航条同一口径）
function turnOf(m) {
  const idx = messages.value.findIndex(x => x.id === m.id)
  if (idx < 0) return null
  for (let i = idx; i >= 0; i--) {
    if (messages.value[i].role === 'user') {
      const t = turnsMeta.value.find(x => x.id === messages.value[i].id)
      return t ? { turn: t.n, q: t.q } : null
    }
  }
  return null
}

function bmOf(m) {
  const info = turnOf(m)
  if (!info || !convId.value) return null
  return bookmarkList.value.find(b => b.conversation_id === convId.value && b.turn === info.turn) || null
}

function isStarred(m) { return !!bmOf(m) }

async function toggleBookmark(m) {
  // 临时会话（未落库）不支持收藏
  if (!convId.value || convId.value.startsWith('temp-')) return
  const info = turnOf(m)
  if (!info) return
  const existing = bmOf(m)
  try {
    if (existing) {
      await fetch(`/api/bookmarks/${existing.id}`, { method: 'DELETE' })
    } else {
      const content = agentParts(m).filter(x => x.kind === 'text').map(x => x.text).join('\n\n')
      if (!content.trim()) return
      await fetch('/api/bookmarks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: convId.value, turn: info.turn, title: info.q.slice(0, 60), content }),
      })
    }
    await loadBookmarks()
  } catch { /* 后端不可用时静默 */ }
}

// 轻量 toast：跳转来源失效等降级提示
const toast = ref('')
let toastTimer = null
function showToast(msg) {
  toast.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 2600)
}

// 从笔记本跳回原会话的对应轮次（收藏是全文快照，跳转尽力而为：
// 原轮次被分支重生成截断 / 原会话被删时降级提示，不反向动收藏）
async function jumpToBookmark(b) {
  bookmarksOpen.value = false
  if (!conversations.value.some(c => c.id === b.conversation_id)) {
    showToast('原会话已删除，只能在笔记本中查看存档内容')
    return
  }
  if (convId.value !== b.conversation_id) await selectConv(b.conversation_id)
  await nextTick()
  setTimeout(() => {
    measureTurns()
    const t = turnsMeta.value.find(x => x.n === b.turn)
    if (t) jumpToTurn(t)
    else showToast('原轮次已被重新生成截断，只能在笔记本中查看存档内容')
  }, 80)
}

// 首屏建议：图标 + 问题。图标用与应用一致的线性 stroke 风格（currentColor 继承主题色）
const PRESETS = [
  { text: '上海月薪 2 万，到手能拿多少？', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6 12h.01M18 12h.01"/></svg>' },
  { text: '上海社保公积金怎么缴？', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/></svg>' },
  { text: '上海月租 5000，租房要准备多少钱？', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10l9-7 9 7"/><path d="M5 9v11h14V9"/><path d="M10 20v-6h4v6"/></svg>' },
  { text: '我在徐汇，公司在浦东，单程 12 公里通勤开销大吗？', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.3-7-11a7 7 0 0 1 14 0c0 4.7-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg>' },
  { text: '贷款 100 万、利率 3.5%、还 30 年，等额本息和等额本金哪个省？', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="5" x2="5" y2="19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/></svg>' },
  { text: '以上海为基准，北京、广州、成都的生活成本差多少？', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="20" x2="6" y2="12"/><line x1="12" y1="20" x2="12" y2="5"/><line x1="18" y1="20" x2="18" y2="14"/></svg>' },
]

function submit(text) {
  const q = (text ?? input.value).trim()
  if (!q) return

  // 新建会话时，先在侧边栏插入临时会话项，让用户立刻看到标题 + loading
  let tempIdForWatch = ''
  let isTempNew = false
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
    tempIdForWatch = tempId
    isTempNew = true
  }

  // 新建会话：启动 watcher，在回答生成期间提前对账真实会话 id 并轮询侧栏，使 AI 总结标题尽早显示
  if (isTempNew) watchNewConv(tempIdForWatch, q)

  sendMessage({ text: q })
  input.value = ''
  scrollToBottom(true)
}

// 新会话生成期间的对账 + 标题轮询：
// 真实 id 来自后端在流开头下发的 data-conversation part（权威、无歧义，
// 不按列表位置猜，避免新会话尚未建时误对到旧会话）。
function watchNewConv(tempId, q) {
  const provisional = q.slice(0, 30)   // 后端占位标题（问题截断），用于判断总结是否已写入
  let realId = null
  let tries = 0
  const timer = setInterval(async () => {
    tries++
    // 1) 从已到达的消息 parts 里取后端权威下发的真实会话 id
    if (!realId) {
      for (const m of messages.value) {
        const dc = (m.parts || []).find(p => p.type === 'data-conversation')
        if (dc?.data?.id) { realId = dc.data.id; break }
      }
      if (!realId) { if (tries >= 20) clearInterval(timer); return }  // 未拿到前不刷列表，保留临时项不丢高亮
    }
    // 2) 拿到真实 id：对账 convId（临时项→真实会话），侧栏高亮不丢
    if (convId.value === tempId) {
      convId.value = realId
      localStorage.setItem('convId', realId)
    }
    // 3) 刷新列表拉最新标题（占位问题 → AI 总结）
    await loadConvs()
    conversations.value = conversations.value.filter(c => c.id !== tempId)
    const cur = conversations.value.find(c => c.id === realId)
    // 标题已不再是占位问题 → 总结已写入，停止轮询；否则最多轮询 ~20s
    if ((cur && cur.title !== provisional) || tries >= 20) clearInterval(timer)
  }, 1000)
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

// 用户气泡渲染：支持手打 Markdown 语法；breaks:true 让单换行也断行（符合聊天习惯）
function mdUser(src) {
  return marked.parse(cleanMd(src), { breaks: true })
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
      if (p.type === 'data-salary') return { key: i, kind: 'chart', chart: 'salary', data: p.data }
      if (p.type === 'data-rent') return { key: i, kind: 'chart', chart: 'rent', data: p.data }
      if (p.type === 'data-commute') return { key: i, kind: 'chart', chart: 'commute', data: p.data }
      if (p.type === 'data-mortgage') return { key: i, kind: 'chart', chart: 'mortgage', data: p.data }
      if (p.type === 'data-cost-index') return { key: i, kind: 'chart', chart: 'cost-index', data: p.data }
      if (p.type === 'data-export') return { key: i, kind: 'export', data: p.data }
      if (p.type === 'data-interaction') return { key: i, kind: 'interaction', data: p.data }
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

// 图表去重键：同类图表按关键入参去重（同城市同薪资/同租金/同通勤距离只画一张）
function chartKey(p, idx) {
  const c = p.data?.city || ''
  if (p.chart === 'salary' && p.data?.monthly_salary != null) return `${c}-s-${p.data.monthly_salary}`
  if (p.chart === 'rent' && p.data?.monthly_rent != null) return `${c}-r-${p.data.monthly_rent}`
  if (p.chart === 'commute' && p.data?.one_way_km != null) return `${c}-c-${p.data.one_way_km}-${p.data.days_per_month || 22}`
  if (p.chart === 'mortgage' && p.data?.loan_amount != null) return `m-${p.data.loan_amount}-${p.data.annual_rate}-${p.data.years}-${p.data.rates_label || p.data.loan_type || ''}`
  if (p.chart === 'cost-index') { const cs = (p.data?.cities || []).map(c => c.city).join('-'); return `ci-${p.data?.base_city || ''}-${cs}` }
  return `c-${idx}`
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
      chartSeen.set(chartKey(p, idx), idx) // 记录最后出现的位置
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
        if (chartSeen.get(chartKey(p, parts.indexOf(p))) !== parts.indexOf(p)) continue // 不是最后一个，跳过
      }
      result.push(p)
    }
  }
  if (textBuffer.length > 0) {
    result.push({ key: 'text-' + textStartKey, kind: 'text', text: textBuffer.join('') })
  }
  return result
}

// 流式视图：与历史视图同构——思考/工具归入顶部过程面板，
// 正文只留文字流（charts 统一沉到正文底部，避免先到的图表被后长的文字顶上去）
function streamParts(m) {
  const parts = groupedParts(m)   // 复用：连续 text 合并 + 图表去重
  const processes = parts.filter(p => p.kind === 'reasoning' || p.kind === 'tool')
  const texts = parts.filter(p => p.kind === 'text')
  const charts = parts.filter(p => p.kind === 'chart')
  const interactions = parts.filter(p => p.kind === 'interaction')
  const exports = parts.filter(p => p.kind === 'export')
  return { processes, texts, charts, interactions, exports }
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

// ---- 澄清选择（ask_user 交互）----
// 本会话内已点选的交互：interaction_id -> 所选值（点击即锁定，避免重复回传）
const answeredInteractions = reactive({})

// 交互是否“此刻可点/可审”：仅当属于正在流式的最后一条 assistant 消息、且尚未应答
function isLiveInteraction(m, data) {
  if (!data || data.id == null) return false
  if (answeredInteractions[data.id] != null) return false
  if (data.answered != null) return false   // 已落库的决策（历史/刷新）不再激活
  if (!busy.value || status.value !== 'streaming') return false
  return isLastAssistantMsg(m)
}

// 交互最终呈现的取值：本会话应答优先 → 落库的 answered → 澄清类从 ask_user 工具输出还原
function answeredOf(m, data) {
  if (answeredInteractions[data.id] != null) return answeredInteractions[data.id]
  if (data.answered != null) return data.answered
  if (data.kind !== 'confirm') {
    const tool = agentParts(m).find(x => x.kind === 'tool' && x.name === 'ask_user' && x.output)
    if (tool) return String(tool.output)
  }
  return null
}

// 兼容旧命名：模板统一用这个取当前选择/审批结果
function chosenForInteraction(m, data) {
  return answeredOf(m, data)
}

// 审批结果的可读文案
function approveLabel(v) {
  if (v === 'approve') return '已批准'
  if (v === 'deny') return '已拒绝'
  if (v === 'timeout') return '超时未响应（已取消）'
  return String(v)
}

async function resolveInteraction(m, data, opt) {
  if (!isLiveInteraction(m, data)) return
  answeredInteractions[data.id] = opt
  try {
    await fetch('/api/interact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interaction_id: data.id, value: opt }),
    })
  } catch { /* 后端不可用时静默，工具侧会超时降级 */ }
}

// ---- 报告导出（前端）：每条助手消息可导出 Markdown / 打印存 PDF ----
// 汇总一条消息的正文（markdown），供下载与打印复用
function collectText(m) {
  return agentParts(m).filter(x => x.kind === 'text').map(x => x.text).join('\n\n')
}
function _dlName(prefix) {
  const cv = conversations.value.find(c => c.id === convId.value)
  const stem = ((cv && cv.title) || 'report').replace(/[^\w\u4e00-\u9fff-]+/g, '_').slice(0, 40) || 'report'
  const ts = new Date().toISOString().slice(0, 10)
  return `${stem}_${ts}.md`
}
// 导出当前回答为 .md 文件（纯前端 Blob，不走后端）
function exportMsgMd(m) {
  const text = collectText(m)
  if (!text.trim()) { showToast('这条回答没有可导出的正文'); return }
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = _dlName()
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
// 打印当前回答（浏览器打印→另存为 PDF）：新开窗口注入渲染后的 HTML 再调 print()
function printMsg(m) {
  const html = agentParts(m).filter(x => x.kind === 'text').map(x => md(x.text)).join('\n')
  if (!html.trim()) { showToast('这条回答没有可打印的正文'); return }
  const w = window.open('', '_blank', 'width=860,height=920')
  if (!w) { showToast('浏览器拦截了打印窗口，请允许弹窗后重试'); return }
  const style = 'body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;max-width:760px;margin:32px auto;padding:0 20px;line-height:1.75;color:#1a1a1a}' +
    'h1,h2,h3{line-height:1.35;margin:1.2em 0 .5em}table{border-collapse:collapse;width:100%;margin:1em 0}' +
    'th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}code,pre{background:#f5f5f5;border-radius:4px}' +
    'pre{padding:12px;overflow:auto}blockquote{margin:0;padding-left:14px;border-left:3px solid #ccc;color:#555}' +
    '@media print{body{margin:0}}@page{size:A4;margin:16mm}'
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>报告</title><style>${style}</style></head><body>${html}</body></html>`)
  w.document.close()
  w.focus()
  setTimeout(() => { try { w.print() } catch { /* 用户取消打印 */ } }, 350)
}

// ---- 左侧轮次导航条（Codex/ChatGPT 风格 minimap）----
// 每轮 user 对话对应一条短横线；hover 延长并弹出该轮缩略预览，点击滚动定位
const turnsMeta = ref([])      // [{ n, id, q, a, pct, offsetTop }]
const activeTurn = ref(0)

// 预览摘要：去掉 markdown 符号后截断
function excerpt(s, n) {
  return (s || '').replace(/[#*`>\-|]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, n)
}

function measureTurns() {
  const el = messagesEl.value
  if (!el) return
  const ms = messages.value
  const rows = el.querySelectorAll('.user-row')
  const out = []
  let n = 0
  let rowIdx = 0
  for (let i = 0; i < ms.length; i++) {
    const m = ms[i]
    if (m.role !== 'user') continue
    n++
    // 找该轮之后的第一条 assistant 回复做预览摘要
    let a = ''
    for (let j = i + 1; j < ms.length; j++) {
      if (ms[j].role === 'assistant') {
        a = agentParts(ms[j]).filter(x => x.kind === 'text').map(x => x.text).join(' ')
        break
      }
      if (ms[j].role === 'user') break
    }
    const row = rows[rowIdx++]
    out.push({ n, id: m.id, q: userText(m), a, offsetTop: row ? row.offsetTop : 0 })
  }
  turnsMeta.value = out
  updateActiveTurn()
}

// 当前可视轮次：滚动位置经过的那一轮高亮
function updateActiveTurn() {
  const el = messagesEl.value
  if (!el || !turnsMeta.value.length) { activeTurn.value = 0; return }
  const y = el.scrollTop + 120
  let cur = turnsMeta.value[0].n
  for (const t of turnsMeta.value) { if (t.offsetTop <= y) cur = t.n }
  activeTurn.value = cur
}

function jumpToTurn(t) {
  const el = messagesEl.value
  if (el) el.scrollTo({ top: Math.max(0, t.offsetTop - 24), behavior: 'smooth' })
}

// 分支截断：从含该消息所在轮次起丢弃旧链（DB + 本地），供重生/编辑重发共用。
// 返回 false 表示无法截断（找不到该轮 / DB 报错），调用方可降级回旧行为。
async function truncateFromMessage(msgId) {
  const idx = messages.value.findIndex(x => x.id === msgId)
  if (idx < 0) return false
  let uIdx = idx
  while (uIdx >= 0 && messages.value[uIdx].role !== 'user') uIdx--
  if (uIdx < 0) return false
  const turn = turnsMeta.value.find(x => x.id === messages.value[uIdx].id)?.n
  if (convId.value && !convId.value.startsWith('temp-') && turn) {
    try {
      const r = await fetch(`/api/conversations/${convId.value}/truncate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ turn }),
      })
      if (!r.ok) return false
    } catch { return false }
  }
  messages.value = messages.value.slice(0, uIdx)
  return true
}

// 从轮次导航条发起：丢弃第 N 轮及其后，重发该轮问题
async function regenerateTurn(t) {
  if (busy.value || !t.q) return
  const ok = await truncateFromMessage(t.id)
  if (ok) sendMessage({ text: t.q })
}

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
// 与流式视图同构：文字在上、图表统一在下（避免生成结束时的版式跳变）
function historyParts(m) {
  const parts = groupedParts(m)
  const processes = parts.filter(p => p.kind === 'reasoning' || p.kind === 'tool')
  const texts = parts.filter(p => p.kind === 'text')
  const charts = parts.filter(p => p.kind === 'chart')
  const interactions = parts.filter(p => p.kind === 'interaction')
  const exports = parts.filter(p => p.kind === 'export')
  return { texts, charts, processes, interactions, exports }
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

// 生成中实时计时：busy 时每秒推进 nowTick，让耗时边生成边跳动
const nowTick = ref(Date.now())
let tickTimer = null
watch(busy, (b) => {
  clearInterval(tickTimer)
  tickTimer = null
  if (b) {
    nowTick.value = Date.now()
    tickTimer = setInterval(() => { nowTick.value = Date.now() }, 1000)
  }
})

// 格式化用时
function fmtSec(sec) {
  if (sec < 60) return `共用时 ${sec} 秒`
  const min = Math.floor(sec / 60)
  return `共用时 ${min} 分 ${sec % 60} 秒`
}
function fmtDuration(startTs, endTs) {
  if (!startTs || !endTs) return ''
  return fmtSec(Math.round((endTs - startTs) / 1000))
}
// 耗时显示：历史消息用后端落库的真实耗时；生成中实时递增；刚结束用 onFinish 记录的结束时间
function durationText(m) {
  if (m._durMs != null) return fmtSec(Math.max(1, Math.round(m._durMs / 1000)))
  const start = msgTimes[m.id]
  let end = msgEndTimes[m.id]
  if (!end && busy.value && isLastAssistantMsg(m)) end = nowTick.value
  return fmtDuration(start, end)
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
// 真·重新生成：从该回答对应的那一轮截断旧链后重发，不保留平行分支
async function regenerate(m) {
  if (busy.value) return
  const idx = messages.value.findIndex(x => x.id === m.id)
  if (idx < 0) return
  // 找这条助手消息对应的 user 问题
  let q = ''
  for (let i = idx; i >= 0; i--) {
    if (messages.value[i].role === 'user') { q = userText(messages.value[i]); break }
  }
  if (!q) return
  const ok = await truncateFromMessage(m.id)
  if (!ok) {
    // 无法截断时退回旧行为：填回输入框让用户自行重发
    input.value = q
    nextTick(() => {
      const ta = document.querySelector('.composer textarea')
      if (ta) ta.focus()
    })
    return
  }
  sendMessage({ text: q })
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

// 确认编辑并重新发送：分支语义——从该轮起截断旧链后重发新问题
async function confirmEdit(m) {
  const t = editText.value.trim()
  if (!t) return
  cancelEdit()
  const ok = await truncateFromMessage(m.id)
  if (ok) sendMessage({ text: t })
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
  updateActiveTurn()
}

// 深度监听消息内容变化，流式输出时持续滚动 + 重测轮次位置
watch(() => JSON.stringify(messages.value), () => {
  scrollToBottom()
  nextTick(measureTurns)
})

// 切换会话时强制滚到底部并重测轮次位置
watch(() => convId.value, () => {
  scrollToBottom(true)
  nextTick(measureTurns)
})
onBeforeUnmount(() => {
  clearTimeout(scrollTimer)
  clearTimeout(toastTimer)
  clearInterval(tickTimer)
})
</script>

<template>
  <div class="app" @click="modeOpen = false">
    <Sidebar
      :conversations="conversations"
      :active-id="convId"
      :open="sidebarOpen"
      :status-tone="statusTone"
      :status-label="statusLabel"
      :bookmark-count="bookmarkList.length"
      @close="sidebarOpen = false"
      @new="newConv"
      @select="selectConv"
      @rename="renameConv"
      @delete="deleteConv"
      @open-bookmarks="bookmarksOpen = true"
    />
    <div class="inner" :class="{ 'welcome-mode': messages.length === 0 }">
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
      <!-- 初始态：问候语（输入框由 welcome-mode 居中叠加，胶囊建议挂在输入框下方） -->
      <div v-if="messages.length === 0" class="welcome">
        <div class="w-title">城市生活的账，帮你算清楚</div>
        <div class="w-sub">工资到手、社保公积金、租房成本、通勤开销、房贷月供、城市成本对比，先从这里问起</div>
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
            <div class="bubble user md-user" v-html="mdUser(userText(m))"></div>
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

            <!-- 当前正在生成的消息：与历史视图同构——过程折叠面板在顶部（生成中默认展开），
                 正文流只渲染 text + chart，工具/思考不会再插进回答中间 -->
            <template v-if="isLastAssistantMsg(m) && status === 'streaming'">
              <details v-if="streamParts(m).processes.length > 0" class="reasoning history-reasoning" open>
                <summary>
                  <span class="r-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M9 18h6"/>
                      <path d="M10 22h4"/>
                      <path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0 0 12 2z"/>
                    </svg>
                  </span>
                  <span class="r-label">思考过程</span>
                  <span class="r-count">{{ streamParts(m).processes.length }}</span>
                  <span class="r-toggle">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M9 18l6-6-6-6"/>
                    </svg>
                  </span>
                  <span class="r-duration">{{ durationText(m) }}</span>
                </summary>
                <div class="r-body">
                  <div v-for="(proc, i) in streamParts(m).processes" :key="'sp-' + proc.key" class="proc-item">
                    <template v-if="proc.kind === 'reasoning'">
                      <div class="proc-label">💭 思考</div>
                      <div class="proc-text">{{ proc.text }}</div>
                    </template>
                    <template v-else-if="proc.kind === 'tool'">
                      <details class="proc-tool">
                        <summary>
                          <span class="proc-label">⚙ {{ proc.running ? '正在调用工具…' : proc.name }}</span>
                          <span class="proc-status" :class="{ run: proc.running }">{{ proc.running ? '进行中…' : '完成' }}</span>
                          <span v-if="!proc.running" class="proc-toggle">›</span>
                        </summary>
                        <div v-if="!proc.running" class="proc-detail">
                          <div v-if="proc.input && Object.keys(proc.input).length" class="td">
                            <span class="td-label">输入参数</span>
                            <pre class="td-pre">{{ fmt(proc.input) }}</pre>
                          </div>
                          <div v-if="proc.output" class="td">
                            <span class="td-label">返回结果</span>
                            <pre class="td-pre">{{ fmt(proc.output) }}</pre>
                          </div>
                        </div>
                      </details>
                    </template>
                  </div>
                </div>
              </details>
              <div v-if="streamParts(m).processes.length > 0" class="history-divider"></div>
              <!-- 正文文字流（在上，随生成向下生长） -->
              <div v-for="p in streamParts(m).texts" :key="p.key" class="markdown" v-html="md(p.text)"></div>
              <!-- 交互区（澄清选择 / 工具审批）：生成中途暂停，应答后恢复同一条流继续 -->
              <div v-for="p in streamParts(m).interactions" :key="'sint-' + p.key" class="interaction">
                <template v-if="p.data.kind === 'confirm'">
                  <div class="int-q">🔐 AI 请求执行以下操作，是否批准？</div>
                  <div class="appr-tools">
                    <div v-for="t in p.data.tools" :key="t.tool_call_id" class="appr-tool">
                      <span class="appr-name">⚙ {{ t.name }}</span>
                      <pre v-if="t.input && Object.keys(t.input).length" class="appr-input">{{ fmt(t.input) }}</pre>
                    </div>
                  </div>
                  <div v-if="!chosenForInteraction(m, p.data) && isLiveInteraction(m, p.data)" class="appr-btns">
                    <button class="appr-btn no" @click="resolveInteraction(m, p.data, 'deny')">拒绝</button>
                    <button class="appr-btn ok" @click="resolveInteraction(m, p.data, 'approve')">批准</button>
                  </div>
                  <div v-else-if="chosenForInteraction(m, p.data)" class="int-note">审批结果：{{ approveLabel(chosenForInteraction(m, p.data)) }}</div>
                  <div v-else class="int-note live">等待你的审批…</div>
                </template>
                <template v-else>
                  <div class="int-q">{{ p.data.question }}</div>
                  <div class="int-opts">
                    <button
                      v-for="opt in p.data.options"
                      :key="opt"
                      class="int-chip"
                      :class="{ chosen: chosenForInteraction(m, p.data) === opt }"
                      :disabled="!isLiveInteraction(m, p.data)"
                      @click="resolveInteraction(m, p.data, opt)"
                    >{{ opt }}</button>
                  </div>
                  <div v-if="chosenForInteraction(m, p.data)" class="int-note">已选择：{{ chosenForInteraction(m, p.data) }}</div>
                  <div v-else-if="isLiveInteraction(m, p.data)" class="int-note live">请选择后继续…</div>
                </template>
              </div>
              <!-- 图表区（统一沉在底部，不会先于文字乱入正文中间） -->
              <div v-for="p in streamParts(m).charts" :key="p.key" class="chart-wrap">
                <SalaryChart v-if="p.chart === 'salary'" :data="p.data" />
                <RentChart v-else-if="p.chart === 'rent'" :data="p.data" />
                <CommuteChart v-else-if="p.chart === 'commute'" :data="p.data" />
                <MortgageChart v-else-if="p.chart === 'mortgage'" :data="p.data" />
                <CostIndexChart v-else-if="p.chart === 'cost-index'" :data="p.data" />
              </div>
              <!-- 报告下载卡片（export_report → data-export） -->
              <div v-for="p in streamParts(m).exports" :key="'sexp-' + p.key" class="export-card">
                <span class="ex-icon">📄</span>
                <div class="ex-body">
                  <div class="ex-title">{{ p.data.title }}</div>
                  <div class="ex-meta">{{ p.data.format }}<template v-if="p.data.chars"> · {{ p.data.chars }} 字</template> · {{ p.data.filename }}</div>
                </div>
                <a class="ex-btn" :href="p.data.url" target="_blank" rel="noopener">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>
                  下载
                </a>
              </div>
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
                  <span class="r-duration">{{ durationText(m) }}</span>
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
              <!-- 正文文字（在上） -->
              <div v-for="p in historyParts(m).texts" :key="'text-' + p.key" class="markdown history-text" v-html="md(p.text)"></div>
              <!-- 交互区（历史只读：回显当时选择/审批，不可再点） -->
              <div v-for="p in historyParts(m).interactions" :key="'hint-' + p.key" class="interaction">
                <template v-if="p.data.kind === 'confirm'">
                  <div class="int-q">🔐 AI 曾请求执行以下操作：</div>
                  <div class="appr-tools">
                    <div v-for="t in p.data.tools" :key="t.tool_call_id" class="appr-tool">
                      <span class="appr-name">⚙ {{ t.name }}</span>
                      <pre v-if="t.input && Object.keys(t.input).length" class="appr-input">{{ fmt(t.input) }}</pre>
                    </div>
                  </div>
                  <div v-if="chosenForInteraction(m, p.data)" class="int-note">审批结果：{{ approveLabel(chosenForInteraction(m, p.data)) }}</div>
                </template>
                <template v-else>
                  <div class="int-q">{{ p.data.question }}</div>
                  <div class="int-opts">
                    <button
                      v-for="opt in p.data.options"
                      :key="opt"
                      class="int-chip"
                      :class="{ chosen: chosenForInteraction(m, p.data) === opt }"
                      disabled
                    >{{ opt }}</button>
                  </div>
                  <div v-if="chosenForInteraction(m, p.data)" class="int-note">已选择：{{ chosenForInteraction(m, p.data) }}</div>
                </template>
              </div>
              <!-- 图表区（统一在下） -->
              <div v-for="p in historyParts(m).charts" :key="'chart-' + p.key" class="chart-wrap">
                <SalaryChart v-if="p.chart === 'salary'" :data="p.data" />
                <RentChart v-else-if="p.chart === 'rent'" :data="p.data" />
                <CommuteChart v-else-if="p.chart === 'commute'" :data="p.data" />
                <MortgageChart v-else-if="p.chart === 'mortgage'" :data="p.data" />
                <CostIndexChart v-else-if="p.chart === 'cost-index'" :data="p.data" />
              </div>
              <!-- 报告下载卡片（历史只读） -->
              <div v-for="p in historyParts(m).exports" :key="'hexp-' + p.key" class="export-card">
                <span class="ex-icon">📄</span>
                <div class="ex-body">
                  <div class="ex-title">{{ p.data.title }}</div>
                  <div class="ex-meta">{{ p.data.format }}<template v-if="p.data.chars"> · {{ p.data.chars }} 字</template> · {{ p.data.filename }}</div>
                </div>
                <a class="ex-btn" :href="p.data.url" target="_blank" rel="noopener">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>
                  下载
                </a>
              </div>
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
              <button class="m-act" :class="{ starred: isStarred(m) }" @click="toggleBookmark(m)" :data-tip="isStarred(m) ? '取消收藏' : '收藏到笔记本'">
                <svg viewBox="0 0 24 24" :fill="isStarred(m) ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                </svg>
              </button>
              <button class="m-act" @click="exportMsgMd(m)" data-tip="导出为 Markdown">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>
              </button>
              <button class="m-act" @click="printMsg(m)" data-tip="打印 / 存为 PDF">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9V3h12v6"/><rect x="6" y="14" width="12" height="7"/><path d="M6 14H4a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-2"/><path d="M6 18h12"/></svg>
              </button>
            </span>
            <span class="m-time">{{ fmtTime(msgTimes[m.id]) }}</span>
          </div>
        </div>
      </template>
    </div>

    <!-- 左侧轮次导航条：每轮对话一条短横线，hover 延长+预览，点击定位 -->
    <nav v-if="turnsMeta.length > 1" class="turn-rail">
      <div
        v-for="t in turnsMeta"
        :key="t.n"
        class="tick"
        :class="{ active: t.n === activeTurn }"
        @click="jumpToTurn(t)"
      >
        <span class="node">{{ t.n }}</span>
        <div class="tick-pop">
          <div class="pop-turn">第 {{ t.n }} 轮</div>
          <div class="pop-q">{{ excerpt(t.q, 60) }}{{ t.q.length > 60 ? '…' : '' }}</div>
          <div v-if="excerpt(t.a, 90)" class="pop-a">{{ excerpt(t.a, 90) }}{{ t.a.length > 90 ? '…' : '' }}</div>
          <button class="pop-regen" :disabled="busy" @click.stop="regenerateTurn(t)">↻ 从这轮重新生成</button>
        </div>
      </div>
    </nav>

    <!-- 错误条 -->
    <div v-if="error" class="errorbar">出错：{{ error.message || error }}</div>

    <!-- 输入区：大胶囊输入条 -->
    <div class="inputbar">
      <div class="composer">
        <textarea
          v-model="input"
          rows="1"
          placeholder="问我关于工资到手、社保公积金、租房成本、通勤开销、房贷月供、城市成本对比的问题…"
          :disabled="status !== 'ready'"
          @input="autoGrow"
          @keydown.enter.exact.prevent="submit()"
        ></textarea>
        <div class="composer-bar">
          <div class="mode" :class="{ open: modeOpen }" @click.stop="modeOpen = !modeOpen">
            <svg class="m-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 3l1.7 4.6L18 9l-4.3 1.4L12 15l-1.7-4.6L6 9l4.3-1.4z"/>
              <path d="M18.5 14l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>
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
          <button
            class="approval-toggle"
            :class="{ on: requireApproval }"
            :data-tip="requireApproval ? '工具执行前需你审批（点击切为免审批）' : '工具自动放行（点击切为需审批）'"
            @click="toggleApproval"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              <path d="M9 12l2 2 4-4"/>
            </svg>
            <span class="ap-label">{{ requireApproval ? '需审批' : '免审批' }}</span>
          </button>
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
      <!-- 首屏建议：2 列等宽图标卡片（整齐可发现）；聚焦输入框时整体退让淡出，让输入框独占主角 -->
      <div v-if="messages.length === 0" class="preset-grid">
        <button
          v-for="p in PRESETS"
          :key="p.text"
          class="pcard"
          :disabled="status !== 'ready'"
          @click="submit(p.text)"
        >
          <span class="pc-icon" v-html="p.icon"></span>
          <span class="pc-text">{{ p.text }}</span>
        </button>
      </div>
    </div>
    </div>

    <!-- 收藏笔记本抽屉 -->
    <BookmarksPanel
      v-if="bookmarksOpen"
      :bookmarks="bookmarkList"
      :conversations="conversations"
      @close="bookmarksOpen = false"
      @jump="jumpToBookmark"
      @refresh="loadBookmarks"
    />

    <!-- 轻量 toast -->
    <transition name="toast">
      <div v-if="toast" class="toast">{{ toast }}</div>
    </transition>
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
  position: relative;
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
/* 已收藏的星标 */
.m-act.starred { color: var(--warn); }
/* 轻量 toast：底部居中浮层 */
.toast {
  position: fixed;
  left: 50%;
  bottom: 90px;
  transform: translateX(-50%);
  padding: 9px 18px;
  border-radius: 999px;
  background: var(--panel);
  border: 1px solid var(--border-strong);
  color: var(--text);
  font-size: 13px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.3);
  z-index: 300;
  pointer-events: none;
}
.toast-enter-from, .toast-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(8px);
}
.toast-enter-active, .toast-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
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
/* 首屏建议：2 列等宽「幽灵」卡片——静置时几乎无重量（透明无边框、淡字、图标不抢色），
   把主角位彻底让给全屏唯一的实心输入框；hover 才浮出可点胶囊 */
.preset-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 10px;
  margin-top: 14px;
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.pcard {
  display: flex;
  align-items: center;
  gap: 10px;
  text-align: left;
  padding: 9px 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  line-height: 1.4;
  color: var(--text-dim);
  transition: border-color 0.15s, background 0.15s, color 0.15s;
}
.pcard:hover {
  border-color: var(--border);
  color: var(--text);
  background: var(--panel-soft);
}
.pcard:disabled { opacity: 0.5; cursor: not-allowed; }
.pc-icon {
  flex-shrink: 0;
  width: 17px;
  height: 17px;
  display: inline-flex;
  color: var(--text-2);      /* hover 时中性深灰而非品牌色：主色只留给主操作，建议图标不抢戏 */
  opacity: 0;              /* 静置时图标完整隐藏但保留占位（不用 display，避免 hover 时文字左跳） */
  transition: opacity 0.15s ease;
}
.pcard:hover .pc-icon { opacity: 1; }
.pc-icon svg { width: 100%; height: 100%; }
.pc-text { flex: 1; }
/* 聚焦输入框时：建议卡片整体淡出退让（保留占位不跳动），输入框独占主角位 */
.inputbar:focus-within .preset-grid {
  opacity: 0.28;
  transform: translateY(6px);
}

/* 首屏居中态（welcome-mode）：输入框整体上浮居中成为视觉主角，问候语在其上方 */
.welcome-mode .welcome {
  margin-top: 17vh;
}
.welcome-mode .inputbar {
  position: absolute;
  left: 50%;
  top: 54%;
  transform: translate(-50%, -50%);
  width: min(780px, calc(100% - 48px));
  max-width: none;
  padding: 0;
}
.welcome-mode .composer {
  box-shadow: 0 10px 36px rgba(0, 0, 0, 0.12);
}
/* 首屏输入框升格为 2 行高，体量上坐实视觉主角（建议卡片靠退让让位） */
.welcome-mode .composer textarea {
  min-height: 52px;
}

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
/* 左侧轮次导航条：地铁线路图风格——细轨道串起各轮「站点」，
   active 站点亮色光晕，hover 站点膨胀成显示轮次的胶囊并弹预览 */
.turn-rail {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  width: 30px;
  z-index: 6;
  pointer-events: none;
  display: flex;
  flex-direction: column;
}
/* 轨道线：从首站中心连到末站中心，两端按百分比渐隐（轮次越多越像真实线路图） */
.turn-rail::before {
  content: '';
  position: absolute;
  left: 7px;
  top: 13px;
  bottom: 13px;
  width: 1px;
  border-radius: 1px;
  background: linear-gradient(
    180deg,
    transparent 0%,
    color-mix(in srgb, var(--border-strong) 60%, transparent) 14%,
    color-mix(in srgb, var(--border-strong) 60%, transparent) 86%,
    transparent 100%
  );
}
.turn-rail .tick {
  position: relative;
  height: 26px;
  display: flex;
  align-items: center;
  cursor: pointer;
  pointer-events: auto;
}
.node {
  width: 9px;
  height: 9px;
  margin-left: 3px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  border: 1.5px solid var(--border-strong);
  background: var(--bg-base);
  color: var(--text-on-accent);
  font-size: 0;
  font-weight: 600;
  transition: all 0.18s ease;
}
/* 当前轮次：站点点亮 + 光晕，不改变尺寸 */
.tick.active .node {
  border-color: var(--accent);
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
}
/* hover：站点膨胀成胶囊，浮现轮次数字 */
.tick:hover .node {
  width: 22px;
  height: 22px;
  margin-left: -3px;
  font-size: 12px;
  border-color: var(--accent);
  background: var(--accent);
}
.tick-pop {
  position: absolute;
  left: 34px;
  top: 50%;
  transform: translateY(-50%) translateX(-4px);
  width: 250px;
  padding: 10px 12px;
  background: var(--panel-soft-trans);
  border: 1px solid var(--border-strong);
  border-radius: 10px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.28);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.tick:hover .tick-pop {
  opacity: 1;
  transform: translateY(-50%) translateX(0);
  pointer-events: auto;
}
.pop-turn {
  font-size: 11px;
  color: var(--accent);
  font-weight: 600;
  margin-bottom: 4px;
}
.pop-q { font-size: 13px; color: var(--text); line-height: 1.5; }
.pop-a { font-size: 12px; color: var(--text-dim); line-height: 1.5; margin-top: 5px; }
.pop-regen {
  margin-top: 8px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  padding: 3px 9px;
  border-radius: 6px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
}
.pop-regen:hover { color: var(--accent); border-color: var(--accent); }
.pop-regen:disabled { opacity: 0.5; cursor: not-allowed; }
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
/* 用户气泡里的 Markdown：预渲染 HTML 后改用正常流排版，
   代码/表格等元素在渐变蓝底上用半透明白适配，不沿用正文配色 */
.md-user { white-space: normal; }
.md-user :deep(p) { margin: 0 0 6px; }
.md-user :deep(p:last-child) { margin-bottom: 0; }
.md-user :deep(ul), .md-user :deep(ol) { margin: 6px 0 6px 20px; }
.md-user :deep(li) { margin: 2px 0; }
.md-user :deep(strong) { color: #fff; }
.md-user :deep(code) {
  background: rgba(255, 255, 255, 0.16);
  border: none;
  color: #fff;
  padding: 1px 6px;
  font-size: 14px;
}
.md-user :deep(pre) {
  background: rgba(0, 0, 0, 0.18);
  border: none;
  border-radius: 8px;
  padding: 8px 10px;
  margin: 6px 0;
  overflow-x: auto;
  font-size: 14px;
}
.md-user :deep(pre code) { background: transparent; padding: 0; }
.md-user :deep(blockquote) {
  border-left: 2px solid rgba(255, 255, 255, 0.5);
  background: rgba(255, 255, 255, 0.1);
  color: inherit;
  margin: 6px 0;
  padding: 2px 10px;
  border-radius: 0 8px 8px 0;
}
.md-user :deep(a) { color: #fff; }
.md-user :deep(table) { border-collapse: collapse; margin: 6px 0; font-size: 14px; }
.md-user :deep(th), .md-user :deep(td) { border: 1px solid rgba(255, 255, 255, 0.35); padding: 2px 8px; }
.md-user :deep(h1), .md-user :deep(h2), .md-user :deep(h3) { color: #fff; margin: 6px 0 2px; font-size: 16px; }
.md-user :deep(hr) { border: none; border-top: 1px solid rgba(255, 255, 255, 0.35); margin: 8px 0; }
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

/* 工具明细内联块（.td 系列，被历史/流式的 .proc-detail 复用） */
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

/* 澄清选择区：AI 生成中途暂停，给出互斥选项让用户点选后继续 */
.interaction {
  margin: 10px 0 12px;
  padding: 12px 14px;
  background: var(--panel-soft);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 10px;
}
.int-q {
  font-size: 14px;
  color: var(--text);
  line-height: 1.5;
  margin-bottom: 10px;
}
.int-opts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.int-chip {
  appearance: none;
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  color: var(--text);
  background: var(--bg-base);
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  padding: 8px 14px;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.int-chip:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-glow);
}
.int-chip.chosen {
  border-color: var(--accent);
  background: var(--accent);
  color: #fff;
  font-weight: 600;
}
.int-chip:disabled {
  cursor: default;
  opacity: 0.55;
}
.int-chip.chosen:disabled {
  opacity: 1;
}
.int-note {
  margin-top: 10px;
  font-size: 12px;
  color: var(--text-dim);
}
.int-note.live {
  color: var(--accent);
}

/* 工具审批卡片（kind=confirm） */
.appr-tools {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 4px;
}
.appr-tool {
  background: var(--bg-base);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
}
.appr-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.appr-input {
  margin: 6px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2);
  font-family: inherit;
}
.appr-btns {
  display: flex;
  gap: 10px;
  margin-top: 12px;
}
.appr-btn {
  appearance: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  border-radius: 999px;
  padding: 8px 20px;
  border: 1px solid var(--border-strong);
  background: var(--bg-base);
  color: var(--text);
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.appr-btn.ok {
  border-color: var(--ok, #10b981);
  background: var(--ok, #10b981);
  color: #fff;
}
.appr-btn.ok:hover { filter: brightness(1.08); }
.appr-btn.no:hover {
  border-color: var(--err, #ef4444);
  color: var(--err, #ef4444);
  background: var(--err-bg, rgba(239, 68, 68, 0.12));
}

/* 全局审批开关（输入条内，与模式选择器并列） */
.approval-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 8px;
  background: transparent;
  border: none;
  font-size: 13px;
  line-height: 1;
  color: var(--text-2);
  cursor: pointer;
  flex-shrink: 0;
  user-select: none;
  transition: all 0.15s;
}
.approval-toggle:hover { color: var(--text); background: var(--panel-soft); }
.approval-toggle svg { width: 14px; height: 14px; color: var(--text-faint); display: block; flex-shrink: 0; }
.approval-toggle.on { color: var(--accent); }
.approval-toggle.on svg { color: var(--accent); }

/* 报告导出下载卡片（data-export） */
.export-card {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0;
  padding: 12px 14px;
  border: 1px solid var(--border-line, #e5e7eb);
  border-radius: 12px;
  background: var(--panel-soft, #f8f9fb);
}
.export-card .ex-icon {
  font-size: 22px;
  line-height: 1;
  flex-shrink: 0;
}
.export-card .ex-body {
  flex: 1;
  min-width: 0;
}
.export-card .ex-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text, #1a1a1a);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.export-card .ex-meta {
  font-size: 12px;
  color: var(--text-dim, #6b7280);
  margin-top: 2px;
}
.export-card .ex-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border-radius: 8px;
  background: var(--accent, #4f46e5);
  color: #fff;
  font-size: 12px;
  text-decoration: none;
  border: 1px solid transparent;
  transition: filter 0.15s;
}
.export-card .ex-btn:hover { filter: brightness(1.08); }
.export-card .ex-btn svg { width: 13px; height: 13px; }


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
.proc-status.run {
  color: var(--warn, #f59e0b);
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

/* 输入区：大胶囊输入条（首屏居中态下额外挂胶囊建议在下方） */
.inputbar {
  display: flex;
  flex-direction: column;
  gap: 14px;
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
  line-height: 1;
  color: var(--text-2);
  cursor: pointer;
  flex-shrink: 0;
  user-select: none;
  transition: all 0.15s;
}
.mode:hover { color: var(--text); background: var(--panel-soft); box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15); }
.m-icon {
  width: 14px;
  height: 14px;
  color: var(--text-faint);
  display: block;
  flex-shrink: 0;
}
.m-label { line-height: 1; }
.m-caret {
  width: 12px;
  height: 12px;
  color: var(--text-faint);
  display: block;
  flex-shrink: 0;
  transition: transform 0.2s ease;
}
.mode.open .m-caret { transform: rotate(180deg); }
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
  transform-origin: bottom left;
  animation: modeMenuIn 0.16s ease-out;
}
@keyframes modeMenuIn {
  from { opacity: 0; transform: translateY(6px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
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
  width: 100%;
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
  box-shadow: 0 2px 14px var(--accent-glow);
}
.composer:focus-within {
  border-color: var(--accent-line);    /* 实色薄荷细线 */
  box-shadow: 0 0 0 1px var(--accent-line);   /* 与边框同色，合成一条锐利实色薄荷环，无光晕 */
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
