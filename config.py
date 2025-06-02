# Configuration management
# This module defines configuration settings for the Flask application that includes
# YouTube downloading capabilities, CORS settings, and logging configurations.

import os

class Config:
    """Base configuration class."""
    SECRET_KEY = os.getenv('SECRET_KEY')
    
    # YouTube downloader settings
    TARGET_RESOLUTIONS = ["360p", "480p", "720p", "1080p", "1440p", "2160p"]
    TEMP_DIR = os.getenv('TEMP_DIR', '/tmp')
    
    # Download settings
    # Stream the file as it's being downloaded
    CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', '8192'))  # 8KB chunks
    MAX_WAIT_TIME = int(os.getenv('MAX_WAIT_TIME', '45'))  # Wait up to 30 seconds for file to appear
    
    # CORS settings
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*').split(',')
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    HOST = '127.0.0.1'
    PORT = 5000
    LOG_LEVEL = 'DEBUG'

class TestConfig(Config):
    """Testing configuration."""
    TESTING = True
    DEBUG = True
    HOST = '127.0.0.1'
    PORT = 5001

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    HOST = '0.0.0.0'
    PORT = int(os.getenv('PORT', '5000'))
    
    # Production security
    SECRET_KEY = os.getenv('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY environment variable must be set in production")
    
    # Production optimizations
    CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', '8192'))  # 8KB chunks for production because of free plan
    
    # Stricter CORS in production (customize as needed)
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*').split(',')

# Configuration mapping
config_map = {
    'development': DevelopmentConfig,
    'test': TestConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

def get_config():
    """Get configuration based on FLASK_ENV environment variable."""
    env = os.getenv('FLASK_ENV', 'default').lower()
    return config_map.get(env, config_map['default'])