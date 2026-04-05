<template>
  <div class="p-8 max-w-4xl mx-auto w-full">

    <div class="mb-8">
      <h1 class="text-2xl font-bold text-white mb-1.5">Literature Review</h1>
      <p class="text-sm text-muted">Generate a structured academic review of any research topic.</p>
    </div>

    <!-- Input -->
    <div class="bg-surface border border-border rounded-2xl p-6 mb-6">
      <label class="block text-xs font-semibold text-muted uppercase tracking-wider mb-3">Research topic</label>
      <input
        v-model="topic"
        :disabled="loading"
        placeholder="e.g. Cognitive effects of sleep deprivation in adolescents"
        class="w-full bg-surface2 border border-border rounded-xl px-4 py-3 text-sm text-white placeholder-muted focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30 transition-all disabled:opacity-50"
        @keydown.enter="submit"
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
        <button @click="submit" :disabled="loading || !topic.trim()"
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

    <!-- Review output -->
    <div v-if="review && !loading" class="space-y-5 fade-up">

      <!-- Stats row -->
      <div v-if="review.stats" class="grid grid-cols-3 gap-3">
        <div v-for="(val, key) in statsDisplay" :key="key"
          class="bg-surface border border-border rounded-xl p-4 text-center">
          <div class="text-2xl font-bold text-white mb-0.5">{{ val }}</div>
          <div class="text-xs text-muted capitalize">{{ key.replace(/_/g,' ') }}</div>
        </div>
      </div>

      <!-- Sections -->
      <template v-for="(section, i) in sections" :key="i">
        <div class="bg-surface border border-border rounded-2xl overflow-hidden">
          <button @click="openSections[i] = !openSections[i]"
            class="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-surface2/50 transition-colors">
            <h2 class="text-sm font-semibold text-white flex items-center gap-2">
              <span>{{ sectionIcon(section.title) }}</span>
              {{ section.title }}
            </h2>
            <svg :class="openSections[i] ? 'rotate-180' : ''"
              class="w-4 h-4 text-muted transition-transform duration-200"
              fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
            </svg>
          </button>
          <div v-if="openSections[i]" class="px-6 pb-5 border-t border-border/60">
            <p class="text-sm text-muted leading-relaxed mt-3 whitespace-pre-wrap">{{ section.content }}</p>
            <div v-if="section.key_papers?.length" class="mt-3 pt-3 border-t border-border/40">
              <div class="text-xs font-semibold text-muted uppercase tracking-wider mb-2">Key papers</div>
              <div class="flex flex-wrap gap-1.5">
                <span v-for="p in section.key_papers" :key="p"
                  class="text-xs px-2 py-0.5 bg-accent/10 text-accent border border-accent/20 rounded-full">
                  {{ p }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Export -->
      <div class="flex gap-2">
        <button @click="exportMarkdown" class="btn-sm">📄 Export Markdown</button>
        <button @click="copyReview" class="btn-sm">{{ copiedReview ? '✓ Copied' : '📋 Copy text' }}</button>
      </div>
    </div>

    <!-- Empty -->
    <div v-if="!loading && !review" class="text-center py-24">
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
const copiedReview= ref(false)

const sections = computed(() => {
  if (!review.value) return []
  const keys = ['background','methodology','findings','gaps','conclusion']
  return keys
    .filter(k => review.value[k])
    .map(k => ({ title: k.charAt(0).toUpperCase() + k.slice(1), content: review.value[k], key_papers: review.value[k + '_papers'] || [] }))
    .concat((review.value.sections || []))
})

const statsDisplay = computed(() => {
  const s = review.value?.stats || {}
  return {
    papers: s.papers_analysed || s.total || '—',
    years:  s.year_range || '—',
    topics: s.main_topics || '—',
  }
})

const ICONS = { background:'📖', methodology:'🔬', findings:'💡', gaps:'🔭', conclusion:'🎯' }
function sectionIcon(title) { return ICONS[title.toLowerCase()] || '📄' }

async function submit() {
  if (!topic.value.trim() || loading.value) return
  loading.value  = true
  review.value   = null
  progressPct.value = 0
  progressMsg.value = 'Searching…'
  Object.keys(openSections).forEach(k => { openSections[k] = false })
  sections.value?.forEach((_, i) => { openSections[i] = true })

  await streamPost('/api/review', { topic: topic.value, max_papers: +maxPapers.value }, {
    onProgress(e) { progressMsg.value = e.message; progressPct.value = e.progress || 0 },
    onReview(r)   { review.value = r; sections.value?.forEach((_, i) => { openSections[i] = true }) },
    onDone()      { progressPct.value = 100; loading.value = false; historyStore.add({ type: 'review', query: topic.value, path: '/review' }) },
    onError(e)    { progressMsg.value = '⚠ ' + e.message; loading.value = false }
  })
}

function exportMarkdown() {
  let md = `# Literature Review: ${topic.value}\n\n`
  sections.value.forEach(s => {
    md += `## ${s.title}\n\n${s.content}\n\n`
    if (s.key_papers?.length) md += `**Key papers:** ${s.key_papers.join(', ')}\n\n`
  })
  const a = document.createElement('a')
  a.href = 'data:text/markdown;charset=utf-8,' + encodeURIComponent(md)
  a.download = 'literature-review.md'
  a.click()
}

function copyReview() {
  const text = sections.value.map(s => `${s.title}\n${s.content}`).join('\n\n')
  navigator.clipboard.writeText(text).then(() => {
    copiedReview.value = true
    setTimeout(() => { copiedReview.value = false }, 2000)
  })
}
</script>

<style scoped>
.btn-sm {
  @apply px-3 py-1.5 text-xs font-medium bg-surface2 border border-border rounded-lg text-muted hover:text-white hover:border-accent/40 transition-all duration-150;
}
</style>
