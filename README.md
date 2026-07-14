# YS AI UAT

This branch contains the YS backend and the local UAT Compose coordinator. It never publishes fixed host ports: Docker assigns the loopback port for `web` dynamically.

## Start locally

1. Copy `.env.uat.example` to `F:\Projects\ys\config\uat\backend.env` and set local-only values.
2. Run `powershell -ExecutionPolicy Bypass -File .\scripts\start-local-uat.ps1`.
3. Run `powershell -ExecutionPolicy Bypass -File .\scripts\test-local-uat.ps1`.

The exact browser URL is printed by the start script. Do not use Docker commands that stop or remove other Compose projects.
