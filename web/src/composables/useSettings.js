// 全局应用设置：目前含「工具审批」开关，跨组件共享
// （ChatView 输入条状态 chip + Sidebar 设置面板的权威开关）。
// 模块级单例 ref + localStorage 持久化：任一处修改即时同步到另一处，且跨会话生效。
import { ref, watch } from 'vue'

// requireApproval=true：工具执行前弹确认卡片（需审批）；false：BYPASS 自动放行（免审批）
const requireApproval = ref(localStorage.getItem('requireApproval') === '1')
watch(requireApproval, (v) => localStorage.setItem('requireApproval', v ? '1' : '0'))

export function useSettings() {
  function toggleApproval() {
    requireApproval.value = !requireApproval.value
  }
  return { requireApproval, toggleApproval }
}
