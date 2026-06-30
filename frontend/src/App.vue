<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useAppStore } from "./stores/dashboard";
import DashboardView from "./views/DashboardView.vue";
import AIReportsView from "./views/AIReportsView.vue";
import StrategiesView from "./views/StrategiesView.vue";
import BacktestView from "./views/BacktestView.vue";
import SettingsView from "./views/SettingsView.vue";
import ChatView from "./views/ChatView.vue";
import NewsView from "./views/NewsView.vue";
import AutoPilotView from "./views/AutoPilotView.vue";

const store = useAppStore();
const tab = ref("dashboard");

const tabs = [
  { id: "dashboard", label: "主面板" },
  { id: "autopilot", label: "自动驾驶" },
  { id: "chat", label: "AI助手" },
  { id: "news", label: "新闻" },
  { id: "ai", label: "AI报告" },
  { id: "strategies", label: "策略" },
  { id: "backtest", label: "回测" },
  { id: "settings", label: "设置" },
];

const modeLabel: Record<string, string> = { paper: "模拟盘", testnet: "测试网" };
const modeColor: Record<string, string> = { paper: "text-blue-400", testnet: "text-yellow-400" };

onMounted(() => store.loadBase());
</script>

<template>
  <div class="min-h-screen bg-[#0a0a0a] text-[#e0e0e0]">
    <!-- Top Nav -->
    <header class="sticky top-0 z-20 flex items-center justify-between px-6 h-12 border-b border-white/10 bg-[#0a0a0a]/95 backdrop-blur">
      <div class="flex items-center gap-6">
        <h1 class="text-sm font-semibold tracking-wide">CryptoAgents <span class="text-indigo-400">Pro</span></h1>
        <nav class="flex items-center gap-1">
          <button
            v-for="t in tabs" :key="t.id"
            class="px-3 py-1.5 text-xs rounded-lg transition-colors"
            :class="tab === t.id ? 'bg-white/10 text-white' : 'text-white/50 hover:text-white hover:bg-white/5'"
            @click="tab = t.id"
          >{{ t.label }}</button>
        </nav>
      </div>
      <div class="flex items-center gap-4 text-xs">
        <span class="flex items-center gap-1.5">
          <span class="w-1.5 h-1.5 rounded-full" :class="store.tradingMode === 'testnet' ? 'bg-yellow-400' : 'bg-blue-400'"></span>
          <span :class="modeColor[store.tradingMode]">{{ modeLabel[store.tradingMode] || store.tradingMode }}</span>
        </span>
        <span :class="store.hasExchangeKey ? 'text-green-400' : 'text-white/30'">{{ store.hasExchangeKey ? '交易所✓' : '交易所✗' }}</span>
        <span :class="store.hasDeepseekKey ? 'text-green-400' : 'text-white/30'">{{ store.hasDeepseekKey ? 'AI✓' : 'AI✗' }}</span>
      </div>
    </header>

    <!-- Toast -->
    <transition name="fade">
      <div v-if="store.toast" class="fixed top-16 right-6 z-50 px-4 py-2 rounded-lg text-xs shadow-lg"
        :class="store.toast.type === 'error' ? 'bg-red-500/90 text-white' : store.toast.type === 'success' ? 'bg-green-500/90 text-white' : 'bg-white/10 text-white border border-white/20'">
        {{ store.toast.msg }}
      </div>
    </transition>

    <!-- Content -->
    <main class="max-w-[1600px] mx-auto p-6">
      <DashboardView v-show="tab === 'dashboard'" />
      <AutoPilotView v-if="tab === 'autopilot'" />
      <ChatView v-if="tab === 'chat'" />
      <NewsView v-if="tab === 'news'" />
      <AIReportsView v-if="tab === 'ai'" />
      <StrategiesView v-if="tab === 'strategies'" />
      <BacktestView v-if="tab === 'backtest'" />
      <SettingsView v-if="tab === 'settings'" />
    </main>
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
