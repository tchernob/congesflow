"""
Point d'entrée pour Vercel serverless.
"""
import sys
import os

# Ajouter le répertoire parent au path pour importer l'app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

app = create_app()

# Vercel utilise cette variable
application = app
