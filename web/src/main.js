import { createApp } from 'vue'
import App from './App.vue'
import { consumeInviteToken } from './auth.js'
import './assets/theme.css'
import './tooltip'

// 先于挂载消费邀请链接里的 ?t= 令牌，让 ChatView 首个数据请求即带身份
consumeInviteToken()

createApp(App).mount('#app')
