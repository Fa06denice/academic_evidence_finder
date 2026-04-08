import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import ClaimVerifier from './views/ClaimVerifier.vue'
import PaperSummarizer from './views/PaperSummarizer.vue'
import PaperChat from './views/PaperChat.vue'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/',       component: ClaimVerifier,    name: 'verify' },
    { path: '/review', redirect: to => ({ path: '/', query: to.query }) },
    { path: '/search', component: PaperSummarizer,  name: 'search' },
    { path: '/chat',   component: PaperChat,        name: 'chat'   },
  ]
})

createApp(App).use(router).mount('#app')
