const express = require('express');
const wppconnect = require('@wppconnect-team/wppconnect');
const path = require('path');

// ==========================================================
// CONFIGURAÇÕES GERAIS
// ==========================================================

require('dotenv').config({ path: path.resolve(__dirname, '../.env') });

const app = express();
app.use(express.json());

const PORT = process.env.WPP_API_PORT || 3000;
const API_TOKEN = process.env.WPP_API_TOKEN
const MIN_DELAY = 10000; // 10 segundos
const MAX_DELAY = 25000; // 25 segundos

if (!API_TOKEN) {
    console.error("❌ ERRO CRÍTICO: WPP_API_TOKEN não definido no arquivo .env");
    process.exit(1);
}

let clientWpp = null;
const messageQueue = [];
let isProcessingQueue = false;

// ==========================================================
// FUNÇÕES UTILITÁRIAS
// ==========================================================
const getRandomDelay = () => {
  return Math.floor(Math.random() * (MAX_DELAY - MIN_DELAY + 1) + MIN_DELAY);
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ==========================================================
// PROCESSADOR DA FILA (O Cérebro do Anti-Ban)
// ==========================================================
async function processQueue() {
  if (isProcessingQueue || messageQueue.length === 0 || !clientWpp) {
    return;
  }

  isProcessingQueue = true;

  while (messageQueue.length > 0) {
    const item = messageQueue.shift(); 
    const { number, message } = item;
    
    try {
      const cleanNumber = number.toString().replace(/\D/g, '');
      const formattedNumber = `${cleanNumber}@c.us`;

      await clientWpp.sendText(formattedNumber, message);
      
      const timestamp = new Date().toLocaleTimeString();
      console.log(`[${timestamp}] ✅ Enviado para ${cleanNumber}. Restam na fila: ${messageQueue.length}`);

    } catch (error) {
      console.error(`[ERRO] Falha ao enviar para ${number}:`, error.message);
    }

    if (messageQueue.length > 0) {
      const delay = getRandomDelay();
      console.log(`⏳ Esperando ${Math.floor(delay / 1000)}s para o próximo envio...`);
      await sleep(delay);
    }
  }

  isProcessingQueue = false;
  console.log('🏁 Fila finalizada. Aguardando novas requisições.');
}

// ==========================================================
// INICIALIZAÇÃO DO WPPCONNECT
// ==========================================================
wppconnect
  .create({
    session: 'timesheet-session',
    logQR: true, 
    headless: true,
    devtools: false,
    useChrome: false,
    debug: false,
    catchQR: (base64Qr, asciiQR) => {
      console.log('📱 QR Code gerado. Escaneie no terminal ou via interface.');
    },
  })
  .then((client) => {
    clientWpp = client;
    console.log('\n===================================================');
    console.log(`✅ WhatsApp conectado! Modo Anti-Banimento Ativo.`);
    console.log(`🕒 Delay configurado: ${MIN_DELAY/1000}s a ${MAX_DELAY/1000}s.`);
    console.log(`🚀 Servidor rodando em http://localhost:${PORT}`);
    console.log('===================================================\n');
    
    processQueue();
  })
  .catch((error) => {
    console.log('Erro ao iniciar WPPConnect:', error);
    process.exit(1);
  });

// ==========================================================
// ROTA DE HEALTH CHECK (Monitoramento)
// ==========================================================
app.get('/health', (req, res) => {
  if (!clientWpp) {
    return res.status(503).json({ 
        status: 'starting', 
        message: 'Aguardando leitura do QR Code ou inicialização.' 
    });
  }
  
  return res.status(200).json({ 
      status: 'online', 
      queueSize: messageQueue.length 
  });
});

// ==========================================================
// ROTA DA API
// ==========================================================
app.post('/send-message', (req, res) => {
  const token = req.headers['x-api-token'];
  if (token !== API_TOKEN) {
    console.log(`[SEGURANÇA] Tentativa de acesso negada.`);
    return res.status(403).json({ status: 'error', message: 'Acesso negado.' });
  }

  if (!clientWpp) {
    return res.status(503).json({ status: 'error', message: 'WhatsApp ainda está inicializando. Tente novamente em breve.' });
  }

  const { number, message } = req.body;

  if (!number || !message) {
    return res.status(400).json({ status: 'error', message: 'Campos "number" e "message" são obrigatórios.' });
  }

  messageQueue.push({ number, message });
  
  console.log(`[RECEBIDO] Mensagem para ${number} entrou na fila. Posição: ${messageQueue.length}`);

  processQueue();

  return res.status(200).json({ 
    status: 'queued', 
    message: 'Mensagem colocada na fila de envio.',
    queueSize: messageQueue.length
  });
});

// ==========================================================
// INICIA O SERVIDOR EXPRESS
// ==========================================================
app.listen(PORT, () => {
  console.log(`Servidor HTTP ouvindo na porta ${PORT}`);
});