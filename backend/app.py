import os
from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv

from routes.query import query_bp
from routes.auth import auth_bp
from routes.admin import admin_bp
from routes.refine import refine_bp  # NEW: query refinement / feedback chatbot
from services.schema_service import get_schema

# Step 0: Load .env (must happen before reading os.environ below)
load_dotenv()

# Step 1: Create Flask app
app = Flask(__name__)

# Step 2: Enable CORS (AFTER app creation)
CORS(app)

# Step 2.5: JWT config
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY")
jwt = JWTManager(app)

# Step 3: Register blueprints
app.register_blueprint(query_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(refine_bp)  # NEW

# Step 4: Home route
@app.route("/")
def home():
    return "Backend is running"

# Step 5: Schema route
@app.route("/schema")
def schema():
    return get_schema()

# Step 6: Run app
if __name__ == "__main__":
    app.run(debug=True)