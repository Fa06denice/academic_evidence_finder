import { reactive } from 'vue'

const MAX = 20
const KEY = 'aef_history'

function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]') }
  catch { return [] }
}
function save(items) {
  try { localStorage.setItem(KEY, JSON.stringify(items.slice(0, MAX))) }
  catch {}
}

export const historyStore = reactive({
  items: load(),

  add(entry) {
    // Deduplicate: remove existing entry with same query + type
    this.items = this.items.filter(
      i => !(i.query === entry.query && i.type === entry.type)
    )
    this.items.unshift({ ...entry, id: Date.now(), date: new Date().toISOString() })
    if (this.items.length > MAX) this.items = this.items.slice(0, MAX)
    save(this.items)
  },

  remove(id) {
    this.items = this.items.filter(i => i.id !== id)
    save(this.items)
  },

  clear() {
    this.items = []
    save([])
  }
})
