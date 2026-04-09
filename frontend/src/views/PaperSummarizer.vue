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
        class="w-full bg-surface2 border border-border rounded-xl px-4 py-3 text-sm text-white placeholder-muted focus:outline-none focus:border-accent/50 disabled:opacity-50 transition-all"
        @keydown.enter.prevent="submit"
      />
      <div class="flex items-center gap-4 mt-4">
        <PaperCountPicker v-model="maxPapers" label="Results" :disabled="loading" />
        <label class="inline-flex items-center gap-2 text-xs text-muted">
          <input
            v-model="exactTitle"
            type="checkbox"
            :disabled="loading"
            class="h-4 w-4 rounded border-border bg-surface2 text-accent focus:ring-accent/40"
          />
          <span>I know the exact title</span>
        </label>
        <button type="button" @click="submit" :disabled="loading || !query.trim()"
          class="ml-auto px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-medium rounded-xl transition-all flex items-center gap-2">
          <span v-if="loading" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          {{ loading ? 'Searching…' : 'Search Papers' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="mb-4 p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-sm text-red-400">{{ error }}</div>

    <div v-if="loading" class="flex items-center gap-3 py-10 justify-center">
      <div class="w-5 h-5 border-2 border-accent/30 border-t-accent rounded-full animate-spin"></div>
      <span class="text-sm text-muted">{{ progress }}</span>
    </div>

    <div v-if="papers.length && !loading" class="space-y-3">
      <p class="text-xs text-muted mb-2">{{ papers.length }} results for &ldquo;{{ lastQuery }}&rdquo;</p>
      <div v-for="p in papers" :key="p.paperId" class="bg-surface border border-border rounded-xl p-5">
        <div class="flex gap-4">
          <div class="flex-1 min-w-0">
            <a v-if="p.url" :href="p.url" target="_blank" rel="noopener"
              class="text-sm font-semibold text-white hover:text-accent transition-colors block mb-1">{{ p.title }}</a>
            <span v-else class="text-sm font-semibold text-white block mb-1">{{ p.title }}</span>
            <div class="flex flex-wrap gap-3 text-xs text-muted mb-2">
              <span>{{ (p.authors||[]).slice(0,3).map(a=>a.name).join(', ') }}</span>
              <span>{{ p.year }}</span>
              <span v-if="p.citationCount">📚 {{ p.citationCount }}</span>
            </div>
            <p v-if="p.abstract" class="text-xs text-muted leading-relaxed line-clamp-3">{{ p.abstract }}</p>
          </div>

          <!-- Action buttons -->
          <div class="shrink-0 flex flex-col gap-2 self-start">
            <button type="button" @click="openChat(p)"
              class="px-3 py-1.5 text-xs border border-accent/30 bg-accent/10 text-accent hover:bg-accent/20 rounded-lg transition-all flex items-center gap-1.5">
              💬 Chat
            </button>
            <button type="button" @click="toggleSummary(p)" :disabled="summaryLoading[p.paperId]"
              class="px-3 py-1.5 text-xs border border-border rounded-lg text-muted hover:text-white hover:border-accent/40 transition-all disabled:opacity-50">
              {{ summaryLoading[p.paperId] ? '…' : summaries[p.paperId] ? 'Hide' : '✨ Summarize' }}
            </button>
          </div>
        </div>
        <div v-if="summaries[p.paperId]" class="mt-4 bg-surface2 rounded-lg p-4 border border-border">
          <p class="text-xs font-semibold text-accent uppercase tracking-wider mb-2">AI Summary</p>
          <p class="text-sm text-muted leading-relaxed whitespace-pre-wrap">{{ summaries[p.paperId] }}</p>
        </div>
      </div>
    </div>

    <div v-if="!loading && !papers.length && !error" class="text-center py-24">
      <div class="text-5xl mb-4">🔍</div>
      <p class="text-sm text-muted">Enter a query and click Search Papers</p>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { streamPost, summarizePaper } from '../api/index.js'
import PaperCountPicker from '../components/PaperCountPicker.vue'

const router     = useRouter()
const query      = ref('')
const maxPapers  = ref(10)
const exactTitle = ref(false)
const loading    = ref(false)
const progress   = ref('Searching…')
const papers     = ref([])
const lastQuery  = ref('')
const error      = ref('')
const summaries      = reactive({})
const summaryLoading = reactive({})

async function submit() {
  if (!query.value.trim() || loading.value) return
  loading.value = true
  papers.value  = []
  error.value   = ''
  lastQuery.value = query.value
  progress.value  = 'Searching…'

  const body = { topic: query.value, max_papers: maxPapers.value, exact_title: exactTitle.value }
  console.log('[submit] body:', body)

  await streamPost('/api/search', body, {
    onProgress(e) { progress.value = e.message },
    onPapers(p)   { papers.value = p },
    onError(e)    { error.value = e.message },
    onDone()      { loading.value = false },
  })
}

async function toggleSummary(paper) {
  const id = paper.paperId
  if (summaries[id]) { delete summaries[id]; return }
  summaryLoading[id] = true
  try { summaries[id] = await summarizePaper(paper) }
  catch(e) { summaries[id] = 'Error: ' + e.message }
  finally { summaryLoading[id] = false }
}

// Passe le paper complet dans le state du router — pas d'ID à connaître
function openChat(paper) {
  router.push({ name: 'chat', state: { paper: JSON.stringify(paper) } })
}
</script>
