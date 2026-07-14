<template>
  <header class="quote-summary">
    <div class="quote-summary__controls">
      <div class="quote-sort" data-quote-panel="sort">
        <button type="button" class="quote-sort__settings" @click.stop="togglePanel('sort')">
          {{ sortRuleCountLabel }}
          <span>&#9662;</span>
        </button>
        <div v-if="showSortPanel" class="quote-sort__panel">
          <label class="quote-switch-row">
            <input type="checkbox" :checked="sortGrouping" @change="setSortGrouping(!sortGrouping)" />
            {{ t('quote.sort.group_by_producer') }}
          </label>
          <div
            v-for="rule in sortRules"
            :key="rule.id"
            class="quote-sort__row"
            @dragover="handleDragOver"
            @drop="handleDrop(rule)"
            @dragend="handleDragEnd"
          >
            <div class="quote-sort__field">
              <span
                class="quote-drag"
                aria-hidden="true"
                draggable="true"
                @dragstart.stop="handleDragStart(rule, $event)"
              >
                <img :src="iconDrag" alt="" />
              </span>
              <select
                class="quote-sort__select"
                :value="rule.field"
                @change="updateSortField(rule, $event.target.value)"
              >
                <option
                  v-for="option in sortFieldOptions"
                  :key="option"
                  :value="option"
                >
                  {{ option }}
                </option>
              </select>
            </div>
            <div class="quote-sort__direction">
              <button
                type="button"
                class="quote-sort__direction-btn"
                @click="toggleDirection(rule)"
              >
                <img :src="iconUpDown" alt="" aria-hidden="true" />
                <span>{{ rule.direction }}</span>
              </button>
              <button
                type="button"
                class="quote-sort__remove"
                :aria-label="t('quote.sort.remove_rule')"
                @click="removeSortRule(rule.id)"
              >
                ×
              </button>
            </div>
          </div>
          <div class="quote-sort__actions">
            <button type="button" class="quote-link" @click="addSortRule">
              + {{ t('quote.sort.add_rule') }}
            </button>
            <button type="button" class="quote-link" @click="resetSortRules">
              {{ t('quote.sort.reset_rules') }}
            </button>
          </div>
        </div>
      </div>

      <label class="result-toggle quote-bundle-toggle">
        <span>{{ t('quote.sort.show_bundle_column') }}</span>
        <input type="checkbox" :checked="showBundleColumn" @change="setBundleColumn(!showBundleColumn)" />
      </label>
    </div>
  </header>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const props = defineProps({
  sortRuleCountLabel: String,
  sortRules: { type: Array, required: true },
  sortFieldOptions: { type: Array, required: true },
  sortGrouping: { type: Boolean, default: false },
  showSortPanel: { type: Boolean, default: false },
  showBundleColumn: { type: Boolean, default: false },
  togglePanel: { type: Function, required: true },
  handleDragStart: { type: Function, required: true },
  handleDragOver: { type: Function, required: true },
  handleDrop: { type: Function, required: true },
  handleDragEnd: { type: Function, required: true },
  updateSortField: { type: Function, required: true },
  toggleDirection: { type: Function, required: true },
  removeSortRule: { type: Function, required: true },
  addSortRule: { type: Function, required: true },
  resetSortRules: { type: Function, required: true },
  setSortGrouping: { type: Function, required: true },
  setBundleColumn: { type: Function, required: true },
  iconDrag: String,
  iconUpDown: String,
})

const {
  togglePanel,
  handleDragStart,
  handleDragOver,
  handleDrop,
  handleDragEnd,
  updateSortField,
  toggleDirection,
  removeSortRule,
  addSortRule,
  resetSortRules,
  setSortGrouping,
  setBundleColumn,
} = props
</script>
