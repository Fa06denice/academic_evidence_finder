<template>
  <div class="p-8 max-w-4xl mx-auto w-full">

    <div class="mb-8">
      <h1 class="text-2xl font-bold text-white mb-1.5">Paper Search</h1>
      <p class="text-sm text-muted">Search academic papers by topic and summarise any result on demand.</p>
    </div>

    <!-- Input -->
    <div class="bg-surface border border-border rounded-2xl p-6 mb-6">
      <label class="block text-xs font-semibold text-muted uppercase tracking-wider mb-3">Search query</label>
      <input
        v-model="query"
        :disabled="loading"
        placeholder="e.g. CRISPR gene editing off-target effects"
        class="w-full bg-surface2 border border-border rounded-xl px-4 py-3 text-sm text-white placeholder-muted focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30 transition-all disabled:opacity-50"
        @keydown.enter="submit"
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
        <button @click="submit" :disabled="loading || !query.trim()"
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
        class="bg-surface border border-border rounded-xl p-5 hover:border-accent/30 transition-all fade-up">
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
              <span v-if="paper.citationCount">📚 {{ paper.citationCount }} citations</span>
              <span v-if="paper.venue" class="truncate max-w-40">{{ paper.venue }}</span>
            </div>
            <p v-if="paper.abstract" class="text-xs text-muted leading-relaxed line-clamp-3">{{ paper.abstract }}</p>
          </div>
          <!-- Summarize btn -->
          <div class="shrink-0 flex flex-col gap-2">
            <button @click="toggleSummary(paper)" :disabled="summaryLoading[paper.paperId]"
              class="px-3 py-1.5 text-xs font-medium border border-border rounded-lg text-muted hover:text-white hover:border-accent/40 hover:bg-accent/5 transition-all disabled:opacity-50">
              {{ summaryLoading[paper.paperId] ? '…' : summaries[paper.paperId] ? 'Hide' : '✨ Summarize' }}
            </button>
          </div>
        </div>
        <!-- Summary panel -->
        <div v-if="summaries[paper.paperId]" class="mt-4 bg-surface2 rounded-lg p-4 border border-border">
          <div class="text-xs font-semibold text-accent uppercase tracking-wider mb-2">AI Summary</div>
          <p class="text-sm text-muted leading-relaxed whitespace-pre-wrap">{{ summaries[paper.paperId] }}</p>
        </div>
      </div>
    </div>

    <!-- Empty -->
    <div v-if="!loading && !papers.length" class="text-center py-24">
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
  lastQuery.value = query.value

  await streamPost('/api/search', { query: query.value, limit: +limit.value }, {
    onPapers(p) { papers.value = p },
    onDone()    { loading.value = false; historyStore.add({ type: 'search', query: query.value, path: '/search' }) },
    onError(e)  { loading.value = false; console.error(e) }
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
