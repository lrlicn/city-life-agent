/**
 * 全局 tooltip 控制器（替代纯 CSS ::after 方案）
 *
 * 用法不变：元素加 data-tip="提示文字" 即可，无需注册。
 *
 * 相比 CSS 伪元素方案的提升：
 * - 单例浮层挂在 body 下，不受任何 overflow/视口边缘裁切，自动上下翻转、左右收边
 * - 显示节奏：首次悬停 350ms 后才出现（快速扫过工具栏不刷屏）；
 *   已有提示时移到相邻元素 80ms 快显（连续阅读不等待）；
 *   离开 150ms 宽限期再隐藏（穿越空隙/滑向邻钮不闪烁）
 * - 滚动 / 点击 / 元素消失时立即收起，不会留下悬空提示
 */

const SHOW_DELAY = 350      // 首次悬停显示延迟
const FAST_SHOW = 80        // 从其他 tooltip 移过来时的快速显示
const HIDE_DELAY = 150      // 隐藏宽限期
const GAP = 8               // 与目标元素的间距

let tipEl = null
let showTimer = null
let hideTimer = null
let current = null          // 当前锚定元素

function ensureTip() {
  if (!tipEl) {
    tipEl = document.createElement('div')
    tipEl.className = 'g-tip'
    tipEl.setAttribute('aria-hidden', 'true')
    document.body.appendChild(tipEl)
  }
  return tipEl
}

function position(target) {
  const el = ensureTip()
  const r = target.getBoundingClientRect()
  const tw = el.offsetWidth
  const th = el.offsetHeight
  // 默认在元素上方；顶部空间不足则翻到下方
  let top = r.top - th - GAP
  if (top < 6) top = Math.min(r.bottom + GAP, window.innerHeight - th - 6)
  // 水平居中于元素，超出视口时收边
  let left = r.left + r.width / 2 - tw / 2
  left = Math.max(6, Math.min(left, window.innerWidth - tw - 6))
  el.style.top = `${Math.round(top)}px`
  el.style.left = `${Math.round(left)}px`
}

function show(target) {
  const text = target.getAttribute('data-tip')
  if (!text) return
  const el = ensureTip()
  el.textContent = text
  el.classList.add('on')
  position(target)
}

function hideNow() {
  clearTimeout(showTimer)
  clearTimeout(hideTimer)
  if (tipEl) tipEl.classList.remove('on')
  current = null
}

function anchorOf(e) {
  const t = e.target
  return t && t.closest ? t.closest('[data-tip]') : null
}

document.addEventListener('pointerover', (e) => {
  const target = anchorOf(e)
  if (!target) return
  if (target === current) {
    // 同一锚点内部子元素（如图标）间微移：取消宽限期隐藏，否则悬停中提示会莫名消失
    clearTimeout(hideTimer)
    return
  }
  current = target
  const visible = tipEl && tipEl.classList.contains('on')
  clearTimeout(showTimer)
  clearTimeout(hideTimer)
  showTimer = setTimeout(() => show(target), visible ? FAST_SHOW : SHOW_DELAY)
})

document.addEventListener('pointerout', (e) => {
  const target = anchorOf(e)
  if (!target || target !== current) return
  // 仍在同一锚点内部移动（如从图标跨到按钮边缘）：什么都不做。
  // 不能清 showTimer，否则图标按钮内微移会把“待显示”定时误杀 → 提示永不出现
  const next = e.relatedTarget
  if (next instanceof Node && target.contains(next)) return
  clearTimeout(showTimer)
  hideTimer = setTimeout(hideNow, HIDE_DELAY)
})

// 滚动 / 点击 / 窗口尺寸变化 → 立即收起（避免悬空或错位）
window.addEventListener('scroll', hideNow, true)
window.addEventListener('resize', hideNow)
document.addEventListener('click', () => { clearTimeout(showTimer); hideNow() }, true)
