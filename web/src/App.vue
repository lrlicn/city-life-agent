<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import ChatView from './components/ChatView.vue'
import TokenGate from './components/TokenGate.vue'
import { getToken, getUserName } from './auth.js'

// 登录门：
//  - 令牌缺失/无效 → 任一 /api 请求 401 → authFetch 广播 'agent-unauthorized' → 弹「登录」模式；
//  - 邀请链接已带有效令牌、但还没填过昵称 → 挂载时弹「仅补昵称」模式。
// 本地未开启鉴权（无令牌）时两者都不触发，零摩擦。
const gateOpen = ref(false)
const gateMode = ref('login')   // 'login' | 'name'

function onUnauthorized() {
  gateMode.value = 'login'
  gateOpen.value = true
}

onMounted(() => {
  window.addEventListener('agent-unauthorized', onUnauthorized)
  if (getToken() && !getUserName()) {
    gateMode.value = 'name'
    gateOpen.value = true
  }
})
onBeforeUnmount(() => window.removeEventListener('agent-unauthorized', onUnauthorized))
</script>

<template>
  <ChatView />
  <TokenGate v-if="gateOpen" :mode="gateMode" />
</template>
