<script setup lang="ts">
defineProps<{ title?: string }>();
</script>

<template>
  <div class="bg-white/[0.03] border border-white/10 rounded-xl p-4">
    <div v-if="title || $slots.actions" class="flex items-center justify-between mb-3">
      <h3 class="text-xs font-medium text-white/60">{{ title }}</h3>
      <slot name="actions" />
    </div>
    <slot />
  </div>
</template>
