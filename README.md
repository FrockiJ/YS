# YS Vue UAT

This checkout contains only the YS Vue frontend. It has no fixed host port and no committed environment file.

## Develop against local UAT

Start the UAT stack first from `F:\Projects\ys\ys-ai-uat`, then run:

```powershell
cd F:\Projects\ys\ys-vue-uat
npm ci
npm run dev
```

The script obtains the Docker Web service's dynamic loopback URL and starts Vite on another dynamically selected loopback port. It prints the Vite URL; use that URL in the browser.

## Checks

```powershell
npm run check:locale
npm run build
.\scripts\verify-isolation.ps1
```
