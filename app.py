from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, storage
import os
import logging
import hashlib
import time
from werkzeug.utils import secure_filename

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuración de Firebase
try:
    # Inicializar Firebase con credenciales desde variable de entorno
    if not firebase_admin._apps:
        # Usar credenciales desde variable de entorno
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'esp32cam-3db20.firebasestorage.app'
        })
        logger.info("🔑 Usando credenciales de Firebase desde variable de entorno")
    
    # Obtener bucket de Firebase Storage
    bucket = storage.bucket()
    logger.info(f"✅ Firebase inicializado correctamente con bucket: {bucket.name}")

except Exception as e:
    logger.error(f"❌ Error inicializando Firebase: {str(e)}")
    bucket = None

# Crear directorio uploads si no existe
os.makedirs('uploads', exist_ok=True)

@app.route('/')
def home():
    return jsonify({
        'status': 'success',
        'message': 'ESP32-CAM Server está funcionando',
        'firebase_status': 'connected' if bucket else 'disconnected'
    })

@app.route('/test')
def test():
    return jsonify({
        'status': 'ok',
        'message': 'Servidor funcionando correctamente',
        'timestamp': int(time.time())
    })

@app.route('/carga', methods=['POST'])
def upload_file():
    logger.info("📤 Iniciando proceso de carga...")
    
    try:
        # Verificar que hay archivos en la petición
        if 'file' not in request.files:
            logger.warning("⚠️ No se encontró campo 'file' en la petición")
            return jsonify({'error': 'No se encontró archivo'}), 400
        
        file = request.files['file']
        
        # Verificar que el archivo tiene contenido
        if file.filename == '':
            logger.warning("⚠️ Archivo sin nombre")
            return jsonify({'error': 'Archivo sin nombre'}), 400
        
        if file and allowed_file(file.filename):
            logger.info(f"📁 Archivo recibido: {file.filename}")
            
            # Generar nombre único
            timestamp = int(time.time() * 1000)  # milisegundos
            random_hash = hashlib.md5(str(timestamp).encode()).hexdigest()[:8]
            filename = f"esp32cam_{random_hash}.jpg"
            
            # Guardar archivo temporalmente
            temp_path = os.path.join('uploads', filename)
            file.save(temp_path)
            logger.info(f"💾 Guardando archivo como: {temp_path}")
            
            # Verificar que el archivo se guardó
            if os.path.exists(temp_path):
                file_size = os.path.getsize(temp_path)
                logger.info(f"📊 Archivo guardado localmente. Tamaño: {file_size} bytes")
                
                # Subir a Firebase Storage si está disponible
                if bucket:
                    try:
                        logger.info("☁️ Subiendo a Firebase Storage...")
                        
                        # Crear blob en Firebase Storage
                        blob = bucket.blob(f"esp32cam/{filename}")
                        
                        # Subir archivo con metadata
                        blob.upload_from_filename(
                            temp_path, 
                            content_type='image/jpeg',
                            timeout=60  # 60 segundos de timeout
                        )
                        
                        # Hacer el archivo público
                        blob.make_public()
                        
                        # Obtener URL pública
                        public_url = blob.public_url
                        logger.info(f"✅ Archivo subido a Firebase Storage")
                        logger.info(f"🌐 URL pública: {public_url}")
                        
                        # Limpiar archivo temporal
                        os.remove(temp_path)
                        logger.info("🧹 Archivo temporal eliminado")
                        
                        return jsonify({
                            'status': 'success',
                            'message': 'Archivo subido correctamente',
                            'filename': filename,
                            'url': public_url,
                            'size': file_size
                        }), 200
                        
                    except Exception as firebase_error:
                        logger.error(f"❌ Error subiendo a Firebase: {str(firebase_error)}")
                        # Si falla Firebase, al menos confirmamos recepción
                        return jsonify({
                            'status': 'partial_success',
                            'message': 'Archivo recibido pero error en Firebase',
                            'filename': filename,
                            'error': str(firebase_error)
                        }), 200
                else:
                    logger.warning("⚠️ Firebase no disponible")
                    return jsonify({
                        'status': 'success',
                        'message': 'Archivo recibido (Firebase no disponible)',
                        'filename': filename,
                        'size': file_size
                    }), 200
            else:
                logger.error("❌ Error: El archivo no se guardó correctamente")
                return jsonify({'error': 'Error guardando archivo'}), 500
                
        else:
            logger.warning("⚠️ Tipo de archivo no permitido")
            return jsonify({'error': 'Tipo de archivo no permitido'}), 400
            
    except Exception as e:
        logger.error(f"❌ Error general en upload: {str(e)}")
        return jsonify({
            'error': 'Error interno del servidor',
            'details': str(e)
        }), 500

def allowed_file(filename):
    """Verificar si el archivo es una imagen permitida"""
    if not filename:
        return False
    
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/health')
def health_check():
    """Endpoint para verificar el estado del servidor"""
    return jsonify({
        'status': 'healthy',
        'timestamp': int(time.time()),
        'firebase_connected': bucket is not None
    })

@app.errorhandler(413)
def too_large(e):
    logger.warning("⚠️ Archivo demasiado grande")
    return jsonify({'error': 'Archivo demasiado grande'}), 413

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"❌ Error interno: {str(e)}")
    return jsonify({'error': 'Error interno del servidor'}), 500

if __name__ == '__main__':
    # Configurar límite de subida (16MB)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    
    # Ejecutar en modo debug para desarrollo
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
