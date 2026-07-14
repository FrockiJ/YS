export const extractRatingValue = (value) => {
  if (typeof value === 'number') {
    return value
  }
  if (!value) {
    return 0
  }
  const matches = value.match(/\d+(?:\.\d+)?/g)
  if (!matches) {
    return 0
  }
  const numbers = matches.map(Number)
  const sum = numbers.reduce((acc, num) => acc + num, 0)
  return sum / numbers.length
}
