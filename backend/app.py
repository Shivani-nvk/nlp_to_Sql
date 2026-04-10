from flask import Flask
from routes.query import query_bp
from services.schema_service import get_schema
from flask_cors import CORS

# Step 1: Create Flask app
app = Flask(__name__)

# Step 2: Enable CORS (AFTER app creation)
CORS(app)

# Step 3: Register blueprints
app.register_blueprint(query_bp)

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