<template>
  <div class="p-8 max-w-4xl mx-auto w-full">

    <div class="mb-8">
      <h1 class="text-2xl font-bold text-white mb-1.5">Paper Search</h1>
      <p class="text-sm text-muted">Search academic papers by topic and summarise any result on demand.</p>
    </div>

    <div class="bg-surface border border-border rounded-2xl p-6 mb-6">
      <label class="block text-xs font-semibold text-muted uppercase tracking-wider mb-3">Search query</label>
      <input v-model="query" :disabled="loading"
        placeholder="e.g. CRISPR gene editing off-target effects"
        class="w-full bg-surface2 border border-border rounded-xl px-4 py-3 text-sm text-white placeholder-muted focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30 transition-all disabled:opacity-50"
        @keydown.enter.prevent="submit"
      />
      <div class="flex items-center gap-4 mt-4">
        <div class="flex items-center gap-2">
          <span class="text-xs text-muted">Limit:</span>
          <select v-model="limit" :disabled="loading"
            class="bg-surface2 border border-border rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-accent/50 disabled:opacity-50">
            <option value="5">5</option>
            <option value="10">10</option>
            <option value="20">20</option>
          </select>
        </div>
        <button type="button" @click.prevent="submit" :disabled="loading || !query.trim()"
          class="ml-auto flex items-center gap-2 px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-xl transition-all">
          <span v-if="loading" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          <span>{{ loading ? 'Searching…' : 'Search Papers' }}</span>
        </button>
      </div>
    </div>

    <!-- Results -->
    <div v-if="papers.length" class="space-y-3">
      <div class="flex items-center gap-2 mb-4">
        <h2 class="text-sm font-semibold text-white">{{ papers.length }} results</h2>
        <span class="text-xs text-muted">for "{{ lastQuery }}"</span>
      </div>
      <div v-for="paper in papers" :key="paper.paperId"
        class="bg-surface border border-border rounded-xl p-5 hover:border-accent/30 transition-all">
        <div class="flex items-start gap-4">
          <div class="flex-1 min-w-0">
            <a v-if="paperUrl(paper)" :href="paperUrl(paper)" target="_blank" rel="noopener"
              class="text-sm font-semibold text-white hover:text-accent transition-colors leading-snug block mb-1.5">
              {{ paper.title }}
            </a>
            <span v-else class="text-sm font-semibold text-white leading-snug block mb-1.5">{{ paper.title }}</span>
            <div class="flex items-center gap-3 flex-wrap text-xs text-muted mb-2">
              <span>{{ authors(paper) }}</span>
              <span>{{ paper.year }}</span>
              <span v-if="paper.citationCount">📚 {{ paper.citationCount }}</span>
              <span v-if="paper.venue" class="truncate max-w-xs">{{ paper.venue }}</span>
            </div>
            <p v-if="paper.abstract" class="text-xs text-muted leading-relaxed line-clamp-3">{{ paper.abstract }}</p>
          </div>
          <div class="shrink-0">
            <button type="button" @click="toggleSummary(paper)" :disabled="summaryLoading[paper.paperId]"
              class="px-3 py-1.5 text-xs font-medium border border-border rounded-lg text-muted hover:text-white hover:border-accent/40 hover:bg-accent/5 transition-all disabled:opacity-50 whitespace-nowrap">
              {{ summaryLoading[paper.paperId] ? '…' : summaries[paper.paperId] ? 'Hide' : '✨ Summarize' }}
            </button>
          </div>
        </div>
        <div v-if="summaries[paper.paperId]" class="mt-4 bg-surface2 rounded-lg p-4 border border-border">
          <div class="text-xs font-semibold text-accent uppercase tracking-wider mb-2">AI Summary</div>
          <p class="text-sm text-muted leading-relaxed whitespace-pre-wrap">{{ summaries[paper.paperId] }}</p>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center gap-3 py-8 justify-center">
      <div class="w-5 h-5 border-2 border-accent/30 border-t-accent rounded-full animate-spin"></div>
      <span class="text-sm text-muted">Searching…</span>
    </div>

    <!-- Error -->
    <div v-if="error" class="mt-4 p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">
      {{ error }}
    </div>

    <!-- Empty -->
    <div v-if="!loading && !papers.length && !error" class="text-center py-24">
      <div class="text-5xl mb-4">🔍</div>
      <h3 class="text-base font-semibold text-white mb-1">Find papers</h3>
      <p class="text-sm text-muted max-w-xs mx-auto">Search across millions of peer-reviewed publications and summarise any result instantly.</p>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { streamPost, summarizePaper } from '../api/index.js'
import { historyStore } from '../stores/history.js'

const query    = ref('')
const limit    = ref('10')
const loading  = ref(false)
const papers   = ref([])
const lastQuery= ref('')
const error    = ref('')
const summaries      = reactive({})
const summaryLoading = reactive({})

function authors(paper) {
  const a = paper.authors || []
  return a.slice(0,3).map(x => x.name).filter(Boolean).join(', ') + (a.length > 3 ? ' et al.' : '')
}
function paperUrl(paper) {
  const doi = paper.externalIds?.DOI
  return paper.url || (doi ? `https://doi.org/${doi}` : '')
}

async function submit() {
  if (!query.value.trim() || loading.value) return
  loading.value = true
  papers.value  = []
  error.value   = ''
  lastQuery.value = query.value

  await streamPost('/api/search', { topic: query.value, max_papers: +limit.value }, {
    onPapers(p) { papers.value = p },
    onError(e)  { error.value = e.message; loading.value = false },
    onDone()    {
      loading.value = false
      historyStore.add({ type: 'search', query: query.value, path: '/search' })
    },
  })
}

async function toggleSummary(paper) {
  const id = paper.paperId
  if (summaries[id]) { delete summaries[id]; return }
  summaryLoading[id] = true
  try { summaries[id] = await summarizePaper(paper) }
  catch (e) { summaries[id] = 'Error: ' + e.message }
  finally { summaryLoading[id] = false }
}
</script>
