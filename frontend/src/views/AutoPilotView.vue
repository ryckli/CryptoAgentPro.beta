<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { useAppStore } from "../stores/dashboard";
import { api } from "../api";
import Card from "../components/Card.vue";

const store = useAppStore();

const running = ref(false);
const startedAt = ref(0);
const loopCount = ref(0);
const lastAction = ref("");
const uptime = ref(0);
const account = ref<any>(null);
const positions = ref<any[]>([]);
const history = ref<any[]>([]);
const mode = ref("paper");
const apiError = ref("");
const symbolStatus = ref<Record<string, any>>({});
const selectedSymbols = ref<string[]>(["BTC/USDT"]);
let pollTimer: any = null;
let uptimeTimer: any = null;

async function refresh() {
  try {
    const s = await api.autopilotStatus();
    running.value = s.running;
    startedAt.value = s.started_at;
    loopCount.value = s.loop_count;
    lastAction.value = s.last_action;
    positions.value = s.positions || [];
    mode.value = s.mode || "paper";
    symbolStatus.value = s.symbol_status || {};
    selectedSymbols.value = s.selected_symbols || store.symbols;
  } catch {}
  try { account.value = await api.autopilotAccount(); } catch {}
}

async function loadHistory() {
  try { history.value = (await api.autopilotHistory(50)).history || []; } catch {}
}

async function start() {
  apiError.value = "";
  try {
    // 先检查 API 接入状态
    const check = await api.get("/autopilot/check");
    if (!check.ready) {
      apiError.value = check.message;
      store.notify(check.message, "error");
      return;
    }
    const r = await api.autopilotStart(selectedSymbols.value.join(","));
    if (r.status === "error") {
      apiError.value = r.message;
      store.notify(r.message, "error");
      return;
    }
    if (r.status === "already_running") { store.notify("已在运行中", "info"); return; }
    store.notify(`自动驾驶已启动 [${mode.value}] — AI接管全部操作`, "success");
    await refresh();
  } catch (e: any) { store.notify(e.message, "error"); }
}

async function stop() {
  try {
    const r = await api.autopilotStop();
    store.notify(`已停止 · 平仓${r.closed || 0}笔`, "success");
    await refresh();
    await loadHistory();
  } catch (e: any) { store.notify(e.message, "error"); }
}

function fmtTime(ts: number) {
  if (!ts) return "--";
  return new Date(ts * 1000).toLocaleTimeString();
}
function fmtDur(sec: number) {
  if (!sec) return "0秒";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h) return `${h}时${m}分`;
  if (m) return `${m}分${s}秒`;
  return `${s}秒`;
}

onMounted(() => {
  refresh();
  loadHistory();
  pollTimer = setInterval(() => { refresh(); if (running.value) loadHistory(); }, 5000);
  uptimeTimer = setInterval(() => { if (running.value) uptime.value++; }, 1000);
});
onUnmounted(() => { clearInterval(pollTimer); clearInterval(uptimeTimer); });
</script>

<template>
  <div class="max-w-5xl mx-auto space-y-5">
    <!-- 标题 -->
    <div class="text-center pt-2">
      <h2 class="text-lg font-semibold">AI 自动驾驶</h2>
      <p class="text-xs text-white/40 mt-1">一键启动后，AI全权接管策略切换与下单，无需人工干预</p>
    </div>

    <!-- 币种选择 -->
    <div class="flex items-center justify-center gap-3 flex-wrap">
      <span class="text-xs text-white/40">交易币种:</span>
      <label v-for="s in store.symbols" :key="s" class="flex items-center gap-1 text-xs cursor-pointer"
        :class="selectedSymbols.includes(s) ? 'text-white' : 'text-white/30'">
        <input type="checkbox" :value="s" v-model="selectedSymbols" class="rounded" />
        {{ s.split('/')[0] }}
      </label>
    </div>

    <!-- 双按钮 -->
    <div class="flex gap-4 justify-center">
      <button
        class="px-10 py-5 rounded-2xl text-base font-bold transition-all"
        :class="running ? 'bg-white/5 text-white/30 cursor-not-allowed' : 'bg-green-500 hover:bg-green-600 text-white shadow-lg shadow-green-500/20'"
        :disabled="running"
        @click="start"
      >
        ▶ 一键启动
      </button>
      <button
        class="px-10 py-5 rounded-2xl text-base font-bold transition-all"
        :class="!running ? 'bg-white/5 text-white/30 cursor-not-allowed' : 'bg-red-500 hover:bg-red-600 text-white shadow-lg shadow-red-500/20'"
        :disabled="!running"
        @click="stop"
      >
        ■ 一键平仓停止
      </button>
    </div>

    <!-- 状态条 -->
    <div class="flex items-center justify-center gap-6 text-xs">
      <span class="flex items-center gap-1.5">
        <span class="w-2 h-2 rounded-full" :class="running ? 'bg-green-400 animate-pulse' : 'bg-white/20'"></span>
        <span :class="running ? 'text-green-400' : 'text-white/40'">{{ running ? '运行中' : '已停止' }}</span>
      </span>
      <span class="px-2 py-0.5 rounded-full" :class="mode === 'testnet' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-blue-500/20 text-blue-400'">
        {{ mode === 'paper' ? '模拟盘' : '测试网' }}
      </span>
      <span v-if="running" class="text-white/50">运行: {{ fmtDur(uptime) }}</span>
      <span v-if="running" class="text-white/50">循环: {{ loopCount }}</span>
      <span v-if="running" class="text-white/50">间隔: 15秒</span>
    </div>

    <!-- API 未接入提示 -->
    <div v-if="apiError" class="bg-red-500/10 border border-red-500/30 rounded-xl p-4 flex items-start gap-3">
      <span class="text-red-400 text-lg">⚠</span>
      <div class="flex-1">
        <p class="text-sm text-red-300 font-medium">API 未接入，无法启动</p>
        <p class="text-xs text-white/50 mt-1">{{ apiError }}</p>
        <p class="text-xs text-indigo-400 mt-2">→ 请到「设置」页填入所需 API Key 后再启动</p>
      </div>
    </div>

    <div v-if="lastAction" class="text-center text-xs text-white/40">
      最近操作: {{ lastAction }}
    </div>

    <!-- 账户概览 -->

    <!-- 各币种实时状态 -->
    <Card v-if="running && Object.keys(symbolStatus).length" title="各币种AI决策状态">
      <table class="w-full text-xs">
        <thead class="text-white/40">
          <tr class="text-left border-b border-white/5">
            <th class="py-2">币种</th><th>市场状态</th><th>置信度</th><th>策略</th><th>信号</th><th>阶段</th><th>持仓</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(ss, sym) in symbolStatus" :key="sym" class="border-b border-white/5">
            <td class="py-1.5 font-medium">{{ sym }}</td>
            <td :class="(ss.market_state||'').includes('BULL')?'text-green-400':(ss.market_state||'').includes('BEAR')?'text-red-400':'text-yellow-400'">{{ ss.market_state || '--' }}</td>
            <td>{{ ss.confidence ?? '--' }}%</td>
            <td class="text-blue-400">{{ ss.strategy || '--' }}</td>
            <td :class="ss.signal==='BUY'?'text-green-400':ss.signal==='SELL'?'text-red-400':'text-white/40'">
              {{ ss.signal || '--' }}
              <span v-if="ss.signal_dir" class="ml-1 text-white/30">{{ ss.signal_dir }}</span>
            </td>
            <td class="text-white/40">{{ ss.phase || '--' }}</td>
            <td :class="ss.has_position?'text-green-400':'text-white/30'">{{ ss.has_position ? '有' : '无' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="Object.values(symbolStatus).some((s:any)=>s.error)" class="mt-2 text-xs text-red-400">
        <span v-for="(ss, sym) in symbolStatus" :key="sym">
          <span v-if="ss.error">⚠ {{ sym }}: {{ ss.error }} </span>
          <span v-if="ss.signal_error">⚠ {{ sym }}下单: {{ ss.signal_error }} </span>
        </span>
      </div>
    </Card>

    <!-- 账户概览 -->
    <div class="grid grid-cols-4 gap-3">
      <div class="bg-white/[0.03] border border-white/10 rounded-xl p-3 text-center">
        <div class="text-[10px] text-white/30">账户权益</div>
        <div class="text-lg font-semibold">${{ account?.equity?.toFixed(2) ?? '--' }}</div>
      </div>
      <div class="bg-white/[0.03] border border-white/10 rounded-xl p-3 text-center">
        <div class="text-[10px] text-white/30">已实现盈亏</div>
        <div class="text-lg font-semibold" :class="(account?.realized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'">
          {{ (account?.realized_pnl ?? 0) >= 0 ? '+' : '' }}${{ account?.realized_pnl?.toFixed(2) ?? '--' }}
        </div>
      </div>
      <div class="bg-white/[0.03] border border-white/10 rounded-xl p-3 text-center">
        <div class="text-[10px] text-white/30">持仓数</div>
        <div class="text-lg font-semibold">{{ account?.open_positions ?? 0 }}</div>
      </div>
      <div class="bg-white/[0.03] border border-white/10 rounded-xl p-3 text-center">
        <div class="text-[10px] text-white/30">胜率</div>
        <div class="text-lg font-semibold">{{ account?.win_rate ?? 0 }}%</div>
      </div>
    </div>

    <!-- 实时持仓 -->
    <Card title="实时持仓状态">
      <div v-if="positions.length === 0" class="text-xs text-white/30 py-6 text-center">暂无持仓</div>
      <table v-else class="w-full text-xs">
        <thead class="text-white/40">
          <tr class="text-left border-b border-white/5">
            <th class="py-2">币种</th><th>方向</th><th>策略</th><th>数量</th>
            <th>开仓价</th><th>现价</th><th>杠杆</th><th>浮盈%</th><th>止损</th><th>止盈</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in positions" :key="p.id" class="border-b border-white/5">
            <td class="py-2 font-medium">{{ p.symbol }}</td>
            <td :class="p.direction === 'LONG' ? 'text-green-400' : 'text-red-400'">{{ p.direction }}</td>
            <td class="text-blue-400">{{ p.strategy_id }}</td>
            <td>{{ p.qty }}</td>
            <td>{{ p.entry_price?.toFixed(2) }}</td>
            <td>{{ p.current_price?.toFixed(2) }}</td>
            <td>{{ p.leverage }}x</td>
            <td :class="(p.unrealized_pnl_pct ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'">
              {{ p.unrealized_pnl_pct ?? 0 }}%
            </td>
            <td class="text-white/40">{{ p.stop_loss?.toFixed(2) ?? '-' }}</td>
            <td class="text-white/40">{{ p.take_profit?.toFixed(2) ?? '-' }}</td>
          </tr>
        </tbody>
      </table>
    </Card>

    <!-- 历史仓位 -->
    <Card title="历史仓位">
      <div v-if="history.length === 0" class="text-xs text-white/30 py-6 text-center">暂无历史记录</div>
      <table v-else class="w-full text-xs">
        <thead class="text-white/40">
          <tr class="text-left border-b border-white/5">
            <th class="py-2">币种</th><th>方向</th><th>策略</th>
            <th>开仓价</th><th>平仓价</th><th>盈亏</th><th>盈亏%</th><th>开仓时间</th><th>平仓时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in history" :key="h.id" class="border-b border-white/5">
            <td class="py-1.5 font-medium">{{ h.symbol }}</td>
            <td :class="h.direction === 'LONG' ? 'text-green-400' : 'text-red-400'">{{ h.direction }}</td>
            <td class="text-blue-400">{{ h.strategy_id }}</td>
            <td>{{ h.entry_price?.toFixed(2) }}</td>
            <td>{{ h.exit_price?.toFixed(2) }}</td>
            <td :class="(h.pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'">
              {{ (h.pnl ?? 0) >= 0 ? '+' : '' }}${{ h.pnl?.toFixed(2) }}
            </td>
            <td :class="(h.pnl_pct ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'">
              {{ h.pnl_pct }}%
            </td>
            <td class="text-white/30">{{ fmtTime(h.opened_at) }}</td>
            <td class="text-white/30">{{ fmtTime(h.closed_at) }}</td>
          </tr>
        </tbody>
      </table>
    </Card>
  </div>
</template>
