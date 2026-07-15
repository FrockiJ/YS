import qrcode from 'qrcode-generator'

export const normalizeLabelCode = (value) => String(value || '').trim()

export const createLabelQrSvg = (value) => {
  const code = normalizeLabelCode(value)
  if (!code) return ''

  const qr = qrcode(0, 'M')
  qr.addData(code)
  qr.make()
  return qr.createSvgTag({ cellSize: 4, margin: 4, scalable: true })
}
