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
        class="w-full bg-surface2 border border-border rounded-xl px-4 py-3 text-sm text-white placeholder-muted focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30 transition-all disabled:opacity-50"
        @keydown.enter.prevent="submit"
      />
      <div class="flex items-center gap-4 mt-4">
        <div class="flex items-center gap-2">
          <span class="text-xs text-muted">Papers:</span>
          <select v-model="maxPapers" :disabled="loading"
            class="bg-surface2 border border-border rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-accent/50 disabled:opacity-50">
            <option value="10">10</option>
            <option value="15">15</option>
            <option value="20">20</option>
          </select>
        </div>
        <button type="button" @click.prevent="submit" :disabled="loading || !topic.trim()"
          class="ml-auto flex items-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-xl transition-all">
          <span v-if="loading" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          <span>{{ loading ? 'Reviewing…' : 'Generate Review' }}</span>
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
    <div v-if="error" class="mb-4 p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
      {{ error }}
    </div>

    <!-- Review output -->
    <div v-if="review && !loading" class="space-y-3">
      <div v-for="(section, i) in sections" :key="i"
        class="bg-surface border border-border rounded-2xl overflow-hidden">
        <button type="button" @click="openSections[i] = !openSections[i]"
          class="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-surface2/50 transition-colors">
          <h2 class="text-sm font-semibold text-white flex items-center gap-2">
            <span>{{ sectionIcon(section.title) }}</span>{{ section.title }}
          </h2>
          <svg :class="openSections[i] ? 'rotate-180' : ''"
            class="w-4 h-4 text-muted transition-transform duration-200"
            fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
          </svg>
        </button>
        <div v-if="openSections[i]" class="px-6 pb-5 border-t border-border/60">
          <p class="text-sm text-muted leading-relaxed mt-3 whitespace-pre-wrap">{{ section.content }}</p>
        </div>
      </div>
      <div class="flex gap-2 pt-2">
        <button type="button" @click="exportMarkdown" class="btn-sm">📄 Export Markdown</button>
      </div>
    </div>

    <!-- Debug: affiche les données brutes si la review est là mais pas de sections -->
    <div v-if="review && !sections.length && !loading" class="p-4 bg-surface border border-border rounded-xl text-xs text-muted">
      <div class="font-semibold mb-2">Raw review data:</div>
      <pre class="overflow-auto max-h-64">{{ JSON.stringify(review, null, 2) }}</pre>
    </div>

    <!-- Empty -->
    <div v-if="!loading && !review && !error" class="text-center py-24">
      <div class="text-5xl mb-4">📚</div>
      <h3 class="text-base font-semibold text-white mb-1">Generate a review</h3>
      <p class="text-sm text-muted max-w-xs mx-auto">Enter a research topic to automatically synthesise findings from recent literature.</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, reactive } from 'vue'
import { streamPost } from '../api/index.js'
import { historyStore } from '../stores/history.js'

const topic       = ref('')
const maxPapers   = ref('15')
const loading     = ref(false)
const progressMsg = ref('')
const progressPct = ref(0)
const review      = ref(null)
const openSections= reactive({})
const error       = ref('')

// Extrait les sections depuis n'importe quelle structure retournée par le backend
const sections = computed(() => {
  if (!review.value) return []
  const r = review.value
  const KEYS = ['background','methodology','findings','gaps','conclusion','introduction','discussion']
  const ICONS = { background:'📖', methodology:'🔬', findings:'💡', gaps:'🔭', conclusion:'🎯', introduction:'📝', discussion:'💬' }

  // Si le backend retourne un tableau sections[]
  if (Array.isArray(r.sections)) return r.sections.map(s => ({ ...s, icon: ICONS[s.title?.toLowerCase()] || '📄' }))

  // Sinon on mappe les clés connues
  return KEYS.filter(k => r[k]).map(k => ({
    title: k.charAt(0).toUpperCase() + k.slice(1),
    content: r[k],
  }))
})

function sectionIcon(title) {
  const ICONS = { background:'📖', methodology:'🔬', findings:'💡', gaps:'🔭', conclusion:'🎯', introduction:'📝', discussion:'💬' }
  return ICONS[title?.toLowerCase()] || '📄'
}

async function submit() {
  if (!topic.value.trim() || loading.value) return
  loading.value = true
  review.value  = null
  error.value   = ''
  progressPct.value = 0
  progressMsg.value = 'Searching literature…'

  await streamPost('/api/review', { topic: topic.value, max_papers: +maxPapers.value }, {
    onProgress(e) {
      progressMsg.value = e.message
      if (e.step && e.total) progressPct.value = Math.round((e.step / e.total) * 90)
    },
    onReview(r) {
      console.log('[Review] received:', r)
      review.value = r
      // Ouvre toutes les sections par défaut
      sections.value.forEach((_, i) => { openSections[i] = true })
    },
    onError(e) { error.value = e.message; loading.value = false },
    onDone()   {
      progressPct.value = 100
      loading.value = false
      historyStore.add({ type: 'review', query: topic.value, path: '/review' })
    },
  })
}

function exportMarkdown() {
  let md = `# Literature Review: ${topic.value}\n\n`
  sections.value.forEach(s => { md += `## ${s.title}\n\n${s.content}\n\n` })
  const a = document.createElement('a')
  a.href = 'data:text/markdown;charset=utf-8,' + encodeURIComponent(md)
  a.download = 'literature-review.md'
  a.click()
}
</script>

<style scoped>
.btn-sm {
  @apply px-3 py-1.5 text-xs font-medium bg-surface2 border border-border rounded-lg text-muted hover:text-white hover:border-accent/40 transition-all duration-150;
}
</style>
