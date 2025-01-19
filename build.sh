#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

# Inicializa e executa as migrações do banco de dados
python -c "from app import db; db.create_all()" 