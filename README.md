# BMW RSS Digest

Инструмент для мониторинга BMW-форумов (bimmerpost, 5post, 1addicts, m5post).
Фильтрует темы по ключевым словам (кодинг, тюнинг, ECU, прошивки и др.) и сохраняет дайджест в Markdown.

---

## Версии

### v3.0 — GUI + логирование + фильтр по дате
**Коммит:** `5098d40`
**Файлы:** `bmw_rss_digest.py` (обновлён), `bmw_rss_gui.py` (новый), `run_rss_gui.command` (новый)

Добавлен графический интерфейс и полное логирование.

**Что нового:**
- **GUI** (`bmw_rss_gui.py`) на tkinter — три вкладки: Feeds, Keywords, Settings
- Кнопка **▶ Run Digest** запускает обход лент в фоновом потоке
- **Фильтр по дате** — поля From / To в формате `YYYY-MM-DD`
- **Статистика** после запуска: сколько совпадений, из скольких лент, время
- **Цветной лог** в реальном времени (зелёный = INFO, жёлтый = WARNING, красный = ERROR)
- Кнопка **Open in Obsidian** — открывает последний дайджест прямо в Obsidian
- Кнопка **Open output folder** — открывает папку с дайджестами в Finder
- `bmw_rss_digest.py`: все `print()` заменены на `logging` с `RotatingFileHandler` (500 КБ × 3 архива), лог пишется в `bmw_rss.log`
- CLI: новые флаги `--from-date YYYY-MM-DD` и `--to-date YYYY-MM-DD`
- `run_digest()` возвращает dict со статистикой

**Запуск:**
```bash
python3 bmw_rss_gui.py          # GUI
# или двойной клик на run_rss_gui.command
```

---

### v2.0 — Архивный скрапер + расширение лент
**Коммит:** `b3cd46c`
**Файлы:** `bmw_scraper.py` (новый), `bmw_scraper_resume.py` (новый), `run_scraper.command` (новый), `bmw_rss_config.json` (расширен)

Добавлен скрапер для глубокого архивного поиска.

**Что нового:**
- `bmw_scraper.py` — парсит архивы форумов (vBulletin) за **3 года**, обходит пагинацию
- Фильтрация по ключевым словам, сохранение в месячные Markdown-файлы + полный JSON-индекс (`bmw_archive_index.json`)
- `bmw_scraper_resume.py` — продолжение прерванного скрапинга с последнего места
- Конфиг расширен: добавлены 14 новых лент (F87/F80/G80 M2/M3/M4, G05 X5, G20/G87 M2, F90/G90 M5)
- Лаунчеры `run_scraper.command` и `run_scraper_resume.command`

**Запуск:**
```bash
python3 bmw_scraper.py              # полный скрапинг
python3 bmw_scraper.py --stats      # статистика индекса
python3 bmw_scraper_resume.py       # продолжить с прерванного места
```

---

### v1.1 — Обход SSL
**Коммит:** `ab772b9`
**Файлы:** `bmw_rss_digest.py`

**Что нового:**
- Добавлен обход верификации SSL-сертификатов для macOS (`ssl._create_unverified_context`)
- Исправлена ошибка при обращении к форумам с самоподписанными сертификатами

---

### v1.0 — Первый релиз
**Коммит:** `5b2a8a1`
**Файлы:** `bmw_rss_digest.py`, `bmw_rss_config.json`

Базовый RSS-дайджест.

**Возможности:**
- Обход RSS-лент 6 форумов (F10, F20, F30, G30)
- Фильтрация по 23 ключевым словам (coding, ECU, DME, WinOLS, ISTA, E-Sys и др.)
- Сохранение дайджеста в `.md` файл с группировкой по лентам
- Фильтр по возрасту записей (`max_age_days`)
- CLI-команды: `--add-feed`, `--add-keyword`, `--remove-keyword`, `--list`

**Запуск:**
```bash
python3 bmw_rss_digest.py           # запустить дайджест
python3 bmw_rss_digest.py --list    # показать конфиг
```

---

## Быстрый старт

### Зависимости
Только стандартная библиотека Python 3.8+. Установка пакетов не нужна.

### Запуск GUI (рекомендуется)
```bash
python3 bmw_rss_gui.py
# или двойной клик на run_rss_gui.command
```

### Запуск из терминала
```bash
python3 bmw_rss_digest.py
python3 bmw_rss_digest.py --from-date 2026-03-01
python3 bmw_rss_digest.py --from-date 2026-01-01 --to-date 2026-03-01
```

---

## Структура проекта

```
bmw_rss_digest.py        # основной модуль: fetch → filter → save
bmw_rss_gui.py           # GUI-обёртка над digest
bmw_rss_config.json      # конфиг: ленты, ключевые слова, настройки
bmw_scraper.py           # архивный скрапер (глубокий поиск за 3 года)
bmw_scraper_resume.py    # продолжение прерванного скрапинга
bmw_archive_index.json   # JSON-индекс найденных тем (создаётся скрапером)
run_rss_digest.command   # лаунчер CLI-дайджеста (двойной клик)
run_rss_gui.command      # лаунчер GUI (двойной клик)
run_scraper.command      # лаунчер архивного скрапера
run_scraper_resume.command
bmw_rss.log              # лог-файл (создаётся автоматически, в git не включён)
```

---

## Конфиг (`bmw_rss_config.json`)

| Поле | Описание |
|------|----------|
| `feeds` | Список RSS-лент (`url` + `name`) |
| `keywords` | Ключевые слова для фильтрации |
| `output_dir` | Папка для сохранения дайджестов |
| `max_age_days` | Глубина поиска по умолчанию (дней) |

---

## Просмотр дайджестов

Дайджесты сохраняются как `.md` файлы в `~/bmw_rss_digests/`.
Рекомендуется открывать в **[Obsidian](https://obsidian.md)** — указать папку `~/bmw_rss_digests` как vault.
Или в VS Code: `Cmd+Shift+V` для превью.
