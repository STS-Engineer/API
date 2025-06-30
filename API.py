# app.py
# --- Dependencies ---

import os
import socket # To automatically find the local IP address
import logging # To show informational messages
import sys # For system exit
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import exc
from datetime import datetime
from dotenv import load_dotenv
from urllib.parse import quote_plus # Import quote_plus to handle special characters

# Load environment variables from .env file
load_dotenv()

# --- Basic Configuration ---
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# --- Database Configuration with Validation ---
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD_RAW = os.environ.get("DB_PASSWORD")
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME")

# Validate required environment variables
required_env_vars = ["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME"]
missing_vars = [var for var in required_env_vars if not os.environ.get(var)]

if missing_vars:
    logging.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    logging.error("Please ensure your .env file contains all required database configuration variables.")
    sys.exit(1)

if DB_PASSWORD_RAW:
    DB_PASSWORD_ENCODED = quote_plus(DB_PASSWORD_RAW)
else:
    DB_PASSWORD_ENCODED = ""

# Construct database URI only if all required variables are present
app.config['SQLALCHEMY_DATABASE_URI'] = \
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD_ENCODED}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

logging.info(f"Database URI configured for: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

# Initialize the SQLAlchemy extension
try:
    db = SQLAlchemy(app)
    logging.info("SQLAlchemy initialized successfully")
except Exception as e:
    logging.error(f"Failed to initialize SQLAlchemy: {str(e)}")
    sys.exit(1)

# --- UPDATED Database Model Definition ---
class EdiRecord(db.Model):
    __tablename__ = 'EDITunisia'

    ID = db.Column(db.Integer, primary_key=True)
    ClientCode = db.Column(db.String(50), nullable=False)
    ProductCode = db.Column(db.String(50), nullable=False)
    Date = db.Column(db.String(20), nullable=False) 
    Quantity = db.Column(db.Integer, nullable=False)
    EDIWeekNumber = db.Column(db.Integer, nullable=True)
    ExpectedDeliveryDate = db.Column(db.String(20), nullable=True) 
    DeliveryNature = db.Column(db.String(100), nullable=True)
    DeliveredQuantity = db.Column(db.Integer, nullable=True)

    # UPDATED Helper method to handle string dates
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

# --- API Endpoints (Routes) ---

@app.route('/')
def index():
    """A simple root endpoint to confirm the API is running."""
    return jsonify({"message": "EDI Records API is running. Use /records to interact."})

@app.route('/records', methods=['GET'])
def get_records():
    """Retrieves all EDI records from the database."""
    try:
        records = EdiRecord.query.order_by(EdiRecord.ID).all()
        return jsonify([record.to_dict() for record in records])
    except exc.SQLAlchemyError as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

@app.route('/records', methods=['POST'])
def add_record():
    """Adds a new EDI record to the database."""
    data = request.get_json()

    required_fields = ["ClientCode", "ProductCode", "Date", "Quantity"]
    if not data or not all(field in data for field in required_fields):
        return jsonify({"error": f"Invalid payload. Required fields are: {required_fields}"}), 400

    try:
        # UPDATED: No longer converting date strings to date objects
        new_record = EdiRecord(
            ClientCode=data['ClientCode'],
            ProductCode=data['ProductCode'],
            Date=data['Date'], # Pass the string directly
            Quantity=data['Quantity'],
            EDIWeekNumber=data.get('EDIWeekNumber'),
            ExpectedDeliveryDate=data.get('ExpectedDeliveryDate'), # Pass the string directly
            DeliveryNature=data.get('DeliveryNature'),
            DeliveredQuantity=data.get('DeliveredQuantity')
        )
        db.session.add(new_record)
        db.session.commit()
        
        return jsonify({
            "message": "Record added successfully",
            "record": new_record.to_dict()
        }), 201
    except exc.SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

# --- Health check endpoint ---
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint to verify database connectivity."""
    try:
        # Test database connection
        db.session.execute('SELECT 1')
        return jsonify({"status": "healthy", "database": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

# --- Main execution ---
if __name__ == '__main__':
    with app.app_context():
        try:
            db.create_all()
            logging.info("Database tables created/verified successfully")
        except Exception as e:
            logging.error(f"Failed to create database tables: {str(e)}")
            sys.exit(1)
    
    app.run(host='127.0.0.1', port=5000, debug=True)