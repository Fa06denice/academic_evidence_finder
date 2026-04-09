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
                <p class="text-xs text-muted">Mini guide d’usage</p>
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
                <span class="text-base">🧰</span> Que faire ici ?
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
                <span class="text-base">🚀</span> Flow recommandé
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
                <span class="text-base">⚠️</span> À garder en tête
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
              Ne plus afficher au démarrage
            </label>
            <button @click="close"
              class="px-4 py-2 rounded-lg bg-accent hover:bg-accent/80 text-white text-xs font-semibold transition-colors">
              J'ai compris — Commencer
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
    desc: "Entre un claim scientifique pour obtenir des papers, une analyse par paper et un verdict global."
  },
  {
    icon: '🔍',
    name: 'Paper Search',
    desc: "Cherche des papers par sujet ou par titre exact, puis ouvre un résumé ou le chat du paper."
  },
  {
    icon: '💬',
    name: 'Paper Chat',
    desc: "Pose des questions à un paper spécifique avec réponses sourcées et passages utilisés."
  },
]

const steps = [
  {
    n: '1',
    title: 'Commencer par Claim Verifier',
    desc: "Utilise-le quand tu veux tester une affirmation et voir rapidement quels papers vont dans son sens, la nuancent ou la contredisent."
  },
  {
    n: '2',
    title: 'Explorer avec Paper Search',
    desc: "Utilise-le si tu connais déjà le sujet ou le titre d’un paper et que tu veux ouvrir rapidement les bons résultats."
  },
  {
    n: '3',
    title: 'Approfondir avec Paper Chat',
    desc: "Ouvre ensuite les papers les plus intéressants pour poser des questions précises sur les résultats, la méthodo ou les limites."
  },
]

const tips = [
  "Les résultats restent dépendants des papers disponibles et de leur qualité.",
  "Le verdict du Claim Verifier est une synthèse rapide, pas une méta-analyse formelle.",
  "Pour confirmer un point important, ouvre toujours le paper et vérifie les sources citées dans Paper Chat.",
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
