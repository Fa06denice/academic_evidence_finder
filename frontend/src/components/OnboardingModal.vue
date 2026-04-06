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
                <h2 class="font-semibold text-white text-sm">Evidence Finder — Guide d'utilisation</h2>
                <p class="text-xs text-muted">Comment fonctionne l'outil et ses limites</p>
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

            <!-- How it works -->
            <section>
              <h3 class="font-semibold text-white mb-3 flex items-center gap-2">
                <span class="text-base">⚙️</span> Comment ça fonctionne
              </h3>
              <div class="space-y-2 text-muted leading-relaxed">
                <p>L'outil interroge <strong class="text-white">Semantic Scholar</strong> pour trouver des articles scientifiques pertinents, puis un <strong class="text-white">LLM</strong> analyse chaque abstract en deux passes :</p>
                <div class="mt-3 space-y-2">
                  <div class="flex gap-3 p-3 rounded-lg bg-surface2 border border-border">
                    <span class="text-accent font-bold shrink-0">1</span>
                    <div><strong class="text-white">Extraction factuelle</strong> — le LLM identifie le résultat principal du paper et sa direction (A > B, B > A, pas de différence, pas de comparaison) sans encore évaluer le claim.</div>
                  </div>
                  <div class="flex gap-3 p-3 rounded-lg bg-surface2 border border-border">
                    <span class="text-accent font-bold shrink-0">2</span>
                    <div><strong class="text-white">Verdict</strong> — le LLM compare le résultat extrait au claim pour attribuer un verdict (SUPPORTS, CONTRADICTS, NEUTRAL…) avec un niveau de confiance.</div>
                  </div>
                </div>
              </div>
            </section>

            <!-- Features -->
            <section>
              <h3 class="font-semibold text-white mb-3 flex items-center gap-2">
                <span class="text-base">🧰</span> Les fonctionnalités
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
              <div class="mt-3 p-3 rounded-lg bg-accent/5 border border-accent/20 text-xs text-muted leading-relaxed">
                <strong class="text-accent">Combo recommandé :</strong> Lance d'abord <em>Claim Verifier</em> pour avoir une vue d'ensemble, puis utilise <em>Paper Chat</em> sur les papers marqués CONTRADICTS pour approfondir leur contexte et conditions.
              </div>
            </section>

            <!-- Risks -->
            <section>
              <h3 class="font-semibold text-white mb-3 flex items-center gap-2">
                <span class="text-base">⚠️</span> Risques à connaître
              </h3>
              <div class="space-y-2">
                <div v-for="r in risks" :key="r.title" class="flex gap-3 p-3 rounded-lg bg-surface2 border border-border">
                  <span class="text-lg shrink-0">{{ r.emoji }}</span>
                  <div>
                    <strong class="text-white text-xs block mb-0.5">{{ r.title }}</strong>
                    <p class="text-muted text-xs leading-relaxed">{{ r.desc }}</p>
                  </div>
                </div>
              </div>
            </section>

            <!-- Limitations -->
            <section>
              <h3 class="font-semibold text-white mb-3 flex items-center gap-2">
                <span class="text-base">🚧</span> Limitations connues
              </h3>
              <ul class="space-y-1.5">
                <li v-for="l in limitations" :key="l" class="flex gap-2 text-muted text-xs leading-relaxed">
                  <span class="text-border shrink-0 mt-0.5">›</span>
                  <span>{{ l }}</span>
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
    desc: 'Entre une affirmation scientifique. L'outil cherche des papers, les analyse et rend un verdict global avec les détails par paper.'
  },
  {
    icon: '📚',
    name: 'Literature Review',
    desc: 'Entre un sujet ou topic. Génère une synthèse structurée de la littérature récente sous forme de revue académique.'
  },
  {
    icon: '🔍',
    name: 'Paper Search',
    desc: 'Cherche des papers directement par mots-clés sur Semantic Scholar. Utile pour explorer un domaine sans claim précis.'
  },
  {
    icon: '💬',
    name: 'Paper Chat',
    desc: 'Pose des questions à un paper spécifique. Le LLM répond en se basant strictement sur l'abstract fourni.'
  },
]

const risks = [
  {
    emoji: '🎰',
    title: 'Biais de sélection des papers',
    desc: 'Semantic Scholar retourne les papers les plus cités pour les requêtes générées. Des études importantes mais récentes ou peu citées peuvent être manquées.'
  },
  {
    emoji: '🔒',
    title: 'Abstracts manquants (paywall)',
    desc: 'Environ 30–40 % des papers ont leur abstract indisponible via API. Ces papers apparaissent en INSUFFICIENT ou NEUTRAL — non pas parce qu'ils sont hors sujet, mais parce que le contenu n'est pas accessible.'
  },
  {
    emoji: '🤖',
    title: 'Erreurs d'interprétation du LLM',
    desc: 'Le LLM peut mal identifier A et B pour des claims ambigus, sur-généraliser un résultat étroit, ou classer CONTRADICTS un paper dont le scope est très restreint. Toujours lire l'explication et vérifier le paper source.'
  },
  {
    emoji: '📊',
    title: 'Le verdict global n'est pas une méta-analyse',
    desc: 'Le verdict SUPPORTED/CONTRADICTED est une synthèse qualitative, pas une méta-analyse statistique. Des papers de qualité inégale comptent autant dans le décompte brut.'
  },
]

const limitations = [
  'Les requêtes sont générées en anglais. Un claim en français sera traduit, ce qui peut introduire des nuances perdues.',
  'Seuls les abstracts sont analysés — pas les corps des articles. Un résultat mentionné uniquement dans les résultats détaillés sera invisible.',
  'Le score de pertinence (0–10) est une estimation LLM, pas un calcul statistique rigoureux.',
  'Les papers très récents (< 6 mois) sont sous-représentés car peu indexés et peu cités.',
  'Les comparaisons A vs B très générales ("Traditional CS vs Quantum CS") couvrent un spectre trop large — les papers trouvés portent souvent sur des sous-domaines spécifiques, pas la question globale.',
  'Le mode Fast (5 papers) donne une vue partielle. Utiliser Deep (15 papers) pour les sujets controversés.',
]

function close() {
  if (dontShow.value) {
    // Store in a module-level variable (no localStorage in sandboxed env)
    window.__evidenceFinderOnboardingSeen = true
  }
  visible.value = false
}

onMounted(() => {
  if (!window.__evidenceFinderOnboardingSeen) {
    visible.value = true
  }
})

// Expose for manual trigger from parent
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
