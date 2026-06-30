<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useAppStore } from "../stores/dashboard";
import { api } from "../api";
import Card from "../components/Card.vue";

const store = useAppStore();
const reports = ref<any[]>([]);
const schedule = ref<any>({ enabled: true, interval_minutes: 15, running: false, next_run: null });
const filterSymbol = ref("");
const sensing = ref(false);

async function loadReports() {
  try { reports.value = (await api.getReports(filterSymbol.value, 50)).reports || []; } catch {}
}
async function loadSchedule() {
  try { schedule.value = await api.getSchedule(); } catch {}
}
async function senseNow() {
  sensing.value = true;
  try { await api.senseNow(); store.notify("已对全部币种执行感知", "success"); await loadReports(); }
  catch (e: any) { store.notify(e.message, "error"); }
  sensing.value = false;
}
async function toggleSchedule() {
  try {
    const r = await api.setSchedule(!schedule.value.enabled, schedule.value.interval_minutes);
    schedule.value = r;
    store.notify("调度已更新", "success");
  } catch (e: any) { store.notify(e.message, "error"); }
}
async function updateInterval() {
  try {
    const r = await api.setSchedule(schedule.value.enabled, schedule.value.interval_minutes);
    schedule.value = r;
    store.notify(`间隔已设为 ${r.interval_minutes} 分钟`, "success");
  } catch (e: any) { store.notify(e.message, "error"); }
}

function stateClass(s: string) {
  if (!s) return "text-white/50";
  if (s.includes("BULL")) return "text-green-400";
  if (s.includes("BEAR")) return "text-red-400";
  return "text-yellow-400";
}
function fmtTime(ts: number) { return new Date(ts * 1000).toLocaleString(); }

onMounted(() => { loadReports(); loadSchedule(); });
</script>

<template>
  <div class="space-y-4">
    <!-- Schedule control -->
    <Card title="15分钟自动趋势感知调度">
      <div class="flex items-center gap-6 flex-wrap">
        <label class="flex items-center gap-2 text-sm cursor-pointer">
          <input type="checkbox" :checked="schedule.enabled" @change="toggleSchedule" />
          <span :class="schedule.enabled ? 'text-green-400' : 'text-white/40'">{{ schedule.enabled ? '已启用' : '已停用' }}</span>
        </label>
        <label class="flex items-center gap-2 text-sm">
          <span class="text-white/50">间隔(分钟)</span>
          <input v-model.number="schedule.interval_minutes" type="number" min="1" class="w-16 bg-white/5 border border-white/10 rounded px-2 py-1" @change="updateInterval" />
        </label>
        <span class="text-xs text-white/40">下次运行: {{ schedule.next_run ? new Date(schedule.next_run).toLocaleString() : '--' }}</span>
        <button class="px-4 py-1.5 text-xs rounded-lg bg-indigo-500 hover:bg-indigo-600 disabled:opacity-50" :disabled="sensing" @click="senseNow">
          {{ sensing ? '感知中...' : '立即感知全部' }}
        </button>
      </div>
      <p v-if="!store.hasDeepseekKey" class="text-xs text-yellow-400 mt-2">⚠ 未配置 DeepSeek API Key，AI 将返回默认状态。请到「设置」配置。</p>
    </Card>

    <!-- Reports -->
    <Card title="AI报告历史">
      <template #actions>
        <select v-model="filterSymbol" class="bg-white/5 border border-white/10 rounded px-2 py-1 text-xs" @change="loadReports">
          <option value="">全部币种</option>
          <option v-for="s in store.symbols" :key="s" :value="s">{{ s }}</option>
        </select>
      </template>
      <div v-if="reports.length === 0" class="text-xs text-white/30 py-4">暂无报告。点击「立即感知全部」生成。</div>
      <div v-else class="space-y-2 max-h-[60vh] overflow-y-auto">
        <div v-for="r in reports" :key="r.id" class="bg-white/[0.02] border border-white/5 rounded-lg p-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-3">
              <span class="text-sm font-medium">{{ r.symbol }}</span>
              <span :class="stateClass(r.market_state)" class="text-sm">{{ r.market_state }}</span>
              <span class="text-xs text-white/40">置信 {{ Math.round((r.confidence || 0) * 100) }}%</span>
              <span class="text-xs text-blue-400">{{ r.recommended_strategy }} · {{ r.suggested_leverage }}x</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-xs px-2 py-0.5 rounded-full"
                :class="r.action === 'auto_traded' ? 'bg-purple-500/20 text-purple-300' : r.action === 'pending' ? 'bg-yellow-500/20 text-yellow-300' : 'bg-white/5 text-white/40'">{{ r.action }}</span>
              <span class="text-xs text-white/30">{{ fmtTime(r.created_at) }}</span>
            </div>
          </div>
          <p v-if="r.reasoning" class="text-xs text-white/50 mt-1.5">{{ r.reasoning }}</p>
          <div v-if="r.key_levels && (r.key_levels.support || r.key_levels.resistance)" class="text-xs text-white/40 mt-1">
            支撑 {{ r.key_levels.support }} · 阻力 {{ r.key_levels.resistance }}
          </div>
        </div>
      </div>
    </Card>
  </div>
</template>
