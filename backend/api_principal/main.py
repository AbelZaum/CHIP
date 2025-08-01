# ARQUIVO: backend/api_principal/main.py

import json
import subprocess
import uuid
import datetime
import shutil
import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# --- Configuração do CORS ---
origins = ["http://localhost:5500", "http://127.0.0.1:5500", "null"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- Modelos de Dados ---
class UserLogin(BaseModel):
    username: str
    password: str

# --- Gerenciamento de Estado ---
class ConnectionManager:
    def __init__(self):
        self.active_frontend_connections: dict[str, WebSocket] = {}
        self.active_bot_connections: dict[str, WebSocket] = {}

    async def connect_frontend(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_frontend_connections[session_id] = websocket

    async def connect_bot(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_bot_connections[session_id] = websocket

    def disconnect_frontend(self, session_id: str):
        self.active_frontend_connections.pop(session_id, None)
        
    def disconnect_bot(self, session_id: str):
        self.active_bot_connections.pop(session_id, None)

    async def send_to_frontend(self, session_id: str, message: dict):
        if session_id in self.active_frontend_connections:
            await self.active_frontend_connections[session_id].send_json(message)
            
    async def broadcast_to_frontends(self, message: dict):
        for connection in self.active_frontend_connections.values():
            await connection.send_json(message)

    async def send_to_bot(self, session_id: str, message: dict):
        if session_id in self.active_bot_connections:
            await self.active_bot_connections[session_id].send_json(message)

manager = ConnectionManager()
accounts_db = {} 
running_processes = {} 
conversation_state = {}
app.state.start_time = datetime.datetime.utcnow()

# Roteiros de conversa para aquecimento
conversation_scripts = {
    "casual": [
        "Oi! Tudo bem?", "Tudo sim! E você?", "Também, na correria de sempre.",
        "Imagino. Fim de semana promete?", "Tomara! Precisando descansar um pouco.",
        "Com certeza. Bom, vou indo nessa. Se cuida!", "Você também! Abraço."
    ],
    "trabalho": [
        "Oi! Como foi o dia?", "Corrido, mas produtivo. E o seu?", "Também foi bem movimentado.",
        "Conseguiu resolver aquela questão?", "Sim, deu tudo certo no final.",
        "Que bom! Bom trabalho então!", "Valeu! Até mais!"
    ],
    "familia": [
        "Oi! Como estão as crianças?", "Tudo bem! Estudando bastante.", "Que ótimo!",
        "E o trabalho, como está?", "Na medida, sabe como é.",
        "Se cuida! Manda abraço pra família!", "Valeu! Abraço pra vocês também!"
    ]
}

# --- Tarefa de Fundo para Aquecimento ---
async def warming_scheduler():
    while True:
        await asyncio.sleep(30)  # Verifica a cada 30 segundos
        
        online_accounts = [acc for acc in accounts_db.values() if acc.get("status") == "Online"]
        
        if len(online_accounts) >= 2:
            # Escolhe pares aleatórios para conversar
            import random
            random.shuffle(online_accounts)
            
            for i in range(0, len(online_accounts) - 1, 2):
                acc1 = online_accounts[i]
                acc2 = online_accounts[i+1]
                
                conversation_id = f"{acc1['id']}-{acc2['id']}"
                
                # Verifica se já existe uma conversa ativa entre eles
                if conversation_id not in conversation_state:
                    # Escolhe um roteiro aleatório
                    script_type = random.choice(list(conversation_scripts.keys()))
                    script = conversation_scripts[script_type]
                    
                    print(f"[🔥 AQUECIMENTO] Iniciando conversa {script_type} entre {acc1.get('numero')} e {acc2.get('numero')}")
                    
                    conversation_state[conversation_id] = {
                        "step": 0, 
                        "participants": [acc1['id'], acc2['id']],
                        "script": script,
                        "script_type": script_type,
                        "start_time": datetime.datetime.now()
                    }
                    
                    # Envia primeira mensagem
                    first_message = script[0]
                    await manager.send_to_bot(acc1['id'], {
                        "type": "send_message", 
                        "to": acc2['raw_numero'], 
                        "text": first_message
                    })
                    
                    # Atualiza status
                    accounts_db[acc1['id']]['status'] = 'Aquecendo'
                    accounts_db[acc2['id']]['status'] = 'Aquecendo'
                    
                    # Notifica frontend
                    await manager.broadcast_to_frontends({"type": "full_update"})
                    
                    print(f"[🔥 AQUECIMENTO] Primeira mensagem enviada: '{first_message}'")
                    
                    # Aguarda um pouco antes de iniciar próxima conversa
                    await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(warming_scheduler())

# --- Endpoints HTTP ---
@app.get("/")
def read_root():
    return {"message": "API do ChipWarmer está no ar!"}

@app.post("/api/login")
async def login(user: UserLogin):
    if user.username == "chefe" and user.password == "123":
        return {"status": "success"}
    raise HTTPException(status_code=401, detail="Credenciais inválidas.")

@app.get("/api/accounts")
def get_accounts():
    return {"accounts": list(accounts_db.values())}

@app.get("/api/system-stats")
def get_system_stats():
    uptime_delta = datetime.datetime.utcnow() - app.state.start_time
    days, hours, rem = uptime_delta.days, 0, 0
    if uptime_delta.seconds > 0:
        hours, rem = divmod(uptime_delta.seconds, 3600)
        minutes, _ = divmod(rem, 60)
    uptime_string = f"{days}d {hours}h {minutes}m"
    
    # Estatísticas de aquecimento
    active_conversations = len(conversation_state)
    online_accounts = len([acc for acc in accounts_db.values() if acc.get("status") == "Online"])
    warming_accounts = len([acc for acc in accounts_db.values() if acc.get("status") == "Aquecendo"])
    
    return {
        "messagesToday": sum(acc.get("mensagensEnviadas", 0) for acc in accounts_db.values()),
        "systemStatus": "Online", 
        "systemStatusColor": "text-green-400", 
        "uptime": uptime_string,
        "activeConversations": active_conversations,
        "onlineAccounts": online_accounts,
        "warmingAccounts": warming_accounts
    }

@app.get("/api/conversations")
def get_conversations():
    """Retorna as conversas ativas para debug"""
    conversations = []
    for conv_id, conv_data in conversation_state.items():
        participants = []
        for pid in conv_data["participants"]:
            if pid in accounts_db:
                participants.append(accounts_db[pid]["numero"])
        
        conversations.append({
            "id": conv_id,
            "participants": participants,
            "script_type": conv_data["script_type"],
            "step": conv_data["step"],
            "total_steps": len(conv_data["script"]),
            "start_time": conv_data["start_time"].isoformat()
        })
    
    return {"conversations": conversations}

@app.post("/api/start-session")
async def start_session():
    session_id = str(uuid.uuid4())
    accounts_db[session_id] = { "id": session_id, "numero": "Iniciando...", "status": "Pendente", "ultimaAtividade": datetime.datetime.now().isoformat() }
    process = subprocess.Popen(['node', 'index.js', session_id], cwd='../automacao_whatsapp')
    running_processes[session_id] = process
    return {"sessionId": session_id}

@app.delete("/api/accounts/{session_id}")
async def remove_account(session_id: str):
    if session_id in running_processes:
        process = running_processes[session_id]
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        del running_processes[session_id]
    if session_id in accounts_db:
        del accounts_db[session_id]
    session_folder_path = os.path.join("..", "automacao_whatsapp", ".wwebjs_auth", f"session-{session_id}")
    try:
        shutil.rmtree(session_folder_path)
    except FileNotFoundError:
        pass
    return {"status": "success"}

# --- Endpoints WebSocket ---
@app.websocket("/ws/frontend/{session_id}")
async def websocket_frontend_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect_frontend(websocket, session_id)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: manager.disconnect_frontend(session_id)

@app.websocket("/ws/automacao/{session_id}")
async def websocket_automacao_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect_bot(websocket, session_id)
    try:
        while True:
            data = json.loads(await websocket.receive_text())
            if session_id not in accounts_db: continue
            
            if data.get("type") == "qr":
                accounts_db[session_id]["status"] = "Aguardando Scan"
                await manager.send_to_frontend(session_id, {"type": "qr", "data": data["data"]})

            elif data.get("type") == "status":
                print(f"[DEBUG] Status update received for session {session_id}: {data}")
                if "status" in data: accounts_db[session_id]["status"] = data["status"]
                if "numero" in data:
                    num = data['numero']
                    accounts_db[session_id]["raw_numero"] = f"{num}@c.us"
                    accounts_db[session_id]["numero"] = f"+{num[:2]} {num[2:4]} {num[4:9]}-{num[9:]}"
                
                # Envia a mensagem específica de 'status_update' para o modal fechar
                print(f"[DEBUG] Sending status_update to frontend: {data.get('status')}")
                await manager.send_to_frontend(session_id, {"type": "status_update", "status": data.get("status")})
                # E DEPOIS avisa a todos para atualizarem suas listas
                await manager.broadcast_to_frontends({"type": "full_update"})

            elif data.get("type") == "message_received":
                print(f"[📨 MENSAGEM] Recebida de {session_id}: '{data.get('text', '')}'")
                
                active_conversation = next((conv_id for conv_id, conv_data in conversation_state.items() if session_id in conv_data["participants"]), None)
                if active_conversation:
                    conv_data = conversation_state[active_conversation]
                    conv_data["step"] += 1
                    
                    script = conv_data["script"]
                    if conv_data["step"] < len(script):
                        next_message = script[conv_data["step"]]
                        print(f"[🔥 AQUECIMENTO] Próxima mensagem do roteiro '{conv_data['script_type']}': '{next_message}'")
                        
                        await manager.send_to_bot(session_id, {
                            "type": "send_message", 
                            "to": data["from"], 
                            "text": next_message
                        })
                    else:
                        # Fim da conversa
                        duration = datetime.datetime.now() - conv_data["start_time"]
                        print(f"[✅ CONVERSA FINALIZADA] {active_conversation} - Duração: {duration.total_seconds():.1f}s")
                        
                        # Volta status para Online
                        for pid in conv_data["participants"]:
                            if pid in accounts_db:
                                accounts_db[pid]["status"] = "Online"
                                accounts_db[pid]["ultimaAtividade"] = datetime.datetime.now().isoformat()
                        
                        await manager.broadcast_to_frontends({"type": "full_update"})
                        del conversation_state[active_conversation]

    except WebSocketDisconnect:
        if session_id in accounts_db:
            accounts_db[session_id]["status"] = "Erro"
            await manager.broadcast_to_frontends({"type": "full_update"})
        manager.disconnect_bot(session_id)
