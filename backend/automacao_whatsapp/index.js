// ARQUIVO: backend/automacao_whatsapp/index.js

const { Client, LocalAuth } = require('whatsapp-web.js');
const WebSocket = require('ws');

const sessionId = process.argv[2];
if (!sessionId) {
    console.error('Erro: ID da sessão não fornecido.');
    process.exit(1);
}

console.log(`[BOT ${sessionId}] Iniciando...`);

const ws = new WebSocket(`ws://127.0.0.1:8000/ws/automacao/${sessionId}`);

ws.on('open', () => {
    console.log(`[BOT ${sessionId}] Conectado ao Cérebro (API Python).`);
    // CORREÇÃO: Adicionamos o campo "status" que estava faltando.
    ws.send(JSON.stringify({ type: 'status', message: 'Bot iniciado, aguardando QR Code.', status: 'Iniciando' }));
});

ws.on('error', (error) => {
    console.error(`[BOT ${sessionId}] Erro de WebSocket:`, error);
});

const client = new Client({
    authStrategy: new LocalAuth({ clientId: sessionId }),
    puppeteer: {
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
    }
});

client.on('qr', (qr) => {
    console.log(`[BOT ${sessionId}] QR Code gerado.`);
    ws.send(JSON.stringify({ type: 'qr', data: qr }));
});

client.on('ready', () => {
    const botNumber = client.info.wid.user;
    console.log(`[BOT ${sessionId}] Cliente conectado e pronto! Número: ${botNumber}`);
    ws.send(JSON.stringify({ type: 'status', message: 'Conectado com sucesso!', status: 'Online', numero: botNumber }));
});

client.on('disconnected', (reason) => {
    console.log(`[BOT ${sessionId}] Cliente foi desconectado!`, reason);
    ws.send(JSON.stringify({ type: 'status', message: 'Desconectado.', status: 'Offline' }));
    process.exit(1);
});

client.initialize();
