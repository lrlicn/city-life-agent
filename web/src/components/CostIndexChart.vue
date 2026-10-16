<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as echarts from 'echarts'

// 生活成本指数：多城市 × 多品类（租房/餐饮/交通/日用）分组柱状对比图。
// data = { base_city, categories: string[], cities: [{ city, index: number[], composite }], cheapest }
const props = defineProps({
  data: { type: Object, required: true },
})

const el = ref(null)
let chart = null
let themeObserver = null

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'
}

const PALETTE = ['#3b82c4', '#34d399', '#f59e0b', '#a78bfa', '#f472b6', '#60a5fa', '#22d3ee']

function render() {
  if (!el.value) return
  if (!chart) chart = echarts.init(el.value)
  const d = props.data
  const cats = d.categories || []
  const cities = d.cities || []
  if (!cats.length || !cities.length) return
  const base = d.base_city || ''
  const title = base ? `生活成本指数对比（基准：${base} = 100）` : '生活成本指数对比'
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
      valueFormatter: v => `${v}（${v >= 100 ? '高于' : '低于'}基准）`,
    },
    legend: {
      data: cities.map(c => (c.city === base ? c.city + ' ·基准' : c.city)),
      bottom: 2,
      itemGap: 14,
      textStyle: { color: cssVar('--text-2'), fontSize: 11 },
      itemWidth: 12,
      itemHeight: 8,
    },
    // right 留宽：基准线标签「基准 100」画在网格右外侧，不被裁；bottom 抬高：分离 x 轴品类标签与图例
    grid: { left: 48, right: 68, top: 44, bottom: 58 },
    xAxis: {
      type: 'category',
      data: cats,
      axisLabel: { color: cssVar('--text-2') },
      axisLine: { lineStyle: { color: cssVar('--border-line') } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: '指数',
      nameTextStyle: { color: cssVar('--text-dim'), fontSize: 11 },
      axisLabel: { color: cssVar('--text-dim') },
      splitLine: { lineStyle: { color: cssVar('--border-line') } },
    },
    // 基准线 100：帮助一眼看出谁贵谁便宜
    series: cities.map((c, i) => ({
      name: c.city === base ? c.city + ' ·基准' : c.city,
      type: 'bar',
      data: c.index,
      barMaxWidth: 22,
      itemStyle: {
        color: PALETTE[i % PALETTE.length],
        borderRadius: [4, 4, 0, 0],
        opacity: c.city === base ? 1 : 0.86,
      },
      markLine:
        i === 0
          ? {
              silent: true,
              symbol: 'none',
              lineStyle: { type: 'dashed', color: cssVar('--text-dim'), width: 1 },
              label: { formatter: '基准 100', position: 'end', distance: 4, color: cssVar('--text-dim'), fontSize: 10 },
              data: [{ yAxis: 100 }],
            }
          : undefined,
    })),
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
  <div ref="el" class="cost-chart"></div>
</template>

<style scoped>
.cost-chart {
  width: 100%;
  height: 320px;
}
</style>
