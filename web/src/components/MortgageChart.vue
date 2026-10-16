<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: { type: Object, required: true },
})

const el = ref(null)
const donutEl = ref(null)
let chart = null
let donut = null
let themeObserver = null

// 环图模板引用：仅当 data.structure 存在（v-if 渲染后）才接住 DOM
function setDonutEl(elm) {
  if (elm) donutEl.value = elm
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'
}

function fmtWan(v) {
  return v >= 10000 ? (v / 10000).toFixed(1) + '万' : Math.round(v) + ''
}

function render() {
  if (!el.value) return
  const d = props.data
  // 数据不足（缺月供或年限）时不画，避免除零/空图
  if (!d || d.annuity_pay == null || !d.years || d.ep_first == null || d.ep_last == null) return
  if (!chart) chart = echarts.init(el.value)

  const n = Math.max(1, Math.round(d.years * 12))
  // x 轴按年出刻度：按年限自适应步长（约 6 个标签），避免 30 年时 30 个标签挤成一排
  const yearStep = Math.max(1, Math.ceil(d.years / 6))
  const months = []
  const annuity = []
  const equal = []
  // 等额本金月供线性递减：首月 → 末月，公差 = (首月-末月)/(n-1)
  const step = n > 1 ? (d.ep_first - d.ep_last) / (n - 1) : 0
  for (let k = 0; k < n; k++) {
    months.push(k + 1)
    annuity.push(Math.round(d.annuity_pay))
    equal.push(Math.round(d.ep_first - step * k))
  }

  // 交叉月份：等额本金月供递减到与等额本息持平的那个月（仅当平线落在递减区间内才有交点）
  let crossMonth = null
  if (step > 0 && d.annuity_pay > d.ep_last && d.annuity_pay < d.ep_first) {
    crossMonth = Math.round((d.ep_first - d.annuity_pay) / step) + 1
  }
  const crossYear = crossMonth ? (crossMonth / 12).toFixed(1) : null

  const loanWan = d.loan_amount ? (d.loan_amount / 10000).toFixed(0) : null
  // 标题优先用解析出的利率标签（商贷/公积金单利率、组合贷双利率），回退旧字段
  const rateLabel = d.rates_label
    ? (d.loan_type === '组合' ? `组合贷 ${d.rates_label}` : d.rates_label)
    : (d.annual_rate != null ? `${d.annual_rate}%` : '')
  const title = loanWan
    ? `房贷还款计划对比 · 贷款 ${loanWan} 万 · ${d.years} 年 · ${rateLabel}`
    : '房贷还款计划对比'

  chart.setOption({
    backgroundColor: 'transparent',
    title: {
      text: title,
      left: 'center',
      top: 4,
      textStyle: { color: cssVar('--text-strong'), fontSize: 13, fontWeight: 500 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: cssVar('--panel'),
      borderColor: cssVar('--border-strong'),
      textStyle: { color: cssVar('--text'), fontSize: 12 },
      formatter: (params) => {
        const mo = params[0].axisValue
        const yr = (mo % 12 === 0) ? `（第 ${mo / 12} 年）` : ''
        let s = `第 ${mo} 个月${yr}<br/>`
        for (const p of params) s += `${p.marker}${p.seriesName}：${p.value} 元/月<br/>`
        return s
      },
    },
    legend: {
      data: ['等额本息', '等额本金'],
      bottom: 2,
      textStyle: { color: cssVar('--text-dim'), fontSize: 12 },
    },
    grid: { left: 56, right: 24, top: 44, bottom: 48 },
    xAxis: {
      type: 'category',
      data: months,
      boundaryGap: false,
      axisLabel: {
        color: cssVar('--text-dim'),
        // 每 yearStep 年出一个标签，并始终保留最后一年（末期月供最低点）
        interval: (index) => {
          const mo = index + 1
          return mo % (yearStep * 12) === 0 || mo === n
        },
        formatter: (value) => (value % 12 === 0 ? value / 12 + '年' : ''),
      },
      axisLine: { lineStyle: { color: cssVar('--border-line') } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: '元/月',
      nameTextStyle: { color: cssVar('--text-dim'), fontSize: 11 },
      axisLabel: { color: cssVar('--text-dim'), formatter: v => fmtWan(v) },
      splitLine: { lineStyle: { color: cssVar('--border-line') } },
      axisLine: { show: false },
    },
    series: [
      {
        name: '等额本息',
        type: 'line',
        data: annuity,
        symbol: 'none',
        lineStyle: { color: '#3b82c4', width: 2 },
        areaStyle: { color: '#3b82c4', opacity: 0.06 },
      },
      {
        name: '等额本金',
        type: 'line',
        data: equal,
        symbol: 'none',
        lineStyle: { color: '#34d399', width: 2 },
        areaStyle: { color: '#34d399', opacity: 0.06 },
        // 交叉点：两线持平之月，之后等额本金月供更低（“何时反超”的直观锚点）
        markPoint: crossMonth
          ? {
              symbol: 'circle',
              symbolSize: 9,
              itemStyle: { color: '#f59e0b', borderColor: '#fff', borderWidth: 1.5 },
              label: {
                show: true,
                position: 'top',
                distance: 10,
                formatter: `≈${crossYear} 年持平`,
                color: cssVar('--text-strong'),
                fontSize: 11,
                backgroundColor: cssVar('--panel'),
                borderColor: cssVar('--border-strong'),
                borderWidth: 1,
                borderRadius: 4,
                padding: [3, 6],
              },
              data: [{ coord: [crossMonth, Math.round(d.annuity_pay)] }],
            }
          : undefined,
      },
    ],
  })
}

// 组合贷月供构成环图：仅 data.structure 多段时渲染（折线仍画合计月供，构成在这里拆开）
const SEG_COLORS = { 商贷: '#3b82c4', 公积金: '#34d399' }

function renderDonut() {
  const d = props.data
  const segs = d && Array.isArray(d.structure) ? d.structure : null
  if (!donutEl.value) {
    donut?.dispose()
    donut = null
    return
  }
  if (!segs || segs.length < 2) return
  if (!donut) donut = echarts.init(donutEl.value)
  const totalPay = segs.reduce((a, s) => a + (s.annuity_pay || 0), 0)
  donut.setOption({
    backgroundColor: 'transparent',
    title: {
      text: '组合贷月供构成', subtext: `合计 ≈ ${totalPay} 元/月`,
      left: 'center', top: 6,
      textStyle: { color: cssVar('--text-strong'), fontSize: 13, fontWeight: 500 },
      subtextStyle: { color: cssVar('--text-dim'), fontSize: 11 },
    },
    tooltip: {
      trigger: 'item',
      backgroundColor: cssVar('--panel'),
      borderColor: cssVar('--border-strong'),
      textStyle: { color: cssVar('--text'), fontSize: 12 },
      formatter: (p) => {
        const s = segs[p.dataIndex]
        const wan = s.amount >= 10000 ? (s.amount / 10000).toFixed(0) + ' 万' : `${s.amount} 元`
        return `${s.type}贷款 ${wan} @ ${s.rate}%<br/>月供 ≈ ${s.annuity_pay} 元/月（占 ${p.percent}%）`
      },
    },
    legend: { bottom: 2, textStyle: { color: cssVar('--text-dim'), fontSize: 12 } },
    series: [{
      type: 'pie', radius: ['42%', '64%'], center: ['50%', '52%'],
      itemStyle: { borderColor: cssVar('--panel'), borderWidth: 2 },
      label: { color: cssVar('--text-2'), fontSize: 11, formatter: '{b} {d}%' },
      labelLine: { length: 8, length2: 8, lineStyle: { color: cssVar('--border-line') } },
      data: segs.map((s, i) => ({
        name: s.type, value: s.annuity_pay,
        itemStyle: { color: SEG_COLORS[s.type] || ['#f59e0b', '#a78bfa', '#f472b6'][i % 3] },
      })),
    }],
  })
}

function onResize() {
  chart?.resize()
  donut?.resize()
}

onMounted(() => {
  render()
  renderDonut()
  window.addEventListener('resize', onResize)
  themeObserver = new MutationObserver(() => { render(); renderDonut() })
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  })
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  themeObserver?.disconnect()
  chart?.dispose()
  chart = null
  donut?.dispose()
  donut = null
})
// deep watch：props.data 变化后 DOM 已由 Vue 更新（v-if 结构先于 watcher 回调 flush），再刷两张图
watch(() => props.data, () => { render(); renderDonut() }, { deep: true })
</script>

<template>
  <div class="mortgage-wrap">
    <div ref="el" class="mortgage-chart" :style="{ height: data.structure ? '200px' : '240px' }"></div>
    <div v-if="data.structure" :ref="setDonutEl" class="mortgage-donut"></div>
  </div>
</template>

<style scoped>
.mortgage-chart {
  width: 100%;
}
.mortgage-donut {
  width: 100%;
  height: 210px;
}
</style>
