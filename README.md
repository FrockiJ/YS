# YS AI UAT

This branch contains the YS backend and the local UAT Compose coordinator. It never publishes fixed host ports: Docker assigns the loopback port for `web` dynamically.

## Start locally

1. Copy `.env.uat.example` to `F:\Projects\ys\config\uat\backend.env` and set local-only values.
2. Run `powershell -ExecutionPolicy Bypass -File .\scripts\start-local-uat.ps1`.
3. Run `powershell -ExecutionPolicy Bypass -File .\scripts\test-local-uat.ps1`.

The exact browser URL is printed by the start script. Do not use Docker commands that stop or remove other Compose projects.

## Temporary public HTTP UAT

Normal startup remains loopback-only. For short external UAT tests, create the ignored `F:\Projects\ys\config\uat\public-web.env`:

```env
YS_UAT_PUBLIC_ENABLED=true
YS_UAT_WEB_BIND_ADDRESS=220.132.241.68
```

After explicitly stopping the local UAT stack, run `powershell -ExecutionPolicy Bypass -File .\scripts\start-local-uat.ps1 -Public`. Docker allocates the port and prints `http://220.132.241.68:<dynamic-port>/`. This mode does not change Windows Firewall rules; if an external device cannot connect, keep the local UAT running and diagnose Firewall or router access separately.
