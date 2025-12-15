# IG → Telegram трекер кликов (Render)

Идея: ссылка в био Instagram ведёт на `/ig`. Мы логируем клик, затем перекидываем человека в Telegram-бота.
Когда человек нажимает **Start**, бот связывает клик с **Telegram user_id** (это и есть “кто именно”, насколько это возможно).

⚠️ Instagram **не отдаёт** список аккаунтов, которые нажали ссылку в био. Поэтому “кто именно” — это **Telegram-пользователь**, который дошёл до бота и нажал Start.

## 0) Что нужно заранее
- Telegram-бот (создаётся в @BotFather)
- Публичный Telegram-канал (ссылка `https://t.me/<channel>`)

## 1) Переменные окружения
Обязательные:
- `BOT_TOKEN` — токен бота от @BotFather
- `BOT_USERNAME` — username бота **без @**
- `CHANNEL_URL` — ссылка на твой канал
- `BASE_URL` — публичный URL сервиса на Render (например `https://xxx.onrender.com`)
- `ADMIN_TOKEN` — длинный секрет для админ-эндпоинтов

База данных:
- Рекомендуется на Render: **Postgres**. Render даст строку подключения в переменной `DATABASE_URL`.
- Для локального теста можно использовать SQLite (`TRACK_DB=./tracker.sqlite3`).

## 2) Render: деплой (Web Service)
1) Залей файлы в GitHub репозиторий
2) Render → **New** → **Web Service** → выбери репозиторий
3) Настройки:
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
4) Добавь переменные окружения (в Render → Environment)

## 3) Render: Postgres (опционально, но очень желательно)
Render → **New** → **PostgreSQL** → Free.
Потом в Web Service добавь `DATABASE_URL` (Render обычно умеет “Connect” и проставляет автоматически).

⚠️ На Free Postgres в Render есть срок жизни (expire) — см. их документацию; поэтому делай периодический экспорт CSV.

## 4) Включить вебхук Telegram
Открой в браузере:
`https://<BASE_URL>/admin/set_webhook?token=<ADMIN_TOKEN>`

## 5) Ссылки
- В Instagram био ставь: `https://<BASE_URL>/ig`
- CSV выгрузка: `https://<BASE_URL>/admin/csv?token=<ADMIN_TOKEN>`

## 6) Что считается “кто именно”
- Если человек **кликнул**, но не нажал **Start** в боте → это будет анонимный клик.
- Если нажал **Start** → появится `tg_user_id`, `tg_username`, имя/фамилия.
