<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'

const KEY = 'city-agent-theme'
const opts = [
  { value: 'dark', label: '深色', icon: '🌙' },
  { value: 'light', label: '浅色', icon: '☀️' },
  { value: 'auto', label: '跟随系统', icon: '◐' },
]

const theme = ref('dark')
const open = ref(false)

const media = window.matchMedia('(prefers-color-scheme: light)')

function applyTheme() {
  let resolved = theme.value
  if (resolved === 'auto') {
    resolved = media.matches ? 'light' : 'dark'
  }
  document.documentElement.setAttribute('data-theme', resolved)
}

function onSystemChange() {
  if (theme.value === 'auto') applyTheme()
}

function pick(v) {
  theme.value = v
  localStorage.setItem(KEY, v)
  applyTheme()
  open.value = false
}

function current() {
  return opts.find(o => o.value === theme.value) || opts[0]
}

onMounted(() => {
  theme.value = localStorage.getItem(KEY) || 'dark'
  applyTheme()
  media.addEventListener('change', onSystemChange)
})
onBeforeUnmount(() => {
  media.removeEventListener('change', onSystemChange)
})
</script>

<template>
  <div class="tt" @click.stop="open = !open" title="主题切换">
    <span class="tt-icon">{{ current().icon }}</span>
    <span class="tt-label">{{ current().label }}</span>
    <span class="tt-caret">▾</span>
    <div v-if="open" class="tt-menu">
      <div
        v-for="o in opts"
        :key="o.value"
        class="tt-opt"
        :class="{ on: theme === o.value }"
        @click.stop="pick(o.value)"
      >
        <span class="tt-opt-icon">{{ o.icon }}</span>{{ o.label }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.tt {
  position: relative;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 9px;
  border-radius: 999px;
  background: var(--panel-soft-trans);
  border: 1px solid var(--border-strong);
  font-size: 11px;
  color: var(--text-3);
  cursor: pointer;
  user-select: none;
  transition: border-color 0.15s;
  margin-left: 8px;
}
.tt:hover { border-color: var(--accent); }
.tt-icon { font-size: 12px; }
.tt-caret { color: var(--text-faint); font-size: 9px; }
.tt-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  min-width: 120px;
  background: var(--panel);
  border: 1px solid var(--border-strong);
  border-radius: 12px;
  padding: 4px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  z-index: 10;
}
.tt-opt {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-2);
  cursor: pointer;
  white-space: nowrap;
}
.tt-opt:hover { background: var(--panel-hover); color: var(--text); }
.tt-opt.on { color: var(--accent); font-weight: 600; }
.tt-opt-icon { font-size: 13px; }
</style>
