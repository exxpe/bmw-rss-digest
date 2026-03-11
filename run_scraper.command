#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "======================================"
echo "  BMW Forum Archive Scraper"
echo "======================================"
echo ""
echo "Папка скрипта: $SCRIPT_DIR"
echo "Период: 3 года"
echo ""

python3 "$SCRIPT_DIR/bmw_scraper.py" "$@"

echo ""
echo "======================================"
echo "  Готово. Можно закрыть окно."
echo "======================================"
echo ""
read -p "Нажми Enter для закрытия..."
