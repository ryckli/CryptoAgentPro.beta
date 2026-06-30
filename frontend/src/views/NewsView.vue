<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useAppStore } from "../stores/dashboard";
import { api } from "../api";
import Card from "../components/Card.vue";

const store = useAppStore();
const news = ref<any[]>([]);
const loading = ref(false);

async function load(force = false) {
  loading.value = true;
  try { news.value = (await api.getNews(30, force)).news || []; }
  catch (e: any) { store.notify(e.message, "error"); }
  loading.value = false;
}

function fmtTime(ts: number) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const diff = (Date.now() - d.getTime()) / 60000;
  if (diff < 60) return `${Math.round(diff)}分钟前`;
  if (diff < 1440) return `${Math.round(diff / 60)}小时前`;
  return d.toLocaleDateString();
}

onMounted(() => load());
</script>

<template>
  <Card title="最新加密金融新闻 (实时)">
    <template #actions>
      <button class="text-xs px-3 py-1 rounded-lg bg-white/5 hover:bg-white/10" :disabled="loading" @click="load(true)">
        {{ loading ? '刷新中...' : '刷新' }}
      </button>
    </template>
    <div v-if="news.length === 0 && !loading" class="text-xs text-white/30 py-6">暂无新闻，点击刷新。</div>
    <div class="space-y-2 max-h-[calc(100vh-12rem)] overflow-y-auto">
      <a v-for="(n, i) in news" :key="i" :href="n.url" target="_blank"
        class="block bg-white/[0.02] hover:bg-white/[0.05] border border-white/5 rounded-lg p-3 transition-colors">
        <div class="flex items-start justify-between gap-3">
          <div class="flex-1">
            <p class="text-sm font-medium text-white/90">{{ n.title }}</p>
            <p v-if="n.body" class="text-xs text-white/40 mt-1 line-clamp-2">{{ n.body }}</p>
          </div>
        </div>
        <div class="flex items-center gap-3 mt-2 text-xs text-white/30">
          <span class="text-indigo-400">{{ n.source }}</span>
          <span>{{ fmtTime(n.published_at) }}</span>
        </div>
      </a>
    </div>
  </Card>
</template>

<style scoped>
.line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
