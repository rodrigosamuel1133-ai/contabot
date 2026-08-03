# ContaBot 🤖

Asistente de contabilidad con IA — lee PDFs de estados de cuenta y clasifica todas las transacciones automáticamente.

## Deploy en Railway (5 minutos)

### 1. Sube este código a GitHub
- Crea una cuenta en github.com (gratis)
- Crea un repositorio nuevo llamado `contabot`
- Sube todos estos archivos

### 2. Conecta Railway
- Ve a railway.app y crea cuenta con GitHub
- Click "New Project" → "Deploy from GitHub repo"
- Selecciona el repositorio `contabot`

### 3. Agrega tu API Key
- En Railway, ve a tu proyecto → "Variables"
- Agrega: `ANTHROPIC_API_KEY` = tu key de console.anthropic.com

### 4. Listo
Railway te da un link público tipo `contabot-production.up.railway.app`

## Estructura
```
contabot/
├── app.py              # Servidor Flask
├── requirements.txt    # Dependencias Python
├── Procfile           # Comando de inicio
├── railway.json       # Config Railway
└── static/
    └── index.html     # Frontend
```

## Cómo funciona
- El PDF se envía al servidor
- El servidor lo manda a Claude API como documento nativo
- Claude lee el PDF completo página por página
- Clasifica todas las transacciones sin perder ninguna
