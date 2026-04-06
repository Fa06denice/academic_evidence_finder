<template>
  <div class="flex min-h-screen bg-bg">

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
      <div v-if="historyStore.items.length" class="px-3 py-3 border-t border-border">
        <div class="flex items-center justify-between mb-2 px-1">
          <span class="text-xs font-semibold text-muted uppercase tracking-wider">History</span>
          <button @click="historyStore.clear()" class="text-xs text-muted hover:text-white transition-colors">Clear</button>
        </div>
        <div class="space-y-1 max-h-40 overflow-y-auto">
          <div v-for="item in historyStore.items.slice(0,8)" :key="item.id"
            class="px-2 py-1.5 rounded text-xs text-muted hover:text-white hover:bg-surface2 cursor-pointer truncate transition-colors"
            @click="reuseHistory(item)"
            :title="item.query">
            <span class="mr-1.5 opacity-60">{{ item.type === 'verify' ? '🧪' : item.type === 'review' ? '📚' : item.type === 'chat' ? '💬' : '🔍' }}</span>
            {{ item.query }}
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="px-5 py-4 border-t border-border">
        <div class="text-xs text-muted">v1.0 · FastAPI + Vue 3</div>
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
import { useRouter, useRoute } from 'vue-router'
import { historyStore } from './stores/history.js'

const router = useRouter()
const route  = useRoute()

const nav = [
  { to: '/',       icon: '🧪', label: 'Claim Verifier'     },
  { to: '/review', icon: '📚', label: 'Literature Review'  },
  { to: '/search', icon: '🔍', label: 'Paper Search'       },
  { to: '/chat',   icon: '💬', label: 'Paper Chat'         },
]

function reuseHistory(item) {
  router.push({ path: item.path, query: { q: item.query } })
}
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
