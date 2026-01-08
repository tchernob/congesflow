#!/bin/bash
# Script de sauvegarde TimeOff
# Sauvegarde quotidienne de la base de données SQLite

BACKUP_DIR="/home/tcher/backups/timeoff"
DB_PATH="/home/tcher/timeoff/conges.db"
DATE=$(date +%Y-%m-%d_%H-%M)
RETENTION_DAYS=30

# Créer le dossier de backup si nécessaire
mkdir -p $BACKUP_DIR

# Copier la base de données (avec sqlite3 pour éviter corruption)
sqlite3 $DB_PATH ".backup '$BACKUP_DIR/conges_$DATE.db'"

# Compresser
gzip $BACKUP_DIR/conges_$DATE.db

# Supprimer les backups de plus de 30 jours
find $BACKUP_DIR -name "conges_*.db.gz" -mtime +$RETENTION_DAYS -delete

echo "Backup terminé: conges_$DATE.db.gz"
