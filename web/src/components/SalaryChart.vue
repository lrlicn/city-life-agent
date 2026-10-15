<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: { type: Object, required: true },
})

const el = ref(null)
let chart = null
let themeObserver = null

// 从全局主题变量读取颜色（深/浅两档随 data-theme 变化）
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'
}

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  const d = props.data
  const title =
    d.city && d.monthly_salary != null
      ? `${d.city} · 月薪 ${Number(d.monthly_salary).toLocaleString()} 元到手构成`
      : '到手金额构成'
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
      axisPointer: { type: 'shadow' },
      backgroundColor: cssVar('--panel'),
      borderColor: cssVar('--border-strong'),
      textStyle: { color: cssVar('--text'), fontSize: 12 },
      valueFormatter: v => (v >= 10000 ? (v / 10000).toFixed(2) + ' 万' : v + ' 元'),
    },
    grid: { left: 56, right: 64, top: 44, bottom: 8 },
    xAxis: {
      type: 'value',
      axisLabel: {
        color: cssVar('--text-dim'),
        formatter: v => (v >= 10000 ? (v / 10000).toFixed(1) + '万' : v),
      },
      splitLine: { lineStyle: { color: cssVar('--border-line') } },
      axisLine: { show: false },
    },
    yAxis: {
      type: 'category',
      data: ['社保', '公积金', '个税', '到手'],
      axisLabel: { color: cssVar('--text-2') },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: [
          { value: d.social, itemStyle: { color: '#f59e0b', borderRadius: [0, 6, 6, 0] } },
          { value: d.fund, itemStyle: { color: '#3b82c4', borderRadius: [0, 6, 6, 0] } },
          { value: d.tax, itemStyle: { color: '#ef4444', borderRadius: [0, 6, 6, 0] } },
          { value: d.net, itemStyle: { color: '#34d399', borderRadius: [0, 6, 6, 0] } },
        ],
        barWidth: 22,
        label: {
          show: true,
          position: 'right',
          color: cssVar('--text'),
          formatter: p => (p.value >= 10000 ? (p.value / 10000).toFixed(2) + '万' : p.value + ''),
        },
      },
    ],
  })
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  render()
  window.addEventListener('resize', onResize)
  // 主题切换（html[data-theme] 变化）时重新取色重绘
  themeObserver = new MutationObserver(() => render())
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
})
watch(() => props.data, render, { deep: true })
</script>

<template>
  <div ref="el" class="salary-chart"></div>
</template>

<style scoped>
.salary-chart {
  width: 100%;
  height: 240px;
}
</style>
