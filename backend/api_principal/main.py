# ARQUIVO: backend/api_principal/main.py

import json
import subprocess
import uuid
import datetime
import shutil
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# --- Configuração do CORS ---
# ADICIONAMOS AQUI OS ENDEREÇOS DO GO LIVE (normalmente porta 5500)
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "null"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Gerenciamento de Estado ---
class ConnectionManager:
    def __init__(self): self.active_connections: dict[str, WebSocket] = {}
    async def connect(self, websocket: WebSocket, session_id: str): await websocket.accept(); self.active_connections[session_id] = websocket
    def disconnect(self, session_id: str): self.active_connections.pop(session_id, None)
    async def send_to_frontend(self, session_id: str, message: dict):
        if session_id in self.active_connections: await self.active_connections[session_id].send_json(message)

manager = ConnectionManager()
accounts_db = {} 
running_processes = {} 
app.state.start_time = datetime.datetime.utcnow()

# --- Endpoints HTTP ---

@app.get("/")
def read_root():
    return {"message": "API do ChipWarmer está no ar!"}

@app.get("/api/accounts")
def get_accounts():
    return {"accounts": list(accounts_db.values())}

@app.get("/api/system-stats")
def get_system_stats():
    uptime_delta = datetime.datetime.utcnow() - app.state.start_time
    days = uptime_delta.days
    hours, rem = divmod(uptime_delta.seconds, 3600)
    minutes, _ = divmod(rem, 60)
    uptime_string = f"{days}d {hours}h {minutes}m"
    return {
        "messagesToday": sum(acc.get("mensagensEnviadas", 0) for acc in accounts_db.values()),
        "systemStatus": "Online",
        "systemStatusColor": "text-green-400",
        "uptime": uptime_string
    }

@app.post("/api/start-session")
async def start_session():
    session_id = str(uuid.uuid4())
    accounts_db[session_id] = {
        "id": session_id, "numero": "Aguardando QR Code...", "status": "Pendente",
        "mensagensEnviadas": 0, "ultimaAtividade": datetime.datetime.now().isoformat()
    }
    print(f"[API] Iniciando processo do bot para a sessão: {session_id}")
    process = subprocess.Popen(['node', 'index.js', session_id], cwd='../automacao_whatsapp')
    running_processes[session_id] = process
    return {"sessionId": session_id}

@app.delete("/api/accounts/{session_id}")
async def remove_account(session_id: str):
    print(f"[API] Recebida requisição para remover a sessão: {session_id}")
    if session_id in running_processes:
        print(f"[API] Parando processo do bot {session_id}...")
        running_processes[session_id].terminate()
        del running_processes[session_id]

    if session_id in accounts_db:
        del accounts_db[session_id]

    session_folder_path = os.path.join("..", "automacao_whatsapp", ".wwebjs_auth", f"session-{session_id}")
    try:
        shutil.rmtree(session_folder_path)
        print(f"[API] Pasta de sessão {session_folder_path} removida.")
    except FileNotFoundError:
        print(f"[API] Pasta de sessão não encontrada para remover.")
    except Exception as e:
        print(f"[API] Erro ao remover pasta de sessão: {e}")

    return {"status": "success", "message": f"Conta {session_id} removida."}

# --- Endpoints WebSocket ---
@app.websocket("/ws/frontend/{session_id}")
async def websocket_frontend_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: manager.disconnect(session_id)

@app.websocket("/ws/automacao/{session_id}")
async def websocket_automacao_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        while True:
            data = json.loads(await websocket.receive_text())
            if session_id not in accounts_db: continue
            
            if data.get("type") == "qr":
                accounts_db[session_id]["status"] = "Aguardando Scan"
                await manager.send_to_frontend(session_id, {"type": "qr", "data": data["data"]})
            elif data.get("type") == "status":
                if "status" in data:
                  accounts_db[session_id]["status"] = data["status"]
                if "numero" in data:
                    num = data['numero']; accounts_db[session_id]["numero"] = f"+{num[:2]} {num[2:4]} {num[4:9]}-{num[9:]}"
                await manager.send_to_frontend(session_id, {"type": "status_update", "status": data.get("status")})
    except WebSocketDisconnect:
        if session_id in accounts_db:
            accounts_db[session_id]["status"] = "Erro"; await manager.send_to_frontend(session_id, {"type": "status_update", "status": "Erro"})
