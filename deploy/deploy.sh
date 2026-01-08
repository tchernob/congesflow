#!/bin/bash
# Script de déploiement TimeOff
# À exécuter sur le serveur DigitalOcean

set -e

APP_DIR="/home/tcher/timeoff"
REPO="https://github.com/tchernob/congesflow.git"

echo "=== Déploiement TimeOff ==="

# 1. Cloner ou mettre à jour le repo
if [ -d "$APP_DIR" ]; then
    echo "Mise à jour du code..."
    cd $APP_DIR
    git pull origin main
else
    echo "Clonage du repo..."
    git clone $REPO $APP_DIR
    cd $APP_DIR
fi

# 2. Créer/activer l'environnement virtuel
if [ ! -d "venv" ]; then
    echo "Création de l'environnement virtuel..."
    python3 -m venv venv
fi

source venv/bin/activate

# 3. Installer les dépendances
echo "Installation des dépendances..."
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

# 4. Créer le fichier .env si absent
if [ ! -f ".env" ]; then
    echo "Création du fichier .env..."
    cp .env.example .env
    echo ""
    echo "⚠️  IMPORTANT: Éditez /home/tcher/timeoff/.env avec vos valeurs !"
    echo ""
fi

# 5. Initialiser la base de données
if [ ! -f "instance/conges.db" ] && [ ! -f "conges.db" ]; then
    echo "Initialisation de la base de données..."
    python -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.create_all()"
    python run.py init-db
fi

# 6. Configurer les permissions
echo "Configuration des permissions..."
sudo chown -R tcher:www-data $APP_DIR
chmod -R 750 $APP_DIR

# 7. Copier et activer le service systemd
echo "Configuration du service systemd..."
sudo cp deploy/timeoff.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable timeoff
sudo systemctl restart timeoff

# 8. Configurer nginx
echo "Configuration nginx..."
sudo cp deploy/timeoff.nginx /etc/nginx/sites-available/timeoff
sudo ln -sf /etc/nginx/sites-available/timeoff /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

echo ""
echo "=== Déploiement terminé ==="
echo ""
echo "Prochaines étapes :"
echo "1. Éditez /home/tcher/timeoff/.env avec vos valeurs"
echo "2. Configurez le DNS Gandi (A record vers IP du serveur)"
echo "3. Installez SSL : sudo certbot --nginx -d timeoff.fr -d www.timeoff.fr"
echo ""
