import { createServer } from 'node:net'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const findLoopbackPort = () =>
  new Promise((resolve, reject) => {
    const server = createServer()
    server.once('error', reject)
    server.listen({ host: '127.0.0.1', port: 0 }, () => {
      const { port } = server.address()
      server.close((error) => (error ? reject(error) : resolve(port)))
    })
  })

const port = await findLoopbackPort()
const viteEntrypoint = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url))
const vite = spawn(process.execPath, [viteEntrypoint, '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
  env: process.env,
  stdio: 'inherit',
})

vite.on('error', (error) => {
  console.error(error)
  process.exitCode = 1
})
vite.on('exit', (code, signal) => {
  process.exitCode = code ?? (signal ? 1 : 0)
})
