import labelPrintCss from './labelPrint.css?raw'
import { buildLabelPreviewModel } from '../utils/labelPreviewModel.js'

const escapeHtml = (value) =>
  String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

const renderQr = (label) =>
  label.qrSvg
    ? `<div class="print-card__qr" style="--qr-size:${label.qrSizeMm}mm"><div class="print-card__qr-art">${label.qrSvg}</div><span>${escapeHtml(label.code)}</span></div>`
    : ''

const renderMeta = (label) => {
  if (label.size === 'small') return `<span>${escapeHtml(label.specification)}</span><span>${escapeHtml(label.category)}</span>`
  if (label.size === 'medium') return `<span>${escapeHtml(label.feature)}</span><span>${escapeHtml(label.specification)}</span><span>${escapeHtml(label.category)}</span>`
  return `<span>${escapeHtml(label.feature)}</span><span>${escapeHtml(label.specification)}</span><span>${escapeHtml(label.category)}</span>`
}

const renderPrintCardHtml = (item, size) => {
  const label = buildLabelPreviewModel(item, { size })
  return `
    <article class="print-card print-card--${label.size}">
      <div class="print-card__bar"></div>
      <div class="print-card__top">
        <div class="print-card__identity">
          <strong class="print-card__brand">${escapeHtml(label.brand || '-')}</strong>
          <span class="print-card__name">${escapeHtml(label.name || '-')}</span>
        </div>
        ${renderQr(label)}
      </div>
      <div class="print-card__bottom">
        <div class="print-card__meta">${renderMeta(label)}</div>
        <strong class="print-card__price">${escapeHtml(label.price)}</strong>
      </div>
      ${label.size === 'large' && label.description ? `<p class="print-card__description">${escapeHtml(label.description)}</p>` : ''}
    </article>
  `
}

const renderPrintSheetHtml = (size, panelItems) => `
  <section class="print-sheet print-sheet--${size}">
    <div class="print-grid print-grid--${size}">
      ${panelItems.map((item) => renderPrintCardHtml(item, size)).join('')}
    </div>
  </section>
`

export const renderLabelPrintDocumentHtml = (panelsBySize, options = {}) => {
  const title = escapeHtml(options.title || 'Label Print')
  const sheets = []
  for (const section of panelsBySize || []) {
    for (const panelItems of section?.panels || []) {
      sheets.push(renderPrintSheetHtml(section.size, panelItems))
    }
  }

  return `<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>${title}</title><style>${labelPrintCss}</style></head>
<body>${sheets.join('')}</body></html>`
}
