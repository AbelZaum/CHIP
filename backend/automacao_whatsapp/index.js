// ARQUIVO: backend/automacao_whatsapp/index.js

const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const WebSocket = require('ws');
const fs = require('fs');
const path = require('path');

const sessionId = process.argv[2];
if (!sessionId) {
    console.error('Erro: ID da sessão não fornecido.');
    process.exit(1);
}

const client = new Client({
    authStrategy: new LocalAuth({ clientId: sessionId }),
    puppeteer: { 
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
        timeout: 120000 
    },
    // --- CORREÇÃO ADICIONADA PARA ESTABILIDADE DO QR CODE ---
    // Força o uso de uma versão estável do WhatsApp Web em cache
    // para evitar problemas de atualização e garantir que o QR Code seja sempre gerado.
    webVersionCache: {
        type: 'remote',
        remotePath: 'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/2.2412.54.html'
    }
});

let ws;

function connectWebSocket() {
    ws = new WebSocket(`ws://127.0.0.1:8000/ws/automacao/${sessionId}`);

    ws.on('open', () => {
        console.log(`[BOT ${sessionId}] Conectado ao Cérebro (API Python).`);
        ws.send(JSON.stringify({ type: 'status', message: 'Bot iniciado', status: 'Iniciando' }));
    });

    ws.on('error', (error) => {
        console.error(`[BOT ${sessionId}] Erro de WebSocket: ${error.message}.`);
    });

    ws.on('close', () => {
        console.log(`[BOT ${sessionId}] Conexão com o Cérebro perdida. A tentar reconectar em 10s...`);
        setTimeout(connectWebSocket, 10000); 
    });

    ws.on('message', (data) => {
        try {
            const command = JSON.parse(data);
            if (command.type === 'send_message') {
                console.log(`[BOT ${sessionId}] Recebeu ordem para enviar "${command.text}" para ${command.to}`);
                client.sendMessage(command.to, command.text);
            } else if (command.type === 'send_audio') {
                console.log(`[BOT ${sessionId}] Recebeu ordem para enviar áudio "${command.audio_file}" para ${command.to}`);
                
                const audioPath = path.join(__dirname, 'audios', command.audio_file);
                
                if (fs.existsSync(audioPath)) {
                    const audioMedia = MessageMedia.fromFilePath(audioPath);
                    client.sendMessage(command.to, audioMedia, { sendMediaAsDocument: false, caption: command.caption || undefined });
                    console.log(`[BOT ${sessionId}] Áudio "${command.audio_file}" enviado com sucesso!`);
                } else {
                    console.log(`[BOT ${sessionId}] Ficheiro de áudio não encontrado: ${audioPath}. A enviar texto alternativo.`);
                    const fallbackMessage = command.caption ? `🎵 ${command.caption}` : `(áudio)`;
                    client.sendMessage(command.to, fallbackMessage);
                }
            }
        } catch (error) {
            console.error(`[BOT ${sessionId}] Erro ao processar comando do Cérebro:`, error);
        }
    });
}


client.on('qr', (qr) => {
    console.log(`[BOT ${sessionId}] QR Code gerado.`);
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'qr', data: qr }));
    }
});

client.on('ready', () => {
    const botNumber = client.info.wid.user;
    console.log(`[BOT ${sessionId}] Cliente conectado! Número: ${botNumber}`);
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'status', message: 'Conectado!', status: 'Online', numero: botNumber }));
    }
});

client.on('message', (message) => {
    if (message.from.endsWith('@g.us')) return;

    const messageContent = message.body || (message.hasMedia ? '[MÍDIA RECEBIDA]' : '');
    console.log(`[BOT ${sessionId}] Mensagem recebida de ${message.from}: "${messageContent}"`);
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'message_received', from: message.from, text: messageContent }));
    }
});

client.on('auth_failure', (msg) => {
    console.error(`[BOT ${sessionId}] FALHA DE AUTENTICAÇÃO!`, msg);
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'status', message: 'Falha de Autenticação', status: 'Erro' }));
    }
});

client.on('disconnected', (reason) => {
    console.log(`[BOT ${sessionId}] Cliente desconectado! Razão:`, reason);
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'status', message: 'Desconectado, a tentar reconectar...', status: 'Erro' }));
    }
    
    console.log(`[BOT ${sessionId}] A tentar reconectar o WhatsApp em 15 segundos...`);
    setTimeout(() => {
        client.initialize();
    }, 15000);
});

// Inicia a conexão do WebSocket e a inicialização do cliente
connectWebSocket();
client.initialize();
