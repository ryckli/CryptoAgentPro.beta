<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useAppStore } from "../stores/dashboard";
import { api } from "../api";
import Card from "../components/Card.vue";

const store = useAppStore();
const strategies = ref<any[]>([]);
const custom = ref<any[]>([]);
const signals = ref<Record<string, any>>({});
const signalLoading = ref(false);

// custom builder
const newName = ref("");
const newType = ref("ema_cross");
const newParams = ref<Record<string, any>>({ fast: 9, slow: 26, stop_loss_pct: 1.5, take_profit_pct: 2.0 });

const typeParams: Record<string, any> = {
  ema_cross: { fast: 9, slow: 26, stop_loss_pct: 1.5, take_profit_pct: 2.0 },
  rsi: { period: 14, oversold: 30, overbought: 70, stop_loss_pct: 1.5, take_profit_pct: 2.0 },
  macd: { stop_loss_pct: 1.8, take_profit_pct: 2.5 },
  boll: { period: 20, stop_loss_pct: 1.2, take_profit_pct: 1.8 },
};
const typeLabels: Record<string, string> = {
  ema_cross: "EMA双均线金叉死叉", rsi: "RSI超买超卖", macd: "MACD金叉死叉", boll: "布林带突破回归",
};

function onTypeChange() { newParams.value = { ...typeParams[newType.value] }; }

async function loadAll() {
  try { strategies.value = (await api.listStrategies()).strategies || []; } catch {}
  try { custom.value = (await api.listCustom()).custom_strategies || []; } catch {}
}

async function loadSignals() {
  signalLoading.value = true;
  signals.value = {};
  for (const s of strategies.value) {
    try { signals.value[s.id] = await api.getSignal(store.currentSymbol, s.id); }
    catch { signals.value[s.id] = { signal: "ERR" }; }
  }
  signalLoading.value = false;
}

async function activate(sid: string) {
  try { await api.activateStrategy(store.currentSymbol, sid); store.notify(`已激活 ${sid}`, "success"); }
  catch (e: any) { store.notify(e.message, "error"); }
}

async function oneClickOrder(sid: string) {
  try {
    const r = await api.strategyOrder(store.currentSymbol, sid);
    if (r.success) store.notify(r.message, "success");
    else store.notify(r.message || `信号: ${r.signal}`, "info");
  } catch (e: any) { store.notify(e.message, "error"); }
}

async function createCustom() {
  if (!newName.value) { store.notify("请输入策略名称", "error"); return; }
  try {
    await api.createCustom({ name: newName.value, base_type: newType.value, params: newParams.value });
    store.notify("自定义策略已创建", "success");
    newName.value = "";
    await loadAll();
  } catch (e: any) { store.notify(e.message, "error"); }
}

async function delCustom(id: string) {
  try { await api.deleteCustom(id); store.notify("已删除", "success"); await loadAll(); }
  catch (e: any) { store.notify(e.message, "error"); }
}

function sigClass(sig: string) {
  if (sig === "BUY") return "text-green-400";
  if (sig === "SELL") return "text-red-400";
  if (sig === "ERR") return "text-red-400";
  return "text-white/40";
}

onMounted(loadAll);
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center gap-3">
      <select v-model="store.currentSymbol" class="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm">
        <option v-for="s in store.symbols" :key="s" :value="s">{{ s }}</option>
      </select>
      <button class="px-4 py-2 text-xs rounded-lg bg-indigo-500 hover:bg-indigo-600 disabled:opacity-50" :disabled="signalLoading" @click="loadSignals">
        {{ signalLoading ? '计算中...' : '计算所有策略信号' }}
      </button>
    </div>

    <!-- Strategy list -->
    <Card title="策略库">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
        <div v-for="s in strategies" :key="s.id" class="bg-white/[0.02] border border-white/5 rounded-lg p-3 flex items-center justify-between">
          <div>
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium">{{ s.id }}</span>
              <span class="text-sm text-white/70">{{ s.name }}</span>
              <span v-if="s.custom" class="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300">自定义</span>
            </div>
            <p class="text-xs text-white/40 mt-0.5">{{ s.desc }}</p>
          </div>
          <div class="flex items-center gap-3">
            <span v-if="signals[s.id]" class="text-sm font-medium" :class="sigClass(signals[s.id].signal)">{{ signals[s.id].signal }}</span>
            <button class="text-xs px-2 py-1 rounded border border-white/10 hover:bg-white/5" @click="activate(s.id)">激活</button>
            <button class="text-xs px-2 py-1 rounded bg-indigo-500/80 hover:bg-indigo-500 text-white" @click="oneClickOrder(s.id)">一键下单</button>
          </div>
        </div>
      </div>
    </Card>

    <!-- Custom strategy builder -->
    <Card title="创建自定义策略">
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="space-y-3">
          <label class="block text-xs text-white/40">策略名称
            <input v-model="newName" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" placeholder="如: 我的EMA策略" />
          </label>
          <label class="block text-xs text-white/40">指标类型
            <select v-model="newType" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" @change="onTypeChange">
              <option v-for="(label, val) in typeLabels" :key="val" :value="val">{{ label }}</option>
            </select>
          </label>
        </div>
        <div class="space-y-2">
          <p class="text-xs text-white/40">参数</p>
          <div class="grid grid-cols-2 gap-2">
            <label v-for="(_, k) in newParams" :key="k" class="text-xs text-white/40">
              {{ k }}
              <input v-model.number="newParams[k]" type="number" step="0.1" class="w-full mt-0.5 bg-white/5 border border-white/10 rounded px-2 py-1 text-sm" />
            </label>
          </div>
        </div>
      </div>
      <button class="mt-3 px-5 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-600" @click="createCustom">创建策略</button>
    </Card>

    <!-- Custom list -->
    <Card v-if="custom.length" title="我的自定义策略">
      <div class="space-y-2">
        <div v-for="c in custom" :key="c.id" class="flex items-center justify-between bg-white/[0.02] border border-white/5 rounded-lg p-3">
          <div>
            <span class="text-sm font-medium">{{ c.name }}</span>
            <span class="text-xs text-white/40 ml-2">{{ typeLabels[c.base_type] || c.base_type }}</span>
            <span class="text-xs text-white/30 ml-2">{{ JSON.stringify(c.params) }}</span>
          </div>
          <button class="text-xs text-white/40 hover:text-red-400" @click="delCustom(c.id)">删除</button>
        </div>
      </div>
    </Card>
  </div>
</template>
