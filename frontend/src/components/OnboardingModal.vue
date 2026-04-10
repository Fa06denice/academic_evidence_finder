<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center p-4" @click.self="close">
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" @click="close" />

        <!-- Panel -->
        <div class="relative z-10 w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl bg-surface border border-border shadow-2xl">

          <!-- Header -->
          <div class="sticky top-0 bg-surface border-b border-border px-6 py-4 flex items-center justify-between">
            <div class="flex items-center gap-3">
              <div class="w-8 h-8 rounded-lg bg-accent/15 flex items-center justify-center text-lg">🔬</div>
              <div>
                <h2 class="font-semibold text-white text-sm">Evidence Finder — Quick Start</h2>
                <p class="text-xs text-muted">Short usage guide</p>
              </div>
            </div>
            <button @click="close" class="text-muted hover:text-white transition-colors p-1 rounded-lg hover:bg-surface2">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 6 6 18M6 6l12 12"/>
              </svg>
            </button>
          </div>

          <!-- Content -->
          <div class="px-6 py-5 space-y-6 text-sm">

            <!-- Features -->
            <section>
              <h3 class="font-semibold text-white mb-3 flex items-center gap-2">
                <span class="text-base">🧰</span> What can you do here?
              </h3>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div v-for="f in features" :key="f.icon" class="p-3 rounded-lg bg-surface2 border border-border">
                  <div class="flex items-center gap-2 mb-1">
                    <span>{{ f.icon }}</span>
                    <strong class="text-white text-xs">{{ f.name }}</strong>
                  </div>
                  <p class="text-muted text-xs leading-relaxed">{{ f.desc }}</p>
                </div>
              </div>
            </section>

            <!-- Recommended flow -->
            <section>
              <h3 class="font-semibold text-white mb-3 flex items-center gap-2">
                <span class="text-base">🚀</span> Recommended flow
              </h3>
              <div class="space-y-2">
                <div v-for="step in steps" :key="step.title" class="flex gap-3 p-3 rounded-lg bg-surface2 border border-border">
                  <span class="text-accent font-bold shrink-0">{{ step.n }}</span>
                  <div>
                    <strong class="text-white text-xs block mb-0.5">{{ step.title }}</strong>
                    <p class="text-muted text-xs leading-relaxed">{{ step.desc }}</p>
                  </div>
                </div>
              </div>
            </section>

            <!-- Keep in mind -->
            <section>
              <h3 class="font-semibold text-white mb-3 flex items-center gap-2">
                <span class="text-base">⚠️</span> Keep in mind
              </h3>
              <ul class="space-y-1.5">
                <li v-for="tip in tips" :key="tip" class="flex gap-2 text-muted text-xs leading-relaxed">
                  <span class="text-border shrink-0 mt-0.5">›</span>
                  <span>{{ tip }}</span>
                </li>
              </ul>
            </section>

          </div>

          <!-- Footer -->
          <div class="sticky bottom-0 bg-surface border-t border-border px-6 py-4 flex items-center justify-between gap-4">
            <label class="flex items-center gap-2 cursor-pointer text-xs text-muted hover:text-white transition-colors">
              <input type="checkbox" v-model="dontShow" class="accent-accent rounded" />
              Do not show this on startup
            </label>
            <button @click="close"
              class="px-4 py-2 rounded-lg bg-accent hover:bg-accent/80 text-white text-xs font-semibold transition-colors">
              Got it — Start
            </button>
          </div>

        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const visible  = ref(false)
const dontShow = ref(false)

const features = [
  {
    icon: '🧪',
    name: 'Claim Verifier',
    desc: "Enter a scientific claim to get relevant papers, per-paper analysis, and an overall verdict."
  },
  {
    icon: '🔍',
    name: 'Paper Search',
    desc: "Search papers by topic or exact title, then open a summary or jump into paper chat."
  },
  {
    icon: '💬',
    name: 'Paper Chat',
    desc: "Ask questions about a specific paper with grounded answers and cited passages."
  },
]

const steps = [
  {
    n: '1',
    title: 'Start with Claim Verifier',
    desc: "Use it when you want to test a scientific claim and quickly see which papers support it, qualify it, or contradict it."
  },
  {
    n: '2',
    title: 'Explore with Paper Search',
    desc: "Use it when you already know the topic or the title of a paper and want to open the right results quickly."
  },
  {
    n: '3',
    title: 'Go deeper with Paper Chat',
    desc: "Then open the most relevant papers to ask focused questions about the results, methodology, or limitations."
  },
]

const tips = [
  "Results still depend on the available papers and on their quality.",
  "The Claim Verifier verdict is a fast synthesis, not a formal meta-analysis.",
  "For any important point, open the paper and verify the cited sources in Paper Chat.",
]

function close() {
  if (dontShow.value) {
    window.__evidenceFinderOnboardingSeen = true
  }
  visible.value = false
}

onMounted(() => {
  if (!window.__evidenceFinderOnboardingSeen) {
    visible.value = true
  }
})

defineExpose({ open: () => { visible.value = true } })
</script>

<style scoped>
.modal-enter-active, .modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-active .relative,
.modal-leave-active .relative {
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.2s ease;
}
.modal-enter-from, .modal-leave-to {
  opacity: 0;
}
.modal-enter-from .relative {
  transform: translateY(12px) scale(0.98);
  opacity: 0;
}
</style>
