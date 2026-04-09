<template>
  <div class="p-8 max-w-6xl mx-auto w-full">
    <div class="mb-8">
      <h1 class="text-2xl font-bold text-white mb-1.5">Paper Chat</h1>
      <p class="text-sm text-muted">Ask questions grounded in the full content of a paper.</p>
    </div>

    <!-- Paper picker (shown when no paper loaded) -->
    <div v-if="!paper" class="space-y-4">
      <div class="bg-accent/10 border border-accent/20 rounded-2xl p-5 flex items-center gap-4">
        <span class="text-2xl">🔍</span>
        <div class="flex-1">
          <p class="text-sm font-semibold text-white">Find a paper first</p>
          <p class="text-xs text-muted mt-0.5">Search for papers, then click the 💬 Chat button on any result.</p>
        </div>
        <router-link to="/search"
          class="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm font-medium rounded-xl transition-all">
          Go to Search
        </router-link>
      </div>

      <div class="flex items-center gap-3">
        <div class="flex-1 h-px bg-border"></div>
        <span class="text-xs text-muted">or paste a Semantic Scholar ID</span>
        <div class="flex-1 h-px bg-border"></div>
      </div>

      <div class="bg-surface border border-border rounded-2xl p-5">
        <div class="flex gap-3">
          <input v-model="pidInput" placeholder="Paper ID — e.g. 649def34f8be52c8b66281af98ae884c09aef38b"
            class="flex-1 bg-surface2 border border-border rounded-xl px-4 py-2.5 text-sm text-white placeholder-muted focus:outline-none focus:border-accent/50 transition-all"
            @keydown.enter.prevent="loadByPid"
          />
          <button @click="loadByPid" :disabled="!pidInput.trim() || fetching"
            class="px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-medium rounded-xl transition-all flex items-center gap-2">
            <span v-if="fetching" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
            Load
          </button>
        </div>
        <p v-if="fetchError" class="mt-3 text-sm text-red-400">{{ fetchError }}</p>
      </div>
    </div>

    <!-- Main split layout -->
    <div v-if="paper" class="space-y-6">
      <div class="flex flex-col lg:flex-row gap-6" style="min-height: 70vh">

        <!-- Left: content panel -->
        <div class="lg:w-1/2 flex flex-col">

          <!-- Header: title + source badge -->
          <div class="flex items-center justify-between mb-3">
            <div class="min-w-0 flex-1">
              <h2 class="text-sm font-semibold text-white line-clamp-2">{{ paper.title }}</h2>
              <p class="text-xs text-muted mt-0.5">
                {{ paper.year }}
                <span v-if="sourceStatus === 'pdf'"       class="ml-2 text-accent">• 📄 {{ fetchSource }}</span>
                <span v-else-if="sourceStatus === 'html'" class="ml-2 text-emerald-400">• 🌐 {{ fetchSource }}</span>
                <span v-else                              class="ml-2 text-amber-400">• Abstract only</span>
              </p>
            </div>
            <button @click="reset" class="text-xs text-muted hover:text-white transition-all ml-4 shrink-0">&times; Change</button>
          </div>

          <!-- 1. PDF inline viewer -->
          <div v-if="sourceStatus === 'pdf'" class="flex-1 rounded-xl overflow-hidden border border-border bg-surface2">
            <iframe :src="pdfDataUrl" class="w-full h-full" style="min-height: 60vh" title="Paper PDF"></iframe>
          </div>

          <!-- 2 & 3. Abstract panel (used for both HTML full-text and abstract-only) -->
          <div v-else
            :class="sourceStatus === 'html'
              ? 'border-emerald-500/20'
              : 'border-border'"
            class="flex-1 bg-surface2 border rounded-xl p-5 overflow-y-auto"
            style="min-height: 300px">

            <!-- Status pill -->
            <div class="flex items-center gap-2 mb-4">
              <!-- Full text available -->
              <span v-if="sourceStatus === 'html'"
                class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400 font-medium">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
                Full text available — chat grounded in full content
              </span>
              <!-- Abstract only -->
              <span v-else
                class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 text-xs text-amber-400 font-medium">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                Abstract only — full text unavailable
              </span>
            </div>

            <!-- Abstract (always shown) -->
            <p class="text-xs font-semibold text-muted uppercase tracking-wider mb-2">Abstract</p>
            <p class="text-sm text-muted leading-relaxed">{{ paper.abstract || 'No abstract available.' }}</p>

            <!-- Publisher link if DOI available (only for HTML full-text case) -->
            <div v-if="sourceStatus === 'html' && paperDoi" class="mt-4 pt-4 border-t border-border">
              <p class="text-xs text-muted mb-1.5">Read full text at publisher</p>
              <a :href="'https://doi.org/' + paperDoi" target="_blank" rel="noopener noreferrer"
                class="inline-flex items-center gap-1.5 text-xs text-accent hover:text-accent-hover transition-all">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                  <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
                </svg>
                doi.org/{{ paperDoi }}
              </a>
            </div>
          </div>
        </div>

        <!-- Right: Chat -->
        <div class="lg:w-1/2 flex flex-col">
          <div class="flex-1 bg-surface border border-border rounded-2xl flex flex-col" style="min-height: 60vh">

            <!-- Messages -->
            <div ref="messagesEl" class="flex-1 overflow-y-auto p-5 space-y-4" style="max-height: 55vh">
              <div v-if="!messages.length" class="text-center py-12">
                <div class="text-4xl mb-3">💬</div>
                <p class="text-sm text-muted max-w-xs mx-auto">Ask anything about this paper. Answers are grounded in the paper content only.</p>
                <div class="mt-5 space-y-2">
                  <button v-for="q in suggestedQuestions" :key="q"
                    @click="sendQuestion(q)"
                    class="block w-full max-w-xs mx-auto text-left px-4 py-2.5 bg-surface2 border border-border rounded-xl text-xs text-muted hover:text-white hover:border-accent/40 transition-all">
                    {{ q }}
                  </button>
                </div>
              </div>

              <div v-for="(msg, i) in messages" :key="i"
                :class="msg.role === 'user' ? 'flex justify-end' : 'flex justify-start'">
                <div :class="msg.role === 'user'
                  ? 'bg-accent/20 border border-accent/30 text-white rounded-2xl rounded-tr-sm'
                  : 'bg-surface2 border border-border text-muted rounded-2xl rounded-tl-sm'"
                  class="max-w-sm px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap">
                  <template v-if="msg.role === 'assistant'">
                    <template v-for="(part, partIdx) in renderMessageParts(msg.content)" :key="partIdx">
                      <span v-if="part.type === 'text'">{{ part.value }}</span>
                      <span v-else class="inline-flex items-center gap-1 align-middle">
                        <button
                          v-for="id in part.ids"
                          :key="id"
                          type="button"
                          @click="jumpToSource(findMessageSource(msg, id))"
                          class="inline-flex rounded-md border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent hover:bg-accent/20"
                        >
                          {{ id }}
                        </button>
                      </span>
                    </template>
                  </template>
                  <template v-else>
                    {{ msg.content }}
                  </template>
                  <span v-if="msg.streaming" class="inline-block w-1.5 h-4 bg-accent/60 animate-pulse ml-0.5 align-middle"></span>

                  <div v-if="msg.role === 'assistant' && msg.sources?.length" class="mt-3 border-t border-border/60 pt-3 space-y-2">
                    <div class="text-[10px] font-semibold uppercase tracking-wider text-muted">Sources Used</div>
                    <button
                      v-for="source in msg.sources"
                      :key="source.id"
                      type="button"
                      @click="jumpToSource(source)"
                      class="block w-full rounded-xl border px-3 py-2 text-left transition-all"
                      :class="activeSourceId === source.id
                        ? 'border-accent/40 bg-accent/10'
                        : 'border-border bg-surface hover:border-accent/30'"
                    >
                      <div class="mb-1 flex items-center gap-2">
                        <span class="inline-flex rounded-md border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                          {{ source.id }}
                        </span>
                        <span class="text-[11px] font-medium text-white">{{ source.locator }}</span>
                        <span v-if="source.page" class="ml-auto text-[10px] text-muted">p. {{ source.page }}</span>
                      </div>
                      <p class="text-xs leading-relaxed text-muted whitespace-pre-wrap">{{ source.excerpt }}</p>
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- Input -->
            <div class="p-4 border-t border-border">
              <div class="flex gap-3">
                <input v-model="question" :disabled="streaming"
                  placeholder="Ask about this paper…"
                  class="flex-1 bg-surface2 border border-border rounded-xl px-4 py-2.5 text-sm text-white placeholder-muted focus:outline-none focus:border-accent/50 disabled:opacity-50 transition-all"
                  @keydown.enter.prevent="sendQuestion(question)"
                />
                <button @click="sendQuestion(question)" :disabled="!question.trim() || streaming"
                  class="px-4 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-medium rounded-xl transition-all">
                  <svg v-if="!streaming" xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
                  <span v-else class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin block"></span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="textBlocks.length" class="rounded-2xl border border-border bg-surface">
        <div class="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h3 class="text-sm font-semibold text-white">Full Text Viewer</h3>
            <p class="text-xs text-muted">Click a citation or source card to jump to the relevant passage.</p>
          </div>
          <span class="text-xs text-muted">{{ textBlocks.length }} text block{{ textBlocks.length > 1 ? 's' : '' }}</span>
        </div>
        <div ref="fullTextEl" class="max-h-[34rem] space-y-3 overflow-y-auto p-5">
          <article
            v-for="block in textBlocks"
            :id="block.anchor_id"
            :key="block.anchor_id"
            class="scroll-mt-24 rounded-xl border p-4 transition-all"
            :class="activeAnchorId === block.anchor_id
              ? 'border-accent/40 bg-accent/10'
              : 'border-border bg-surface2'"
          >
            <div class="mb-2 flex items-center gap-2">
              <span class="text-[10px] font-semibold uppercase tracking-wider text-muted">{{ block.locator }}</span>
              <span v-if="block.page" class="text-[10px] text-muted">p. {{ block.page }}</span>
            </div>
            <p class="whitespace-pre-wrap text-sm leading-relaxed text-muted">{{ block.text }}</p>
          </article>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { streamPost, post } from '../api/index.js'
import { historyStore } from '../stores/history.js'

// Paper state
const paper       = ref(null)
const pdfB64      = ref(null)
const fetchSource = ref('')
const fetchAvail  = ref(false)
const fetching    = ref(false)
const fetchError  = ref('')
const pidInput    = ref('')
const textBlocks  = ref([])

// Chat state
const messages   = ref([])
const question   = ref('')
const streaming  = ref(false)
const messagesEl = ref(null)
const fullTextEl = ref(null)
const focusedPage = ref(1)
const activeSourceId = ref('')
const activeAnchorId = ref('')

// ── Derived state ─────────────────────────────────────────────────────────────

const sourceStatus = computed(() => {
  if (pdfB64.value) return 'pdf'
  const s = fetchSource.value.toLowerCase()
  if (fetchAvail.value && s && !s.includes('abstract') && !s.includes('unavailable')) return 'html'
  return 'abstract'
})

const pdfDataUrl = computed(() =>
  pdfB64.value ? `data:application/pdf;base64,${pdfB64.value}#page=${focusedPage.value || 1}` : ''
)

const paperDoi = computed(() => paper.value?.externalIds?.DOI || '')

const suggestedQuestions = [
  'What is the main contribution of this paper?',
  'What methodology did the authors use?',
  'What are the key limitations mentioned?',
  'What are the main findings?',
]

// ── On mount: check router state
onMounted(() => {
  window.addEventListener('aef:reuse-history', handleHistoryReplay)
  const state = window.history.state
  if (state?.paper) {
    try { loadPaperObject(JSON.parse(state.paper)) } catch {}
  }
})

onUnmounted(() => {
  window.removeEventListener('aef:reuse-history', handleHistoryReplay)
})

// ── Load by manual ID
async function loadByPid() {
  const pid = pidInput.value.trim()
  if (!pid) return
  fetchError.value = ''
  await loadPaperObject({ paperId: pid, title: 'Loading…', abstract: '' })
}

// ── Core load function
async function loadPaperObject(p) {
  fetching.value    = true
  fetchError.value  = ''
  pdfB64.value      = null
  fetchSource.value = ''
  fetchAvail.value  = false
  messages.value    = []
  textBlocks.value  = []
  paper.value       = null
  focusedPage.value = 1
  activeSourceId.value = ''
  activeAnchorId.value = ''

  try {
    const res = await post('/api/paper/fetch', { paper: p })
    paper.value       = { ...p, ...(res.paper_meta || {}) }
    pdfB64.value      = res.pdf_b64   || null
    fetchSource.value = res.source    || 'unknown'
    fetchAvail.value  = res.available ?? false
    textBlocks.value  = res.text_blocks || []
    historyStore.add({
      type: 'chat',
      query: paper.value?.title || paper.value?.paperId || p?.paperId || 'Paper Chat',
      path: '/chat',
      routeState: {
        paper: JSON.stringify(paper.value),
      },
    })
  } catch (e) {
    fetchError.value = e.message || 'Failed to fetch paper.'
  } finally {
    fetching.value = false
  }
}

// ── Chat
async function sendQuestion(q) {
  q = (q || '').trim()
  if (!q || streaming.value) return
  question.value = ''

  messages.value.push({ role: 'user', content: q })
  scrollToBottom()

  const assistantMsg = { role: 'assistant', content: '', streaming: true, sources: [] }
  messages.value.push(assistantMsg)
  streaming.value = true
  activeSourceId.value = ''
  activeAnchorId.value = ''

  const history = messages.value
    .slice(0, -1)
    .map(m => ({ role: m.role, content: m.content }))

  await streamPost('/api/paper/chat', { paper: paper.value, question: q, history }, {
    onToken(t)  { assistantMsg.content += t.text; scrollToBottom() },
    onSources(data) {
      assistantMsg.sources = data?.used?.length ? data.used : (data?.all || [])
      scrollToBottom()
    },
    onDone()    { assistantMsg.streaming = false; streaming.value = false },
    onError(e)  {
      assistantMsg.content   = '⚠️ ' + (e.message || 'An error occurred.')
      assistantMsg.streaming = false
      streaming.value = false
    },
  })
}

function scrollToBottom() {
  nextTick(() => { if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight })
}

function reset() {
  paper.value       = null
  pdfB64.value      = null
  fetchSource.value = ''
  fetchAvail.value  = false
  messages.value    = []
  textBlocks.value  = []
  pidInput.value    = ''
  fetchError.value  = ''
  focusedPage.value = 1
  activeSourceId.value = ''
  activeAnchorId.value = ''
}

function renderMessageParts(text) {
  const parts = []
  const regex = /(\[S\d+(?:,\s*S\d+)*\])/g
  let lastIndex = 0
  for (const match of text.matchAll(regex)) {
    const index = match.index ?? 0
    if (index > lastIndex) {
      parts.push({ type: 'text', value: text.slice(lastIndex, index) })
    }
    parts.push({
      type: 'citation',
      ids: match[1].slice(1, -1).split(',').map(id => id.trim()).filter(Boolean),
    })
    lastIndex = index + match[1].length
  }
  if (lastIndex < text.length) {
    parts.push({ type: 'text', value: text.slice(lastIndex) })
  }
  return parts.length ? parts : [{ type: 'text', value: text }]
}

function findMessageSource(message, id) {
  return (message.sources || []).find(source => source.id === id)
}

function jumpToSource(source) {
  if (!source) return
  activeSourceId.value = source.id
  activeAnchorId.value = source.anchor_id || ''
  if (source.page) focusedPage.value = source.page
  if (source.anchor_id) {
    nextTick(() => {
      const el = document.getElementById(source.anchor_id)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      } else if (fullTextEl.value) {
        fullTextEl.value.scrollTop = 0
      }
    })
  }
}

function handleHistoryReplay(event) {
  const item = event?.detail
  if (!item || item.path !== '/chat' || fetching.value || streaming.value) return

  const rawPaper = item.routeState?.paper
  if (!rawPaper) return

  try {
    loadPaperObject(JSON.parse(rawPaper))
  } catch {}
}
</script>
