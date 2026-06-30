import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "../api";

export const useAppStore = defineStore("app", () => {
  const symbols = ref<string[]>(["BTC/USDT", "ETH/USDT", "SOL/USDT"]);
  const currentSymbol = ref("BTC/USDT");
  const tradingMode = ref("paper");
  const hasExchangeKey = ref(false);
  const hasDeepseekKey = ref(false);
  const toast = ref<{ msg: string; type: string } | null>(null);

  async function loadBase() {
    try {
      const cfg = await api.getConfig();
      tradingMode.value = cfg.trading_mode;
      hasExchangeKey.value = cfg.has_exchange_key;
      hasDeepseekKey.value = cfg.has_deepseek_key;
    } catch {}
    try {
      const s = await api.getSettings();
      if (s.watchlist?.length) symbols.value = s.watchlist;
    } catch {}
  }

  function notify(msg: string, type = "info") {
    toast.value = { msg, type };
    setTimeout(() => (toast.value = null), 3000);
  }

  return { symbols, currentSymbol, tradingMode, hasExchangeKey, hasDeepseekKey, toast, loadBase, notify };
});
