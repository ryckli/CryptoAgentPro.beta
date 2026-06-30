<script setup lang="ts">
import { ref, nextTick } from "vue";
import { useAppStore } from "../stores/dashboard";
import { api } from "../api";

const store = useAppStore();

interface Msg { role: string; content: string; action?: any; applied?: any }
const messages = ref<Msg[]>([
  { role: "assistant", content: "你好！我是 CryptoAgents AI 助手。我可以分析实时K线和最新加密新闻，也能根据你的描述创建交易策略。\n\n试试问我：「分析一下 BTC 现在的走势」或「帮我创建一个 RSI 超卖买入的策略」" },
]);
const input = ref("");
const sending = ref(false);
const includeNews = ref(true);
const includeKline = ref(true);
const autoApply = ref(false);
const chatBox = ref<HTMLElement | null>(null);

async function scrollDown() {
  await nextTick();
  if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight;
}

async function send() {
  const text = input.value.trim();
  if (!text || sending.value) return;
  messages.value.push({ role: "user", content: text });
  input.value = "";
  sending.value = true;
  scrollDown();

  try {
    const history = messages.value.filter(m => m.role === "user" || m.role === "assistant").map(m => ({ role: m.role, content: m.content }));
    const r = await api.chat({
      messages: history,
      symbol: store.currentSymbol,
      include_news: includeNews.value,
      include_kline: includeKline.value,
      auto_apply: autoApply.value,
    });
    messages.value.push({ role: "assistant", content: r.reply, action: r.action, applied: r.applied });
    if (r.applied?.applied) store.notify(r.applied.message, "success");
  } catch (e: any) {
    messages.value.push({ role: "assistant", content: "出错了: " + e.message });
  }
  sending.value = false;
  scrollDown();
}

async function applyAction(msg: Msg) {
  try {
    const r = await api.applyAction(msg.action);
    msg.applied = r;
    if (r.applied) store.notify(r.message, "success");
    else store.notify(r.message, "error");
  } catch (e: any) { store.notify(e.message, "error"); }
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
}

const quickPrompts = [
  "分析当前币种的K线走势和指标",
  "结合最新新闻，市场情绪如何？",
  "帮我创建一个EMA金叉做多的策略",
  "创建一个RSI低于25买入、高于75卖出的策略",
];
</script>

<template>
  <div class="flex flex-col h-[calc(100vh-7rem)]">
    <!-- Controls -->
    <div class="flex items-center gap-4 mb-3 flex-wrap text-xs">
      <select v-model="store.currentSymbol" class="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm">
        <option v-for="s in store.symbols" :key="s" :value="s">{{ s }}</option>
      </select>
      <label class="flex items-center gap-1.5 cursor-pointer"><input v-model="includeKline" type="checkbox" /> 注入K线</label>
      <label class="flex items-center gap-1.5 cursor-pointer"><input v-model="includeNews" type="checkbox" /> 注入新闻</label>
      <label class="flex items-center gap-1.5 cursor-pointer"><input v-model="autoApply" type="checkbox" /> 自动执行建策略</label>
      <span v-if="!store.hasDeepseekKey" class="text-yellow-400">⚠ 未配置 DeepSeek Key</span>
    </div>

    <!-- Messages -->
    <div ref="chatBox" class="flex-1 overflow-y-auto space-y-4 pr-2">
      <div v-for="(m, i) in messages" :key="i" class="flex" :class="m.role === 'user' ? 'justify-end' : 'justify-start'">
        <div class="max-w-[80%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap"
          :class="m.role === 'user' ? 'bg-indigo-500 text-white' : 'bg-white/[0.05] border border-white/10'">
          {{ m.content }}
          <!-- action block -->
          <div v-if="m.action && m.action.type === 'create_strategy'" class="mt-3 pt-3 border-t border-white/10">
            <div class="text-xs text-white/50 mb-2">
              📋 AI建议创建策略: <span class="text-white">{{ m.action.name }}</span>
              <span class="text-white/40">({{ m.action.base_type }})</span>
            </div>
            <div class="text-xs text-white/40 mb-2 font-mono">{{ JSON.stringify(m.action.params) }}</div>
            <div v-if="m.applied?.applied" class="text-xs text-green-400">✓ {{ m.applied.message }}</div>
            <button v-else class="text-xs px-3 py-1 rounded bg-indigo-500 hover:bg-indigo-600 text-white" @click="applyAction(m)">
              创建此策略
            </button>
          </div>
        </div>
      </div>
      <div v-if="sending" class="flex justify-start">
        <div class="bg-white/[0.05] border border-white/10 rounded-2xl px-4 py-2.5 text-sm text-white/40">思考中...</div>
      </div>
    </div>

    <!-- Quick prompts -->
    <div class="flex gap-2 flex-wrap my-2">
      <button v-for="q in quickPrompts" :key="q" class="text-xs px-2.5 py-1 rounded-full bg-white/5 hover:bg-white/10 text-white/50"
        @click="input = q">{{ q }}</button>
    </div>

    <!-- Input -->
    <div class="flex gap-2">
      <textarea v-model="input" rows="2" placeholder="输入消息... (Enter发送, Shift+Enter换行)"
        class="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm resize-none focus:outline-none focus:border-indigo-500/50"
        @keydown="onKey" />
      <button class="px-6 rounded-xl bg-indigo-500 hover:bg-indigo-600 disabled:opacity-50 text-sm" :disabled="sending" @click="send">发送</button>
    </div>
  </div>
</template>
