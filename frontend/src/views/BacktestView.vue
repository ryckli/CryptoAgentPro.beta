<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { useAppStore } from "../stores/dashboard";
import { api } from "../api";
import Card from "../components/Card.vue";

const store = useAppStore();
const strategies = ref<any[]>([]);

const form = ref({
  symbol: "BTC/USDT",
  strategy_id: "S1",
  timeframe: "15m",
  start_date: "2024-06-01",
  end_date: "2024-12-31",
  initial_capital: 10000,
  leverage: 10,
  speed: 10,
});
const speeds = [1, 2, 5, 10, 20, 100];
const timeframes = ["15m", "1h", "4h", "1d"];

const running = ref(false);
const progress = ref(0);
const equity = ref(0);
const result = ref<any>(null);
let pollTimer: any = null;
let taskId = "";

// Monte Carlo
const useMonteCarlo = ref(false);
const mcRuns = ref(50);
const mcNoise = ref(0.001);
const mcSkip = ref(0.05);

async function run() {
  running.value = true;
  progress.value = 0;
  equity.value = 0;
  result.value = null;
  if (useMonteCarlo.value) {
    try {
      const d = await api.post("/backtest/monte-carlo", {
        strategy_id: form.value.strategy_id, symbol: form.value.symbol,
        timeframe: form.value.timeframe, start_date: form.value.start_date,
        end_date: form.value.end_date, initial_capital: form.value.initial_capital,
        leverage: form.value.leverage, n_runs: mcRuns.value,
        noise: mcNoise.value, skip_prob: mcSkip.value,
      });
      result.value = d.summary;
      running.value = false;
      store.notify("蒙特卡洛回测完成", "success");
    } catch (e: any) { running.value = false; store.notify(e.message, "error"); }
    return;
  }
  try {
    const d = await api.runBacktest(form.value);
    taskId = d.task_id;
    pollTimer = setInterval(pollProgress, 500);
  } catch (e: any) {
    running.value = false;
    store.notify(e.message, "error");
  }
}

async function pollProgress() {
  try {
    const m = await api.get(`/backtest/${taskId}/progress`);
    progress.value = m.progress_pct || 0;
    equity.value = m.current_equity || equity.value;
    if (m.status === "completed") {
      result.value = m.result;
      finish();
      store.notify("回测完成", "success");
    } else if (m.status === "cancelled") {
      finish();
    } else if (m.status === "error") {
      finish();
      store.notify("回测错误: " + (m.error || ""), "error");
    }
  } catch (e: any) {
    finish();
    store.notify("回测查询失败", "error");
  }
}

function finish() {
  running.value = false;
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function cancel() {
  try { await api.cancelBacktest(taskId); } catch {}
  finish();
}

onMounted(async () => {
  try { strategies.value = (await api.listStrategies()).strategies || []; } catch {}
});
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer); });
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
    <!-- Config -->
    <Card title="回测配置" class="lg:col-span-1">
      <div class="space-y-3">
        <label class="block text-xs text-white/40">币种
          <select v-model="form.symbol" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm">
            <option v-for="s in store.symbols" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <label class="block text-xs text-white/40">策略
          <select v-model="form.strategy_id" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm">
            <option v-for="s in strategies" :key="s.id" :value="s.id">{{ s.id }} - {{ s.name }}</option>
          </select>
        </label>
        <label class="block text-xs text-white/40">K线周期
          <div class="flex gap-1 mt-1">
            <button v-for="tf in timeframes" :key="tf" type="button"
              class="flex-1 py-1.5 text-xs rounded border transition-colors"
              :class="form.timeframe === tf ? 'bg-indigo-500 border-indigo-500' : 'border-white/10 text-white/40 hover:bg-white/5'"
              @click="form.timeframe = tf">{{ tf }}</button>
          </div>
        </label>
        <div class="grid grid-cols-2 gap-2">
          <label class="block text-xs text-white/40">起始<input v-model="form.start_date" type="date" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-2 py-1.5 text-sm" /></label>
          <label class="block text-xs text-white/40">结束<input v-model="form.end_date" type="date" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-2 py-1.5 text-sm" /></label>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <label class="block text-xs text-white/40">初始资金<input v-model.number="form.initial_capital" type="number" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-2 py-1.5 text-sm" /></label>
          <label class="block text-xs text-white/40">杠杆<input v-model.number="form.leverage" type="number" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-2 py-1.5 text-sm" /></label>
        </div>
        <div>
          <p class="text-xs text-white/40 mb-1">倍速 {{ useMonteCarlo ? '(蒙特卡洛模式下忽略)' : '' }}</p>
          <div class="flex gap-1">
            <button v-for="s in speeds" :key="s" class="flex-1 py-1.5 text-xs rounded border transition-colors"
              :class="form.speed === s ? 'bg-indigo-500 border-indigo-500' : 'border-white/10 text-white/40 hover:bg-white/5'"
              @click="form.speed = s">{{ s }}x</button>
          </div>
        </div>
        <!-- Monte Carlo -->
        <label class="flex items-center gap-2 text-xs cursor-pointer">
          <input v-model="useMonteCarlo" type="checkbox" />
          <span class="text-yellow-400">蒙特卡洛模拟</span>
          <span class="text-white/30">(N次随机扰动回测)</span>
        </label>
        <div v-if="useMonteCarlo" class="grid grid-cols-3 gap-2">
          <label class="text-xs text-white/40">次数<input v-model.number="mcRuns" type="number" min="10" max="200" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-sm" /></label>
          <label class="text-xs text-white/40">噪声<input v-model.number="mcNoise" type="number" step="0.001" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-sm" /></label>
          <label class="text-xs text-white/40">跳过%<input v-model.number="mcSkip" type="number" step="0.01" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-sm" /></label>
        </div>
        <div class="flex gap-2">
          <button class="flex-1 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-600 disabled:opacity-50" :disabled="running" @click="run">
            {{ running ? '回测中...' : '开始回测' }}
          </button>
          <button v-if="running" class="px-4 py-2 text-sm rounded-lg border border-red-500/30 text-red-400 hover:bg-red-500/10" @click="cancel">取消</button>
        </div>
        <div v-if="running || progress > 0" class="space-y-1.5">
          <div class="flex justify-between text-xs text-white/40"><span>进度</span><span>{{ progress.toFixed(1) }}% · ${{ equity.toFixed(0) }}</span></div>
          <div class="w-full bg-white/10 rounded-full h-1.5 overflow-hidden"><div class="bg-indigo-500 h-full transition-all" :style="{ width: progress + '%' }" /></div>
        </div>
      </div>
    </Card>

    <!-- Results -->
    <Card title="回测结果" class="lg:col-span-2">
      <div v-if="!result" class="text-xs text-white/30 py-8 text-center">运行回测以查看结果</div>
      <!-- MC 结果 -->
      <div v-else-if="useMonteCarlo && result.returns" class="space-y-4">
        <div class="grid grid-cols-4 gap-3">
          <div class="bg-white/[0.02] rounded-lg p-3 text-center"><div class="text-[10px] text-white/30">均值收益</div><div class="text-lg font-semibold" :class="result.returns.mean>=0?'text-green-400':'text-red-400'">{{ result.returns.mean }}%</div></div>
          <div class="bg-white/[0.02] rounded-lg p-3 text-center"><div class="text-[10px] text-white/30">盈利概率</div><div class="text-lg font-semibold">{{ result.returns.prob_profit }}%</div></div>
          <div class="bg-white/[0.02] rounded-lg p-3 text-center"><div class="text-[10px] text-white/30">VaR 95%</div><div class="text-lg font-semibold text-red-400">{{ result.var_cvar.var_95 }}%</div></div>
          <div class="bg-white/[0.02] rounded-lg p-3 text-center"><div class="text-[10px] text-white/30">CVaR 95%</div><div class="text-lg font-semibold text-red-400">{{ result.var_cvar.cvar_95 }}%</div></div>
        </div>
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div class="flex justify-between"><span class="text-white/40">95% CI</span><span>[{{ result.returns.ci_95[0] }}%, {{ result.returns.ci_95[1] }}%]</span></div>
          <div class="flex justify-between"><span class="text-white/40">中位数</span><span>{{ result.returns.median }}%</span></div>
          <div class="flex justify-between"><span class="text-white/40">Sharpe均值</span><span>{{ result.sharpe.mean }}</span></div>
          <div class="flex justify-between"><span class="text-white/40">胜率CI</span><span>[{{ result.win_rate.ci_95[0] }}%, {{ result.win_rate.ci_95[1] }}%]</span></div>
        </div>
        <div class="text-xs text-white/30">N={{ result.n_runs }} 耗时{{ result.elapsed_seconds }}s</div>
      </div>
      <!-- 普通回测结果 -->
      <div v-else class="space-y-4">
        <div class="grid grid-cols-4 gap-3">
          <div class="bg-white/[0.02] rounded-lg p-3 text-center">
            <div class="text-[10px] text-white/30">总收益</div>
            <div class="text-lg font-semibold" :class="parseFloat(result.total_return) >= 0 ? 'text-green-400' : 'text-red-400'">{{ result.total_return }}</div>
          </div>
          <div class="bg-white/[0.02] rounded-lg p-3 text-center">
            <div class="text-[10px] text-white/30">胜率</div>
            <div class="text-lg font-semibold">{{ result.win_rate }}</div>
          </div>
          <div class="bg-white/[0.02] rounded-lg p-3 text-center">
            <div class="text-[10px] text-white/30">交易数</div>
            <div class="text-lg font-semibold">{{ result.total_trades }}</div>
          </div>
          <div class="bg-white/[0.02] rounded-lg p-3 text-center">
            <div class="text-[10px] text-white/30">最大回撤</div>
            <div class="text-lg font-semibold text-red-400">{{ result.max_drawdown }}</div>
          </div>
        </div>
        <div class="grid grid-cols-3 gap-3 text-sm">
          <div class="flex justify-between"><span class="text-white/40">盈亏比</span><span>{{ result.profit_factor }}</span></div>
          <div class="flex justify-between"><span class="text-white/40">平均盈利</span><span class="text-green-400">{{ result.avg_win }}</span></div>
          <div class="flex justify-between"><span class="text-white/40">平均亏损</span><span class="text-red-400">{{ result.avg_loss }}</span></div>
        </div>
        <!-- equity curve (simple sparkline) -->
        <div v-if="result.equity_curve?.length" class="h-24 flex items-end gap-px">
          <div v-for="(e, i) in result.equity_curve" :key="i"
            class="flex-1 bg-indigo-500/40 rounded-t"
            :style="{ height: (((e - Math.min(...result.equity_curve)) / (Math.max(...result.equity_curve) - Math.min(...result.equity_curve) + 1)) * 100) + '%' }" />
        </div>
        <!-- trade log -->
        <div v-if="result.trade_log?.length" class="max-h-48 overflow-y-auto">
          <table class="w-full text-xs">
            <thead class="text-white/40 sticky top-0 bg-[#0f0f0f]"><tr class="text-left"><th class="py-1">方向</th><th>开仓</th><th>平仓</th><th>盈亏%</th><th>原因</th></tr></thead>
            <tbody>
              <tr v-for="(t, i) in result.trade_log.slice(-50)" :key="i" class="border-t border-white/5">
                <td class="py-1" :class="t.direction === 'LONG' ? 'text-green-400' : 'text-red-400'">{{ t.direction }}</td>
                <td>{{ t.entry_price }}</td>
                <td>{{ t.exit_price }}</td>
                <td :class="t.pnl_pct >= 0 ? 'text-green-400' : 'text-red-400'">{{ t.pnl_pct }}%</td>
                <td class="text-white/40">{{ t.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  </div>
</template>
