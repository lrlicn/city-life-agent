<script setup>
// 收藏笔记本：搜索 / 标签筛选 / 备注与标签编辑 / 跳转原会话轮次 / 导出 Markdown
import { ref, computed } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  bookmarks: { type: Array, default: () => [] },
  conversations: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'jump', 'refresh'])

// 来源会话已删除 → 卡片标记失效，隐藏跳转（收藏内容是全文快照，仍可查看/导出）
const convIds = computed(() => new Set(props.conversations.map(c => c.id)))
function stale(b) { return !convIds.value.has(b.conversation_id) }

const query = ref('')
const activeTag = ref('')

// 全部标签（逗号分隔去重）
const allTags = computed(() => {
  const set = new Set()
  for (const b of props.bookmarks) {
    for (const t of (b.tags || '').split(',')) {
      const s = t.trim()
      if (s) set.add(s)
    }
  }
  return [...set]
})

// 搜索 + 标签过滤
const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  return props.bookmarks.filter(b => {
    if (activeTag.value) {
      const tags = (b.tags || '').split(',').map(x => x.trim())
      if (!tags.includes(activeTag.value)) return false
    }
    if (!q) return true
    return [b.title, b.content, b.note, b.tags].some(x => (x || '').toLowerCase().includes(q))
  })
})

// ---- 备注 / 标签编辑（失焦即保存）----
async function saveField(b, field, value) {
  if ((b[field] || '') === value) return
  b[field] = value  // 本地先行更新
  await fetch(`/api/bookmarks/${b.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ [field]: value }),
  })
  emit('refresh')
}

async function remove(b) {
  await fetch(`/api/bookmarks/${b.id}`, { method: 'DELETE' })
  emit('refresh')
}

// ---- Markdown 导出（纯前端生成，单条 / 全部）----
function toMd(b) {
  const tags = b.tags ? `**标签**：${b.tags}\n\n` : ''
  const note = b.note ? `### 我的备注\n\n${b.note}\n\n` : ''
  const time = new Date(b.updated_at * 1000).toLocaleString()
  return `## ${b.title || '收藏'}\n\n${tags}${note}${b.content}\n\n> 来源：会话 ${b.conversation_id} · 第 ${b.turn} 轮 · 收藏于 ${time}\n\n---\n\n`
}

function download(name, text) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }))
  a.download = name
  a.click()
  URL.revokeObjectURL(a.href)
}

function exportOne(b) {
  download(`收藏-${(b.title || 'note').slice(0, 20)}.md`, `# 城事小灵通 · 收藏\n\n${toMd(b)}`)
}

function exportAll() {
  if (!filtered.value.length) return
  const body = filtered.value.map(toMd).join('')
  download(`城事小灵通-收藏笔记本-${new Date().toISOString().slice(0, 10)}.md`,
    `# 城事小灵通 · 收藏笔记本\n\n共 ${filtered.value.length} 条\n\n---\n\n${body}`)
}

function md(src) {
  return marked.parse(src || '')
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <aside class="panel">
      <header class="p-head">
        <span class="p-title">★ 收藏笔记本</span>
        <span class="p-count">{{ filtered.length }} / {{ props.bookmarks.length }}</span>
        <div class="p-head-acts">
          <button class="p-btn" :disabled="!filtered.length" data-tip="把当前列表导出为 Markdown" @click="exportAll">导出 MD</button>
          <button class="p-btn close" data-tip="关闭" @click="emit('close')">✕</button>
        </div>
      </header>

      <div class="p-tools">
        <input v-model="query" class="p-search" placeholder="搜索标题 / 内容 / 备注 / 标签…" />
        <div v-if="allTags.length" class="p-tags">
          <button class="tag-chip" :class="{ on: !activeTag }" @click="activeTag = ''">全部</button>
          <button
            v-for="t in allTags"
            :key="t"
            class="tag-chip"
            :class="{ on: activeTag === t }"
            @click="activeTag = activeTag === t ? '' : t"
          >{{ t }}</button>
        </div>
      </div>

      <div class="p-list">
        <div v-if="!filtered.length" class="p-empty">
          {{ props.bookmarks.length ? '没有匹配的收藏' : '还没有收藏 —— 点击回答下方的 ☆ 把有用的内容收进来' }}
        </div>
        <article v-for="b in filtered" :key="b.id" class="card" :class="{ 'is-stale': stale(b) }">
          <div class="c-head" :class="{ clickable: !stale(b) }" @click="!stale(b) && emit('jump', b)" :data-tip="stale(b) ? '来源会话已删除' : '跳回原会话该轮'">
            <span class="c-title">{{ b.title || '未命名收藏' }}</span>
            <span v-if="stale(b)" class="c-stale">来源已失效</span>
            <span v-else class="c-jump">↗</span>
          </div>
          <input
            class="c-tags"
            :value="b.tags"
            placeholder="标签（逗号分隔，如：社保, 重要）"
            @blur="saveField(b, 'tags', $event.target.value.trim())"
            @keydown.enter="$event.target.blur()"
          />
          <details class="c-body">
            <summary>查看收藏内容</summary>
            <div class="markdown" v-html="md(b.content)"></div>
          </details>
          <textarea
            class="c-note"
            :value="b.note"
            placeholder="写点备注…"
            rows="1"
            @blur="saveField(b, 'note', $event.target.value)"
          ></textarea>
          <div class="c-acts">
            <button v-if="!stale(b)" class="c-btn" @click="emit('jump', b)" data-tip="跳转原会话轮次">↻ 跳转</button>
            <button class="c-btn" @click="exportOne(b)" data-tip="导出这条为 Markdown">⬇ 导出</button>
            <button class="c-btn del" @click="remove(b)" data-tip="删除收藏">✕ 删除</button>
          </div>
        </article>
      </div>
    </aside>
  </div>
</template>

<style scoped>
/* 本组件未继承 ChatView 的 scoped 通配，需自带 box-sizing，否则 width:100% + padding 会溢出 */
.overlay, .overlay * { box-sizing: border-box; }
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}
.panel {
  width: 440px;
  max-width: 94vw;
  height: 100%;
  background: var(--panel);
  border-left: 1px solid var(--border-strong);
  box-shadow: -12px 0 40px rgba(0, 0, 0, 0.3);
  display: flex;
  flex-direction: column;
  animation: slide-in 0.22s ease;
}
@keyframes slide-in {
  from { transform: translateX(40px); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
.p-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}
.p-title { font-size: 15px; font-weight: 600; color: var(--text-strong); }
.p-count { font-size: 12px; color: var(--text-faint); }
.p-head-acts { margin-left: auto; display: flex; gap: 6px; }
.p-btn {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 7px;
  cursor: pointer;
}
.p-btn:hover { border-color: var(--accent); color: var(--accent); }
.p-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.p-btn.close { border: none; font-size: 14px; }

.p-tools { padding: 10px 16px 4px; }
.p-search {
  width: 100%;
  border: 1px solid var(--border);
  background: var(--panel-soft);
  color: var(--text);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13px;
  outline: none;
}
.p-search:focus { border-color: var(--accent); }
.p-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.tag-chip {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  padding: 2px 9px;
  border-radius: 999px;
  cursor: pointer;
}
.tag-chip.on { border-color: var(--accent); color: var(--accent); background: var(--accent-ring); }

.p-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) transparent;
}
.p-empty { color: var(--text-faint); font-size: 13px; text-align: center; padding: 40px 10px; }

.card {
  border: 1px solid var(--border);
  background: var(--panel-soft-trans);
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.c-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: -3px -6px;
  padding: 3px 6px;
  border-radius: 8px;
  transition: background .15s;
}
.c-head.clickable { cursor: pointer; }
.c-title {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* hover 对齐全局可点击行模式：整行底色提亮 + 文字加重（同侧边栏/消息操作） */
.c-head.clickable:hover { background: var(--panel-hover); }
.c-head.clickable:hover .c-title { color: var(--text-strong); }
.c-head.clickable:hover .c-jump { color: var(--text); }
.c-stale {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-faint);
  border: 1px solid var(--border);
  padding: 1px 7px;
  border-radius: 999px;
}
.card.is-stale .c-title { color: var(--text-dim); }
.c-jump { color: var(--text-faint); font-size: 13px; }

.c-tags, .c-note {
  width: 100%;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  padding: 3px 6px;
  border-radius: 6px;
  outline: none;
  font-family: inherit;
  resize: none;
}
.c-tags:hover, .c-note:hover { border-color: var(--border); }
.c-tags:focus, .c-note:focus { border-color: var(--accent); color: var(--text); background: var(--panel-soft); }

.c-body summary { cursor: pointer; font-size: 12px; color: var(--text-faint); user-select: none; }
.c-body .markdown { font-size: 13px; line-height: 1.6; color: var(--text-2); margin-top: 6px; max-height: 300px; overflow-y: auto; }
.c-body :deep(table) { border-collapse: collapse; font-size: 12px; }
.c-body :deep(th), .c-body :deep(td) { border: 1px solid var(--border-line); padding: 2px 6px; }

.c-acts { display: flex; gap: 6px; }
.c-btn {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  padding: 3px 9px;
  border-radius: 6px;
  cursor: pointer;
}
.c-btn:hover { color: var(--accent); border-color: var(--accent); }
.c-btn.del:hover { color: var(--err); border-color: var(--err); }
</style>
