import os
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv

from routes.query import query_bp
from routes.auth import auth_bp
from routes.admin import admin_bp
from routes.refine import refine_bp  # NEW: query refinement / feedback chatbot
from services.schema_service import get_schema, get_primary_keys

# Step 0: Load .env (must happen before reading os.environ below)
load_dotenv()

# Step 1: Create Flask app
app = Flask(__name__)

# Step 2: Enable CORS (AFTER app creation)
CORS(app)

# Step 2.2: Preserve column/key order in JSON responses. Flask alphabetizes
# JSON object keys by default, which was silently reordering query result
# columns (e.g. "SELECT name, marks" coming back as marks-before-name in
# the response) regardless of the SELECT order. Column order is meaningful
# here - users pick it explicitly via NLP/refine feedback - so this is off.
app.json.sort_keys = False

# Step 2.5: JWT config
# Fail loudly at startup if the secret is missing, instead of letting every
# authenticated request fail later with an opaque flask_jwt_extended error.
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY is not set in the environment/.env file. Refusing to start.")
app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
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
    return jsonify(get_schema())

# Step 5.5: Primary-key route. Not every table's primary key is literally
# named 'id' (students.student_id, classes.class_id, faculty.faculty_id,
# exams.exam_id, results.result_id all use their own name) - the admin
# panel needs this to know which column to hide from the Insert/Update
# forms and which one to look a row up by, per table.
@app.route("/schema/keys")
def schema_keys():
    return jsonify(get_primary_keys())

# Step 6: Run app
if __name__ == "__main__":
    # Debug mode only when explicitly requested via FLASK_DEBUG=1 - the
    # Werkzeug debugger can execute arbitrary code, so it shouldn't be on
    # by default even for a local dev tool.
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(debug=debug)