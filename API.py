# app.py - Azure Database for PostgreSQL Optimized
# --- Dependencies ---
# To install the necessary libraries, run:
# pip install Flask Flask-SQLAlchemy psycopg2-binary python-dotenv

import os
import logging
import sys
import ssl
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import exc, create_engine, text
from datetime import datetime
from dotenv import load_dotenv
from urllib.parse import quote_plus

# Load environment variables from .env file
load_dotenv()

# --- Basic Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)

# --- Azure Database Configuration ---
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD_RAW = os.environ.get("DB_PASSWORD")
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME")
DB_SSLMODE = os.environ.get("DB_SSLMODE", "require")  # Azure requires SSL
USE_DATABASE = os.environ.get("USE_DATABASE", "true").lower() == "true"

# Azure-specific settings
AZURE_SSL_CERT_PATH = os.environ.get("AZURE_SSL_CERT_PATH")  # Optional: path to SSL cert
CONNECTION_TIMEOUT = int(os.environ.get("CONNECTION_TIMEOUT", "30"))  # Longer timeout for Azure
COMMAND_TIMEOUT = int(os.environ.get("COMMAND_TIMEOUT", "30"))

logging.info("=== Azure Database Configuration ===")
logging.info(f"DB_USER: {DB_USER}")
logging.info(f"DB_HOST: {DB_HOST}")
logging.info(f"DB_PORT: {DB_PORT}")
logging.info(f"DB_NAME: {DB_NAME}")
logging.info(f"DB_SSLMODE: {DB_SSLMODE}")
logging.info(f"CONNECTION_TIMEOUT: {CONNECTION_TIMEOUT}")
logging.info(f"USE_DATABASE: {USE_DATABASE}")
logging.info("====================================")

# Global variable to track database status
db_connected = False
db = None

if USE_DATABASE:
    # Validate required environment variables
    required_env_vars = ["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME"]
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]

    if missing_vars:
        logging.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logging.info("Starting in NO-DATABASE mode. Set USE_DATABASE=false in .env to suppress this warning.")
        USE_DATABASE = False
    else:
        if DB_PASSWORD_RAW:
            DB_PASSWORD_ENCODED = quote_plus(DB_PASSWORD_RAW)
        else:
            DB_PASSWORD_ENCODED = ""

        # Construct Azure-optimized database URI
        database_uri = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD_ENCODED}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        
        # Add SSL parameters for Azure
        ssl_params = f"?sslmode={DB_SSLMODE}"
        
        # Add SSL certificate if provided
        if AZURE_SSL_CERT_PATH and os.path.exists(AZURE_SSL_CERT_PATH):
            ssl_params += f"&sslcert={AZURE_SSL_CERT_PATH}"
            logging.info(f"Using SSL certificate: {AZURE_SSL_CERT_PATH}")
        
        database_uri += ssl_params
        
        app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_timeout': CONNECTION_TIMEOUT,
            'pool_recycle': 300,  # Recycle connections every 5 minutes
            'pool_pre_ping': True,  # Verify connections before use
            'connect_args': {
                'connect_timeout': CONNECTION_TIMEOUT,
                'application_name': 'flask_edi_api',
                'sslmode': DB_SSLMODE,
                'options': f'-c statement_timeout={COMMAND_TIMEOUT}s'
            }
        }
        
        # Test database connection before initializing SQLAlchemy
        logging.info("Testing Azure database connection...")
        try:
            # Create a test engine with Azure-specific settings
            test_engine = create_engine(
                database_uri,
                connect_args={
                    "connect_timeout": CONNECTION_TIMEOUT,
                    "application_name": "flask_app_test",
                    "sslmode": DB_SSLMODE,
                    "options": f"-c statement_timeout={COMMAND_TIMEOUT}s"
                },
                pool_timeout=CONNECTION_TIMEOUT,
                pool_recycle=300,
                pool_pre_ping=True
            )
            
            # Test the connection
            with test_engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                logging.info("✅ Azure database connection successful!")
                db_connected = True
                
        except Exception as e:
            logging.error(f"❌ Azure database connection failed: {str(e)}")
            logging.error("Common Azure issues:")
            logging.error("1. Check if your IP is whitelisted in Azure firewall rules")
            logging.error("2. Verify SSL settings (Azure requires sslmode=require)")
            logging.error("3. Check if the server name format is correct: servername.postgres.database.azure.com")
            logging.error("4. Ensure the username format is correct: username@servername")
            logging.info("Starting in NO-DATABASE mode...")
            USE_DATABASE = False
            db_connected = False

if USE_DATABASE and db_connected:
    # Initialize SQLAlchemy only if database is accessible
    try:
        db = SQLAlchemy(app)
        logging.info("✅ SQLAlchemy initialized successfully")
    except Exception as e:
        logging.error(f"❌ Failed to initialize SQLAlchemy: {str(e)}")
        USE_DATABASE = False
        db_connected = False
else:
    # No database mode - use in-memory storage
    logging.info("🔄 Running in NO-DATABASE mode with in-memory storage")
    
    # In-memory storage for records
    in_memory_records = []
    next_id = 1

# --- Database Model Definition (only if using database) ---
if USE_DATABASE and db_connected:
    class EdiRecord(db.Model):
        __tablename__ = 'edi_records'

        ID = db.Column(db.Integer, primary_key=True)
        ClientCode = db.Column(db.String(50), nullable=False)
        ProductCode = db.Column(db.String(50), nullable=False)
        Date = db.Column(db.String(20), nullable=False)
        Quantity = db.Column(db.Integer, nullable=False)
        EDIWeekNumber = db.Column(db.Integer, nullable=True)
        ExpectedDeliveryDate = db.Column(db.String(20), nullable=True)
        DeliveryNature = db.Column(db.String(100), nullable=True)
        DeliveredQuantity = db.Column(db.Integer, nullable=True)

        def to_dict(self):
            return {
                "ID": self.ID,
                "ClientCode": self.ClientCode,
                "ProductCode": self.ProductCode,
                "Date": self.Date,
                "Quantity": self.Quantity,
                "EDIWeekNumber": self.EDIWeekNumber,
                "ExpectedDeliveryDate": self.ExpectedDeliveryDate,
                "DeliveryNature": self.DeliveryNature,
                "DeliveredQuantity": self.DeliveredQuantity
            }

# --- Helper functions for in-memory storage ---
def create_in_memory_record(data):
    global next_id
    record = {
        "ID": next_id,
        "ClientCode": data['ClientCode'],
        "ProductCode": data['ProductCode'],
        "Date": data['Date'],
        "Quantity": data['Quantity'],
        "EDIWeekNumber": data.get('EDIWeekNumber'),
        "ExpectedDeliveryDate": data.get('ExpectedDeliveryDate'),
        "DeliveryNature": data.get('DeliveryNature'),
        "DeliveredQuantity": data.get('DeliveredQuantity')
    }
    in_memory_records.append(record)
    next_id += 1
    return record

# --- API Endpoints (Routes) ---

@app.route('/')
def index():
    """A simple root endpoint to confirm the API is running."""
    mode = "Azure Database" if (USE_DATABASE and db_connected) else "In-Memory"
    return jsonify({
        "message": "EDI Records API is running. Use /records to interact.",
        "mode": mode,
        "database_connected": db_connected,
        "environment": "Azure" if "azure" in DB_HOST.lower() else "Local"
    })

@app.route('/display', methods=['GET'])
def get_records():
    """Retrieves all EDI records."""
    try:
        if USE_DATABASE and db_connected:
            # Use database with timeout handling
            records = EdiRecord.query.order_by(EdiRecord.ID).all()
            return jsonify([record.to_dict() for record in records])
        else:
            # Use in-memory storage
            return jsonify(sorted(in_memory_records, key=lambda x: x['ID']))
    except exc.SQLAlchemyError as e:
        logging.error(f"Database error in get_records: {str(e)}")
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error in get_records: {str(e)}")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

@app.route('/insert', methods=['POST'])
def add_record():
    """Adds a new EDI record."""
    data = request.get_json()

    required_fields = ["ClientCode", "ProductCode", "Date", "Quantity"]
    if not data or not all(field in data for field in required_fields):
        return jsonify({"error": f"Invalid payload. Required fields are: {required_fields}"}), 400

    try:
        if USE_DATABASE and db_connected:
            # Use database
            new_record = EdiRecord(
                ClientCode=data['ClientCode'],
                ProductCode=data['ProductCode'],
                Date=data['Date'],
                Quantity=data['Quantity'],
                EDIWeekNumber=data.get('EDIWeekNumber'),
                ExpectedDeliveryDate=data.get('ExpectedDeliveryDate'),
                DeliveryNature=data.get('DeliveryNature'),
                DeliveredQuantity=data.get('DeliveredQuantity')
            )
            db.session.add(new_record)
            db.session.commit()
            
            return jsonify({
                "message": "Record added successfully",
                "record": new_record.to_dict()
            }), 201
        else:
            # Use in-memory storage
            new_record = create_in_memory_record(data)
            return jsonify({
                "message": "Record added successfully (in-memory)",
                "record": new_record
            }), 201
            
    except exc.SQLAlchemyError as e:
        if USE_DATABASE and db_connected:
            db.session.rollback()
        logging.error(f"Database error in add_record: {str(e)}")
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    except Exception as e:
        if USE_DATABASE and db_connected:
            db.session.rollback()
        logging.error(f"Unexpected error in add_record: {str(e)}")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

# --- Health check endpoint ---
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint with Azure-specific checks."""
    if USE_DATABASE and db_connected:
        try:
            # Test database connection with timeout
            result = db.session.execute(text('SELECT 1'))
            return jsonify({
                "status": "healthy", 
                "database": "connected",
                "mode": "azure_database",
                "ssl_mode": DB_SSLMODE
            }), 200
        except Exception as e:
            logging.error(f"Health check failed: {str(e)}")
            return jsonify({
                "status": "unhealthy", 
                "database": "disconnected",
                "error": str(e),
                "mode": "azure_database"
            }), 500
    else:
        return jsonify({
            "status": "healthy",
            "database": "not_used",
            "mode": "in-memory"
        }), 200

@app.route('/azure-info', methods=['GET'])
def azure_info():
    """Azure-specific information endpoint."""
    return jsonify({
        "azure_host": DB_HOST,
        "ssl_mode": DB_SSLMODE,
        "connection_timeout": CONNECTION_TIMEOUT,
        "command_timeout": COMMAND_TIMEOUT,
        "database_connected": db_connected,
        "using_ssl_cert": bool(AZURE_SSL_CERT_PATH and os.path.exists(AZURE_SSL_CERT_PATH)),
        "tips": [
            "Ensure your IP is whitelisted in Azure firewall",
            "Use format: username@servername for DB_USER",
            "Server format: servername.postgres.database.azure.com",
            "SSL is required for Azure Database"
        ]
    })

# --- Main execution ---
if __name__ == '__main__':
    if USE_DATABASE and db_connected:
        with app.app_context():
            try:
                logging.info("Creating/verifying database tables...")
                db.create_all()
                logging.info("✅ Database tables created/verified successfully")
            except Exception as e:
                logging.error(f"❌ Failed to create database tables: {str(e)}")
                logging.info("🔄 Switching to in-memory mode...")
                USE_DATABASE = False
                db_connected = False
    
    logging.info("🚀 Starting Flask application...")
    logging.info(f"🌐 Access the API at: http://127.0.0.1:5000")
    logging.info(f"📊 Mode: {'Azure Database' if (USE_DATABASE and db_connected) else 'In-Memory'}")
    logging.info(f"🔍 Azure info endpoint: http://127.0.0.1:5000/azure-info")
    
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)