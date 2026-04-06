<template>
  <div class="p-8 max-w-6xl mx-auto w-full">
    <div class="mb-8">
      <h1 class="text-2xl font-bold text-white mb-1.5">Paper Chat</h1>
      <p class="text-sm text-muted">Load a paper and ask questions grounded in its content.</p>
    </div>

    <!-- Paper input -->
    <div v-if="!paper" class="bg-surface border border-border rounded-2xl p-6 mb-6">
      <label class="block text-xs font-semibold text-muted uppercase tracking-wider mb-3">Paste a Semantic Scholar Paper ID or select one from your previous searches</label>
      <div class="flex gap-3">
        <input v-model="pidInput" placeholder="e.g. 649def34f8be52c8b66281af98ae884c09aef38b"
          class="flex-1 bg-surface2 border border-border rounded-xl px-4 py-3 text-sm text-white placeholder-muted focus:outline-none focus:border-accent/50 transition-all"
          @keydown.enter.prevent="loadByPid"
        />
        <button @click="loadByPid" :disabled="!pidInput.trim() || fetching"
          class="px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-medium rounded-xl transition-all flex items-center gap-2">
          <span v-if="fetching" class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          Load Paper
        </button>
      </div>
      <p v-if="fetchError" class="mt-3 text-sm text-red-400">{{ fetchError }}</p>

      <!-- Recent papers from session history -->
      <div v-if="recentPapers.length" class="mt-5">
        <p class="text-xs text-muted mb-2 uppercase tracking-wider font-semibold">Or pick from recent papers</p>
        <div class="space-y-2">
          <button v-for="p in recentPapers" :key="p.paperId"
            @click="loadPaperObject(p)"
            class="w-full text-left px-4 py-3 bg-surface2 border border-border rounded-xl hover:border-accent/40 transition-all">
            <span class="text-sm text-white font-medium line-clamp-1">{{ p.title }}</span>
            <span class="text-xs text-muted">{{ p.year }} · {{ p.authors?.[0]?.name || 'Unknown' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Main split layout -->
    <div v-if="paper" class="flex flex-col lg:flex-row gap-6" style="min-height: 70vh">

      <!-- Left: PDF viewer or abstract fallback -->
      <div class="lg:w-1/2 flex flex-col">
        <div class="flex items-center justify-between mb-3">
          <div>
            <h2 class="text-sm font-semibold text-white line-clamp-2">{{ paper.title }}</h2>
            <p class="text-xs text-muted mt-0.5">
              {{ paper.year }}
              <span v-if="pdfSource !== 'abstract_only'" class="ml-2 text-accent">&#x2022; PDF via {{ pdfSource }}</span>
              <span v-else class="ml-2 text-amber-400">&#x2022; Abstract only (PDF unavailable)</span>
            </p>
          </div>
          <button @click="reset" class="text-xs text-muted hover:text-white transition-all ml-4 shrink-0">&#x2715; Change paper</button>
        </div>

        <!-- PDF rendered via pdf.js -->
        <div v-if="pdfB64" class="flex-1 rounded-xl overflow-hidden border border-border bg-surface2">
          <iframe
            :src="pdfDataUrl"
            class="w-full h-full"
            style="min-height: 60vh"
            title="Paper PDF"
          ></iframe>
        </div>

        <!-- Fallback: abstract -->
        <div v-else class="flex-1 bg-surface2 border border-border rounded-xl p-5 overflow-y-auto" style="min-height: 300px">
          <p class="text-xs font-semibold text-muted uppercase tracking-wider mb-3">Abstract</p>
          <p class="text-sm text-muted leading-relaxed">{{ paper.abstract || 'No abstract available.' }}</p>
          <div class="mt-4 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
            <p class="text-xs text-amber-400">Full PDF not available for this paper. The chat will be based on the abstract only.</p>
          </div>
        </div>
      </div>

      <!-- Right: Chat -->
      <div class="lg:w-1/2 flex flex-col">
        <div class="flex-1 bg-surface border border-border rounded-2xl flex flex-col" style="min-height: 60vh">

          <!-- Messages -->
          <div ref="messagesEl" class="flex-1 overflow-y-auto p-5 space-y-4" style="max-height: 55vh">
            <!-- Welcome -->
            <div v-if="!messages.length" class="text-center py-12">
              <div class="text-4xl mb-3">&#x1F4AC;</div>
              <p class="text-sm text-muted max-w-xs mx-auto">Ask anything about this paper. All answers are grounded in the paper content.</p>
              <!-- Suggested questions -->
              <div class="mt-5 space-y-2">
                <button v-for="q in suggestedQuestions" :key="q"
                  @click="sendQuestion(q)"
                  class="block w-full max-w-xs mx-auto text-left px-4 py-2.5 bg-surface2 border border-border rounded-xl text-xs text-muted hover:text-white hover:border-accent/40 transition-all">
                  {{ q }}
                </button>
              </div>
            </div>

            <!-- Message bubbles -->
            <div v-for="(msg, i) in messages" :key="i"
              :class="msg.role === 'user' ? 'flex justify-end' : 'flex justify-start'">
              <div :class="msg.role === 'user'
                ? 'bg-accent/20 border border-accent/30 text-white rounded-2xl rounded-tr-sm'
                : 'bg-surface2 border border-border text-muted rounded-2xl rounded-tl-sm'"
                class="max-w-sm px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap">
                {{ msg.content }}
                <span v-if="msg.streaming" class="inline-block w-1.5 h-4 bg-accent/60 animate-pulse ml-0.5 align-middle"></span>
              </div>
            </div>
          </div>

          <!-- Input -->
          <div class="p-4 border-t border-border">
            <div class="flex gap-3">
              <input v-model="question" :disabled="streaming"
                placeholder="Ask about this paper\u2026"
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
  </div>
</template>

<script setup>
import { ref, computed, nextTick, inject } from 'vue'
import { streamPost, post } from '../api/index.js'

// Paper state
const paper     = ref(null)
const pdfB64    = ref(null)
const pdfSource = ref('')
const fetching  = ref(false)
const fetchError = ref('')
const pidInput  = ref('')

// Chat state
const messages   = ref([])
const question   = ref('')
const streaming  = ref(false)
const messagesEl = ref(null)

// Recent papers: injected from App-level store if available, otherwise empty
const recentPapers = inject('recentPapers', ref([]))

const pdfDataUrl = computed(() => {
  if (!pdfB64.value) return ''
  return `data:application/pdf;base64,${pdfB64.value}`
})

const suggestedQuestions = computed(() => [
  'What is the main contribution of this paper?',
  'What methodology did the authors use?',
  'What are the key limitations mentioned?',
  'What are the main findings?',
])

// ── Load a paper by Semantic Scholar ID ──────────────────────────────────────
async function loadByPid() {
  const pid = pidInput.value.trim()
  if (!pid) return
  fetching.value  = true
  fetchError.value = ''
  try {
    // Minimal paper object — backend will enrich via openAccessPdf
    const minimalPaper = { paperId: pid, title: 'Loading…', abstract: '' }
    await loadPaperObject(minimalPaper)
  } catch (e) {
    fetchError.value = e.message || 'Failed to load paper.'
  } finally {
    fetching.value = false
  }
}

// ── Load a full paper object (from other features or by ID) ──────────────────
async function loadPaperObject(p) {
  fetching.value   = true
  fetchError.value = ''
  pdfB64.value     = null
  messages.value   = []

  try {
    const res = await post('/api/paper/fetch', { paper: p })
    paper.value     = { ...p, ...(res.paper_meta || {}) }
    pdfB64.value    = res.pdf_b64 || null
    pdfSource.value = res.source  || 'unknown'
  } catch (e) {
    fetchError.value = e.message || 'Failed to fetch paper.'
    paper.value = null
  } finally {
    fetching.value = false
  }
}

// ── Send a chat message ───────────────────────────────────────────────────────
async function sendQuestion(q) {
  q = (q || '').trim()
  if (!q || streaming.value) return
  question.value = ''

  // Push user message
  messages.value.push({ role: 'user', content: q })
  scrollToBottom()

  // Push empty assistant message that we'll stream into
  const assistantMsg = { role: 'assistant', content: '', streaming: true }
  messages.value.push(assistantMsg)
  streaming.value = true

  const history = messages.value
    .slice(0, -1)  // exclude the empty assistant stub
    .map(m => ({ role: m.role, content: m.content }))

  await streamPost('/api/paper/chat', {
    paper:    paper.value,
    question: q,
    history,
  }, {
    onToken(t) {
      assistantMsg.content += t.text
      scrollToBottom()
    },
    onDone() {
      assistantMsg.streaming = false
      streaming.value = false
    },
    onError(e) {
      assistantMsg.content   = '\u26a0\ufe0f ' + (e.message || 'An error occurred.')
      assistantMsg.streaming = false
      streaming.value = false
    },
  })
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesEl.value)
      messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  })
}

function reset() {
  paper.value     = null
  pdfB64.value    = null
  messages.value  = []
  pidInput.value  = ''
  fetchError.value = ''
}
</script>
