<script setup>
import { ref } from 'vue'
import { getToken, setToken, getUserName, setUserName } from '../auth.js'

// mode: 'login' = 昵称 + 访问令牌（缺令牌 / 401 时的完整登录）；
//       'name'  = 仅补昵称（邀请链接已带有效令牌，只差一个显示名）。
const props = defineProps({ mode: { type: String, default: 'login' } })

const name = ref(getUserName())
const val = ref(getToken())
const err = ref('')

function save() {
  const n = name.value.trim()
  if (!n) { err.value = '请输入你的昵称'; return }
  setUserName(n)
  if (props.mode === 'login') {
    const t = val.value.trim()
    if (!t) { err.value = '请输入访问令牌'; return }
    setToken(t)
  }
  // 保存后整页重载：以新身份重新拉取数据（简单可靠，避免逐个重放请求）
  location.reload()
}
</script>

<template>
  <div class="gate-mask">
    <div class="gate-card">
      <div class="gate-logo">
        <svg viewBox="0 0 64 64" width="44" height="44" aria-hidden="true">
          <line x1="32" y1="19" x2="32" y2="12" stroke="#0A7F60" stroke-width="3.2" stroke-linecap="round"/>
          <circle cx="32" cy="10.5" r="3.2" fill="#0A7F60"/>
          <rect x="14" y="19" width="36" height="29" rx="6" fill="#0A7F60"/>
          <circle cx="25" cy="32" r="3.6" fill="#fff"/>
          <circle cx="39" cy="32" r="3.6" fill="#fff"/>
          <path d="M25 41 Q32 45 39 41" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/>
        </svg>
      </div>
      <h2 class="gate-title">{{ mode === 'name' ? '欢迎回来' : '登录城事小灵通' }}</h2>
      <p class="gate-sub">{{ mode === 'name' ? '给自己起个显示名，方便辨认这台设备上的会话' : '请输入管理员分发的访问令牌' }}</p>
      <input
        v-model="name"
        class="gate-input"
        type="text"
        placeholder="你的昵称"
        maxlength="24"
        autocomplete="off"
        @keydown.enter="save"
      />
      <input
        v-if="mode === 'login'"
        v-model="val"
        class="gate-input gate-input-2"
        type="password"
        placeholder="访问令牌"
        autocomplete="off"
        @keydown.enter="save"
      />
      <div v-if="err" class="gate-err">{{ err }}</div>
      <button class="gate-save" @click="save">进入</button>
    </div>
  </div>
</template>

<style scoped>
/* 本组件挂在 App.vue 下，未继承 ChatView 的 scoped 通配重置，需自带 box-sizing；
   否则 .gate-input 的 width:100% + padding 会按 content-box 溢出卡片、与按钮错位 */
.gate-mask, .gate-mask * { box-sizing: border-box; }
.gate-mask {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(10, 20, 18, 0.55);
  backdrop-filter: blur(6px);
}
.gate-card {
  width: min(92vw, 380px);
  padding: 32px 28px;
  border-radius: 20px;
  background: var(--panel, #fff);
  border: 1px solid var(--border-soft, rgba(0, 0, 0, 0.08));
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.25);
  text-align: center;
  color: var(--text, #1a1a1a);
}
.gate-logo { margin-bottom: 8px; }
.gate-title { font-size: 18px; font-weight: 600; margin: 0 0 8px; }
.gate-sub { font-size: 13px; color: var(--text-dim, #666); margin: 0 0 18px; line-height: 1.6; }
.gate-input {
  width: 100%;
  padding: 11px 14px;
  font-size: 14px;
  border-radius: 12px;
  border: 1px solid var(--border, rgba(0, 0, 0, 0.15));
  background: var(--bg-base, #f7f7f8);
  color: inherit;
  outline: none;
}
.gate-input-2 { margin-top: 10px; }
.gate-input:focus { border-color: #0A7F60; }
.gate-err { color: #d33; font-size: 12px; margin-top: 8px; }
.gate-save {
  margin-top: 16px;
  width: 100%;
  padding: 11px 0;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  background: #0A7F60;
  border: none;
  border-radius: 12px;
  cursor: pointer;
}
.gate-save:hover { background: #0b9068; }
</style>
