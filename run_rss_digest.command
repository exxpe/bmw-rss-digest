#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "======================================"
echo "  BMW RSS Digest"
echo "======================================"
echo ""
echo "Папка скрипта: $SCRIPT_DIR"
echo ""

python3 "$SCRIPT_DIR/bmw_rss_digest.py" "$@"

echo ""
echo "======================================"
echo "  Готово. Можно закрыть окно."
echo "======================================"
echo ""
read -p "Нажми Enter для закрытия..."
