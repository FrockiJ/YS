export const extractFeatureValue = (value) => {
  if (typeof value === 'number') return value
  if (!value) return 0
  const matches = String(value).match(/\d+(?:\.\d+)?/g)
  if (!matches) return 0
  const numbers = matches.map(Number)
  return numbers.reduce((sum, number) => sum + number, 0) / numbers.length
}
