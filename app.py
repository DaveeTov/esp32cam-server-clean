from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, storage
import os
import uuid
import logging
import json

app = Flask(__name__)

# Configurar logging para debug
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def initialize_firebase():
    """Inicializar Firebase usando variables de entorno o archivo local"""
    try:
        # Intentar usar variables de entorno primero (para producción)
        firebase_credentials = os.getenv('FIREBASE_CREDENTIALS')
        
        if firebase_credentials:
            # Usar credenciales desde variable de entorno (Render, Heroku, etc.)
            logger.info("🔑 Usando credenciales de Firebase desde variable de entorno")
            cred_dict = json.loads(firebase_credentials)
            cred = credentials.Certificate(cred_dict)
        else:
            # Usar archivo local para desarrollo
            SERVICE_ACCOUNT_PATH = "serviceAccount.json"
            if not os.path.exists(SERVICE_ACCOUNT_PATH):
                raise Exception(f"No se encontró {SERVICE_ACCOUNT_PATH} ni la variable FIREBASE_CREDENTIALS")
            
            logger.info("🔑 Usando credenciales de Firebase desde archivo local")
            cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
        
        # Obtener bucket desde variable de entorno o usar default
        storage_bucket = os.getenv('FIREBASE_STORAGE_BUCKET', 'esp32cam-3db20.firebasestorage.app')
        
        firebase_admin.initialize_app(cred, {
            "storageBucket": storage_bucket
        })
        
        logger.info(f"✅ Firebase inicializado correctamente con bucket: {storage_bucket}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error al inicializar Firebase: {e}")
        return False

# Inicializar Firebase al arrancar la aplicación
if not initialize_firebase():
    logger.error("❌ No se pudo inicializar Firebase. Cerrando aplicación.")
    exit(1)

# Carpeta temporal para archivos
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/', methods=['GET'])
def home():
    """Endpoint de inicio"""
    return jsonify({
        'message': '🚀 ESP32 Cam Firebase Server',
        'version': '1.0.0',
        'endpoints': {
            'GET /': 'Información del servidor',
            'GET /test': 'Prueba del servidor',
            'GET /test-firebase': 'Prueba de Firebase',
            'POST /upload': 'Subir imagen',
            'GET /list-files': 'Listar archivos'
        }
    }), 200

@app.route('/test', methods=['GET'])
def test():
    """Endpoint de prueba para verificar que el servidor funciona"""
    return jsonify({'message': '✅ Servidor Flask funcionando correctamente'}), 200

@app.route('/test-firebase', methods=['GET'])
def test_firebase():
    """Endpoint para probar la conexión con Firebase"""
    try:
        bucket = storage.bucket()
        logger.info(f"✅ Bucket conectado: {bucket.name}")
        return jsonify({
            'message': '✅ Conexión a Firebase Storage exitosa',
            'bucket': bucket.name
        }), 200
    except Exception as e:
        logger.error(f"❌ Error conectando a Firebase: {e}")
        return jsonify({'error': f'❌ Error conectando a Firebase: {str(e)}'}), 500

@app.route('/upload', methods=['POST'])
def upload():
    logger.info("📤 Iniciando proceso de upload...")
    
    # Verificar que hay archivo en la petición
    if 'photo' not in request.files:
        logger.error("❌ No se encontró 'photo' en request.files")
        logger.info(f"Archivos disponibles: {list(request.files.keys())}")
        return jsonify({'error': 'No se encontró el archivo "photo" en la solicitud'}), 400

    file = request.files['photo']
    logger.info(f"📁 Archivo recibido: {file.filename}")
    
    # Verificar que el archivo tiene nombre
    if file.filename == '':
        logger.error("❌ Archivo sin nombre")
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400

    # Verificar que el archivo tiene contenido
    if not file:
        logger.error("❌ Archivo vacío")
        return jsonify({'error': 'El archivo está vacío'}), 400

    # Generar nombre único con timestamp
    timestamp = int(uuid.uuid4().time_low)
    filename = f"esp32cam_{timestamp}.jpg"
    local_path = os.path.join(UPLOAD_FOLDER, filename)
    
    logger.info(f"💾 Guardando archivo como: {local_path}")

    try:
        # Guardar archivo temporalmente
        file.save(local_path)
        
        # Verificar que el archivo se guardó correctamente
        if not os.path.exists(local_path):
            raise Exception("No se pudo guardar el archivo temporalmente")
            
        file_size = os.path.getsize(local_path)
        logger.info(f"📊 Archivo guardado localmente. Tamaño: {file_size} bytes")
        
        if file_size == 0:
            raise Exception("El archivo guardado está vacío")

        # Subir a Firebase Storage
        logger.info("☁️ Subiendo a Firebase Storage...")
        bucket = storage.bucket()
        blob_path = f"esp32cam/{filename}"
        blob = bucket.blob(blob_path)
        
        # Subir archivo con metadata
        blob.upload_from_filename(local_path, content_type='image/jpeg')
        logger.info("✅ Archivo subido a Firebase Storage")
        
        # Hacer público (opcional)
        blob.make_public()
        public_url = blob.public_url
        logger.info(f"🌐 URL pública: {public_url}")

        # Limpiar archivo temporal
        os.remove(local_path)
        logger.info("🧹 Archivo temporal eliminado")

        return jsonify({
            'message': '✅ Imagen subida exitosamente',
            'filename': filename,
            'url': public_url,
            'size': file_size,
            'timestamp': timestamp
        }), 200

    except Exception as e:
        logger.error(f"❌ Error durante el upload: {str(e)}")
        
        # Limpiar archivo temporal si existe
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
                logger.info("🧹 Archivo temporal eliminado después del error")
            except:
                logger.error("❌ No se pudo eliminar el archivo temporal")
        
        return jsonify({'error': f'❌ Error al subir imagen: {str(e)}'}), 500

@app.route('/list-files', methods=['GET'])
def list_files():
    """Listar archivos en Firebase Storage"""
    try:
        bucket = storage.bucket()
        blobs = bucket.list_blobs(prefix='esp32cam/')
        
        files = []
        for blob in blobs:
            files.append({
                'name': blob.name,
                'size': blob.size,
                'created': blob.time_created.isoformat() if blob.time_created else None,
                'url': f"https://storage.googleapis.com/{bucket.name}/{blob.name}"
            })
        
        # Ordenar por fecha de creación (más reciente primero)
        files.sort(key=lambda x: x['created'] or '', reverse=True)
        
        return jsonify({
            'message': f'✅ {len(files)} archivos encontrados',
            'files': files
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error listando archivos: {e}")
        return jsonify({'error': f'❌ Error listando archivos: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check para servicios de hosting"""
    return jsonify({'status': 'healthy', 'timestamp': uuid.uuid4().time_low}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug_mode = os.getenv('FLASK_ENV') == 'development'
    
    logger.info("🚀 Iniciando servidor Flask...")
    logger.info("📍 Endpoints disponibles:")
    logger.info("  GET  / - Información del servidor")
    logger.info("  GET  /test - Prueba del servidor")
    logger.info("  GET  /test-firebase - Prueba de Firebase")
    logger.info("  POST /upload - Subir imagen")
    logger.info("  GET  /list-files - Listar archivos")
    logger.info("  GET  /health - Health check")
    logger.info(f"🔧 Puerto: {port}, Debug: {debug_mode}")
    
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
