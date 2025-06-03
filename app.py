# Main Flask application

from flask_cors import CORS
from dotenv import load_dotenv
from config import get_config
from flask import Flask, request, jsonify, Response
import yt_dlp
import os, time, queue, logging
import threading, tempfile

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
# Set a secret key for session management
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

# Load configuration based on environment
config = get_config()
app.config.from_object(config)

# Set up logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Enable CORS for all routes
CORS(app)

# Target resolutions
# TARGET_RESOLUTIONS = ["360p", "480p", "720p", "1080p", "1440p", "2160p"]

class StreamLogger:
    """Simple logger that suppresses output."""
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def format_size(size):
    """Convert bytes to a human-readable format."""
    if size is None:
        return "Unknown size"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

def sanitize_filename(name):
    """Clean file names from forbidden characters."""
    return "".join(c for c in name if c.isalnum() or c in (' ', '.', '_', '-')).strip()


def get_video_info(url):
    """Fetch video or playlist info without downloading."""
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True}) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        logger.error(f"Error retrieving video info: {e}")
    return None

def stream_download_generator(url, format_id, filename):
    """Generator to stream download video data in chunks."""

    # Create a temporary file to stream through
    temp_path = os.path.join(config.TEMP_DIR, f"temp_download_{int(time.time())}_{filename}")

    # cookie file path
    cookie_file = '/etc/secrets/cookies.txt'   # For production 

    if os.path.exists(cookie_file):
        logging.error(f"Cookie file found at {cookie_file}")
        print(f"Cookie file found at {cookie_file}")
        # Check if file is readable
        try:
            with open(cookie_file, 'r') as f:
                content = f.read()
                logging.error(f"Cookie file size: {len(content)} characters")
                print(f"Cookie file size: {len(content)} characters")
        except Exception as e:
            logging.error(f"Cannot read cookie file: {e}")
            print(f"Cannot read cookie file: {e}")
    
    # Check if the cookie file exists
    # Fallback to development cookies if not found(for testing purposes)
    if not os.path.exists(cookie_file):
        # use development cookies
        cookie_file = 'youtube.com_cookies.txt'
        logging.error(f"Cookie file not found at {cookie_file}")
        print(f"Cookie file not found at {cookie_file}. Using development cookies instead.")
    
    try:
        ydl_opts = {
            'logger': StreamLogger(),
            'format': f"{format_id}+bestaudio/best" if '+bestaudio' not in format_id else format_id,
            'outtmpl': temp_path + '.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'ignoreerrors': False,
            'cookiefile': cookie_file,  # Use the cookie file for authentication
        }

        # Start download in background thread
        download_queue = queue.Queue()
        download_error = queue.Queue()
        
        def download_worker():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.download([url])
                    if result == 0:
                        download_queue.put("SUCCESS")
                    else:
                        download_error.put("Download failed")
            except Exception as e:
                download_error.put(str(e))
        
        # Start download
        download_thread = threading.Thread(target=download_worker)
        download_thread.daemon = True
        download_thread.start()

        # Find the actual downloaded file (yt-dlp adds extension)
        actual_file = None
        wait_time = 0
        
        while wait_time < config.MAX_WAIT_TIME:
            # Check for files matching our temp path
            for ext in ['mp4', 'mkv', 'webm', 'flv']:
                potential_file = f"{temp_path}.{ext}"
                if os.path.exists(potential_file):
                    actual_file = potential_file
                    break
            
            if actual_file:
                break
                
            # Check if download failed
            if not download_error.empty():
                error_msg = download_error.get()
                raise Exception(f"Download error: {error_msg}")
            
            time.sleep(0.5)
            wait_time += 0.5
        
        if not actual_file:
            raise Exception("Download file not found after timeout")
        
        while download_thread.is_alive() or os.path.exists(actual_file):
            try:
                if os.path.exists(actual_file):
                    with open(actual_file, 'rb') as f:
                        while True:
                            chunk = f.read(config.CHUNK_SIZE)
                            if not chunk:
                                # If download is still active, wait and try again
                                if download_thread.is_alive():
                                    time.sleep(0.1)
                                    continue
                                else:
                                    break
                            yield chunk
                    break
                else:
                    time.sleep(0.1)
            except IOError:
                # File might be temporarily locked, wait and retry
                time.sleep(0.1)
                continue
        
        # Check for download errors
        if not download_error.empty():
            error_msg = download_error.get()
            raise Exception(f"Download error: {error_msg}")
            
    finally:
        # Cleanup: Remove temporary file
        try:
            for ext in ['mp4', 'mkv', 'webm', 'flv']:
                temp_file = f"{temp_path}.{ext}"
                if os.path.exists(temp_file):
                    os.remove(temp_file)
        except Exception as e:
            logger.error(f"Error cleaning up temporary file: {e}")

@app.route('/api/video-info', methods=['POST'])
def get_video_info_api():
    """Get video information and available formats."""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Get video information
        logger.info(f"Getting video info for URL: {url}")
        video_info = get_video_info(url)
        if not video_info:
            return jsonify({'error': 'Could not retrieve video information'}), 400
        
        title = video_info.get('title', 'Unknown')
        formats = video_info.get('formats', [])
        
        # Filter formats 
        filtered_formats = []
        for f in formats:
            resolution = f.get('format_note') or f.get('height')
            if f.get('vcodec') != 'none' and resolution in config.TARGET_RESOLUTIONS:
                # Normalize resolution to string format
                if isinstance(resolution, int):
                    resolution = f"{resolution}p"
                
                filtered_formats.append({
                    'format_id': f['format_id'],
                    'resolution': resolution or 'Unknown',
                    'ext': f.get('ext'),
                    'filesize_str': format_size(f.get('filesize') or f.get('filesize_approx'))
                })
        
        # Sort formats by resolution
        filtered_formats.sort(key=lambda x: int(x['resolution'].replace('p', '')) if x['resolution'].endswith('p') else 0)
        
        # Prepare response
        logger.info(f"Found {len(filtered_formats)} formats for video: {title}")
        return jsonify({
            'title': title,
            'formats': filtered_formats
        })
    
    except Exception as e:
        logger.error(f"Error getting video info: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download-stream', methods=['POST'])
def download_stream():
    """Start a video download stream and stream it directly to client."""
    try:
        data = request.get_json()
        url = data.get('url')
        format_id = data.get('format_id')
        
        if not url or not format_id:
            return jsonify({'error': 'URL and format_id are required'}), 400
        
        logger.info(f"Starting download stream for URL: {url} with format_id: {format_id}")
        
        # Get video info for filename
        video_info = get_video_info(url)
        if not video_info:
            return jsonify({'error': 'Could not retrieve video information'}), 400
        
        title = sanitize_filename(video_info.get('title', 'video'))

        # Create streaming response
        def generate():
            try:
                for chunk in stream_download_generator(url, format_id, title):
                    yield chunk
            except Exception as e:
                # Send error as part of stream (browser extension can handle this)
                logger.error(f"Error during download stream: {e}")
                error_msg = f"Download error: {str(e)}"
                yield error_msg.encode('utf-8')
            
        response = Response(
            generate(),
            mimetype='application/octet-stream',
            headers={
                'Content-Disposition': f'attachment; filename="{title}.mp4"',
                'Cache-Control': 'no-cache',
                'Content-Type': 'application/octet-stream',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
            }
        )
        return response
    
    except Exception as e:
        logger.error(f"Error in download stream: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy', 
        'message': 'YouTube Downloader API is running',
        'environment': os.getenv('FLASK_ENV', 'development'),
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Run the app with the configured host and port
    app.run(
        debug=config.DEBUG, 
        host=config.HOST, 
        port=config.PORT, 
        threaded=True
    )
# This will allow the app to handle multiple requests simultaneously
# and stream downloads efficiently.
