import fs from 'node:fs'
import path from 'node:path'

const localeDir = new URL('../src/locales/', import.meta.url)
const localeFiles = fs
  .readdirSync(localeDir)
  .filter((name) => name.endsWith('.json'))
  .map((name) => new URL(name, localeDir))

const allowedPatterns = [/^\s*@[:.]/, /\{'@'\}/]
const violations = []

const hasBareAt = (value) => {
  if (!value.includes('@')) return false
  const sanitized = value.replace(/\{'@'\}/g, '').replace(/@[:.][\w.-]+/g, '')
  return sanitized.includes('@')
}

const walk = (node, keyPath, filePath) => {
  if (typeof node === 'string') {
    if (hasBareAt(node) && !allowedPatterns.some((pattern) => pattern.test(node))) {
      violations.push({
        file: filePath,
        key: keyPath,
        value: node,
      })
    }
    return
  }

  if (Array.isArray(node)) {
    node.forEach((item, index) => walk(item, `${keyPath}[${index}]`, filePath))
    return
  }

  if (node && typeof node === 'object') {
    Object.entries(node).forEach(([key, value]) => {
      const nextPath = keyPath ? `${keyPath}.${key}` : key
      walk(value, nextPath, filePath)
    })
  }
}

localeFiles.forEach((fileUrl) => {
  const filePath = fileUrl.pathname
  const content = fs.readFileSync(fileUrl, 'utf8')
  const json = JSON.parse(content)
  walk(json, '', path.basename(filePath))
})

if (violations.length) {
  console.error('Found unescaped @ in locale messages:')
  violations.forEach(({ file, key, value }) => {
    console.error(`- ${file} :: ${key} :: ${value}`)
  })
  process.exit(1)
}

console.log('Locale @ check passed.')
