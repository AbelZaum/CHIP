// ARQUIVO: backend/automacao_whatsapp/index.js

const { Client, LocalAuth } = require('whatsapp-web.js');
const WebSocket = require('ws');

const sessionId = process.argv[2];
if (!sessionId) {
    console.error('Erro: ID da sessão não fornecido.');
    process.exit(1);
}

const client = new Client({
    authStrategy: new LocalAuth({ clientId: sessionId }),
    puppeteer: { args: ['--no-sandbox', '--disable-setuid-sandbox'] }
});

const ws = new WebSocket(`ws://127.0.0.1:8000/ws/automacao/${sessionId}`);

ws.on('open', () => {
    console.log(`[BOT ${sessionId}] Conectado ao Cérebro (API Python).`);
    ws.send(JSON.stringify({ type: 'status', message: 'Bot iniciado', status: 'Iniciando' }));
});

ws.on('error', (error) => console.error(`[BOT ${sessionId}] Erro de WebSocket:`, error));

ws.on('message', (data) => {
    const command = JSON.parse(data);
    if (command.type === 'send_message') {
        console.log(`[BOT ${sessionId}] Recebeu ordem para enviar "${command.text}" para ${command.to}`);
        client.sendMessage(command.to, command.text);
    }
});

client.on('qr', (qr) => {
    console.log(`[BOT ${sessionId}] QR Code gerado.`);
    ws.send(JSON.stringify({ type: 'qr', data: qr }));
});

client.on('ready', () => {
    const botNumber = client.info.wid.user;
    console.log(`[BOT ${sessionId}] Cliente conectado! Número: ${botNumber}`);
    ws.send(JSON.stringify({ type: 'status', message: 'Conectado!', status: 'Online', numero: botNumber }));
});

client.on('message', (message) => {
    console.log(`[BOT ${sessionId}] Mensagem recebida de ${message.from}: "${message.body}"`);
    if (!message.from.endsWith('@g.us')) {
        ws.send(JSON.stringify({ type: 'message_received', from: message.from, text: message.body }));
    }
});

client.on('disconnected', (reason) => {
    console.log(`[BOT ${sessionId}] Cliente desconectado!`, reason);
    ws.send(JSON.stringify({ type: 'status', message: 'Desconectado.', status: 'Offline' }));
    process.exit(1);
});

client.initialize();