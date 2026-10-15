<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: { type: Object, required: true },
})

const el = ref(null)
let chart = null
let themeObserver = null

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'
}

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  const d = props.data
  const title =
    d.city && d.monthly_rent != null
      ? `${d.city} · 月租 ${Number(d.monthly_rent).toLocaleString()} 元 · 入住首笔构成`
      : '租房成本构成'
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
    grid: { left: 76, right: 64, top: 44, bottom: 8 },
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
      data: ['押金(可退)', '中介费', '首月租金'],
      axisLabel: { color: cssVar('--text-2') },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: [
          { value: d.deposit, itemStyle: { color: '#3b82c4', borderRadius: [0, 6, 6, 0] } },
          { value: d.agency, itemStyle: { color: '#f59e0b', borderRadius: [0, 6, 6, 0] } },
          { value: d.monthly_rent, itemStyle: { color: '#34d399', borderRadius: [0, 6, 6, 0] } },
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
  <div ref="el" class="rent-chart"></div>
</template>

<style scoped>
.rent-chart {
  width: 100%;
  height: 220px;
}
</style>
