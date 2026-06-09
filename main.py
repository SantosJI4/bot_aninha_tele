import os
import sqlite3
import logging
import asyncio
from typing import Dict
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
import uvicorn
import stripe
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Configuração de Logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()

# Validação de Variáveis de Ambiente
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUCCESS_URL = os.getenv("SUCCESS_URL", "https://bot-giulia-vip.squareweb.app/sucesso")
CANCEL_URL = os.getenv("CANCEL_URL", "https://bot-giulia-vip.squareweb.app/cancelado")

if not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET or not TELEGRAM_TOKEN:
    logger.error("ERRO: Variáveis de ambiente críticas (STRIPE/TELEGRAM) não configuradas.")
    exit(1)

stripe.api_key = STRIPE_SECRET_KEY

# Diretório de Produtos Fixos
PRODUCTS_DIR = os.path.join(os.path.dirname(__file__), 'produtos')
if not os.path.exists(PRODUCTS_DIR):
    os.makedirs(PRODUCTS_DIR)

# --- BANCO DE DADOS SQLITE ---
DB_PATH = './bot.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Users (
            id TEXT PRIMARY KEY,
            is_vip INTEGER DEFAULT 0,
            name TEXT,
            email TEXT,
            phone TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_user(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO Users (id) VALUES (?)", (user_id,))
        conn.commit()
        cursor.execute("SELECT * FROM Users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
    conn.close()
    return dict(user)

def update_user(user_id: str, fields: dict):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    query = f"UPDATE Users SET {', '.join([f'{k} = ?' for k in fields.keys()])} WHERE id = ?"
    cursor.execute(query, list(fields.values()) + [user_id])
    conn.commit()
    conn.close()

# --- CATALOGO DE PRODUTOS ---
CATALOGO_PRODUTOS = {
    '1': {
        'nome': "Ebooks diversos",
        'subcategorias': {
            '1': {
                'nome': "Receitas",
                'produtos': {
                    '1': { 
                        'nome': "Como Fazer um Bolo Perfeito", 
                        'preco': 1500, 
                        'descricao': "Aprenda confeitaria do zero.",
                        'tipoEntrega': "arquivo",
                        'payload': "ebooks/receitas/como_fazer_um_bolo.pdf" 
                    }
                }
            },
            '2': {
                'nome': "Livros Técnicos",
                'produtos': {
                    '1': { 
                        'nome': "Clean Code", 
                        'preco': 4500, 
                        'descricao': "Manual de artesanato de software.",
                        'tipoEntrega': "arquivo",
                        'payload': "ebooks/livros/clean_code.pdf" 
                    }
                }
            }
        }
    },
    '2': {
        'nome': "Cybersecurity",
        'subcategorias': {
            '1': {
                'nome': "Livros e Manuais",
                'produtos': {
                    '1': { 
                        'nome': "Hacking com Kali Linux Técnicas práticas", 
                        'preco': 2489, 
                        'descricao': "Aprenda a usar o Kali Linux para testes de invasão.",
                        'tipoEntrega': "arquivo",
                        'payload': "cybersecurity/Hacking com Kali Linux Técnicas práticas para testes de invasão (James Broad Andrew Bindner [Broad, James]).pdf" 
                    },
                    '2': {
                        'nome': "Livro - Programação Avançada em Lua assembly",
                        'preco': 2489,
                        'descricao': "Aprenda a programar em Lua assembly para segurança ofensiva.",
                        'tipoEntrega': "arquivo",
                        'payload': "cybersecurity/Livro - Programação Avançada em Lua assembly.pdf"
                    }
                }
            }
        }
    },
    '3': {
        'nome': "Pendrives de musicas",
        'subcategorias': {
            '1': {
                'nome': "Playlists 2026",
                'produtos': {
                    '1': { 
                        'nome': "Pendrive 8GB - Top Hits 2026", 
                        'preco': 1299, 
                        'descricao': "Melhor playlist do ano!",
                        'tipoEntrega': "link", 
                        'payload': "https://drive.google.com/drive/folders/12OMdWH2GoJEm3a-w4eYC8Y2teY6MZQgL" 
                    },
                    '2': { 
                        'nome': "Pendrive 16GB - Hits 2026", 
                        'preco': 2489, 
                        'descricao': "Mais música, mais memória! atualizadinha!",
                        'tipoEntrega': "link", 
                        'payload': "https://drive.google.com/drive/folders/12OMdWH2GoJEm3a-w4eYC8Y2teY6MZQgL" 
                    },
                    '3': { 
                        'nome': "Festa junina 2026 - Pendrive 16GB [em alta 🔥]", 
                        'preco': 1669, 
                        'descricao': "Melhores musicas de festa junina 2026.",
                        'tipoEntrega': "link", 
                        'payload': "https://drive.google.com/drive/folders/12OMdWH2GoJEm3a-w4eYC8Y2teY6MZQgL" 
                    }
                }
            }
        }
    },
    '4': {
        'nome': "Cursos Onlines",
        'subcategorias': {
            '1': {
                'nome': "Cursos tecnico",
                'produtos': {
                    '1': { 'nome': "curso de eletricista residencial - Telegram", 'preco': 2599, 'descricao': "Curso completo, do zero.", 'tipoEntrega': "link", 'payload': "https://t.me/+yZVCSvSwWQw0OTMx" },
                    '2': { 'nome': "Curso de CFTV - Instalação de câmeras", 'preco': 2489, 'descricao': "Instalação e manutenção.", 'tipoEntrega': "link", 'payload': "https://t.me/+5sECAlTDCOhlZGVh" },
                    '3': { 'nome': "Técnicas de invasão de redes sem fios", 'preco': 1089, 'descricao': "Segurança ofensiva e pentesting.", 'tipoEntrega': "link", 'payload': "https://t.me/joinchat/ykYpDxojm3BhY2Jh" },
                    '4': { 'nome': "Técnico em energia solar", 'preco': 1089, 'descricao': "Curso prático completo.", 'tipoEntrega': "link", 'payload': "https://t.me/+kLGNRAefxj84YTIx" },
                    '5': { 'nome': "Aprenda criar jogos na godot 3.2", 'preco': 1089, 'descricao': "Desenvolvimento de jogos com GDscript.", 'tipoEntrega': "link", 'payload': "https://t.me/+Vmn5iCWjMp84MzY5" },
                    '6': { 'nome': "Ethical Hacking e Pentest Profissional", 'preco': 1089, 'descricao': "Seja um pentester profissional.", 'tipoEntrega': "link", 'payload': "https://t.me/joinchat/s4AU2k6uv6tkM2Ux" },
                    '7': { 'nome': "Design IA - Curso", 'preco': 1099, 'descricao': "Criação de designs assistidos por IA.", 'tipoEntrega': "link", 'payload': "https://t.me/joinchat/c1SQzLAKXpRkMWRh" }
                }
            },
            '2': {
                'nome': "Cursos Desenvolvimento Pessoal",
                'produtos': {
                    '1': { 'nome': "A Arte da Imperfeição", 'preco': 1299, 'descricao': "Superar o medo do fracasso.", 'tipoEntrega': "link", 'payload': "https://t.me/+mGtLGbRVBcAyMDE0" },
                    '2': { 'nome': "Crescimento Acelerado com IA", 'preco': 1299, 'descricao': "Estratégias eficazes com IA.", 'tipoEntrega': "link", 'payload': "https://t.me/joinchat/iXWB7nLxxvgwN2Ix" },
                    '3': { 'nome': "Maestria Emocional Para Homens", 'preco': 1299, 'descricao': "Dominar suas emoções com resiliência.", 'tipoEntrega': "link", 'payload': "https://t.me/+Tfgzghe0FTg5YzAx" },
                    '4': { 'nome': "Autoconhecimento Pedro Calabrez", 'preco': 1299, 'descricao': "Insights profundos para transformar sua vida.", 'tipoEntrega': "link", 'payload': "https://t.me/+w2o65G-G_xNmOWRh" },
                    '5': { 'nome': "Nomade Milionário - Thiago Finch", 'preco': 1299, 'descricao': "Construir liberdade financeira.", 'tipoEntrega': "link", 'payload': "https://t.me/+xOgPvKe872I3ZTdh" }
                }
            }
        }
    },
}

# --- APLICATIVO DO TELEGRAM ---
telegram_app: Application = None

# --- HANDLERS DO BOT ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user(str(update.effective_user.id))
    welcome_text = (
        "🤖 *Menu do Bot*\n\n"
        "🟢 `/comprar` - Loja de Produtos\n"
        "📊 `/status` - Seu Status da conta\n"
        "👑 `/sobrevip` - Vantagens do plano VIP\n"
        "💳 `/comprarvip` - Assinar Plano VIP"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = get_user(user_id)
    
    if user['is_vip']:
        text = "👑 *Status VIP Ativo!* Você tem acesso ilimitado aos recursos."
    else:
        text = "📊 *Seu Status (Grátis):*\nVocê pode realizar compras na nossa loja usando o comando `/comprar`."
    await update.message.reply_text(text, parse_mode="Markdown")

async def sobrevip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👑 *VANTAGENS DO VIP*\n"
        "♾️ Consultas e interações prioritárias na nossa rede\n"
        "🔥 Descontos exclusivos em lançamentos futuros\n\n"
        "Para assinar, use o formato exato:\n"
        "`/comprarvip Nome | Email | Telefone`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def comprarvip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    raw_args = update.message.text.replace('/comprarvip', '').strip()
    
    args = [s.strip() for s in raw_args.split('|') if s.strip()]
    if len(args) < 3:
        await update.message.reply_text("❌ *Formato inválido!* Use:\n`/comprarvip Nome | Email | Telefone`", parse_mode="Markdown")
        return

    name, email, phone = args[0], args[1], args[2]
    update_user(user_id, {"name": name, "email": email, "phone": phone})
    
    await update.message.reply_text("⏳ Gerando seu link de checkout seguro via Stripe...")
    
    try:
        session = stripe.checkout.Session.create(
            line_items=[{
                'price_data': {
                    'currency': 'brl',
                    'product_data': {'name': 'Acesso VIP', 'description': 'Benefícios exclusivos no Bot'},
                    'unit_amount': 1199, # R$ 11.99
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=SUCCESS_URL,
            cancel_url=CANCEL_URL,
            metadata={'telegram_id': user_id, 'tipo_compra': 'vip'}
        )
        await update.message.reply_text(f"Prontinho, {name}! 💳\nPague no link abaixo:\n🔗 {session.url}")
    except Exception as e:
        logger.error(f"Erro Stripe VIP: {e}")
        await update.message.reply_text("❌ Erro ao gerar link de pagamento.")

async def comprar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for cat_id, cat in CATALOGO_PRODUTOS.items():
        keyboard.append([InlineKeyboardButton(cat['nome'], callback_data=f"cat_{cat_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🛍️ *LOJA DO BOT - CATEGORIAS* 🛍️\nSelecione a categoria desejada:", reply_markup=reply_markup, parse_mode="Markdown")

async def loja_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = str(query.from_user.id)

    if data.startswith("cat_"):
        cat_id = data.split("_")[1]
        categoria = CATALOGO_PRODUTOS.get(cat_id)
        
        keyboard = []
        for sub_id, sub in categoria['subcategorias'].items():
            keyboard.append([InlineKeyboardButton(sub['nome'], callback_data=f"sub_{cat_id}_{sub_id}")])
        keyboard.append([InlineKeyboardButton("⬅️ Voltar", callback_data="voltar_cat")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"📁 *Subcategorias de: {categoria['nome']}*", reply_markup=reply_markup, parse_mode="Markdown")

    elif data == "voltar_cat":
        keyboard = []
        for cat_id, cat in CATALOGO_PRODUTOS.items():
            keyboard.append([InlineKeyboardButton(cat['nome'], callback_data=f"cat_{cat_id}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🛍️ *LOJA DO BOT - CATEGORIAS* 🛍️\nSelecione a categoria desejada:", reply_markup=reply_markup, parse_mode="Markdown")

    elif data.startswith("sub_"):
        _, cat_id, sub_id = data.split("_")
        subcategoria = CATALOGO_PRODUTOS[cat_id]['subcategorias'][sub_id]
        
        keyboard = []
        for prod_id, prod in subcategoria['produtos'].items():
            txt = f"{prod['nome']} - R$ {prod['preco']/100:.2f}"
            keyboard.append([InlineKeyboardButton(txt, callback_data=f"buy_{cat_id}_{sub_id}_{prod_id}")])
        keyboard.append([InlineKeyboardButton("⬅️ Voltar", callback_data=f"cat_{cat_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"🛍️ *Produtos em: {subcategoria['nome']}*", reply_markup=reply_markup, parse_mode="Markdown")

    elif data.startswith("buy_"):
        _, cat_id, sub_id, prod_id = data.split("_")
        produto = CATALOGO_PRODUTOS[cat_id]['subcategorias'][sub_id]['produtos'][prod_id]
        
        await query.edit_message_text(f"⏳ Gerando link de checkout para: *{produto['nome']}*...", parse_mode="Markdown")
        
        try:
            session = stripe.checkout.Session.create(
                line_items=[{
                    'price_data': {
                        'currency': 'brl',
                        'product_data': {'name': produto['nome'], 'description': produto['descricao']},
                        'unit_amount': produto['preco'],
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=SUCCESS_URL,
                cancel_url=CANCEL_URL,
                metadata={
                    'telegram_id': user_id,
                    'tipo_compra': 'produto',
                    'category_id': cat_id,
                    'subcategory_id': sub_id,
                    'product_id': prod_id
                }
            )
            
            pay_keyboard = [[InlineKeyboardButton("💳 Pagar Agora", url=session.url)]]
            markup = InlineKeyboardMarkup(pay_keyboard)
            await query.message.reply_text(
                f"🛒 *Pedido Gerado!*\n\n*Produto:* {produto['nome']}\n*Valor:* R$ {produto['preco']/100:.2f}\n\nClique no botão abaixo para concluir:",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Erro Stripe Produto: {e}")
            await query.message.reply_text("❌ Erro ao processar o link de pagamento.")


# --- CONFIGURAÇÃO DO LIFESPAN DO FASTAPI (Instanciado antes de usar as rotas!) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app
    # Inicializa o bot do Telegram usando a instância global de loop existente
    telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("ajuda", start_command))
    telegram_app.add_handler(CommandHandler("status", status_command))
    telegram_app.add_handler(CommandHandler("sobrevip", sobrevip_command))
    telegram_app.add_handler(CommandHandler("comprarvip", comprarvip_command))
    telegram_app.add_handler(CommandHandler("comprar", comprar_command))
    telegram_app.add_handler(CallbackQueryHandler(loja_callback))
    
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Bot do Telegram inicializado com sucesso em segundo plano!")
    
    yield  # Mantém o FastAPI servindo as requisições HTTP do Webhook
    
    if telegram_app:
        logger.info("Encerrando recursos assíncronos do Bot...")
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()


# --- DEFINIÇÃO DO APLICATIVO FASTAPI ---
app = FastAPI(lifespan=lifespan)


# --- ENTREGA ASSÍNCRONA ---
async def enviar_entrega_assincrona(telegram_id: str, metadata: dict):
    tipo_compra = metadata.get("tipo_compra")
    bot = telegram_app.bot

    if tipo_compra == "vip":
        update_user(telegram_id, {"is_vip": 1})
        await bot.send_message(
            chat_id=int(telegram_id),
            text="🎉 *PAGAMENTO APROVADO!* 🎉\n\nSeja muito bem-vindo ao VIP! Seu acesso vitalício está ativo. Digite `/sobrevip` para ver os detalhes.",
            parse_mode="Markdown"
        )
    elif tipo_compra == "produto":
        cat_id = metadata.get("category_id")
        sub_id = metadata.get("subcategory_id")
        prod_id = metadata.get("product_id")
        
        produto = CATALOGO_PRODUTOS.get(cat_id, {}).get('subcategorias', {}).get(sub_id, {}).get('produtos', {}).get(prod_id)
        if not produto:
            await bot.send_message(chat_id=int(telegram_id), text="✅ Pagamento aprovado, mas houve um erro ao localizar seu produto. Chame o suporte!")
            return

        await bot.send_message(chat_id=int(telegram_id), text=f"🎉 *PAGAMENTO APROVADO!* 🎉\n\nEntrega iniciada para o produto: *{produto['nome']}*", parse_mode="Markdown")
        
        if produto['tipoEntrega'] == 'link':
            await bot.send_message(chat_id=int(telegram_id), text=f"🔗 *Acesse seu produto aqui:*\n{produto['payload']}")
        elif produto['tipoEntrega'] == 'arquivo':
            file_path = os.path.join(PRODUCTS_DIR, produto['payload'])
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    await bot.send_document(chat_id=int(telegram_id), document=f, caption="📦 *Arquivo entregue com sucesso!* Bom proveito.", write_timeout=60)
            else:
                logger.error(f"Arquivo ausente: {file_path}")
                await bot.send_message(chat_id=int(telegram_id), text="❌ *Erro interno:* O arquivo físico do produto não foi localizado no servidor. Contate o suporte.")


# --- ROTAS DA API DO WEBHOOK ---
@app.post("/webhook")
async def stripe_webhook(request: Request):
    # 1. Pega os bytes brutos do corpo da requisição
    body_bytes = await request.body()
    # 2. Converte para string pura UTF-8, essencial para bater o hash da assinatura
    payload = body_bytes.decode("utf-8")
    
    sig_header = request.headers.get("stripe-signature")

    try:
        # AQUI ESTÁ A SOLUÇÃO DEFINITIVA: Webhook com 'W' maiúsculo
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        logger.error(f"Erro na validação do Webhook: {e}")
        raise HTTPException(status_code=400, detail=f"Erro de assinatura: {str(e)}")

    # 3. Processamento do evento igualzinho ao seu código em Node.js
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})
        telegram_id = metadata.get("telegram_id")
        
        if telegram_id:
            # Dispara a entrega em segundo plano para o FastAPI responder 200 OK imediatamente para a Stripe
            asyncio.create_task(enviar_entrega_assincrona(telegram_id, metadata))
            logger.info(f"Entrega agendada via asyncio com sucesso para o ID: {telegram_id}")

    return {"received": True}

@app.get("/sucesso", response_class=HTMLResponse)
async def sucesso():
    return """
    <html>
        <head>
            <title>Sucesso</title>
            <meta charset="utf-8">
        </head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px; background-color: #121212; color: #ffffff;">
            <h1 style="color: #2ecc71;">✅ Pagamento Aprovado!</h1>
            <p style="font-size: 18px;">O seu produto ou acesso VIP já foi liberado no Telegram.</p>
            <p style="color: #aaaaaa;">Você já pode fechar esta aba e retornar ao chat.</p>
        </body>
    </html>
    """

@app.get("/cancelado", response_class=HTMLResponse)
async def cancelado():
    return """
    <html>
        <head>
            <title>Cancelado</title>
            <meta charset="utf-8">
        </head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px; background-color: #121212; color: #ffffff;">
            <h1 style="color: #e74c3c;">❌ Pagamento Cancelado</h1>
            <p style="font-size: 18px;">A operação foi cancelada e nenhuma cobrança foi realizada.</p>
            <p style="color: #aaaaaa;">Se precisar, basta iniciar o pedido novamente pelo menu do bot.</p>
        </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 80)), reload=False)