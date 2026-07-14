<template>
  <div
    class="quote-sort file-resource-sort-control"
    data-file-resource-panel="sort"
    @pointerdown.stop
  >
    <button
      ref="buttonRef"
      type="button"
      class="quote-sort__settings file-resource-sort-control__trigger"
      @click.stop="togglePanel"
    >
      <span>{{ summaryLabel }}</span>
      <span class="file-resource-sort-control__caret" :class="{ 'is-open': showPanel }">&#9662;</span>
    </button>

    <div v-if="showPanel" ref="panelRef" class="quote-sort__panel file-resource-sort-control__panel">
      <label class="quote-switch-row file-resource-sort-control__switch">
        <input type="checkbox" :checked="sortGrouping" @change="toggleGrouping" />
        {{ groupingLabel }}
      </label>

      <div
        v-for="rule in sortRules"
        :key="rule.id"
        class="quote-sort__row file-resource-sort-control__row"
        @dragover="handleDragOver"
        @drop="handleDrop(rule)"
        @dragend="handleDragEnd"
      >
        <div class="quote-sort__field file-resource-sort-control__field">
          <span
            class="quote-drag file-resource-sort-control__drag"
            aria-hidden="true"
            draggable="true"
            @dragstart.stop="handleDragStart(rule, $event)"
          >
            <img :src="iconDrag" alt="" />
          </span>

          <select
            class="quote-sort__select file-resource-sort-control__select"
            :value="rule.field"
            @change="updateSortField(rule, $event.target.value)"
          >
            <option v-for="option in sortFieldOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </div>

        <div class="quote-sort__direction file-resource-sort-control__direction">
          <button
            type="button"
            class="quote-sort__direction-btn file-resource-sort-control__direction-btn"
            @click="toggleDirection(rule)"
          >
            <img :src="iconUpDown" alt="" aria-hidden="true" />
            <span>{{ resolveDirectionLabel(rule.field, rule.direction) }}</span>
          </button>

          <button
            type="button"
            class="quote-sort__remove file-resource-sort-control__remove"
            :aria-label="removeRuleLabel"
            @click="removeSortRule(rule.id)"
          >
            &times;
          </button>
        </div>
      </div>

      <div class="quote-sort__actions file-resource-sort-control__actions">
        <button type="button" class="quote-link" @click="addSortRule">+ {{ addRuleLabel }}</button>
        <button type="button" class="quote-link" @click="resetSortRules">{{ resetRulesLabel }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  summaryLabel: { type: String, required: true },
  showPanel: { type: Boolean, default: false },
  sortRules: { type: Array, required: true },
  sortFieldOptions: { type: Array, required: true },
  sortGrouping: { type: Boolean, default: false },
  groupingLabel: { type: String, required: true },
  togglePanel: { type: Function, required: true },
  toggleGrouping: { type: Function, required: true },
  handleDragStart: { type: Function, required: true },
  handleDragOver: { type: Function, required: true },
  handleDrop: { type: Function, required: true },
  handleDragEnd: { type: Function, required: true },
  updateSortField: { type: Function, required: true },
  toggleDirection: { type: Function, required: true },
  removeSortRule: { type: Function, required: true },
  addSortRule: { type: Function, required: true },
  resetSortRules: { type: Function, required: true },
  resolveDirectionLabel: { type: Function, required: true },
  iconDrag: { type: String, required: true },
  iconUpDown: { type: String, required: true },
  addRuleLabel: { type: String, required: true },
  resetRulesLabel: { type: String, required: true },
  removeRuleLabel: { type: String, required: true },
})

const buttonRef = ref(null)
const panelRef = ref(null)

defineExpose({
  buttonRef,
  panelRef,
})
</script>
