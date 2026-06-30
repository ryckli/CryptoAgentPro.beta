<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useAppStore } from "../stores/dashboard";
import { api } from "../api";
import Card from "../components/Card.vue";

const store = useAppStore();

// API keys
const keys = ref({ exchange_api_key: "", exchange_secret: "", exchange_password: "", exchange_name: "binance", exchange_testnet: true, deepseek_api_key: "" });
const cfg = ref<any>({});

// settings
const settings = ref<any>({});
const watchlistText = ref("");

async function loadAll() {
  try {
    cfg.value = await api.getConfig();
    keys.value.exchange_name = cfg.value.exchange_name;
    keys.value.exchange_testnet = cfg.value.exchange_testnet;
  } catch {}
  try {
    settings.value = await api.getSettings();
    watchlistText.value = (settings.value.watchlist || []).join(", ");
  } catch {}
}

async function saveKeys() {
  try {
    await api.saveConfig(keys.value);
    store.notify("API密钥已保存", "success");
    keys.value.exchange_api_key = "";
    keys.value.exchange_secret = "";
    keys.value.exchange_password = "";
    keys.value.deepseek_api_key = "";
    await loadAll();
    await store.loadBase();
  } catch (e: any) { store.notify(e.message, "error"); }
}

async function saveSettings() {
  try {
    const payload = { ...settings.value };
    payload.watchlist = watchlistText.value.split(",").map((s: string) => s.trim()).filter(Boolean);
    await api.saveSettings(payload);
    store.notify("设置已保存", "success");
    await loadAll();
    await store.loadBase();
  } catch (e: any) { store.notify(e.message, "error"); }
}

async function resetRisk() {
  try { await api.resetRisk(); store.notify("当日风控已重置", "success"); }
  catch (e: any) { store.notify(e.message, "error"); }
}

onMounted(loadAll);
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
    <!-- API Keys -->
    <Card title="API 密钥">
      <div class="space-y-3">
        <div class="grid grid-cols-2 gap-3">
          <label class="text-xs text-white/40">交易所
            <select v-model="keys.exchange_name" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm">
              <option value="binance">Binance</option><option value="okx">OKX</option><option value="bybit">Bybit</option>
            </select>
          </label>
          <label class="flex items-end gap-2 text-xs text-white/40 pb-2">
            <input v-model="keys.exchange_testnet" type="checkbox" /> 使用测试网
          </label>
        </div>
        <label class="block text-xs text-white/40">API Key {{ cfg.has_exchange_key ? '(已配置)' : '' }}
          <input v-model="keys.exchange_api_key" type="password" placeholder="留空则不修改" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
        </label>
        <label class="block text-xs text-white/40">Secret Key
          <input v-model="keys.exchange_secret" type="password" placeholder="留空则不修改" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
        </label>
        <label class="block text-xs text-white/40">交易所密码 (Passphrase) {{ cfg.has_exchange_password ? '(已配置)' : '' }} <span class="text-white/25">OKX等交易所需要</span>
          <input v-model="keys.exchange_password" type="password" placeholder="留空则不修改" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
        </label>
        <label class="block text-xs text-white/40">DeepSeek API Key {{ cfg.has_deepseek_key ? '(已配置)' : '' }}
          <input v-model="keys.deepseek_api_key" type="password" placeholder="留空则不修改" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
        </label>
        <button class="px-5 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-600" @click="saveKeys">保存密钥</button>
      </div>
    </Card>

    <!-- Trading Mode -->
    <Card title="交易模式">
      <div class="space-y-3">
        <div class="grid grid-cols-3 gap-2">
          <button v-for="m in ['paper', 'testnet']" :key="m"
            class="py-2 text-xs rounded-lg border transition-colors"
            :class="settings.trading_mode === m ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300' : 'border-white/10 text-white/40 hover:bg-white/5'"
            @click="settings.trading_mode = m">
            {{ m === 'paper' ? '模拟盘' : '测试网' }}
          </button>
        </div>
        <p class="text-xs text-white/40">
          <span v-if="settings.trading_mode === 'paper'">模拟盘: 本地撮合, 不接触交易所, 最安全。</span>
          <span v-else-if="settings.trading_mode === 'testnet'">测试网: 交易所沙盒环境, 用测试资金真实下单。</span>
          <span v-else>测试网: 交易所沙盒环境, 用测试资金下单, 无真实资金风险。</span>
        </p>
        <label class="flex items-center gap-2 text-sm cursor-pointer">
          <input v-model="settings.auto_trade" type="checkbox" />
          <span>AI自动交易 <span class="text-xs text-white/40">(关闭则仅生成建议, 需人工确认)</span></span>
        </label>
        <button class="px-5 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-600" @click="saveSettings">保存交易设置</button>
      </div>
    </Card>

    <!-- Risk Params -->
    <Card title="风控参数">
      <div class="space-y-3">
        <div class="grid grid-cols-2 gap-3">
          <label class="text-xs text-white/40">初始本金($)
            <input v-model.number="settings.risk_initial_capital" type="number" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
          </label>
          <label class="text-xs text-white/40">最大杠杆
            <input v-model.number="settings.risk_max_leverage" type="number" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
          </label>
          <label class="text-xs text-white/40">单笔最大亏损%
            <input v-model.number="settings.risk_max_loss_per_trade_pct" type="number" step="0.1" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
          </label>
          <label class="text-xs text-white/40">当日最大亏损%
            <input v-model.number="settings.risk_max_daily_loss_pct" type="number" step="0.1" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
          </label>
          <label class="text-xs text-white/40">最小止损距离%
            <input v-model.number="settings.risk_min_stop_distance_pct" type="number" step="0.1" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
          </label>
        </div>
        <label class="flex items-center gap-2 text-sm cursor-pointer">
          <input v-model="settings.strategy_switch_confirmation" type="checkbox" /> 策略切换需人工确认
        </label>
        <div class="flex gap-2">
          <button class="px-5 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-600" @click="saveSettings">保存风控</button>
          <button class="px-5 py-2 text-sm rounded-lg border border-white/10 hover:bg-white/5" @click="resetRisk">重置当日风控</button>
        </div>
      </div>
    </Card>

    <!-- Watchlist + AI -->
    <Card title="监控币种 & AI">
      <div class="space-y-3">
        <label class="block text-xs text-white/40">监控币种 (逗号分隔)
          <input v-model="watchlistText" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" placeholder="BTC/USDT, ETH/USDT, SOL/USDT" />
        </label>
        <div class="grid grid-cols-2 gap-3">
          <label class="text-xs text-white/40">AI模型
            <input v-model="settings.ai_model" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
          </label>
          <label class="text-xs text-white/40">AI温度
            <input v-model.number="settings.ai_temperature" type="number" step="0.1" min="0" max="1" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
          </label>
          <label class="text-xs text-white/40">感知间隔(分钟)
            <input v-model.number="settings.ai_schedule_minutes" type="number" min="1" class="w-full mt-1 bg-white/5 border border-white/10 rounded px-3 py-2 text-sm" />
          </label>
          <label class="flex items-end gap-2 text-xs text-white/40 pb-2">
            <input v-model="settings.ai_schedule_enabled" type="checkbox" /> 启用定时感知
          </label>
        </div>
        <button class="px-5 py-2 text-sm rounded-lg bg-indigo-500 hover:bg-indigo-600" @click="saveSettings">保存</button>
      </div>
    </Card>
  </div>
</template>
