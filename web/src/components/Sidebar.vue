<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'

const props = defineProps({
  conversations: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  open: { type: Boolean, default: true },
  statusTone: { type: String, default: 'idle' },
})

const emit = defineEmits(['close', 'select', 'new', 'rename', 'delete'])

const editingId = ref('')
const editText = ref('')
const settingsOpen = ref(false)
const confirmDel = ref(null)  // { id, title }
const sideListRef = ref(null)

// 检测每个会话标题是否溢出，溢出则动态设置滚动距离
async function checkOverflow() {
  await nextTick()
  if (!sideListRef.value) return
  const titles = sideListRef.value.querySelectorAll('.conv-title')
  titles.forEach(el => {
    const inner = el.querySelector('.conv-title-inner')
    if (!inner) return

    const overflow = el.scrollWidth - el.clientWidth
    if (overflow > 4) {
      // 一份文字的完整宽度，加上两段之间的间距(2rem=32px)
      const textWidth = inner.scrollWidth
      const gap = 32
      el.style.setProperty('--scroll-distance', (textWidth + gap) + 'px')
      // 滚动速度恒定：约每秒60px，最少3秒
      const duration = Math.max(3, (textWidth + gap) / 60)
      inner.style.animationDuration = duration + 's'
      el.classList.add('is-overflow')
    } else {
      el.classList.remove('is-overflow')
    }
  })
}

// 会话列表变化 / 侧边栏展开收起时，重新检测溢出
watch(() => props.conversations, () => checkOverflow(), { deep: true })
watch(() => props.open, () => checkOverflow())

// 主题选项（直接平铺在设置浮层里，不用下拉）
const THEME_KEY = 'city-agent-theme'
const theme = ref(localStorage.getItem(THEME_KEY) || 'light')
const themeOpts = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'auto', label: '跟随系统' },
]
function applyTheme() {
  let resolved = theme.value
  if (resolved === 'auto') {
    resolved = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  }
  document.documentElement.setAttribute('data-theme', resolved)
}
function pickTheme(v) {
  theme.value = v
  localStorage.setItem(THEME_KEY, v)
  applyTheme()
}

// 点击设置浮层外部时自动关闭
function onDocClick() { settingsOpen.value = false }
onMounted(() => {
  applyTheme()  // 初始化时应用已存主题（刷新后保持）
  document.addEventListener('click', onDocClick)
  checkOverflow()
  window.addEventListener('resize', checkOverflow)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('resize', checkOverflow)
})
function startRename(c) {
  editingId.value = c.id
  editText.value = c.title
}
function commitRename(c) {
  const t = editText.value.trim()
  if (t && t !== c.title) emit('rename', { id: c.id, title: t })
  editingId.value = ''
}
function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  if (sameDay) return hh + ':' + mm
  return (d.getMonth() + 1) + '/' + d.getDate()
}
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: !open }">
    <!-- 品牌头 -->
    <div class="brand-head">
      <div class="brand-logo">
        <img src="/logo.svg" alt="Logo" style="width:100%;height:100%;border-radius:6px"/>
      </div>
      <span class="brand-name">城事小灵通智能体</span>
      <button class="collapse-btn" @click="emit('close')" aria-label="收起侧栏" data-tip="收起侧栏">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="4"/><line x1="14" y1="4" x2="14" y2="20"/></svg>
      </button>
    </div>

    <!-- 新建会话 -->
    <div class="side-actions">
      <button class="new-btn" @click="emit('new')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
        新建会话
      </button>
    </div>

    <!-- 会话列表 -->
    <div class="side-label">最近会话</div>
    <div class="side-list" ref="sideListRef">
      <div
        v-for="c in conversations"
        :key="c.id"
        class="conv-item"
        :class="{ active: c.id === activeId }"
        @click="c.id !== activeId && emit('select', c.id)"
      >
        <template v-if="editingId === c.id">
          <input
            class="rename-input"
            v-model="editText"
            @click.stop
            @keydown.enter="commitRename(c)"
            @keydown.esc="editingId = ''"
            @blur="commitRename(c)"
            autofocus
          />
        </template>
        <template v-else>
          <div class="conv-avatar">
            <img src="/conv-icon.svg" alt="" style="width:100%;height:100%;border-radius:50%"/>
          </div>
          <span class="conv-title">
            <span class="conv-title-inner" :data-text="c.title">{{ c.title }}</span>
          </span>
          <span v-if="c.id === activeId && statusTone === 'busy'" class="loading-dot"></span>
          <span class="conv-time">{{ fmtTime(c.updated_at) }}</span>
          <span class="conv-acts" @click.stop>
            <button class="cact" title="重命名" data-tip="重命名" @click="startRename(c)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3l4 4L8 20l-5 1 1-5z"/></svg>
            </button>
            <button class="cact del" data-tip="删除会话" @click="confirmDel = { id: c.id, title: c.title }">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/></svg>
            </button>
          </span>
        </template>
      </div>
      <div v-if="conversations.length === 0" class="empty">暂无会话，开始一次对话吧</div>
    </div>

    <!-- 底部：设置入口 -->
    <div class="side-footer" @click.stop>
      <button class="settings-btn" @click="settingsOpen = !settingsOpen">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        <span>设置</span>
      </button>

      <!-- 设置浮层 -->
      <div v-if="settingsOpen" class="settings-pop">
        <div class="pop-title">外观</div>
        <div class="theme-group">
          <button
            v-for="o in themeOpts"
            :key="o.value"
            class="theme-opt"
            :class="{ on: theme === o.value }"
            @click="pickTheme(o.value)"
          >{{ o.label }}</button>
        </div>
      </div>
    </div>
  </aside>

  <!-- 删除确认弹窗 -->
  <div v-if="confirmDel" class="del-mask" @click="confirmDel = null">
    <div class="del-dialog" @click.stop>
      <div class="del-title">删除会话</div>
      <div class="del-msg">确定删除「{{ confirmDel.title }}」吗？此操作不可撤销。</div>
      <div class="del-actions">
        <button class="del-cancel" @click="confirmDel = null">取消</button>
        <button class="del-ok" @click="emit('delete', confirmDel.id); confirmDel = null">删除</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 264px; flex-shrink: 0;
  background: var(--panel-deep); border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  transition: width .2s ease;
  overflow: hidden;
}
.sidebar.collapsed { width: 0; border-right: none; }

/* 品牌头 */
.brand-head {
  display: flex; align-items: center; gap: 8px;
  padding: 14px 14px 12px;
}
.brand-logo {
  width: 28px; height: 28px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 15px; color: #fff; border-radius: 8px;
  background: linear-gradient(135deg, #4f6ef7, #7c5cfc);
}
.brand-name {
  flex: 1; font-size: 15px; font-weight: 600; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.collapse-btn {
  width: 32px; height: 32px; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; background: transparent; color: var(--text-dim); cursor: pointer; border-radius: 8px;
}
.collapse-btn:hover { background: var(--border-line); color: var(--text); }
.collapse-btn:hover::after {
  bottom: auto;
  top: calc(100% + 6px);
  left: auto;
  right: 0;
  transform: none;
}
.collapse-btn svg { width: 24px; height: 24px; }

/* 新建会话 */
.side-actions { padding: 0 10px 8px; }
.new-btn {
  width: 100%; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 8px 12px; border-radius: 10px; border: 1px solid var(--border-strong);
  background: var(--panel-soft); color: var(--text); font-size: 13px; cursor: pointer;
  transition: background .15s;
}
.new-btn:hover { background: var(--border-line); }
.new-btn svg { width: 15px; height: 15px; }

/* 分组标签 */
.side-label {
  padding: 10px 14px 6px; font-size: 11px; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: .5px;
}

/* 会话列表 */
.side-list { flex: 1; overflow-y: auto; padding: 0 6px 6px; }
.conv-item {
  position: relative; display: flex; align-items: center; gap: 8px;
  padding: 9px 10px; border-radius: 9px; cursor: pointer; margin-bottom: 2px;
  overflow: hidden;
}
.conv-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  flex-shrink: 0;
  overflow: hidden;
}
.conv-item:hover { background: var(--panel-soft); }
.conv-item.active { background: var(--border-line); }
.conv-title {
  flex: 1; font-size: 13px; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  min-width: 0;
  display: inline-block;
  transition: margin-right .15s;
}
/* hover 时才让出按钮宽度，避免滚动文字被按钮遮挡 */
.conv-item:hover .conv-title {
  margin-right: 56px;
}
.conv-title-inner {
  display: inline-block;
  white-space: nowrap;
  will-change: transform;
}
/* 溢出时 hover 触发 marquee 无缝滚动 */
.conv-item:hover .conv-title.is-overflow .conv-title-inner {
  animation: marquee 6s linear infinite;
}
/* hover 时复制一份文字，实现无缝衔接 */
.conv-item:hover .conv-title.is-overflow .conv-title-inner::after {
  content: attr(data-text);
  margin-right: 2rem;
}
@keyframes marquee {
  from { transform: translateX(0); }
  to { transform: translateX(calc(-1 * var(--scroll-distance, 0px))); }
}
.conv-time { display: none; }
/* 当前会话生成中的 loading 转圈 */
.loading-dot {
  width: 12px; height: 12px; flex-shrink: 0;
  border: 2px solid var(--border-line, #e5e7eb);
  border-top-color: var(--accent, #4f6ef7);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.conv-acts {
  display: flex; gap: 2px; flex-shrink: 0;
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  opacity: 0; transition: opacity .15s;
  z-index: 2;
}
.conv-item:hover .conv-acts { opacity: 1; }
.cact {
  width: 26px; height: 26px; display: inline-flex; align-items: center; justify-content: center;
  border: none; background: transparent; color: var(--text-dim); cursor: pointer; border-radius: 6px;
}
.cact:hover { background: var(--border-strong); color: var(--text); }
.cact.del:hover { color: var(--err); }
.conv-item:has(.cact.del svg[stroke="#22c55e"]) .cact.del,
.cact.del:has(svg path[d*="M5 13"]) { color: var(--err); background: rgba(239,68,68,.12); }
.cact svg { width: 16px; height: 16px; }
.rename-input {
  flex: 1; padding: 4px 8px; border: 1px solid var(--accent); border-radius: 6px;
  background: var(--bg); color: var(--text); font-size: 13px; outline: none;
}
.empty { padding: 24px 12px; text-align: center; color: var(--text-dim); font-size: 13px; }

/* 底部设置 */
.side-footer {
  position: relative;
  padding: 8px 10px;
  border-top: 1px solid var(--border);
}
.settings-btn {
  width: 100%; display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; border: none; border-radius: 9px;
  background: transparent; color: var(--text-dim); font-size: 13px; cursor: pointer;
  transition: background .15s, color .15s;
}
.settings-btn:hover { background: var(--border-line); color: var(--text); }
.settings-btn svg { width: 16px; height: 16px; }

.settings-pop {
  position: absolute; bottom: calc(100% - 4px); left: 10px; right: 10px;
  background: var(--panel); border: 1px solid var(--border-strong);
  border-radius: 12px; padding: 12px;
  box-shadow: 0 8px 28px rgba(0,0,0,.12);
}
.pop-title { font-size: 11px; color: var(--text-dim); margin-bottom: 10px; text-transform: uppercase; letter-spacing: .5px; }

/* 删除确认弹窗 */
.del-mask {
  position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 100;
  display: flex; align-items: center; justify-content: center;
}
.del-dialog {
  background: var(--panel); border: 1px solid var(--border-strong);
  border-radius: 14px; padding: 20px; width: 320px;
  box-shadow: 0 12px 40px rgba(0,0,0,.2);
}
.del-title { font-size: 15px; font-weight: 600; color: var(--text); margin-bottom: 8px; }
.del-msg { font-size: 13px; color: var(--text-dim); line-height: 1.5; margin-bottom: 18px; }
.del-actions { display: flex; gap: 8px; justify-content: flex-end; }
.del-cancel, .del-ok {
  padding: 7px 16px; border-radius: 8px; font-size: 13px; cursor: pointer; border: none;
}
.del-cancel { background: var(--panel-soft); color: var(--text-2); }
.del-cancel:hover { background: var(--border-line); }
.del-ok { background: #ef4444; color: #fff; }
.del-ok:hover { background: #dc2626; }
.theme-group { display: flex; gap: 4px; background: var(--panel-soft); border-radius: 8px; padding: 3px; }
.theme-opt {
  flex: 1; padding: 6px 0; border: none; border-radius: 6px;
  background: transparent; color: var(--text-dim); font-size: 12px; cursor: pointer;
  transition: background .15s, color .15s;
}
.theme-opt.on { background: var(--panel); color: var(--text); box-shadow: 0 1px 3px rgba(0,0,0,.08); }
</style>
