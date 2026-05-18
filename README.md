# Telegram Prompt Lab Bot

Мини-бот Telegram на Python: обычный диалог с контекстом + яркая фича для портфолио — `/compare`, сравнение трёх режимов ответа модели.

Проект сделан под учебное задание: `aiogram` + OpenAI API, контекст в памяти, `.env`, логирование ошибок и параметров, README-отчёт с таблицей прогонов.

## Что умеет бот

- Ведёт обычный диалог с пользователем.
- Хранит последние сообщения каждого пользователя в RAM (`dict` внутри `ContextManager`).
- Очищает контекст по `/reset` или фразе `очистить контекст`.
- Команда `/compare <запрос>` запускает один и тот же запрос в 3 режимах:
  - `compact` — сжато и по делу;
  - `balanced` — структурно и достаточно подробно;
  - `creative` — более образно и презентабельно.
- Логирует:
  - параметры запроса: model, planned/actual temperature, reasoning effort, max_output_tokens, режим;
  - response status и incomplete reason;
  - usage tokens;
  - response_id;
  - ориентировочную стоимость;
  - ошибки API.
- Команда `/stats` показывает токены и стоимость за текущий запуск бота.

## Что улучшено после тестового запуска

В первом тесте модель отклонила `temperature`, а часть ответов оказалась обрезанной или пустой из-за слишком малого `max_output_tokens`. В этой версии исправлено:

1. Подобраны более безопасные и при этом компактные лимиты `max_output_tokens`:
   - compact: `800`;
   - balanced: `1100`;
   - creative: `1000`;
   - обычный диалог по умолчанию: `1200`.
2. Краткость `compact` задаётся не жёстким маленьким лимитом, а инструкцией: максимум 5 предложений.
3. Добавлен `reasoning.effort` как современный управляемый параметр для reasoning/GPT-5 моделей:
   - compact: `minimal`;
   - balanced: `low`;
   - creative: `low`.
4. Добавлен fallback, если модель или аккаунт отклоняет:
   - `temperature`;
   - `reasoning.effort`.
5. Добавлена диагностика `response.status` и `incomplete_details.reason`.
6. Если модель вернула пустой видимый текст, бот теперь показывает понятную причину вместо загадочного `[Пустой ответ модели]`.

## Дополнительная полировка после второго теста

После повторного теста `/compare Объясни Docker Compose простыми словами` бот успешно вернул все три режима со статусом `completed`.

Дополнительно были внесены косметические правки:

- `creative`-режим ограничен по длине, чтобы ответ не превращался в слишком большой Telegram-текст;
- в compare-режимах запрещены финальные фразы вроде «если хочешь, могу...»;
- для Docker Compose бот предпочитает современный CLI-синтаксис `docker compose up`, а не legacy-вариант `docker-compose up`;
- длинные Telegram-сообщения теперь режутся аккуратнее: по абзацам, а не просто по количеству символов.


## Структура проекта

```text
.
├── bot.py              # основной Telegram-бот на aiogram
├── config.py           # настройки и переменные окружения
├── context_manager.py  # контекст пользователей и локальная статистика
├── api_client.py       # работа с OpenAI Responses API
├── requirements.txt
├── .env.example
├── .gitignore
├── logs/.gitkeep
└── README.md
```

## Технологии

- Python 3.10+
- aiogram 3.x
- OpenAI Python SDK
- OpenAI Responses API
- python-dotenv

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполни `.env`:

```env
BOT_TOKEN=токен_из_BotFather
OPENAI_API_KEY=твой_openai_api_key
OPENAI_MODEL=gpt-5-mini-2025-08-07
```

Запуск:

```bash
python bot.py
```

Если появляется ошибка `ModuleNotFoundError: No module named 'aiogram'`, значит зависимости установлены не в то окружение или окружение не активировано:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python bot.py
```

## Команды бота

```text
/start                      # приветствие
/help                       # справка
/reset                      # очистить контекст и статистику
/stats                      # статистика токенов за текущий запуск
/compare <текст запроса>    # сравнить 3 режима генерации
```

Также работает фраза:

```text
очистить контекст
```

## Пример использования `/compare`

```text
/compare Объясни Docker Compose простыми словами
```

Бот вернёт 3 ответа: compact, balanced, creative, а ниже таблицу параметров:

```text
№ | режим | temp план/факт | effort | max_tokens | статус | эффект | tokens | cost | response_id
1 | compact  | 0.2/— | minimal | 800  | completed | сжатость через инструкцию | 274 | $0.000312 | resp_...
2 | balanced | 0.5/— | low     | 1100 | completed | баланс ясности и полноты   | 509 | $0.000782 | resp_...
3 | creative | 0.9/— | low     | 1000 | completed | образный стиль             | 813 | $0.001376 | resp_...
```

`temp план/факт` показывает две вещи:

- плановое значение из учебного эксперимента;
- фактически применённое значение.

Если модель отклонила `temperature`, в фактическом значении будет `—`, а в таблице появится предупреждение.

Полные usage-записи сохраняются в:

```text
logs/usage.jsonl
```

Ошибки и параметры запросов сохраняются в:

```text
logs/bot.log
```

## Таблица для отчёта

После теста скопируй реальные значения из ответа `/compare` или из `logs/usage.jsonl`.

| Модель | Temperature план/факт | Reasoning effort | Max tokens / max_output_tokens | № прогона | Получившийся эффект | Status | Input tokens | Output tokens | Total tokens | Ориентировочная стоимость | Response ID |
|---|---:|---|---:|---:|---|---|---:|---:|---:|---:|---|
| gpt-5-mini-2025-08-07 | 0.2 / заменить | minimal | 800 | 1 | Сжатый ответ, максимум 4-5 предложений | заменить | заменить | заменить | заменить | заменить | заменить |
| gpt-5-mini-2025-08-07 | 0.5 / заменить | low | 1100 | 2 | Более полный и структурный ответ | заменить | заменить | заменить | заменить | заменить | заменить |
| gpt-5-mini-2025-08-07 | 0.9 / заменить | low | 1000 | 3 | Образный ответ с одной аналогией или мини-примером | заменить | заменить | заменить | заменить | заменить | заменить |

> Примечание: в OpenAI Responses API параметр называется `max_output_tokens`. В таблице он указан также как `max_tokens`, потому что такое название использовано в задании.

## Как интерпретировать temperature в этом проекте

В задании требуется таблица `модель → temperature → max_tokens → № прогона → эффект → токены → стоимость`.

На практике некоторые GPT/reasoning-модели могут отклонять ручную настройку `temperature`. Поэтому бот работает честно:

- сохраняет `planned_temperature` — значение, которое мы хотели проверить;
- сохраняет `actual_temperature` — значение, которое реально ушло в успешный API-запрос;
- если модель отклоняет `temperature`, бот повторяет запрос без неё и пишет предупреждение.

Таким образом проект не падает во время демонстрации и показывает production-подход: planned vs actual parameters.

## Что делать, если ответ обрезался

Если в Telegram или `logs/usage.jsonl` видно:

```text
response_status=incomplete
incomplete_reason=max_output_tokens
```

значит лимит ответа оказался слишком маленьким. Увеличь значения в `api_client.py` для нужного режима или сократи запрос.

В этой версии лимиты уже повышены по сравнению с первой сборкой, поэтому для обычных учебных запросов вроде объяснения Docker Compose пустых ответов быть не должно.

## Скрин Usage / ID запросов

Для сдачи можно приложить:

1. Скриншот Usage в кабинете OpenAI после теста.
2. Или `response_id` из Telegram-ответа `/compare` / файла `logs/usage.jsonl`.

Пример строки из `logs/usage.jsonl`:

```json
{"event":"openai_response","mode":"compact","model":"gpt-5-mini-2025-08-07","planned_temperature":0.2,"actual_temperature":null,"reasoning_effort":"minimal","max_output_tokens":900,"response_status":"completed","incomplete_reason":null,"input_tokens":123,"output_tokens":598,"total_tokens":721,"estimated_cost_usd":0.000843,"response_id":"resp_...","warning":"temperature был отклонён моделью; запрос повторён без temperature"}
```

## Особенности реализации

### Почему Responses API

В проекте используется современный OpenAI Responses API вместо старого `ChatCompletion.create`.
Это лучше подходит для актуальных GPT-5/reasoning-моделей и нового SDK.

### Контекст

Контекст хранится только в памяти процесса:

```python
_contexts: dict[int, list[Message]]
```

Это соответствует заданию и упрощает проект. После перезапуска бота контекст очищается.

### Защита от переполнения контекста

В `.env` можно настроить:

```env
CONTEXT_MAX_MESSAGES=12
MAX_ASSISTANT_CONTEXT_CHARS=1800
```

Бот хранит только последние сообщения и обрезает длинные ответы перед сохранением в контекст.

### Логирование

В логах по умолчанию Telegram user_id хешируется:

```env
HASH_USER_IDS_IN_LOGS=true
LOG_SALT=change-me-before-demo
```

Это выглядит аккуратнее для GitHub и демонстрирует базовую заботу о приватности.

### Fallback для optional-параметров

Некоторые модели могут не поддерживать `temperature` или `reasoning.effort`. Если API вернёт ошибку по одному из этих параметров, бот повторит запрос без него и отметит это в usage.

`.env` настройки:

```env
RETRY_WITHOUT_TEMPERATURE=true
RETRY_WITHOUT_REASONING=true
```

## Как подготовить zip для сдачи

Перед упаковкой убедись, что в архив не попал `.env` с реальными ключами.

```bash
zip -r telegram-prompt-lab-bot.zip . -x ".env" "logs/*.log" "logs/*.jsonl" "__pycache__/*" ".venv/*"
```

## Идея для GitHub-описания

> Telegram Prompt Lab Bot — мини-бот на aiogram, который не просто отвечает через OpenAI API, а сравнивает режимы ответа compact / balanced / creative. Проект показывает работу с контекстом, OpenAI Responses API, planned vs actual параметрами модели, логированием usage tokens, диагностикой incomplete responses и оценкой стоимости запросов.
