"""
WSGI entry point for production deployment
"""
import os
from app import app

# Set production environment if not already set
if not os.getenv('FLASK_ENV'):
    os.environ['FLASK_ENV'] = 'production'

if __name__ == "__main__":
    app.run()
