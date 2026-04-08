<template>
  <div ref="rootEl" class="relative">
    <button
      type="button"
      :disabled="disabled"
      @click="toggle"
      class="flex items-center gap-2 rounded-lg border border-border bg-surface2 px-3 py-1.5 text-sm text-white transition-all disabled:opacity-50"
      :class="open ? 'border-accent/50 ring-1 ring-accent/30' : 'hover:border-accent/40'"
    >
      <span class="text-xs text-muted">{{ label }}:</span>
      <span class="font-medium">{{ modelValue }}</span>
      <svg
        class="h-4 w-4 text-muted transition-transform duration-150"
        :class="open ? 'rotate-180' : ''"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
      </svg>
    </button>

    <div v-if="open" class="absolute left-0 top-full z-20 mt-2 w-72 rounded-xl border border-border bg-surface p-4 shadow-xl">
      <div class="mb-3 flex items-center justify-between">
        <span class="text-xs font-semibold uppercase tracking-wider text-muted">{{ label }}</span>
        <span class="text-sm font-semibold text-white">{{ modelValue }}</span>
      </div>

      <input
        :value="modelValue"
        :min="min"
        :max="max"
        type="range"
        class="h-2 w-full cursor-pointer appearance-none rounded-lg bg-surface2 accent-accent"
        @input="updateValue"
      />

      <div class="mt-2 flex items-center justify-between text-xs text-muted">
        <span>{{ min }}</span>
        <span class="text-center">{{ helperText }}</span>
        <span>{{ max }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps({
  modelValue: { type: Number, required: true },
  label: { type: String, default: 'Papers' },
  min: { type: Number, default: 3 },
  max: { type: Number, default: 20 },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const rootEl = ref(null)

const helperText = computed(() => {
  if (props.modelValue <= props.min + 3) return 'Faster'
  if (props.modelValue >= props.max - 3) return 'More coverage'
  return 'Balanced'
})

function toggle() {
  if (props.disabled) return
  open.value = !open.value
}

function updateValue(event) {
  emit('update:modelValue', Number(event.target.value))
}

function onDocumentClick(event) {
  if (!rootEl.value?.contains(event.target)) open.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocumentClick)
})
</script>
