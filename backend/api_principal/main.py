# ARQUIVO: backend/api_principal/main.py

import json
import subprocess
import uuid
import datetime
import shutil
import os
import asyncio
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from typing import Optional

app = FastAPI()

# --- Configuração do CORS ---
origins = ["http://localhost:5500", "http://127.0.0.1:5500", "null", "34.46.184.53"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- Modelos de Dados ---
class UserLogin(BaseModel):
    username: str
    password: str

class UserPasswordChange(BaseModel):
    username: str
    newPassword: str

# --- ALTERAÇÃO: Modelo para o request de start-session ---
class StartSessionRequest(BaseModel):
    username: str
    plano: str

class WarmingConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 30
    max_conversations: int = 10 
    active_scripts: list = ["casual", "trabalho", "familia"]

class SystemConfig(BaseModel):
    debug_mode: bool = False
    log_level: str = "info"
    notifications_enabled: bool = True
    auto_restart: bool = True

class SecurityConfig(BaseModel):
    gemini_api_key: str = ""
    max_sessions: int = 25 
    session_timeout: int = 3600

# Configurações globais
warming_config = WarmingConfig()
system_config = SystemConfig()
security_config = SecurityConfig()

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
            try:
                await self.active_frontend_connections[session_id].send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                self.disconnect_frontend(session_id)
            
    async def broadcast_to_frontends(self, message: dict):
        for session_id, connection in list(self.active_frontend_connections.items()):
            try:
                await connection.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                self.disconnect_frontend(session_id)

    async def send_to_bot(self, session_id: str, message: dict):
        if session_id in self.active_bot_connections:
            try:
                await self.active_bot_connections[session_id].send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                self.disconnect_bot(session_id)


manager = ConnectionManager()
accounts_db = {} 
running_processes = {} 
conversation_state = {}
app.state.start_time = datetime.datetime.utcnow()

# Roteiros de conversa para aquecimento (com áudios)
conversation_scripts = {
    "casual": [
        {"type": "text", "content": "Oi! Tudo bem?"},
        {"type": "text", "content": "Tudo sim! E você?"},
        {"type": "audio", "content": "casual_risada.mp3", "caption": "kkkk"},
        {"type": "text", "content": "Também, na correria de sempre."},
        {"type": "text", "content": "Imagino. Fim de semana promete?"},
        {"type": "audio", "content": "casual_concordar.mp3", "caption": "Sim!"},
        {"type": "text", "content": "Tomara! Precisando descansar um pouco."},
        {"type": "text", "content": "Com certeza. Bom, vou indo nessa. Se cuida!"},
        {"type": "audio", "content": "casual_tchau.mp3", "caption": "Tchau!"},
        {"type": "text", "content": "Você também! Abraço."}
    ],
    "trabalho": [
        {"type": "text", "content": "Oi! Como foi o dia?"},
        {"type": "text", "content": "Corrido, mas produtivo. E o seu?"},
        {"type": "audio", "content": "trabalho_concordar.mp3", "caption": "Concordo"},
        {"type": "text", "content": "Também foi bem movimentado."},
        {"type": "text", "content": "Conseguiu resolver aquela questão?"},
        {"type": "audio", "content": "trabalho_sucesso.mp3", "caption": "Perfeito!"},
        {"type": "text", "content": "Sim, deu tudo certo no final."},
        {"type": "text", "content": "Que bom! Bom trabalho então!"},
        {"type": "audio", "content": "trabalho_obrigado.mp3", "caption": "Obrigado!"},
        {"type": "text", "content": "Valeu! Até mais!"}
    ],
    "familia": [
        {"type": "text", "content": "Oi! Como estão as crianças?"},
        {"type": "text", "content": "Tudo bem! Estudando bastante."},
        {"type": "audio", "content": "familia_beijo.mp3", "caption": "Beijo"},
        {"type": "text", "content": "Que ótimo!"},
        {"type": "text", "content": "E o trabalho, como está?"},
        {"type": "audio", "content": "familia_concordar.mp3", "caption": "Sim"},
        {"type": "text", "content": "Na medida, sabe como é."},
        {"type": "text", "content": "Se cuida! Manda abraço pra família!"},
        {"type": "audio", "content": "familia_abraco.mp3", "caption": "Abraço"},
        {"type": "text", "content": "Valeu! Abraço pra vocês também!"}
    ]
}

# --- Tarefa de Fundo para Aquecimento ---
async def warming_scheduler():
    while True:
        await asyncio.sleep(warming_config.interval_seconds)
        
        if not warming_config.enabled:
            continue
            
        available_accounts = [acc for acc in accounts_db.values() if acc.get("status") == "Online"]
        random.shuffle(available_accounts)
        accounts_in_conversation = {p for conv in conversation_state.values() for p in conv['participants']}

        i = 0
        while i < len(available_accounts) - 1:
            if len(conversation_state) >= warming_config.max_conversations:
                if system_config.debug_mode:
                    print(f"[🔥 AQUECIMENTO] Limite de {warming_config.max_conversations} conversas atingido.")
                break

            acc1 = available_accounts[i]
            acc2 = available_accounts[i+1]

            if acc1['id'] in accounts_in_conversation or acc2['id'] in accounts_in_conversation:
                i += 2
                continue

            conversation_id = f"{acc1['id']}-{acc2['id']}"
            if conversation_id not in conversation_state and f"{acc2['id']}-{acc1['id']}" not in conversation_state:
                available_scripts = [s for s in warming_config.active_scripts if s in conversation_scripts]
                if not available_scripts: continue
                    
                script_type = random.choice(available_scripts)
                script = conversation_scripts[script_type]
                
                if system_config.debug_mode:
                    print(f"[🔥 AQUECIMENTO] Novo par: {acc1.get('numero')} ↔ {acc2.get('numero')} | Roteiro: {script_type}")
                
                conversation_state[conversation_id] = {
                    "step": 0, "participants": [acc1['id'], acc2['id']], "script": script,
                    "script_type": script_type, "start_time": datetime.datetime.now(),
                    "lock": asyncio.Lock()
                }
                
                accounts_in_conversation.update([acc1['id'], acc2['id']])
                first_step = script[0]
                message_payload = {
                    "to": acc2['raw_numero'],
                    **({"type": "send_message", "text": first_step["content"]} if first_step["type"] == "text" else \
                       {"type": "send_audio", "audio_file": first_step["content"], "caption": first_step.get("caption", "")})
                }
                await manager.send_to_bot(acc1['id'], message_payload)
                
                accounts_db[acc1['id']]['status'] = 'Aquecendo'
                accounts_db[acc2['id']]['status'] = 'Aquecendo'
                
                await manager.broadcast_to_frontends({"type": "full_update"})
                
                if system_config.debug_mode:
                    print(f"[🔥 AQUECIMENTO] Primeira msg enviada: {first_step['type']} - '{first_step['content']}'")
                
                await asyncio.sleep(random.uniform(3, 7))
            i += 2

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(warming_scheduler())

# --- Endpoints HTTP ---
@app.get("/")
def read_root():
    return {"message": "API do ChipWarmer está no ar!"}

@app.post("/api/login")
async def login(user: UserLogin):
    APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycby_EHJyfXvVP42YT2eBbgjQXVp57-VWzmJCIEeThBX2WOK_wh_6-d_3gzVb2L2uDHF6QQ/exec"
    payload = {"action": "login", "username": user.username, "password": user.password}
    try:
        response = requests.post(APPS_SCRIPT_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            # --- ALTERAÇÃO: Repassa o plano recebido do Apps Script ---
            return {
                "status": "success", 
                "nome": data.get("nome"), 
                "mustChange": data.get("mustChange"),
                "plano": data.get("plano", "Básico") # Retorna o plano, com 'Básico' como padrão de segurança
            }
        else:
            raise HTTPException(status_code=401, detail=data.get("message", "Credenciais inválidas."))
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Erro ao contatar o serviço de autenticação: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no servidor: {e}")

@app.post("/api/change-password")
async def change_password(req: UserPasswordChange):
    APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycby_EHJyfXvVP42YT2eBbgjQXVp57-VWzmJCIEeThBX2WOK_wh_6-d_3gzVb2L2uDHF6QQ/exec"
    payload = {"action": "changePassword", "username": req.username, "newPassword": req.newPassword}
    try:
        response = requests.post(APPS_SCRIPT_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            return {"status": "success", "message": "Senha alterada."}
        else:
            raise HTTPException(status_code=400, detail=data.get("message", "Não foi possível alterar a senha."))
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Erro ao contatar o serviço de autenticação: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no servidor: {e}")

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
    
    active_conversations = len(conversation_state)
    online_accounts = len([acc for acc in accounts_db.values() if acc.get("status") == "Online"])
    warming_accounts = len([acc for acc in accounts_db.values() if acc.get("status") == "Aquecendo"])
    
    audios_sent = sum(1 for conv in conversation_state.values() for step in conv.get("script", []) if step.get("type") == "audio")
    
    return {
        "messagesToday": sum(acc.get("mensagensEnviadas", 0) for acc in accounts_db.values()),
        "systemStatus": "Online", "uptime": uptime_string,
        "activeConversations": active_conversations, "onlineAccounts": online_accounts,
        "warmingAccounts": warming_accounts, "audiosSent": audios_sent
    }

@app.get("/api/config")
def get_config():
    return { "warming": warming_config.dict(), "system": system_config.dict(), "security": security_config.dict() }

@app.post("/api/config/warming")
async def update_warming_config(config: WarmingConfig):
    global warming_config
    warming_config = config
    await manager.broadcast_to_frontends({"type": "full_update"}) 
    return {"status": "success", "message": "Configurações de aquecimento atualizadas"}

@app.post("/api/config/system")
async def update_system_config(config: SystemConfig):
    global system_config
    system_config = config
    await manager.broadcast_to_frontends({"type": "full_update"}) 
    return {"status": "success", "message": "Configurações do sistema atualizadas"}

@app.post("/api/config/security")
async def update_security_config(config: SecurityConfig):
    global security_config
    security_config = config
    await manager.broadcast_to_frontends({"type": "full_update"}) 
    return {"status": "success", "message": "Configurações de segurança atualizadas"}

# --- ALTERAÇÃO: Endpoint de start-session agora valida o plano ---
@app.post("/api/start-session")
async def start_session(req: StartSessionRequest):
    plan_limit = 20 if req.plano == "PRO" else 5
    
    # A validação agora considera apenas as contas do usuário que está fazendo a requisição
    user_accounts = [acc for acc in accounts_db.values() if acc.get("owner") == req.username]
    if len(user_accounts) >= plan_limit:
        raise HTTPException(
            status_code=403, 
            detail=f"Limite do plano {req.plano} atingido. Máximo {plan_limit} contas permitidas."
        )
    
    session_id = str(uuid.uuid4())
    accounts_db[session_id] = { 
        "id": session_id, "numero": "Iniciando...", "status": "Pendente", 
        "ultimaAtividade": datetime.datetime.now().isoformat(),
        "owner": req.username # Adiciona o dono da sessão
    }
    process = subprocess.Popen(['node', 'index.js', session_id], cwd='../automacao_whatsapp')
    running_processes[session_id] = process
    await manager.broadcast_to_frontends({"type": "full_update"})
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
    
    convs_to_remove = [conv_id for conv_id, data in list(conversation_state.items()) if session_id in data['participants']]
    for conv_id in convs_to_remove:
        other_pid = next((pid for pid in conversation_state[conv_id]['participants'] if pid != session_id), None)
        if other_pid and other_pid in accounts_db:
            accounts_db[other_pid]['status'] = 'Online'
        del conversation_state[conv_id]

    session_folder_path = os.path.join("..", "automacao_whatsapp", ".wwebjs_auth", f"session-{session_id}")
    if os.path.exists(session_folder_path):
        shutil.rmtree(session_folder_path)
    
    await manager.broadcast_to_frontends({"type": "full_update"})
    return {"status": "success"}

# --- Endpoints WebSocket ---
@app.websocket("/ws/frontend/{session_id}")
async def websocket_frontend_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect_frontend(websocket, session_id)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_frontend(session_id)

@app.websocket("/ws/automacao/{session_id}")
async def websocket_automacao_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect_bot(websocket, session_id)
    try:
        while True:
            data = json.loads(await websocket.receive_text())
            if session_id not in accounts_db: continue
            
            accounts_db[session_id]["ultimaAtividade"] = datetime.datetime.now().isoformat()

            if data.get("type") == "qr":
                accounts_db[session_id]["status"] = "Aguardando Scan"
                await manager.send_to_frontend(session_id, {"type": "qr", "data": data["data"]})
                await manager.broadcast_to_frontends({"type": "full_update"})

            elif data.get("type") == "status":
                if "status" in data: accounts_db[session_id]["status"] = data["status"]
                if "numero" in data:
                    num = data['numero']
                    accounts_db[session_id]["raw_numero"] = f"{num}@c.us"
                    accounts_db[session_id]["numero"] = f"+{num[:2]} {num[2:4]} {num[4:9]}-{num[9:]}"
                
                await manager.send_to_frontend(session_id, {"type": "status_update", "status": data.get("status")})
                await manager.broadcast_to_frontends({"type": "full_update"})

            elif data.get("type") == "message_received":
                active_conv_id = next((cid for cid, cdata in conversation_state.items() if session_id in cdata["participants"]), None)
                if active_conv_id:
                    conv_data = conversation_state.get(active_conv_id)
                    if not conv_data: continue
                    
                    async with conv_data["lock"]:
                        if active_conv_id not in conversation_state: continue
                        conv_data["step"] += 1
                        script = conv_data["script"]
                        if conv_data["step"] < len(script):
                            await asyncio.sleep(random.uniform(5, 15))
                            next_step = script[conv_data["step"]]
                            
                            message_payload = {
                                "to": data["from"],
                                **({"type": "send_message", "text": next_step["content"]} if next_step["type"] == "text" else \
                                   {"type": "send_audio", "audio_file": next_step["content"], "caption": next_step.get("caption", "")})
                            }
                            await manager.send_to_bot(session_id, message_payload)
                        else:
                            for pid in conv_data["participants"]:
                                if pid in accounts_db:
                                    accounts_db[pid]["status"] = "Online"
                                    accounts_db[pid]["ultimaAtividade"] = datetime.datetime.now().isoformat()
                            del conversation_state[active_conv_id]
                            await manager.broadcast_to_frontends({"type": "full_update"})

    except WebSocketDisconnect:
        if session_id in accounts_db: accounts_db[session_id]["status"] = "Erro"
        await manager.broadcast_to_frontends({"type": "full_update"})
        manager.disconnect_bot(session_id)
    except Exception as e:
        if system_config.debug_mode:
            print(f"[‼️ ERRO INESPERADO] no websocket de {session_id}: {e}")
        if session_id in accounts_db: accounts_db[session_id]["status"] = "Erro"
        await manager.broadcast_to_frontends({"type": "full_update"})
