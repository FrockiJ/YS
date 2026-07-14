<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, Link2, Paperclip, SendHorizontal, UploadCloud } from 'lucide-vue-next'

const { t } = useI18n()

const props = defineProps({
  modelValue: {
    type: String,
    default: '',
  },
  placeholder: {
    type: String,
    default: '',
  },
  outputTypes: {
    type: Array,
    default: () => [],
  },
  selectedOutputType: {
    type: String,
    default: '',
  },
  outputPlaceholder: {
    type: String,
    default: '',
  },
  attachments: {
    type: Array,
    default: () => [],
  },
  uploadWarning: {
    type: String,
    default: '',
  },
  showAttachments: {
    type: Boolean,
    default: true,
  },
  sendIconSrc: {
    type: String,
    default: '',
  },
  inputRows: {
    type: Number,
    default: 1,
  },
  uploadAriaLabel: {
    type: String,
    default: '',
  },
  sendAriaLabel: {
    type: String,
    default: '',
  },
  twoRowLayout: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits([
  'update:modelValue',
  'submit',
  'selectOutputType',
  'uploadClick',
  'removeAttachment',
  'addUrls',
])

const localeText = (key) => {
  const resolved = t(key)
  return resolved === key ? '' : resolved
}

const internalValue = ref(props.modelValue || '')
const isOutputDropdownOpen = ref(false)
const isOutputDropdownOpenUpward = ref(false)
const isSourceMenuOpen = ref(false)
const isInputComposing = ref(false)
const urlDraft = ref('')
const textareaRef = ref(null)
const outputDropdownRef = ref(null)
const outputDropdownMenuRef = ref(null)
const sourceMenuRef = ref(null)
const urlInputRef = ref(null)
const DROPDOWN_VIEWPORT_GAP = 12

const resolvedUploadAriaLabel = computed(
  () => props.uploadAriaLabel || localeText('chat_composer.aria.upload')
)
const resolvedSendAriaLabel = computed(
  () => props.sendAriaLabel || localeText('chat_composer.aria.send')
)
const resolvedOutputPlaceholder = computed(
  () => props.outputPlaceholder || localeText('chat_composer.output_placeholder')
)
const addFileLabel = computed(() => localeText('chat_composer.actions.add_file'))
const addUrlLabel = computed(() => localeText('chat_composer.actions.add_url'))
const urlPopoverTitle = computed(() => localeText('chat_composer.url.title'))
const urlPopoverHint = computed(() => localeText('chat_composer.url.hint'))
const urlPopoverPlaceholder = computed(
  () => localeText('chat_composer.url.placeholder')
)
const urlSubmitLabel = computed(() => localeText('chat_composer.url.submit'))
const urlCancelLabel = computed(() => localeText('chat_composer.url.cancel'))
const previewImageLabel = computed(() => localeText('chat_composer.preview_image'))
const removeAttachmentLabel = computed(
  () => localeText('chat_composer.aria.remove_attachment')
)
const canSubmit = computed(() => internalValue.value.trim().length > 0)

const resizeTextarea = () => {
  const textareaEl = textareaRef.value
  if (!textareaEl) return
  textareaEl.style.height = 'auto'
  textareaEl.style.height = `${textareaEl.scrollHeight}px`
}

watch(
  () => props.modelValue,
  (value) => {
    internalValue.value = value || ''
  }
)

watch(internalValue, (value) => {
  emit('update:modelValue', value)
  nextTick(() => {
    resizeTextarea()
  })
})

const handleSubmit = () => {
  if (!canSubmit.value) return
  emit('submit')
}

const isImeCompositionEvent = (event) =>
  Boolean(
    isInputComposing.value ||
      event?.isComposing ||
      event?.keyCode === 229 ||
      event?.which === 229
  )

const handleCompositionStart = () => {
  isInputComposing.value = true
}

const handleCompositionEnd = () => {
  isInputComposing.value = false
}

const handleTextareaKeydown = (event) => {
  if (event.key !== 'Enter') return
  if (isImeCompositionEvent(event)) return
  if (event.shiftKey) return

  event.preventDefault()
  if (!canSubmit.value) return
  handleSubmit()
}

const handleSelectOutputType = (type) => {
  emit('selectOutputType', type)
  isOutputDropdownOpen.value = false
}

const updateDropdownDirection = () => {
  if (typeof window === 'undefined') return
  const dropdownEl = outputDropdownRef.value
  const menuEl = outputDropdownMenuRef.value
  if (!dropdownEl || !menuEl) {
    isOutputDropdownOpenUpward.value = false
    return
  }

  const dropdownRect = dropdownEl.getBoundingClientRect()
  const menuRect = menuEl.getBoundingClientRect()
  const spaceAbove = dropdownRect.top
  const spaceBelow = window.innerHeight - dropdownRect.bottom

  isOutputDropdownOpenUpward.value =
    spaceBelow < menuRect.height + DROPDOWN_VIEWPORT_GAP && spaceAbove > spaceBelow
}

const toggleOutputDropdown = () => {
  isOutputDropdownOpen.value = !isOutputDropdownOpen.value
  if (isOutputDropdownOpen.value) {
    isSourceMenuOpen.value = false
  }
}

const closeOutputDropdown = () => {
  isOutputDropdownOpen.value = false
}

const toggleSourceMenu = async () => {
  isSourceMenuOpen.value = !isSourceMenuOpen.value
  if (isSourceMenuOpen.value) {
    closeOutputDropdown()
    await nextTick()
    urlInputRef.value?.focus()
  }
}

const closeSourceMenu = () => {
  isSourceMenuOpen.value = false
  urlDraft.value = ''
}

const handleUploadClick = () => {
  closeSourceMenu()
  emit('uploadClick')
}

const handleAddUrls = () => {
  const value = String(urlDraft.value || '').trim()
  if (!value) return
  emit('addUrls', value)
  urlDraft.value = ''
  closeSourceMenu()
}

const handleRemoveAttachment = (id) => {
  emit('removeAttachment', id)
}

const handleViewportChange = () => {
  resizeTextarea()
  if (!isOutputDropdownOpen.value) return
  updateDropdownDirection()
}

const handleDocumentPointerDown = (event) => {
  const target = event?.target
  if (
    isOutputDropdownOpen.value &&
    outputDropdownRef.value &&
    !outputDropdownRef.value.contains(target)
  ) {
    closeOutputDropdown()
  }
  if (
    isSourceMenuOpen.value &&
    sourceMenuRef.value &&
    !sourceMenuRef.value.contains(target)
  ) {
    closeSourceMenu()
  }
}

watch(isOutputDropdownOpen, async (open) => {
  if (!open) {
    isOutputDropdownOpenUpward.value = false
    return
  }
  await nextTick()
  updateDropdownDirection()
})

onMounted(() => {
  nextTick(() => {
    resizeTextarea()
  })
  if (typeof window === 'undefined') return
  window.addEventListener('resize', handleViewportChange)
  window.addEventListener('scroll', handleViewportChange, true)
  window.addEventListener('pointerdown', handleDocumentPointerDown)
})

onBeforeUnmount(() => {
  isInputComposing.value = false
  if (typeof window === 'undefined') return
  window.removeEventListener('resize', handleViewportChange)
  window.removeEventListener('scroll', handleViewportChange, true)
  window.removeEventListener('pointerdown', handleDocumentPointerDown)
})
</script>

<template>
  <div
    class="chat-composer"
    :class="{
      'is-two-row': twoRowLayout,
      'has-attachments': showAttachments && attachments.length > 0,
    }"
  >
    <div
      v-if="showAttachments && attachments.length"
      class="chat-composer__preview-grid"
    >
      <div
        v-for="attachment in attachments"
        :key="attachment.id"
        class="chat-composer__preview-card"
        :title="attachment.tooltip || attachment.url || attachment.filename || attachment.label"
      >
        <div class="chat-composer__preview-thumb" :class="{ 'is-url': attachment.type === 'url' }">
          <img
            v-if="attachment.type !== 'url' && attachment.previewUrl"
            :src="attachment.previewUrl"
            :alt="attachment.label"
          />
          <span v-else class="chat-composer__preview-placeholder">
            {{ attachment.type === 'url' ? 'URL' : (attachment.extension ? attachment.extension.toUpperCase() : previewImageLabel) }}
          </span>
          <button
            type="button"
            class="chat-composer__preview-remove"
            :aria-label="removeAttachmentLabel"
            @click="handleRemoveAttachment(attachment.id)"
          >
            x
          </button>
        </div>
        <p class="chat-composer__preview-label">{{ attachment.filename || attachment.label }}</p>
      </div>
    </div>

    <div
      v-if="uploadWarning"
      class="chat-composer__upload-hint"
    >
      <p>{{ uploadWarning }}</p>
    </div>

    <div class="chat-composer__row top-row">
      <div class="chat-composer__field">
        <textarea
          ref="textareaRef"
          v-model="internalValue"
          :rows="inputRows"
          :placeholder="placeholder"
          @focus="closeOutputDropdown"
          @input="resizeTextarea"
          @keydown="handleTextareaKeydown"
          @compositionstart="handleCompositionStart"
          @compositionend="handleCompositionEnd"
        />
      </div>
    </div>

    <div class="chat-composer__row bottom-row">
      <div class="chat-composer__actions">
        <div
          v-if="showAttachments"
          ref="sourceMenuRef"
          class="chat-composer__source-menu"
          :class="{ 'is-open': isSourceMenuOpen }"
        >
          <button
            class="icon-button"
            type="button"
            :aria-label="resolvedUploadAriaLabel"
            @click="toggleSourceMenu"
          >
            <Paperclip :size="18" :stroke-width="2" aria-hidden="true" />
          </button>
          <div v-if="isSourceMenuOpen" class="chat-composer__source-popover">
            <button type="button" class="chat-composer__source-action" @click="handleUploadClick">
              <span class="chat-composer__source-icon">
                <UploadCloud :size="16" :stroke-width="2" aria-hidden="true" />
              </span>
              <span>{{ addFileLabel }}</span>
            </button>
            <span class="chat-composer__source-link">
              <Link2 :size="15" :stroke-width="2" aria-hidden="true" />
            </span>
            <div class="chat-composer__source-divider"></div>
            <div class="chat-composer__url-editor">
              <p class="chat-composer__url-title">{{ urlPopoverTitle }}</p>
              <p class="chat-composer__url-hint">{{ urlPopoverHint }}</p>
              <textarea
                ref="urlInputRef"
                v-model="urlDraft"
                class="chat-composer__url-input"
                :placeholder="urlPopoverPlaceholder"
                rows="3"
              />
              <div class="chat-composer__url-actions modal-card__actions">
                <button type="button" class="ghost" @click="closeSourceMenu">
                  {{ urlCancelLabel }}
                </button>
                <button
                  type="button"
                  class="primary"
                  :disabled="!urlDraft.trim()"
                  @click="handleAddUrls"
                >
                  <span>{{ urlSubmitLabel }}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
        <div
          ref="outputDropdownRef"
          class="dropdown chat-dropdown"
          :class="{ 'is-open': isOutputDropdownOpen, 'is-open-upward': isOutputDropdownOpenUpward }"
        >
          <button type="button" @click="toggleOutputDropdown">
            <span class="dropdown-value">{{ selectedOutputType || resolvedOutputPlaceholder }}</span>
            <ChevronDown :size="16" :stroke-width="2" aria-hidden="true" />
          </button>
          <div v-if="isOutputDropdownOpen" ref="outputDropdownMenuRef" class="dropdown-menu">
            <button
              v-for="type in outputTypes"
              :key="`chat-${type}`"
              type="button"
              @click="handleSelectOutputType(type)"
            >
              {{ type }}
            </button>
          </div>
        </div>
      </div>
      <button
        :class="['chat-composer__send', { 'is-enabled': canSubmit }]"
        type="button"
        :disabled="!canSubmit"
        :aria-label="resolvedSendAriaLabel"
        @click="handleSubmit"
      >
        <SendHorizontal :size="20" :stroke-width="2" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-composer {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
  color: #263847;
}

.chat-composer.is-two-row {
  border-radius: var(--ys-chat-radius, 6px);
}

.chat-composer.action-rail__composer {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}

.chat-composer.action-rail__composer .chat-composer__row {
  display: contents;
}

.chat-composer.action-rail__composer .chat-composer__actions {
  display: contents;
}

.chat-composer.action-rail__composer .chat-composer__source-menu {
  order: 1;
}

.chat-composer.action-rail__composer .chat-composer__field {
  order: 2;
  min-width: 0;
}

.chat-composer.action-rail__composer .chat-dropdown {
  order: 3;
}

.chat-composer.action-rail__composer .chat-composer__send {
  order: 4;
  margin-left: 0;
}

.chat-composer.action-rail__composer.has-attachments {
  flex-direction: column;
  align-items: stretch;
}

.chat-composer.action-rail__composer.has-attachments .chat-composer__row {
  display: flex;
}

.chat-composer.action-rail__composer.has-attachments .chat-composer__actions {
  display: flex;
}

.chat-composer__row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
}

.chat-composer.is-two-row .chat-composer__row.top-row {
  align-items: stretch;
}

.chat-composer.is-two-row .chat-composer__row.bottom-row {
  align-items: center;
}

.chat-composer__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.chat-composer__source-menu {
  position: relative;
}

.chat-composer__source-popover {
  position: absolute;
  left: 0;
  bottom: calc(100% + 10px);
  width: 320px;
  padding: 12px;
  border: 1px solid rgba(27, 45, 41, 0.12);
  border-radius: var(--ys-chat-radius, 6px);
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 10px 26px rgba(27, 45, 41, 0.12);
  z-index: 40;
}

.chat-composer__source-action {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  border: none;
  background: transparent;
  padding: 8px 10px;
  border-radius: var(--ys-control-radius, 6px);
  cursor: pointer;
  font: inherit;
  color: #1b2d29;
}

.chat-composer__source-action:hover {
  background: #fff3d4;
}

.chat-composer__source-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 28px;
  border-radius: 999px;
  background: #fff3d4;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  color: #6c4300;
}

.chat-composer__source-link {
  display: none;
}

.chat-composer__source-divider {
  height: 1px;
  background: #d9e2dc;
  margin: 10px 0 12px;
}

.chat-composer__url-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chat-composer__url-title {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #1b2d29;
}

.chat-composer__url-hint {
  margin: 0;
  font-size: 12px;
  color: #64766f;
}

.chat-composer__url-input {
  width: 100%;
  min-height: 74px;
  resize: vertical;
  border-radius: var(--ys-control-radius, 6px);
  border: 1px solid #d9e2dc;
  padding: 10px 12px;
  font: inherit;
  color: #1b2d29;
  background: #fff;
  box-sizing: border-box;
}

.chat-composer__url-input:focus {
  outline: none;
  border-color: rgba(220, 163, 58, 0.58);
  box-shadow: 0 0 0 4px rgba(220, 163, 58, 0.16);
}

.chat-composer__url-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.chat-composer__url-actions .ghost,
.chat-composer__url-actions .primary {
  min-width: 92px;
  font: inherit;
}

.chat-composer__url-actions .primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.chat-dropdown {
  margin-left: 0;
}

.chat-dropdown.is-open-upward .dropdown-menu {
  top: auto;
  bottom: calc(100% + 8px);
}

.chat-composer__field {
  flex: 1;
  min-width: 320px;
  display: flex;
  align-items: center;
}

.chat-composer__field textarea {
  width: 100%;
  min-height: 58px;
  height: 58px;
  resize: none;
  overflow-y: hidden;
  box-sizing: border-box;
  display: block;
  padding: 14px 2px;
  color: #1b2d29;
}

.chat-composer__field textarea::placeholder {
  color: #64766f;
}

.chat-composer__field textarea:focus {
  outline: none;
}

.chat-composer__send {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  border: none;
  background: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  cursor: not-allowed;
  margin-left: auto;
  opacity: 0.56;
  transition: background-color 160ms ease, opacity 160ms ease, transform 160ms ease;
}

.chat-composer__send.is-enabled {
  background: linear-gradient(135deg, #1f4b39, #2f6f53);
  color: #fff;
  box-shadow: 0 6px 16px rgba(31, 75, 57, 0.2);
  cursor: pointer;
  opacity: 1;
}

.chat-composer__send.is-enabled:hover {
  transform: translateY(-1px);
}

.chat-composer__send:disabled {
  pointer-events: none;
}

.chat-composer__preview-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  width: 100%;
  padding: 4px 0;
  max-height: 96px;
  overflow-y: auto;
  justify-content: flex-start;
}

.chat-composer__preview-card {
  width: 88px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  min-height: 96px;
}

@media (max-width: 768px) {
  .chat-composer__preview-card {
    width: calc(50% - 6px);
  }

  .chat-composer__source-popover {
    width: min(320px, calc(100vw - 48px));
  }
}

.chat-composer__preview-thumb {
  position: relative;
  width: 72px;
  height: 72px;
  border-radius: var(--ys-chat-radius, 6px);
  border: 1px dashed #cbd5f5;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.chat-composer__preview-thumb.is-url {
  border-style: solid;
  background: linear-gradient(180deg, #fffaf5 0%, #ffffff 100%);
}

.chat-composer__preview-thumb img {
  width: 72px;
  height: 72px;
  object-fit: cover;
}

.chat-composer__preview-remove {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: none;
  background: rgba(255, 255, 255, 0.94);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  cursor: pointer;
  padding: 0;
  color: #334155;
}

.chat-composer__preview-placeholder {
  font-size: 12px;
  color: #475569;
  text-align: center;
  padding: 0 6px;
  font-weight: 700;
}

.chat-composer__upload-hint {
  font-size: 12px;
  color: #475569;
  margin: 4px 0 0;
}

.chat-composer__preview-label {
  margin: 0;
  width: 80px;
  font-size: 11px;
  line-height: 1.25;
  color: #475569;
  text-align: center;
  word-break: break-word;
}

.composer-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
}
</style>
