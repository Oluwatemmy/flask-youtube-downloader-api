from flask import Flask, request, jsonify, send_file
from flask_socketio import SocketIO, emit, join_room
import yt_dlp
import os, time
import uuid
import threading
from werkzeug.utils import safe_join
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = '7bc8bbc2f76b9bfe947512e33c05e399e8c64abe48f23d1b917534298cb6d1bb'
socketio = SocketIO(app, cors_allowed_origins="*")

# Store active downloads
active_downloads = {}

# Target resolutions
TARGET_RESOLUTIONS = ["360p", "480p", "720p", "1080p", "1440p", "2160p"]

class MyLogger:
    def __init__(self, session_id):
        self.session_id = session_id
    
    def debug(self, msg): 
        pass
    
    def warning(self, msg): 
        pass
    
    def error(self, msg): 
        socketio.emit('download_error', {'message': f"❌ {msg}"}, room=self.session_id)

def create_download_path():
    """Creates and returns the download path."""
    download_path = os.path.join(os.getcwd(), 'downloads')
    os.makedirs(download_path, exist_ok=True)
    return download_path

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

def progress_hook(d, session_id):
    """Show progress of download via WebSocket."""
    if d['status'] == 'downloading':
        progress_data = {
            'status': 'downloading',
            'percent': d.get('_percent_str', '0%'),
            'speed': d.get('_speed_str', 'Unknown'),
            'eta': d.get('_eta_str', 'Unknown')
        }
        socketio.emit('download_progress', progress_data, room=session_id)
    elif d['status'] == 'finished':
        socketio.emit('download_progress', {'status': 'finished', 'filename': d['filename']}, room=session_id)

def handle_errors(e, attempt, retries, session_id):
    """Handle and log errors based on type."""
    msg = str(e)
    error_data = {'attempt': attempt, 'retries': retries}
    
    if "ffmpeg" in msg.lower():
        error_data['message'] = "❌ Missing dependency: ffmpeg is required to merge video and audio formats."
        error_data['suggestion'] = "Please install ffmpeg from: https://ffmpeg.org/download.html"
        socketio.emit('download_error', error_data, room=session_id)
        return False
    elif "getaddrinfo failed" in msg:
        error_data['message'] = "❌ Network error: Could not resolve YouTube. Please check your internet or DNS settings."
    elif "HTTP Error 403" in msg:
        error_data['message'] = "❌ Access denied: This video may be age-restricted or region-blocked."
    elif "HTTP Error 404" in msg:
        error_data['message'] = "❌ Not found: This video might have been removed."
    elif "Failed to extract" in msg:
        error_data['message'] = "❌ Extraction error: YouTube might have changed something. Try updating yt-dlp."
    else:
        error_data['message'] = f"❌ Download error: {msg}"
    
    socketio.emit('download_error', error_data, room=session_id)
    
    if attempt <= retries:
        socketio.emit('download_info', {'message': f"Retrying... ({attempt}/{retries})"}, room=session_id)
        time.sleep(2)   # Wait 2 seconds before retrying
        return True
    return False

def get_video_info(url):
    """Fetch video or playlist info without downloading."""
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True}) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"❌ Error retrieving video info: {e}")
    return None

def download_video_thread(url, format_id, session_id, retries=3):
    """Downloads a video in a separate thread."""
    attempt = 1
    download_path = create_download_path()
    
    try:
        active_downloads[session_id] = {'status': 'starting', 'url': url}
        
        while attempt <= retries:
            try:
                video_info = get_video_info(url)
                if not video_info:
                    socketio.emit('download_error', {'message': 'Could not retrieve video info'}, room=session_id)
                    return
                
                # return video title
                title = video_info.get('title', 'video')
                socketio.emit('download_info', {'message': f"🎬 Title: {title}"}, room=session_id)
                
                # Check if file already exists
                sanitized_title = sanitize_filename(title)
                file_exists = any(
                    os.path.exists(os.path.join(download_path, f"{sanitized_title}.{ext}"))
                    for ext in ['mp4', 'mkv', 'webm']
                )
                
                if file_exists:
                    socketio.emit('download_complete', {
                        'message': f"⚠️ Video already exists: {sanitized_title}",
                        'filename': sanitized_title
                    }, room=session_id)
                    return
                
                # Set download options
                ydl_opts = {
                    'logger': MyLogger(session_id),
                    'quiet': True,
                    'no_warnings': True,
                    'format': f"{format_id}+bestaudio/best" if '+bestaudio' not in format_id else format_id,
                    'outtmpl': os.path.join(download_path, '%(title)s.%(ext)s'),
                    'progress_hooks': [lambda d: progress_hook(d, session_id)],
                    'merge_output_format': 'mp4',  # Ensure merged file format
                    'ignoreerrors': True,  # Skip bad videos
                }
                
                # Download the video
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.download([url])
                
                if result == 0:
                    socketio.emit('download_complete', {
                        'message': f"✅ Download complete: {title}",
                        'filename': sanitized_title,
                        'path': download_path
                    }, room=session_id)
                    return
                else:
                    socketio.emit('download_error', {'message': "❌ Download failed."}, room=session_id)
                    
            except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as e:
                if not handle_errors(e, attempt, retries, session_id):
                    break
            except Exception as e:
                if not handle_errors(e, attempt, retries, session_id):
                    break
            attempt += 1
            
        socketio.emit('download_error', {
            'message': f"❌ Download failed after {retries} attempts."
        }, room=session_id)
        
    finally:
        # Clean up
        if session_id in active_downloads:
            del active_downloads[session_id]

@app.route('/api/video-info', methods=['POST'])
def get_video_info_api():
    """Get video information and available formats."""
    data = request.get_json()
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    video_info = get_video_info(url)
    if not video_info:
        return jsonify({'error': 'Could not retrieve video information'}), 400
    
    title = video_info.get('title', 'Unknown')
    formats = video_info.get('formats', [])
    
    # Filter formats 
    filtered_formats = []
    for f in formats:
        resolution = f.get('format_note') or f.get('height')
        if f.get('vcodec') != 'none' and resolution in TARGET_RESOLUTIONS:
            if isinstance(resolution, int):
                resolution = f"{resolution}p"
            
            filtered_formats.append({
                'format_id': f['format_id'],
                'resolution': resolution or 'Unknown',
                # 'filesize': f.get('filesize') or f.get('filesize_approx'),
                'ext': f.get('ext'),
                'filesize_str': format_size(f.get('filesize') or f.get('filesize_approx'))
            })
    
    # Sort formats by resolution
    filtered_formats.sort(key=lambda x: int(x['resolution'].replace('p', '')) if x['resolution'].endswith('p') else 0)
    
    return jsonify({
        'title': title,
        'formats': filtered_formats
    })

@app.route('/api/download', methods=['POST'])
def start_download():
    """Start a download with selected format."""
    data = request.get_json()
    url = data.get('url')
    format_id = data.get('format_id')
    
    if not url or not format_id:
        return jsonify({'error': 'URL and format_id are required'}), 400
    
    # Generate session ID for this download
    session_id = str(uuid.uuid4())
    
    # Start download in background thread
    thread = threading.Thread(target=download_video_thread, args=(url, format_id, session_id))
    thread.daemon = True
    thread.start()
    
    return jsonify({'session_id': session_id})

@app.route('/api/downloads/<filename>')
def download_file(filename):
    """Serve downloaded files."""
    download_path = create_download_path()
    try:
        return send_file(safe_join(download_path, filename), as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    print(f'Client disconnected: {request.sid}')

@socketio.on('join_session')
def handle_join_session(data):
    """Join a specific download session room."""
    session_id = data.get('session_id')
    if session_id:
        join_room(session_id)
        emit('joined_session', {'session_id': session_id})

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)