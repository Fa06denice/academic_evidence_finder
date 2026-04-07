<template>
  <div class="p-8 max-w-4xl mx-auto w-full">
    <div class="mb-8">
      <h1 class="text-2xl font-bold text-white mb-1.5">Literature Review</h1>
      <p class="text-sm text-muted">Generate a structured academic review of any research topic.</p>
    </div>

    <div class="bg-surface border border-border rounded-2xl p-6 mb-6">
      <label class="block text-xs font-semibold text-muted uppercase tracking-wider mb-3">Research topic</label>
      <input v-model="topic" :disabled="loading"
        placeholder="e.g. Cognitive effects of sleep deprivation in adolescents"
        class="w-full bg-surface2 border border-border rounded-xl px-4 py-3 text-sm text-white placeholder-muted focus:outline-none focus:border-accent/50 disabled:opacity-50 transition-all"
        @keydown.enter.prevent="submit"
      />
      <div class="flex items-center gap-4 mt-4">
        <label class="text-xs text-muted">Papers:
          <select v-model.number="maxPapers" :disabled="loading"
            class="ml-2 bg-surface2 border border-border rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none disabled:opacity-50">
            <option :value="10">10</option>
            <option :value="15">15</option>
            <option :value="20">20</option>
          </select>
        </label>
        <button type="button" @click="submit" :disabled="loading || !topic.trim()"
          class="ml-auto px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-medium rounded-xl transition-all flex items-center gap-2">
          <span v-if="loading" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          {{ loading ? 'Reviewing…' : 'Generate Review' }}
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

    <!-- Error -->
    <div v-if="error" class="mb-4 p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">{{ error }}</div>

    <!-- Review text -->
    <div v-if="reviewText && !loading">
      <div class="flex gap-2 mb-4">
        <button type="button" @click="exportMarkdown"
          class="px-3 py-1.5 text-xs font-medium bg-surface2 border border-border rounded-lg text-muted hover:text-white transition-all">
          📄 Export Markdown
        </button>
      </div>
      <div class="bg-surface border border-border rounded-2xl p-6 mb-6">
        <div class="prose prose-invert prose-sm max-w-none">
          <div v-if="sections.length">
            <div v-for="(s, i) in sections" :key="i" class="mb-6">
              <h2 class="text-base font-semibold text-white mb-2">{{ s.title }}</h2>
              <p class="text-sm text-muted leading-relaxed whitespace-pre-wrap">{{ s.content }}</p>
            </div>
          </div>
          <pre v-else class="text-sm text-muted leading-relaxed whitespace-pre-wrap font-sans">{{ reviewText }}</pre>
        </div>
      </div>

      <!-- Source papers -->
      <div v-if="papers.length" class="mt-2">
        <h2 class="text-sm font-semibold text-white mb-3">{{ papers.length }} Source Papers</h2>
        <div class="space-y-3">
          <PaperCard
            v-for="item in papers"
            :key="item.paper.paperId"
            :paper="item.paper"
            :analysis="item.analysis"
          />
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!loading && !reviewText && !error" class="text-center py-24">
      <div class="text-5xl mb-4">📚</div>
      <p class="text-sm text-muted max-w-xs mx-auto">Enter a research topic to generate a structured literature review.</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { streamPost } from '../api/index.js'
import { historyStore } from '../stores/history.js'
import PaperCard from '../components/PaperCard.vue'

const route       = useRoute()
const topic       = ref('')
const maxPapers   = ref(10)
const loading     = ref(false)
const progressMsg = ref('Searching literature…')
const progressPct = ref(0)
const reviewRaw   = ref(null)
const papers      = ref([])
const error       = ref('')

const reviewText = computed(() => {
  if (!reviewRaw.value) return ''
  if (typeof reviewRaw.value === 'string') return reviewRaw.value
  const keys = ['introduction','background','methodology','findings','gaps','conclusion','discussion']
  return keys.filter(k => reviewRaw.value[k])
    .map(k => `## ${k.charAt(0).toUpperCase()+k.slice(1)}\n\n${reviewRaw.value[k]}`)
    .join('\n\n')
})

const sections = computed(() => {
  const text = reviewText.value
  if (!text) return []
  const parts = text.split(/\n(?=##\s)/)
  return parts.map(p => {
    const lines = p.trim().split('\n')
    const title = lines[0].replace(/^#+\s*/, '').trim()
    const content = lines.slice(1).join('\n').trim()
    return { title, content }
  }).filter(s => s.title && s.content)
})

// ── Clear cache event ─────────────────────────────────────────────────────────
function clearLocalState() {
  reviewRaw.value   = null
  papers.value      = []
  error.value       = ''
  progressPct.value = 0
  progressMsg.value = 'Searching literature…'
}

function onClearCache() { clearLocalState() }

onMounted(() => {
  window.addEventListener('aef:clear-cache', onClearCache)

  const q = route.query.q
  if (q) {
    topic.value = q
    if (route.query.autorun === '1') submit()
  }
})

onUnmounted(() => {
  window.removeEventListener('aef:clear-cache', onClearCache)
})
// ─────────────────────────────────────────────────────────────────────────────

async function submit() {
  if (!topic.value.trim() || loading.value) return
  loading.value = true
  clearLocalState()
  loading.value = true

  const rawPaperBuf = []

  await streamPost('/api/review', { topic: topic.value, max_papers: maxPapers.value }, {
    onProgress(e) {
      progressMsg.value = e.message
      if (e.step && e.total) progressPct.value = Math.round((e.step / e.total) * 90)
    },
    onPapers(payload) {
      const arr = Array.isArray(payload) ? payload : (payload?.papers || [])
      arr.forEach(item => rawPaperBuf.push(item))
    },
    onReview(r) {
      reviewRaw.value = r
    },
    onError(e)  { error.value = e.message },
    onDone()    {
      progressPct.value = 100
      loading.value = false
      historyStore.add({ type: 'review', query: topic.value, path: '/review' })
      papers.value = rawPaperBuf.map(item => {
        if (item && item.paper) return item
        return { paper: item, analysis: { verdict: 'NEUTRAL', confidence: 'LOW', relevance_score: 0, evidence: '', explanation: '', key_finding: 'N/A' } }
      }).filter(item => item.paper && item.paper.paperId)
    },
  })
}

function exportMarkdown() {
  const md = `# Literature Review: ${topic.value}\n\n${reviewText.value}`
  const a = document.createElement('a')
  a.href = 'data:text/markdown;charset=utf-8,' + encodeURIComponent(md)
  a.download = 'literature-review.md'
  a.click()
}
</script>
