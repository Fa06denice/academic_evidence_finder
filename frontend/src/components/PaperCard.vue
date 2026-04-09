<template>
  <div class="border border-border rounded-xl bg-surface overflow-hidden transition-all duration-200 hover:border-accent/30 fade-up">

    <!-- Header -->
    <button class="w-full flex items-start gap-3 px-5 py-4 text-left"
      @click="open = !open">
      <span class="mt-0.5 text-sm shrink-0">{{ verdictIcon }}</span>
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 flex-wrap mb-1">
          <span :class="verdictBadgeCss" class="text-xs font-semibold px-2 py-0.5 rounded-full border">
            {{ verdictLabel }}
          </span>
          <span class="text-xs text-muted">{{ paper.year }}</span>
          <span v-if="paper.citationCount" class="text-xs text-muted">📚 {{ paper.citationCount }}</span>
        </div>
        <h3 class="text-sm font-medium text-white leading-snug line-clamp-2">{{ paper.title }}</h3>
        <p class="text-xs text-muted mt-0.5 truncate">{{ authors }}</p>
      </div>
      <!-- Score gauge -->
      <div class="shrink-0 flex flex-col items-center gap-1 ml-2">
        <div class="relative w-10 h-10">
          <svg viewBox="0 0 36 36" class="w-10 h-10 -rotate-90">
            <circle cx="18" cy="18" r="14" fill="none" stroke="#252836" stroke-width="3"/>
            <circle cx="18" cy="18" r="14" fill="none"
              :stroke="scoreColor" stroke-width="3"
              stroke-linecap="round"
              :stroke-dasharray="`${scorePercent} 100`"
              style="transition: stroke-dasharray 0.8s cubic-bezier(0.16,1,0.3,1)"/>
          </svg>
          <span class="absolute inset-0 flex items-center justify-center text-xs font-bold text-white">{{ analysis.relevance_score }}</span>
        </div>
        <span class="text-xs text-muted">score</span>
      </div>
      <svg :class="open ? 'rotate-180' : ''" class="shrink-0 ml-1 mt-1 w-4 h-4 text-muted transition-transform duration-200"
        fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
      </svg>
    </button>

    <!-- Body -->
    <div v-if="open" class="px-5 pb-5 space-y-3 border-t border-border/60">

      <!-- Evidence -->
      <div v-if="evidence" class="mt-3">
        <div class="text-xs font-semibold text-muted uppercase tracking-wider mb-1.5">📌 Evidence</div>
        <div class="bg-accent/5 border-l-2 border-accent rounded-r-lg px-3 py-2 text-sm text-accent/90 italic leading-relaxed">
          {{ evidence }}
        </div>
      </div>

      <!-- Key finding -->
      <div v-if="analysis.key_finding && analysis.key_finding !== 'N/A'">
        <div class="text-xs font-semibold text-muted uppercase tracking-wider mb-1.5">🔑 Key Finding</div>
        <div class="bg-emerald-500/5 border-l-2 border-emerald-500/50 rounded-r-lg px-3 py-2 text-sm text-emerald-400/90 leading-relaxed">
          {{ analysis.key_finding }}
        </div>
      </div>

      <!-- Explanation -->
      <div v-if="analysis.explanation">
        <div class="text-xs font-semibold text-muted uppercase tracking-wider mb-1.5">🧠 Explanation</div>
        <p class="text-sm text-muted leading-relaxed">{{ analysis.explanation }}</p>
      </div>

      <!-- Confidence bar -->
      <div class="flex items-center gap-3 pt-1">
        <span class="text-xs text-muted w-20 shrink-0">Confidence</span>
        <div class="flex-1 bg-surface2 rounded-full h-1.5">
          <div class="h-1.5 rounded-full gauge-bar" :style="{ width: confWidth, background: confColor }"></div>
        </div>
        <span class="text-xs font-medium" :style="{ color: confColor }">{{ analysis.confidence }}</span>
      </div>

      <!-- Actions row -->
      <div class="flex items-center gap-2 pt-2">
        <button @click="copyCitation" class="btn-ghost text-xs flex items-center gap-1.5">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
          </svg>
          {{ copied ? 'Copied!' : 'Cite' }}
        </button>
        <button v-if="enableChat" @click="openChat"
          class="btn-ghost text-xs flex items-center gap-1.5">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M8 10h8M8 14h5m-7 6 2.4-2H19a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h1z"/>
          </svg>
          Chat
        </button>
        <a v-if="paperUrl" :href="paperUrl" target="_blank" rel="noopener"
          class="btn-ghost text-xs flex items-center gap-1.5">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
          </svg>
          Open Paper
        </a>
        <button v-if="!summary && !loadingSummary" @click="doSummarize"
          class="btn-ghost text-xs flex items-center gap-1.5 ml-auto">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
          Summarize
        </button>
        <button v-if="loadingSummary" disabled class="btn-ghost text-xs ml-auto opacity-50">
          <span class="animate-pulse">Generating…</span>
        </button>
      </div>

      <!-- Abstract toggle -->
      <details v-if="paper.abstract" class="mt-1">
        <summary class="text-xs text-muted cursor-pointer hover:text-white transition-colors select-none">Show abstract</summary>
        <p class="mt-2 text-xs text-muted leading-relaxed">{{ paper.abstract }}</p>
      </details>

      <!-- Summary -->
      <div v-if="summary" class="mt-1 bg-surface2 rounded-lg p-4 text-sm text-muted leading-relaxed border border-border whitespace-pre-wrap">
        {{ summary }}
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { summarizePaper } from '../api/index.js'

const props = defineProps({
  paper:    { type: Object, required: true },
  analysis: { type: Object, required: true },
  enableChat: { type: Boolean, default: false },
})

const router         = useRouter()
const open           = ref(false)
const copied         = ref(false)
const summary        = ref('')
const loadingSummary = ref(false)

const authors = computed(() => {
  const a = props.paper.authors || []
  const names = a.slice(0, 3).map(x => x.name).filter(Boolean)
  if (!names.length) return 'Authors unavailable'
  return names.join(', ') + (a.length > 3 ? ' et al.' : '')
})

const paperUrl = computed(() => {
  const doi = props.paper.externalIds?.DOI
  return props.paper.url || (doi ? `https://doi.org/${doi}` : '')
})

const evidence = computed(() => {
  const e = props.analysis.evidence || ''
  return e === 'No evidence found.' || e === 'Analysis could not be completed.' ? '' : e
})

const VERDICT_MAP = {
  SUPPORTS:           { icon: '🟢', label: 'Supports',        css: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' },
  PARTIALLY_SUPPORTS: { icon: '🟡', label: 'Partially',       css: 'text-amber-400   border-amber-500/30   bg-amber-500/10'   },
  CONTRADICTS:        { icon: '🔴', label: 'Contradicts',     css: 'text-red-400     border-red-500/30     bg-red-500/10'     },
  NEUTRAL:            { icon: '⚪', label: 'Neutral',         css: 'text-gray-400    border-gray-500/30    bg-gray-500/10'    },
  INSUFFICIENT_DATA:  { icon: '⚫', label: 'Insufficient',    css: 'text-gray-500    border-gray-600/30    bg-gray-600/10'    },
}
const vm = computed(() => VERDICT_MAP[props.analysis.verdict] || VERDICT_MAP.INSUFFICIENT_DATA)
const verdictIcon     = computed(() => vm.value.icon)
const verdictLabel    = computed(() => vm.value.label)
const verdictBadgeCss = computed(() => vm.value.css)

const scorePercent = computed(() => {
  const s = props.analysis.relevance_score || 0
  return Math.round((s / 10) * 88)
})
const scoreColor = computed(() => {
  const s = props.analysis.relevance_score || 0
  if (s >= 8) return '#22c55e'
  if (s >= 5) return '#f59e0b'
  return '#6b7280'
})

const CONF_MAP = { HIGH: { w: '90%', c: '#22c55e' }, MEDIUM: { w: '55%', c: '#f59e0b' }, LOW: { w: '25%', c: '#6b7280' } }
const confMap   = computed(() => CONF_MAP[props.analysis.confidence] || CONF_MAP.LOW)
const confWidth = computed(() => confMap.value.w)
const confColor = computed(() => confMap.value.c)

async function doSummarize() {
  loadingSummary.value = true
  try { summary.value = await summarizePaper(props.paper) }
  catch (e) { summary.value = 'Error: ' + e.message }
  finally { loadingSummary.value = false }
}

function openChat() {
  router.push({ name: 'chat', state: { paper: JSON.stringify(props.paper) } })
}

function copyCitation() {
  const a    = props.paper.authors || []
  const last = a[0]?.name?.split(' ').pop() || 'Unknown'
  const year = props.paper.year || 'n.d.'
  const title= props.paper.title || ''
  const doi  = props.paper.externalIds?.DOI || ''
  const text = `${last} (${year}). ${title}.${doi ? ' https://doi.org/' + doi : ''}`
  navigator.clipboard.writeText(text).then(() => {
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  })
}
</script>

<style scoped>
.btn-ghost {
  @apply px-3 py-1.5 rounded-lg border border-border text-muted hover:text-white hover:border-accent/40 hover:bg-accent/5 transition-all duration-150;
}
</style>
