<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from "vue";
import { useAppStore } from "../stores/dashboard";
import { api } from "../api";
import Card from "../components/Card.vue";

const store = useAppStore();

const klines = ref<string[]>([]);
const trend = ref<any>(null);
const risk = ref<any>(null);
const account = ref<any>(null);
const positions = ref<any[]>([]);
const pending = ref<any>(null);
const strategies = ref<any[]>([]);
const activeStrategy = ref("--");
const loading = ref(false);

// manual order form
const orderDir = ref("LONG");
const orderSl = ref(1.8);
const orderTp = ref(2.0);
const orderLev = ref(10);

let timer: any = null;

async function refresh() {
  const sym = store.currentSymbol;
  try { klines.value = (await api.getKline(sym, "15m", 100)).raw || []; } catch {}
  try { risk.value = await api.getRisk(); } catch {}
  try { account.value = await api.getAccount(); } catch {}
  try { positions.value = (await api.getPositions(sym)).positions || []; } catch {}
  try {
    const s = await api.schedulerStatus(sym);
    activeStrategy.value = s.current_strategy;
    pending.value = s.pending;
  } catch {}
}

async function senseTrend() {
  loading.value = true;
  try {
    const r = await api.getTrend(store.currentSymbol);
    trend.value = r.trend;
    store.notify("趋势感知完成", "success");
    await refresh();
  } catch (e: any) {
    store.notify(e.message, "error");
  }
  loading.value = false;
}

async function placeOrder() {
  try {
    const r = await api.placeOrder({
      symbol: store.currentSymbol, direction: orderDir.value,
      stop_loss_pct: orderSl.value, take_profit_pct: orderTp.value, leverage: orderLev.value,
    });
    store.notify(r.message, "success");
    await refresh();
  } catch (e: any) { store.notify(e.message, "error"); }
}

async function closePos(id: number) {
  try { await api.closePosition(id); store.notify("已平仓", "success"); await refresh(); }
  catch (e: any) { store.notify(e.message, "error"); }
}

async function emergencyClose() {
  try { const r = await api.emergencyClose(store.currentSymbol); store.notify(r.message, "success"); await refresh(); }
  catch (e: any) { store.notify(e.message, "error"); }
}

async function confirmSwitch() {
  try { await api.confirmSwitch(store.currentSymbol); store.notify("已切换策略", "success"); await refresh(); }
  catch (e: any) { store.notify(e.message, "error"); }
}
async function rejectSwitch() {
  try { await api.rejectSwitch(store.currentSymbol); pending.value = null; }
  catch (e: any) { store.notify(e.message, "error"); }
}

function stateClass(s: string) {
  if (!s) return "text-white/50";
  if (s.includes("BULL")) return "text-green-400";
  if (s.includes("BEAR")) return "text-red-400";
  return "text-yellow-400";
}

onMounted(async () => {
  try { strategies.value = (await api.listStrategies()).strategies || []; } catch {}
  await refresh();
  timer = setInterval(refresh, 20000);
});
onUnmounted(() => clearInterval(timer));
</script>

<template>
  <div class="space-y-4">
    <!-- Symbol bar -->
    <div class="flex items-center gap-3 flex-wrap">
      <select v-model="store.currentSymbol" class="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm" @change="refresh()">
        <option v-for="s in store.symbols" :key="s" :value="s">{{ s }}</option>
      </select>
      <button class="px-4 py-2 text-xs rounded-lg bg-indigo-500 hover:bg-indigo-600 disabled:opacity-50" :disabled="loading" @click="senseTrend">
        {{ loading ? '感知中...' : 'AI趋势感知' }}
      </button>
      <span class="text-xs text-white/40">活跃策略: <span class="text-blue-400">{{ activeStrategy }}</span></span>
    </div>

    <!-- Strategy switch confirmation -->
    <div v-if="pending" class="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-4 flex items-start gap-3">
      <span class="text-yellow-400">⚠</span>
      <div class="flex-1">
        <p class="text-sm text-yellow-300 font-medium">AI建议切换策略</p>
        <p class="text-xs text-white/50 mt-1">
          市场状态 <span :class="stateClass(pending.market_state)">{{ pending.market_state }}</span>
          · 置信度 {{ Math.round((pending.confidence || 0) * 100) }}%
          · {{ pending.from }} → <span class="text-blue-400">{{ pending.to }}</span>
        </p>
        <p v-if="pending.reasoning" class="text-xs text-white/40 mt-1">{{ pending.reasoning }}</p>
        <div class="flex gap-2 mt-2">
          <button class="px-3 py-1 text-xs rounded bg-indigo-500 hover:bg-indigo-600" @click="confirmSwitch">确认切换</button>
          <button class="px-3 py-1 text-xs rounded border border-white/10 hover:bg-white/5" @click="rejectSwitch">保持当前</button>
        </div>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <!-- AI Trend -->
      <Card title="AI趋势状态">
        <div v-if="trend" class="space-y-1.5 text-sm">
          <div class="flex justify-between"><span class="text-white/50">市场状态</span><span :class="stateClass(trend.market_state)">{{ trend.market_state }}</span></div>
          <div class="flex justify-between"><span class="text-white/50">置信度</span><span>{{ Math.round((trend.confidence || 0) * 100) }}%</span></div>
          <div class="flex justify-between"><span class="text-white/50">推荐策略</span><span class="text-blue-400">{{ trend.recommended_strategy }}</span></div>
          <div class="flex justify-between"><span class="text-white/50">建议杠杆</span><span>{{ trend.suggested_leverage }}x</span></div>
          <div class="flex justify-between"><span class="text-white/50">风险等级</span><span>{{ trend.risk_level }}</span></div>
          <p v-if="trend.reasoning" class="text-xs text-white/40 pt-1 border-t border-white/5 mt-2">{{ trend.reasoning }}</p>
        </div>
        <p v-else class="text-xs text-white/30">点击「AI趋势感知」获取分析</p>
      </Card>

      <!-- Account / Risk -->
      <Card title="账户与风控">
        <div class="space-y-1.5 text-sm">
          <div class="flex justify-between"><span class="text-white/50">权益</span><span>${{ account?.equity ?? '--' }}</span></div>
          <div class="flex justify-between"><span class="text-white/50">已实现盈亏</span>
            <span :class="(account?.realized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'">${{ account?.realized_pnl ?? '--' }}</span>
          </div>
          <div class="flex justify-between"><span class="text-white/50">当日盈亏</span>
            <span :class="(risk?.daily_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'">${{ risk?.daily_pnl ?? '--' }} ({{ risk?.daily_pnl_pct ?? 0 }}%)</span>
          </div>
          <div class="flex justify-between"><span class="text-white/50">交易状态</span>
            <span :class="risk?.trading_blocked ? 'text-red-400' : 'text-green-400'">{{ risk?.trading_blocked ? '已停盘' : '正常' }}</span>
          </div>
          <div class="flex justify-between"><span class="text-white/50">胜率</span><span>{{ account?.win_rate ?? 0 }}%</span></div>
        </div>
      </Card>

      <!-- Manual Order -->
      <Card title="手动下单">
        <div class="space-y-2">
          <div class="flex gap-2">
            <button class="flex-1 py-1.5 text-xs rounded" :class="orderDir === 'LONG' ? 'bg-green-500/20 text-green-400 border border-green-500/30' : 'border border-white/10 text-white/50'" @click="orderDir = 'LONG'">做多</button>
            <button class="flex-1 py-1.5 text-xs rounded" :class="orderDir === 'SHORT' ? 'bg-red-500/20 text-red-400 border border-red-500/30' : 'border border-white/10 text-white/50'" @click="orderDir = 'SHORT'">做空</button>
          </div>
          <div class="grid grid-cols-3 gap-2">
            <label class="text-xs text-white/40">止损%<input v-model.number="orderSl" type="number" step="0.1" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-sm" /></label>
            <label class="text-xs text-white/40">止盈%<input v-model.number="orderTp" type="number" step="0.1" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-sm" /></label>
            <label class="text-xs text-white/40">杠杆<input v-model.number="orderLev" type="number" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-sm" /></label>
          </div>
          <button class="w-full py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-600" @click="placeOrder">提交订单 ({{ store.tradingMode === 'paper' ? '模拟' : store.tradingMode }})</button>
          <button class="w-full py-1.5 text-xs rounded-lg border border-red-500/30 text-red-400 hover:bg-red-500/10" @click="emergencyClose">紧急平仓全部</button>
        </div>
      </Card>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Positions -->
      <Card title="当前持仓">
        <div v-if="positions.length === 0" class="text-xs text-white/30">无持仓</div>
        <table v-else class="w-full text-xs">
          <thead class="text-white/40">
            <tr class="text-left"><th class="py-1">方向</th><th>开仓价</th><th>数量</th><th>浮盈</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="p in positions" :key="p.id" class="border-t border-white/5">
              <td class="py-1.5" :class="p.direction === 'LONG' ? 'text-green-400' : 'text-red-400'">{{ p.direction }}</td>
              <td>{{ p.entry_price?.toFixed?.(2) ?? p.entry_price }}</td>
              <td>{{ p.qty }}</td>
              <td :class="(p.unrealized_pnl_pct ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'">{{ p.unrealized_pnl_pct ?? '--' }}%</td>
              <td><button v-if="p.id" class="text-white/40 hover:text-red-400" @click="closePos(p.id)">平仓</button></td>
            </tr>
          </tbody>
        </table>
      </Card>

      <!-- Kline -->
      <Card title="实时K线 (F/S/L/H)">
        <div class="font-mono text-xs text-white/40 max-h-56 overflow-y-auto space-y-0.5">
          <div v-if="klines.length === 0" class="text-white/20">等待数据... (需配置交易所API)</div>
          <div v-for="(l, i) in klines.slice(-18)" :key="i">{{ l }}</div>
        </div>
      </Card>
    </div>
  </div>
</template>
