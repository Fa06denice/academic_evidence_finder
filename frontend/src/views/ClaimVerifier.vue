<template>
  <div class="p-8 max-w-4xl mx-auto w-full">

    <div class="mb-8">
      <h1 class="text-2xl font-bold text-white mb-1.5">Claim Verifier</h1>
      <p class="text-sm text-muted">Submit a scientific claim and get evidence from peer-reviewed literature.</p>
    </div>

    <div class="bg-surface border border-border rounded-2xl p-6 mb-6">
      <label class="block text-xs font-semibold text-muted uppercase tracking-wider mb-3">Claim to verify</label>
      <textarea v-model="claim" :disabled="loading" rows="3"
        placeholder="e.g. Intermittent fasting improves insulin sensitivity in adults with type 2 diabetes."
        class="w-full bg-surface2 border border-border rounded-xl px-4 py-3 text-sm text-white placeholder-muted resize-none focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30 transition-all disabled:opacity-50"
        @keydown.ctrl.enter="submit" @keydown.meta.enter="submit"
      ></textarea>
      <div class="flex items-center gap-4 mt-4">
        <div class="flex items-center gap-2">
          <span class="text-xs text-muted">Papers:</span>
          <select v-model="depth" :disabled="loading"
            class="bg-surface2 border border-border rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-accent/50 disabled:opacity-50">
            <option value="5">5 · Fast</option>
            <option value="10">10 · Balanced</option>
            <option value="15">15 · Deep</option>
          </select>
        </div>
        <button @click="submit" :disabled="loading || !claim.trim()"
          class="ml-auto flex items-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-xl transition-all duration-150">
          <span v-if="loading" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          <span>{{ loading ? 'Analysing…' : 'Verify Claim' }}</span>
        </button>
      </div>
    </div>

    <!-- Progress -->
    <div v-if="loading" class="mb-5">
      <div class="flex items-center gap-3 mb-2">
        <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin shrink-0"></div>
        <span class="text-sm text-muted">{{ progressMsg }}</span>
      </div>
      <div class="bg-surface2 rounded-full h-1 overflow-hidden">
        <div class="h-full bg-accent rounded-full transition-all duration-500" :style="{ width: progressPct + '%' }"></div>
      </div>
    </div>

    <!-- Verdict banner -->
    <div v-if="verdict && !loading" class="mb-6 fade-up">
      <div class="rounded-2xl p-5 border" :class="verdictStyle.bg">
        <div class="flex items-center gap-3 mb-3">
          <span class="text-2xl">{{ verdictStyle.icon }}</span>
          <div>
            <div class="text-xs font-semibold uppercase tracking-wider mb-0.5" :class="verdictStyle.color">Overall Verdict</div>
            <h2 class="text-lg font-bold text-white">{{ verdictStyle.label }}</h2>
          </div>
          <div class="ml-auto text-right">
            <div class="text-xs text-muted mb-0.5">Confidence</div>
            <span class="font-bold text-base" :class="verdictStyle.color">{{ verdict.overall_confidence || '—' }}</span>
          </div>
        </div>
        <div v-if="verdict.evidence_strength !== undefined" class="mt-2">
          <div class="flex justify-between text-xs text-muted mb-1">
            <span>Evidence strength</span><span>{{ verdict.evidence_strength }}/10</span>
          </div>
          <div class="bg-surface/40 rounded-full h-2">
            <div class="h-2 rounded-full gauge-bar" :style="{ width: (verdict.evidence_strength * 10) + '%', background: verdictStyle.barColor }"></div>
          </div>
        </div>
        <p v-if="verdict.summary" class="mt-3 text-sm text-white/80 leading-relaxed">{{ verdict.summary }}</p>
        <div class="mt-4 flex gap-2">
          <button @click="exportBibtex" class="btn-sm">📄 Export BibTeX</button>
          <button @click="copyAll" class="btn-sm">{{ copiedAll ? '✓ Copied' : '📋 Copy citations' }}</button>
        </div>
      </div>
    </div>

    <!-- Paper cards -->
    <div v-if="results.length" class="space-y-3">
      <div class="flex items-center gap-2 mb-4">
        <h2 class="text-sm font-semibold text-white">{{ results.length }} Papers Analysed</h2>
        <div class="flex gap-1.5 ml-auto">
          <button v-for="f in filters" :key="f.val" @click="activeFilter = f.val"
            :class="activeFilter === f.val ? 'bg-accent text-white border-accent' : 'text-muted hover:text-white'"
            class="px-2.5 py-1 rounded-lg text-xs font-medium border border-border transition-all">
            {{ f.label }}
          </button>
        </div>
      </div>
      <PaperCard v-for="item in filtered" :key="item.paper.paperId"
        :paper="item.paper" :analysis="item.analysis" />
    </div>

    <!-- Loading skeletons -->
    <div v-if="loading && paperPool.length && !results.length" class="space-y-3">
      <div v-for="i in Math.min(paperPool.length, 3)" :key="i"
        class="shimmer rounded-xl h-20 border border-border"></div>
    </div>

    <!-- Empty state -->
    <div v-if="!loading && !results.length && !verdict" class="text-center py-24">
      <div class="text-5xl mb-4">🧪</div>
      <h3 class="text-base font-semibold text-white mb-1">Ready to verify</h3>
      <p class="text-sm text-muted max-w-xs mx-auto">Enter a claim above to search and analyse peer-reviewed evidence automatically.</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { streamPost } from '../api/index.js'
import { historyStore } from '../stores/history.js'
import PaperCard from '../components/PaperCard.vue'

const claim        = ref('')
const depth        = ref('10')
const loading      = ref(false)
const progressMsg  = ref('Starting…')
const progressPct  = ref(0)
const verdict      = ref(null)
const results      = ref([])
const paperPool    = ref([])
const activeFilter = ref('ALL')
const copiedAll    = ref(false)

const filters = [
  { val: 'ALL',         label: 'All' },
  { val: 'SUPPORTS',    label: '🟢 Supports' },
  { val: 'CONTRADICTS', label: '🔴 Contradicts' },
  { val: 'NEUTRAL',     label: '⚪ Neutral' },
]

const filtered = computed(() => {
  if (activeFilter.value === 'ALL') return results.value
  return results.value.filter(r => r.analysis.verdict === activeFilter.value)
})

const VERDICT_STYLES = {
  SUPPORTED:             { icon: '✅', label: 'Claim Supported',      color: 'text-emerald-400', bg: 'bg-emerald-500/5  border-emerald-500/20', barColor: '#22c55e' },
  PARTIALLY_SUPPORTED:   { icon: '⚡', label: 'Partially Supported',   color: 'text-amber-400',   bg: 'bg-amber-500/5    border-amber-500/20',   barColor: '#f59e0b' },
  CONTRADICTED:          { icon: '❌', label: 'Claim Contradicted',     color: 'text-red-400',     bg: 'bg-red-500/5      border-red-500/20',     barColor: '#ef4444' },
  INSUFFICIENT_EVIDENCE: { icon: '❓', label: 'Insufficient Evidence',  color: 'text-gray-400',   bg: 'bg-gray-500/5     border-gray-500/20',    barColor: '#6b7280' },
  MIXED:                 { icon: '🔀', label: 'Mixed Evidence',         color: 'text-purple-400',  bg: 'bg-purple-500/5   border-purple-500/20',  barColor: '#a855f7' },
}
const verdictStyle = computed(() =>
  VERDICT_STYLES[verdict.value?.overall_verdict] || VERDICT_STYLES.MIXED
)

async function submit() {
  if (!claim.value.trim() || loading.value) return
  loading.value = true
  results.value = []
  paperPool.value = []
  verdict.value = null
  progressPct.value = 0
  progressMsg.value = 'Searching literature…'

  await streamPost('/api/verify', { claim: claim.value, max_papers: +depth.value }, {
    onProgress(e) {
      progressMsg.value = e.message
      if (e.step && e.total) progressPct.value = Math.round((e.step / e.total) * 85)
    },

    // Backend envoie la liste complète ici → on la stocke
    onPapers(papers) {
      paperPool.value = papers
      progressMsg.value = `Analysing ${papers.length} papers…`
      progressPct.value = 15
    },

    // Backend envoie: { type:"analysis", index:i, total:N, paper_id:pid, analysis:{...} }
    onAnalysis(e) {
      progressMsg.value = `Paper ${(e.index ?? 0) + 1} / ${e.total}`
      progressPct.value = 15 + Math.round(((e.index + 1) / e.total) * 75)
      const paper = paperPool.value.find(p => p.paperId === e.paper_id)
      if (paper && e.analysis) {
        results.value.push({ paper, analysis: e.analysis })
      }
    },

    onVerdict(v) { verdict.value = v },
    onDone() {
      progressPct.value = 100
      loading.value = false
      historyStore.add({ type: 'verify', query: claim.value, path: '/' })
    },
    onError(e) { progressMsg.value = '⚠ ' + e.message; loading.value = false }
  })
}

function exportBibtex() {
  let bib = ''
  results.value.forEach(({ paper }, i) => {
    const doi = paper.externalIds?.DOI || ''
    bib += `@article{paper${i+1},\n  title = {${paper.title}},\n  year  = {${paper.year}},\n  doi   = {${doi}}\n}\n\n`
  })
  const a = document.createElement('a')
  a.href = 'data:text/plain;charset=utf-8,' + encodeURIComponent(bib)
  a.download = 'references.bib'
  a.click()
}

function copyAll() {
  const lines = results.value.map(({ paper }, i) => {
    const auth = paper.authors?.[0]?.name?.split(' ').pop() || 'Unknown'
    const doi  = paper.externalIds?.DOI || ''
    return `[${i+1}] ${auth} (${paper.year}). ${paper.title}.${doi ? ' https://doi.org/' + doi : ''}`
  })
  navigator.clipboard.writeText(lines.join('\n')).then(() => {
    copiedAll.value = true
    setTimeout(() => { copiedAll.value = false }, 2000)
  })
}
</script>

<style scoped>
.btn-sm {
  @apply px-3 py-1.5 text-xs font-medium bg-surface2 border border-border rounded-lg text-muted hover:text-white hover:border-accent/40 transition-all duration-150;
}
</style>
