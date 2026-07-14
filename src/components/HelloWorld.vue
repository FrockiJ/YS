<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

defineProps({
  msg: String,
})

const { t } = useI18n()
const count = ref(0)
</script>

<template>
  <h1>{{ msg }}</h1>

  <div class="card">
    <button type="button" @click="count++">
      {{ t('hello_world.count_label', { count }) }}
    </button>
    <p>
      {{ t('hello_world.card.edit_prefix') }}
      <code>{{ t('hello_world.card.edit_path') }}</code>
      {{ t('hello_world.card.edit_suffix') }}
    </p>
  </div>

  <p>
    {{ t('hello_world.links.check_out_prefix') }}
    <a href="https://vuejs.org/guide/quick-start.html#local" target="_blank">
      {{ t('hello_world.links.check_out_link') }}
    </a>,
    {{ t('hello_world.links.check_out_suffix') }}
  </p>
  <p>
    {{ t('hello_world.links.learn_more_prefix') }}
    <a
      href="https://vuejs.org/guide/scaling-up/tooling.html#ide-support"
      target="_blank"
    >
      {{ t('hello_world.links.learn_more_link') }}
    </a>
    {{ t('hello_world.links.learn_more_suffix') }}
  </p>
  <p class="read-the-docs">{{ t('hello_world.docs_hint') }}</p>
</template>

<style scoped>
.read-the-docs {
  color: #888;
}
</style>
