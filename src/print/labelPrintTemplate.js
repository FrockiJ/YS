import labelPrintCss from './labelPrint.css?raw'

const escapeHtml = (value) =>
  String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\"/g, '&quot;')
    .replace(/'/g, '&#39;')

const renderMetaLine = (text) =>
  text
    ? `<div class="print-card__meta-line"><span class="print-card__meta-dot" aria-hidden="true"><svg viewBox="0 0 8 8" focusable="false"><circle cx="4" cy="4" r="3.2" fill="currentColor" /></svg></span><span class="print-card__meta-text">${escapeHtml(text)}</span></div>`
    : ''

const renderSmallMeta = (item) => {
  const rows = []
  rows.push(renderMetaLine(item.vintage || 'NV'))
  rows.push(renderMetaLine(item.region || '-'))
  return rows.join('')
}

const renderMediumMeta = (item) => {
  const rows = []
  if (item.rating && item.rating !== '-') rows.push(renderMetaLine(item.rating))
  rows.push(renderMetaLine(item.vintage || 'NV'))
  rows.push(renderMetaLine(item.region || '-'))
  return rows.join('')
}

const renderPrintCardHtml = (item, size) => {
  const producer = escapeHtml(item.producer || '')
  const name = escapeHtml(item.name || '')
  const price = escapeHtml(item.price || '')
  const rating = escapeHtml(item.rating || '-')
  const vintage = escapeHtml(item.vintage || 'NV')
  const region = escapeHtml(item.region || '-')
  const description = escapeHtml(item.description || '')

  if (size === 'small') {
    return `
      <article class="print-card print-card--small">
        <div class="print-card__bar"></div>
        <div class="print-card__content">
          <div class="print-card__producer">${producer}</div>
          <div class="print-card__name">${name}</div>
          <div class="print-card__small-row">
            <div class="print-card__meta">${renderSmallMeta(item)}</div>
            <div class="print-card__price">${price}</div>
          </div>
        </div>
      </article>
    `
  }

  if (size === 'medium') {
    return `
      <article class="print-card print-card--medium">
        <div class="print-card__bar"></div>
        <div class="print-card__content">
          <div class="print-card__producer">${producer}</div>
          <div class="print-card__name">${name}</div>
          <div class="print-card__small-row">
            <div class="print-card__meta">${renderMediumMeta(item)}</div>
            <div class="print-card__price">${price}</div>
          </div>
        </div>
      </article>
    `
  }

  return `
    <article class="print-card print-card--large">
      <div class="print-card__bar"></div>
      <div class="print-card__content">
        <div class="print-card__top">
          <div class="print-card__name-group">
            <div class="print-card__producer">${producer}</div>
            <div class="print-card__name">${name}</div>
          </div>
          <div class="print-card__price">${price}</div>
        </div>
        <div class="print-card__details">
          <span class="print-card__detail print-card__detail--rating">${rating}</span>
          <span class="print-card__divider"></span>
          <span class="print-card__detail print-card__detail--vintage">${vintage}</span>
          <span class="print-card__divider"></span>
          <span class="print-card__detail print-card__detail--region">${region}</span>
        </div>
        <div class="print-card__description">${description}</div>
      </div>
    </article>
  `
}

const renderPrintSheetHtml = (size, panelItems) => {
  const cards = panelItems.map((item) => renderPrintCardHtml(item, size)).join('')
  return `
    <section class="print-sheet print-sheet--${size}">
      <div class="print-grid print-grid--${size}">
        ${cards}
      </div>
    </section>
  `
}

export const renderPrintDocumentHtml = (panelsBySize, options = {}) => {
  const title = escapeHtml(options.title || 'Label Print')
  const sheets = []
  for (const section of panelsBySize || []) {
    for (const panelItems of section?.panels || []) {
      sheets.push(renderPrintSheetHtml(section.size, panelItems))
    }
  }

  return `<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${title}</title>
  <style>${labelPrintCss}</style>
</head>
<body>
  ${sheets.join('')}
</body>
</html>`
}
