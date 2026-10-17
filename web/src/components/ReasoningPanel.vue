<script setup>
/**
 * 思考过程面板：把「推理（为什么）」与「工具（做了什么）」分成两条道呈现。
 * - 推理道：薄荷左边线 + 灯泡标签 + 弱化正文
 * - 工具道：中性左边线 + 齿轮 + 中文人话名 + 状态（spinner / ✓完成）+ 分步耗时 + 可下钻入参/结果
 * 头部：思考中显示 spinner + 微光扫过；结束显示灯泡 + 「思考过程 · N 步 · 共用时 X 秒」。
 */
import { computed } from 'vue'

const props = defineProps({
  processes: { type: Array, default: () => [] },
  streaming: { type: Boolean, default: false },   // 是否默认展开（生成中）
  active: { type: Boolean, default: false },       // 是否处于「思考中」（驱动 spinner + 微光）
  duration: { type: String, default: '' },
})

// 工具函数名 → 中文人话标签（未知工具回退到原名）
const TOOL_LABELS = {
  compute_salary: '测算薪资个税',
  compute_rent: '测算租房成本',
  compute_commute: '测算通勤成本',
  compute_mortgage: '测算房贷月供',
  compute_cost_index: '测算生活成本指数',
  search_knowledge: '检索知识库',
  ask_user: '向用户澄清',
  export_report: '导出报告',
}
function toolLabel(n) { return TOOL_LABELS[n] || n || '工具调用' }

const stepCount = computed(() => props.processes.length)

function fmt(v) {
  if (v == null) return ''
  if (typeof v === 'string') return v
  try { return JSON.stringify(v, null, 2) } catch { return String(v) }
}
function fmtMs(ms) {
  if (ms == null) return ''
  const s = ms / 1000
  return s < 10 ? s.toFixed(1) + 's' : Math.round(s) + 's'
}

// —— 检索知识库输出解析：`[N] (source: 文件名.md)` + 语料正文 → 结构化引用 ——
function _cleanSnippet(raw) {
  return raw
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map(l => l.replace(/^\s*#{1,6}\s*/, '').replace(/^\s*>\s?/, '').replace(/^\s*[-*]\s+/, '').trim())
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim()
}
function parseSources(output) {
  if (typeof output !== 'string' || !output) return []
  const re = /\[(\d+)\]\s*\(source:\s*([^)]+?)\)/g
  const marks = []
  let m
  while ((m = re.exec(output)) !== null) {
    marks.push({
      n: Number(m[1]),
      source: m[2].trim().replace(/\.md$/i, ''),
      head: m.index,
      bodyStart: m.index + m[0].length,
    })
  }
  if (!marks.length) return []
  const items = marks.map((mk, i) => {
    const end = i + 1 < marks.length ? marks[i + 1].head : output.length
    return { n: mk.n, source: mk.source, text: _cleanSnippet(output.slice(mk.bodyStart, end)) }
  })
  // 去重：向量库存在同一文档的重复副本时，检索会返回内容完全相同的段落，折叠为一条
  const seen = new Set()
  const uniq = []
  for (const it of items) {
    const key = it.source + '\u0000' + it.text
    if (seen.has(key)) continue
    seen.add(key)
    uniq.push(it)
  }
  return uniq
}
function _uniqNames(list) {
  const seen = new Set()
  const out = []
  for (const x of list) if (x.source && !seen.has(x.source)) { seen.add(x.source); out.push(x.source) }
  return out
}

// 为检索工具预解析引用，避免模板里重复调用 parseSources
const viewProcesses = computed(() =>
  props.processes.map(p => {
    if (p.kind === 'tool' && p.name === 'search_knowledge') {
      const sources = parseSources(p.output)
      if (sources.length) return { ...p, sources, srcNames: _uniqNames(sources) }
    }
    return p
  }),
)
</script>

<template>
  <details v-if="stepCount > 0" class="rp" :open="streaming || undefined">
    <summary class="rp-head">
      <span class="rp-ic" :class="{ spin: active }">
        <svg v-if="active" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
          <path d="M12 3a9 9 0 1 0 9 9" />
        </svg>
        <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9 18h6" /><path d="M10 22h4" />
          <path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0 0 12 2z" />
        </svg>
      </span>
      <span class="rp-title" :class="{ shimmer: active }">{{ active ? '正在思考' : '思考过程' }}</span>
      <span class="rp-steps">{{ stepCount }} 步</span>
      <span class="rp-chev">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg>
      </span>
      <span v-if="duration" class="rp-dur">{{ duration }}</span>
    </summary>

    <div class="rp-body">
      <div v-for="(proc, i) in viewProcesses" :key="i" class="rp-item" :class="proc.kind">
        <!-- 推理道 -->
        <div v-if="proc.kind === 'reasoning'" class="rp-reason">
          <div class="rp-rhead">
            <span class="rp-ric">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a7 7 0 0 0-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0 0 12 3z" /><path d="M9.5 21h5" /></svg>
            </span>
            <span class="rp-rtag">思考</span>
            <span v-if="proc.ms != null" class="rp-rtime">{{ fmtMs(proc.ms) }}</span>
          </div>
          <div class="rp-rtext">{{ proc.text }}</div>
        </div>

        <!-- 工具道 -->
        <details v-else-if="proc.kind === 'tool'" class="rp-tool">
          <summary class="rp-thead">
            <span class="rp-tic">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
            </span>
            <span class="rp-tname">{{ toolLabel(proc.name) }}</span>
            <span v-if="proc.running" class="rp-tstat run">
              <svg class="rp-minispin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9" /></svg>
              进行中
            </span>
            <span v-else class="rp-tstat ok">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
              完成
            </span>
            <span v-if="proc.ms != null" class="rp-ttime">{{ fmtMs(proc.ms) }}</span>
            <span class="rp-chev rp-tchev">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg>
            </span>
          </summary>
          <div class="rp-tbody">
            <div v-if="proc.input && Object.keys(proc.input).length" class="rp-td">
              <span class="rp-tdlabel">输入参数</span>
              <pre class="rp-tdpre">{{ fmt(proc.input) }}</pre>
            </div>

            <!-- 检索知识库：命中 RAG 输出格式时，用「引用来源」卡片代替原始语料 dump -->
            <div v-if="proc.sources && proc.sources.length" class="rp-td">
              <span class="rp-tdlabel">引用来源 · {{ proc.srcNames.length }} 篇 / {{ proc.sources.length }} 段</span>
              <div class="rp-cites">
                <div v-for="(s, si) in proc.sources" :key="si" class="rp-cite">
                  <span class="rp-cite-n">{{ s.n }}</span>
                  <div class="rp-cite-body">
                    <span class="rp-cite-src">{{ s.source }}</span>
                    <p class="rp-cite-snip">{{ s.text }}</p>
                  </div>
                </div>
              </div>
            </div>

            <!-- 其它工具 / 解析回退：原始返回 -->
            <div v-else-if="proc.output" class="rp-td">
              <span class="rp-tdlabel">返回结果</span>
              <pre class="rp-tdpre">{{ proc.output }}</pre>
            </div>
          </div>
        </details>
      </div>
    </div>
  </details>
</template>

<style scoped>
.rp { margin-bottom: 8px; }

/* 头部 */
.rp-head {
  display: flex;
  align-items: center;
  gap: 7px;
  list-style: none;
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  color: var(--text-dim);
  padding: 6px 8px;
  margin: 0 -8px;
  border-radius: 9px;
  user-select: none;
}
.rp-head::-webkit-details-marker { display: none; }
.rp-head:hover { background: var(--panel-hover2); }
.rp-ic {
  width: 15px; height: 15px; flex-shrink: 0;
  color: var(--text-faint);
  display: inline-flex; align-items: center; justify-content: center;
}
.rp-ic svg { width: 100%; height: 100%; }
.rp-ic.spin { color: var(--accent); }
.rp-ic.spin svg { animation: rp-rot 0.9s linear infinite; }
@keyframes rp-rot { to { transform: rotate(360deg); } }
.rp-title {
  color: var(--text-dim);
  font-weight: 500;
  line-height: 1;
}
.rp-title.shimmer {
  background: linear-gradient(90deg, var(--text-dim) 0%, var(--accent) 50%, var(--text-dim) 100%);
  background-size: 200% 100%;
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
  animation: rp-shimmer 1.6s ease-in-out infinite;
}
@keyframes rp-shimmer { to { background-position: -200% 0; } }
.rp-steps {
  font-size: 12px; color: var(--text-faint); line-height: 1;
  padding: 2px 7px; border-radius: 999px; background: var(--panel-soft);
}
.rp-dur {
  color: var(--text-faint); font-size: 12px;
  margin-left: auto; margin-right: 4px;
}
.rp-chev {
  color: var(--text-faint);
  width: 14px; height: 14px; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  transition: transform 0.15s;
}
.rp-chev svg { width: 100%; height: 100%; }
.rp[open] > .rp-head .rp-chev { transform: rotate(90deg); }

/* 主体：两条道 */
.rp-body { padding: 2px 0 2px 4px; }
.rp-item {
  position: relative;
  margin: 0 0 2px;
  padding: 8px 0 8px 14px;
  border-left: 2px solid var(--border-line);
}
.rp-item:last-child { margin-bottom: 0; }
.rp-item.reasoning { border-left-color: var(--accent-soft); }
.rp-item.tool { border-left-color: var(--border-strong); }

/* 推理道 */
.rp-rhead { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.rp-ric { width: 13px; height: 13px; color: var(--accent-deep); display: inline-flex; }
.rp-ric svg { width: 100%; height: 100%; }
.rp-rtag { font-size: 12px; color: var(--text-dim); font-weight: 500; }
.rp-rtime { font-size: 11px; color: var(--text-faint); margin-left: auto; padding-right: 4px; }
.rp-rtext {
  font-size: 13px; line-height: 1.65; color: var(--text-muted);
  white-space: pre-wrap; word-break: break-word;
}

/* 工具道 */
.rp-tool { }
.rp-thead {
  display: flex; align-items: center; gap: 7px;
  cursor: pointer; list-style: none;
  font-size: 13px; color: var(--text-2);
}
.rp-thead::-webkit-details-marker { display: none; }
.rp-tic { width: 14px; height: 14px; color: var(--text-faint); flex-shrink: 0; display: inline-flex; }
.rp-tic svg { width: 100%; height: 100%; }
.rp-tname { font-weight: 500; color: var(--text); }
.rp-tstat { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; }
.rp-tstat svg { width: 12px; height: 12px; }
.rp-tstat.ok { color: var(--ok, #10b981); }
.rp-tstat.run { color: var(--warn, #f59e0b); }
.rp-minispin { animation: rp-rot 0.9s linear infinite; }
.rp-ttime { font-size: 11px; color: var(--text-faint); }
.rp-tchev { width: 14px; height: 14px; margin-left: auto; margin-right: 4px; }
.rp-tool[open] > .rp-thead .rp-tchev { transform: rotate(90deg); }
.rp-tbody { padding: 6px 0 2px 21px; }
.rp-td { margin-bottom: 8px; }
.rp-td:last-child { margin-bottom: 0; }
.rp-tdlabel { display: block; font-size: 11px; color: var(--text-dim); margin-bottom: 3px; }
.rp-tdpre {
  white-space: pre-wrap; word-break: break-word;
  font-size: 12px; line-height: 1.5; color: var(--text-2);
  background: var(--panel-soft); border: 1px solid var(--border);
  padding: 7px 9px; border-radius: 7px; margin: 0;
  max-height: 220px; overflow-y: auto;
}

/* 引用来源卡片（检索知识库） */
.rp-cites { display: flex; flex-direction: column; gap: 6px; }
.rp-cite {
  display: flex; gap: 8px;
  background: var(--panel-soft); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 10px;
}
.rp-cite-n {
  flex-shrink: 0;
  min-width: 18px; height: 18px; padding: 0 5px;
  font-size: 11px; font-weight: 600; line-height: 18px; text-align: center;
  color: var(--accent-deep); background: var(--accent-soft);
  border-radius: 5px;
}
.rp-cite-body { min-width: 0; flex: 1; }
.rp-cite-src { font-size: 12px; font-weight: 600; color: var(--text); }
.rp-cite-snip {
  margin: 3px 0 0; font-size: 12px; line-height: 1.55; color: var(--text-muted);
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
  overflow: hidden; word-break: break-word;
}
</style>
