<template>
  <div class="flex min-h-screen bg-bg">

    <!-- Onboarding modal -->
    <OnboardingModal ref="onboardingRef" />

    <!-- Sidebar -->
    <aside class="w-56 shrink-0 flex flex-col border-r border-border bg-surface sticky top-0 h-screen">
      <!-- Logo -->
      <div class="px-5 py-5 border-b border-border">
        <div class="flex items-center gap-2.5">
          <div class="w-7 h-7 rounded-lg bg-accent flex items-center justify-center text-sm">🔬</div>
          <span class="font-semibold text-sm text-white tracking-tight">Evidence Finder</span>
        </div>
      </div>

      <!-- Nav -->
      <nav class="flex-1 px-3 py-4 space-y-1">
        <router-link v-for="item in nav" :key="item.to" :to="item.to"
          class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150"
          :class="$route.path === item.to
            ? 'bg-accent/10 text-accent border border-accent/20'
            : 'text-muted hover:text-white hover:bg-surface2'">
          <span class="text-base">{{ item.icon }}</span>
          {{ item.label }}
        </router-link>
      </nav>

      <!-- History -->
      <div class="px-3 py-3 border-t border-border">
        <div class="flex items-center justify-between mb-2 px-1">
          <span class="text-xs font-semibold text-muted uppercase tracking-wider">History</span>
          <button
            v-if="historyStore.items.length"
            @click="historyStore.clear()"
            title="Clear history"
            class="text-xs text-muted hover:text-red-400 transition-colors">
            Clear
          </button>
        </div>

        <div v-if="historyStore.items.length" class="space-y-0.5 max-h-40 overflow-y-auto pr-0.5">
          <div
            v-for="item in historyStore.items.slice(0, 8)"
            :key="item.id"
            class="group flex items-center gap-1 px-2 py-1.5 rounded text-xs text-muted hover:text-white hover:bg-surface2 cursor-pointer transition-colors"
            @click="reuseHistory(item)"
            :title="item.query">
            <span class="shrink-0 opacity-60">{{ typeIcon(item.type) }}</span>
            <span class="truncate flex-1">{{ item.query }}</span>
            <button
              class="shrink-0 opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-red-400 transition-all ml-0.5"
              title="Remove"
              @click.stop="historyStore.remove(item.id)">
              ×
            </button>
          </div>
        </div>

        <div v-else class="px-1 py-2 text-xs text-muted/50 italic">No history yet</div>
      </div>

      <!-- Clear cache button -->
      <div class="px-3 pb-3">
        <button
          @click="clearCache"
          :disabled="cacheClearing"
          :class="cacheCleared ? 'text-emerald-400 border-emerald-500/30' : cacheError ? 'text-red-400 border-red-500/30' : 'text-muted hover:text-white hover:border-accent/30'"
          class="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium border border-border bg-surface2 transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed">
          <span v-if="cacheClearing" class="w-3 h-3 border-2 border-current/30 border-t-current rounded-full animate-spin"></span>
          <span v-else>{{ cacheCleared ? '✓' : cacheError ? '⚠' : '🗑' }}</span>
          {{ cacheClearing ? 'Clearing…' : cacheCleared ? 'Cache cleared!' : cacheError ? 'Clear failed' : 'Clear server cache' }}
        </button>
      </div>

      <!-- Footer -->
      <div class="px-5 py-4 border-t border-border">
        <div class="flex items-center justify-between">
          <div class="text-xs text-muted">v1.0 · FastAPI + Vue 3</div>
          <button @click="onboardingRef?.open()"
            title="Afficher le guide d'utilisation"
            class="text-muted hover:text-white transition-colors p-1 rounded hover:bg-surface2">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <path d="M12 16v-4M12 8h.01"/>
            </svg>
          </button>
        </div>
      </div>
    </aside>

    <!-- Main -->
    <main class="flex-1 flex flex-col min-h-screen overflow-auto">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>

  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { historyStore } from './stores/history.js'
import OnboardingModal from './components/OnboardingModal.vue'
import { del } from './api/index.js'

const router        = useRouter()
const route         = useRoute()
const onboardingRef = ref(null)
const cacheCleared  = ref(false)
const cacheClearing = ref(false)
const cacheError    = ref(false)

const nav = [
  { to: '/',       icon: '🧪', label: 'Claim Verifier'    },
  { to: '/search', icon: '🔍', label: 'Paper Search'      },
  { to: '/chat',   icon: '💬', label: 'Paper Chat'        },
]

function typeIcon(type) {
  return type === 'verify' ? '🧪' : type === 'review' ? '📚' : type === 'chat' ? '💬' : '🔍'
}

function normalizedQuery(query = {}) {
  return JSON.stringify(
    Object.fromEntries(
      Object.entries(query)
        .filter(([, value]) => value !== undefined && value !== null && value !== '')
        .sort(([a], [b]) => a.localeCompare(b))
    )
  )
}

function reuseHistory(item) {
  const path = item.path === '/review' ? '/' : item.path
  const query = { ...(item.routeQuery || { q: item.query, autorun: '1' }) }

  if (route.path === path && normalizedQuery(route.query) === normalizedQuery(query)) {
    window.dispatchEvent(new CustomEvent('aef:reuse-history', { detail: item }))
    return
  }

  router.push({ path, query, state: item.routeState || undefined })
}

/**
 * Clear server cache via DELETE /api/cache, then wipe local UI state.
 * Shows spinner while in-flight, green check on success, red warning on failure.
 */
async function clearCache() {
  if (cacheClearing.value) return
  cacheClearing.value = true
  cacheCleared.value  = false
  cacheError.value    = false
  try {
    await del('/api/cache')
    // Also wipe local view state
    window.dispatchEvent(new CustomEvent('aef:clear-cache'))
    cacheCleared.value = true
    setTimeout(() => { cacheCleared.value = false }, 2500)
  } catch (err) {
    console.error('[clearCache]', err)
    cacheError.value = true
    setTimeout(() => { cacheError.value = false }, 3000)
  } finally {
    cacheClearing.value = false
  }
}
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from,  .fade-leave-to      { opacity: 0; }
</style>
