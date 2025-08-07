from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, storage, db
import os
import uuid
import logging
import json

app = Flask(__name__)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def initialize_firebase():
    try:
        firebase_credentials = os.getenv('FIREBASE_CREDENTIALS')

        if firebase_credentials:
            cred_dict = json.loads(firebase_credentials)
            cred = credentials.Certificate(cred_dict)
            logger.info("🔑 Usando credenciales desde entorno")
        else:
            SERVICE_ACCOUNT_PATH = "serviceAccount.json"
            if not os.path.exists(SERVICE_ACCOUNT_PATH):
                raise Exception(f"No se encontró {SERVICE_ACCOUNT_PATH}")

            cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
            logger.info("🔑 Usando credenciales locales")

        storage_bucket = os.getenv('FIREBASE_STORAGE_BUCKET', 'esp32cam-3db20.firebasestorage.app')
        database_url = os.getenv('FIREBASE_DATABASE_URL', 'https://esp32cam-3db20-default-rtdb.firebaseio.com/')  # <-- cambia esto

        firebase_admin.initialize_app(cred, {
            "storageBucket": storage_bucket,
            "databaseURL": database_url
        })

        logger.info(f"✅ Firebase inicializado: Bucket={storage_bucket}, DB={database_url}")
        return True

    except Exception as e:
        logger.error(f"❌ Error inicializando Firebase: {e}")
        return False

if not initialize_firebase():
    logger.error("❌ Firebase no inicializado")
    exit(1)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/', methods=['GET'])
def home():
    return jsonify({'message': '🚀 ESP32 Cam Firebase Server', 'version': '1.0.0'}), 200

@app.route('/test', methods=['GET'])
def test():
    return jsonify({'message': '✅ Servidor funcionando correctamente'}), 200

@app.route('/upload', methods=['POST'])
def upload():
    if 'photo' not in request.files:
        return jsonify({'error': 'No se encontró archivo "photo"'}), 400

    file = request.files['photo']
    if file.filename == '':
        return jsonify({'error': 'Archivo sin nombre'}), 400

    filename = f"esp32cam_{uuid.uuid4().hex}.jpg"
    local_path = os.path.join(UPLOAD_FOLDER, filename)

    try:
        file.save(local_path)
        bucket = storage.bucket()
        blob = bucket.blob(f"esp32cam/{filename}")
        blob.upload_from_filename(local_path, content_type='image/jpeg')
        blob.make_public()
        public_url = blob.public_url

        # Guardar URL en Firebase Realtime Database
        ref = db.reference('esp32cam/images')
        new_ref = ref.push()
        new_ref.set({
            'filename': filename,
            'url': public_url,
            'timestamp': {'.sv': 'timestamp'}
        })

        os.remove(local_path)

        return jsonify({
            'message': '✅ Imagen subida exitosamente',
            'filename': filename,
            'url': public_url
        }), 200

    except Exception as e:
        logger.error(f"❌ Error en upload: {e}")
        if os.path.exists(local_path):
            os.remove(local_path)
        return jsonify({'error': f"❌ Error al subir imagen: {str(e)}"}), 500

@app.route('/list-files', methods=['GET'])
def list_files():
    try:
        bucket = storage.bucket()
        blobs = bucket.list_blobs(prefix='esp32cam/')

        files = []
        for blob in blobs:
            files.append({
                'name': blob.name,
                'size': blob.size,
                'created': blob.time_created.isoformat(),
                'url': f"https://storage.googleapis.com/{bucket.name}/{blob.name}"
            })

        files.sort(key=lambda x: x['created'], reverse=True)

        return jsonify({'files': files}), 200

    except Exception as e:
        return jsonify({'error': f"❌ Error: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug_mode = os.getenv('FLASK_ENV') == 'development'
    logger.info("🚀 Iniciando servidor Flask...")
    logger.info(f"🔧 Puerto: {port}, Debug: {debug_mode}")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
