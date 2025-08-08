#!/usr/bin/env python3
"""
ACC Forms Dashboard - Flask Web App
Fetches ACC Forms data and displays in a web dashboard
"""

import os
import json
import sys
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, session
import requests
import base64
import urllib3
from dotenv import load_dotenv
import logging
import io
import threading
import time
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

# Import our ACC Forms classes
from acc_forms_client import AutodeskAuthenticator, AutodeskFormsClient, FormsCSVExporter

# Load environment variables
load_dotenv()

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-change-this')

# Configure sessions for OAuth state
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutes

# Global variables for storing data
forms_data = []
last_update = None
is_loading = False
error_message = None
authenticator = None  # Store authenticator globally

@app.route('/')
def dashboard():
    """Main dashboard page"""
    global forms_data, last_update, is_loading, error_message
    
    try:
        return render_template('dashboard.html', 
                             forms_count=len(forms_data),
                             last_update=last_update,
                             is_loading=is_loading,
                             error_message=error_message)
    except Exception as e:
        return f"Template Error: {str(e)}. Make sure dashboard.html is in templates/ folder."

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return {
        'status': 'ok',
        'message': 'Flask app is running',
        'python_version': sys.version,
        'templates_folder': os.path.exists('templates'),
        'dashboard_template': os.path.exists('templates/dashboard.html')
    }

@app.route('/auth/start')
def start_auth():
    """Start Autodesk OAuth authentication"""
    global authenticator
    
    try:
        # Get configuration from environment
        client_id = os.getenv('AUTODESK_CLIENT_ID')
        client_secret = os.getenv('AUTODESK_CLIENT_SECRET')
        
        if not all([client_id, client_secret]):
            return jsonify({'status': 'error', 'message': 'Missing Autodesk credentials'})
        
        authenticator = AutodeskAuthenticator(client_id, client_secret)
        
        # Build authorization URL
        redirect_uri = request.url_root + 'auth/callback'
        params = {
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'scope': 'data:read account:read'
        }
        
        auth_url = f"https://developer.api.autodesk.com/authentication/v2/authorize?{urllib.parse.urlencode(params)}"
        
        # Store redirect URI in session for callback
        session['redirect_uri'] = redirect_uri
        
        return jsonify({'status': 'success', 'auth_url': auth_url})
        
    except Exception as e:
        logger.error(f"Error starting auth: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/auth/callback')
def auth_callback():
    """Handle OAuth callback from Autodesk"""
    global authenticator, is_loading
    
    try:
        code = request.args.get('code')
        error = request.args.get('error')
        
        if error:
            error_message = f"Authentication failed: {error}"
            return f"""
            <html><body style='font-family: Arial; text-align: center; padding: 50px;'>
            <h2>❌ Authentication Failed</h2>
            <p>{error_message}</p>
            <p><a href="/">Return to Dashboard</a></p>
            </body></html>
            """
        
        if not code:
            return f"""
            <html><body style='font-family: Arial; text-align: center; padding: 50px;'>
            <h2>❌ No Authorization Code</h2>
            <p><a href="/">Return to Dashboard</a></p>
            </body></html>
            """
        
        # Exchange code for token
        redirect_uri = session.get('redirect_uri', request.url_root + 'auth/callback')
        
        if authenticator and authenticator.exchange_code_for_token(code, redirect_uri):
            # Authentication successful - start loading data in background
            is_loading = True
            threading.Thread(target=load_forms_data_background, daemon=True).start()
            
            return f"""
            <html><body style='font-family: Arial; text-align: center; padding: 50px;'>
            <h2>✅ Authentication Successful!</h2>
            <p>Loading your ACC Forms data...</p>
            <p><a href="/">Return to Dashboard</a></p>
            <script>
                setTimeout(function() {{
                    window.close();
                    if (window.opener) {{
                        window.opener.location.reload();
                    }}
                }}, 3000);
            </script>
            </body></html>
            """
        else:
            return f"""
            <html><body style='font-family: Arial; text-align: center; padding: 50px;'>
            <h2>❌ Token Exchange Failed</h2>
            <p>Could not complete authentication.</p>
            <p><a href="/">Return to Dashboard</a></p>
            </body></html>
            """
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        return f"""
        <html><body style='font-family: Arial; text-align: center; padding: 50px;'>
        <h2>❌ Authentication Error</h2>
        <p>{str(e)}</p>
        <p><a href="/">Return to Dashboard</a></p>
        </body></html>
        """

def load_forms_data_background():
    """Load forms data in background thread"""
    global forms_data, last_update, is_loading, error_message, authenticator
    
    try:
        if not authenticator or not authenticator.access_token:
            error_message = "No valid authentication token"
            is_loading = False
            return
        
        # Get project ID
        project_ids = os.getenv('AUTODESK_PROJECT_IDS', '').split(',')
        if not project_ids[0]:
            error_message = "No project ID configured"
            is_loading = False
            return
        
        project_id = project_ids[0].strip()
        
        # Fetch forms data
        logger.info("Fetching forms data in background...")
        forms_client = AutodeskFormsClient(authenticator.access_token)
        forms = forms_client.get_all_forms(project_id)
        
        if forms:
            forms_data = forms
            last_update = datetime.now()
            error_message = None
            logger.info(f"Successfully loaded {len(forms)} forms")
        else:
            forms_data = []
            error_message = "No forms found in project"
        
        is_loading = False
        
    except Exception as e:
        logger.error(f"Error loading forms data: {e}")
        error_message = str(e)
        is_loading = False

@app.route('/api/load-data', methods=['POST'])
def load_data():
    """API endpoint to start authentication and load ACC Forms data"""
    global forms_data, last_update, is_loading, error_message
    
    if is_loading:
        return jsonify({'status': 'error', 'message': 'Data is already being loaded'})
    
    try:
        # Get configuration from environment
        client_id = os.getenv('AUTODESK_CLIENT_ID')
        client_secret = os.getenv('AUTODESK_CLIENT_SECRET')
        project_ids = os.getenv('AUTODESK_PROJECT_IDS', '').split(',')
        
        if not all([client_id, client_secret, project_ids[0]]):
            return jsonify({'status': 'error', 'message': 'Missing required environment variables'})
        
        # Start authentication process
        return jsonify({
            'status': 'auth_required',
            'message': 'Authentication required. Please click the authentication link.',
            'auth_url': '/auth/start'
        })
        
    except Exception as e:
        logger.error(f"Error in load_data: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/forms-data')
def get_forms_data():
    """API endpoint to get forms data as JSON"""
    global forms_data
    
    if not forms_data:
        return jsonify({'status': 'error', 'message': 'No data loaded'})
    
    # Convert forms data to a more frontend-friendly format
    processed_data = []
    
    for form in forms_data:
        # Extract key information
        form_info = {
            'id': form.get('id'),
            'formNum': form.get('formNum'),
            'name': form.get('name'),
            'status': form.get('status'),
            'formDate': form.get('formDate'),
            'templateName': form.get('template_name'),
            'templateType': form.get('template_type'),
            'createdAt': form.get('createdAt'),
            'updatedAt': form.get('updatedAt'),
            'assigneeId': form.get('assigneeId'),
            'locationId': form.get('locationId'),
            'customFieldsCount': len(form.get('customValues', [])),
            'tabularDataCount': len(form.get('tabularValues', {})),
            'hasNotes': bool(form.get('notes', '').strip()),
            'hasDescription': bool(form.get('description', '').strip())
        }
        
        # Add custom fields summary
        custom_values = form.get('customValues', [])
        custom_fields = {}
        for field in custom_values:
            if isinstance(field, dict):
                field_name = field.get('itemLabel', field.get('name', ''))
                field_value = field.get('textVal', field.get('numberVal', field.get('dateVal', '')))
                if field_name:
                    custom_fields[field_name] = field_value
        
        form_info['customFields'] = custom_fields
        
        # Add tabular data summary
        tabular_values = form.get('tabularValues', {})
        tabular_summary = {}
        for table_name, table_data in tabular_values.items():
            if isinstance(table_data, list):
                tabular_summary[table_name] = {
                    'rowCount': len(table_data),
                    'columns': list(table_data[0].keys()) if table_data and isinstance(table_data[0], dict) else []
                }
        
        form_info['tabularData'] = tabular_summary
        processed_data.append(form_info)
    
    return jsonify({'status': 'success', 'data': processed_data})

@app.route('/api/export-csv')
def export_csv():
    """Export forms data as CSV file"""
    global forms_data
    
    if not forms_data:
        return jsonify({'status': 'error', 'message': 'No data to export'})
    
    try:
        # Create CSV exporter
        exporter = FormsCSVExporter()
        
        # Generate CSV data in memory
        output = io.StringIO()
        
        # Create detailed CSV data
        fieldnames = [
            'form_id', 'form_number', 'form_name', 'template_name',
            'field_type', 'field_name', 'field_value', 'field_id',
            'field_section', 'field_data_type', 'field_required',
            'status', 'form_date', 'created_at', 'created_by',
            'assignee_id', 'assignee_type', 'location_id'
        ]
        
        import csv
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for form in forms_data:
            form_base = {
                'form_id': form.get('id'),
                'form_number': form.get('formNum'),
                'form_name': form.get('name'),
                'template_name': form.get('template_name'),
                'status': form.get('status'),
                'form_date': form.get('formDate'),
                'created_at': form.get('createdAt'),
                'created_by': form.get('createdBy'),
                'assignee_id': form.get('assigneeId'),
                'assignee_type': form.get('assigneeType'),
                'location_id': form.get('locationId')
            }
            
            # Write custom values
            custom_values = form.get('customValues', [])
            if custom_values:
                for field in custom_values:
                    if isinstance(field, dict):
                        field_value = ""
                        value_name = field.get('valueName', 'textVal')
                        
                        if value_name and value_name in field:
                            field_value = field.get(value_name)
                        elif 'textVal' in field:
                            field_value = field.get('textVal')
                        elif 'value' in field:
                            field_value = field.get('value')
                        elif 'numberVal' in field:
                            field_value = field.get('numberVal')
                        elif 'dateVal' in field:
                            field_value = field.get('dateVal')
                        elif 'booleanVal' in field:
                            field_value = field.get('booleanVal')
                        
                        row = form_base.copy()
                        row.update({
                            'field_type': 'custom',
                            'field_name': field.get('itemLabel', field.get('name', '')),
                            'field_value': str(field_value) if field_value is not None else '',
                            'field_id': field.get('fieldId', field.get('id', '')),
                            'field_section': field.get('sectionLabel', ''),
                            'field_data_type': value_name if value_name else 'text',
                            'field_required': field.get('required', False)
                        })
                        writer.writerow(row)
            
            # Write tabular values
            tabular_values = form.get('tabularValues', {})
            if tabular_values:
                for table_name, table_data in tabular_values.items():
                    if table_data and isinstance(table_data, list):
                        for i, row_data in enumerate(table_data):
                            if isinstance(row_data, dict):
                                for field_name, field_value in row_data.items():
                                    row = form_base.copy()
                                    row.update({
                                        'field_type': 'tabular',
                                        'field_name': f"{table_name}.{field_name}",
                                        'field_value': str(field_value) if field_value is not None else '',
                                        'field_id': f"{table_name}_row_{i}_{field_name}",
                                        'field_section': table_name,
                                        'field_data_type': 'tabular_cell',
                                        'field_required': False
                                    })
                                    writer.writerow(row)
        
        # Create response
        output.seek(0)
        csv_data = output.getvalue()
        
        # Create file-like object for download
        csv_buffer = io.BytesIO()
        csv_buffer.write(csv_data.encode('utf-8'))
        csv_buffer.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ACC_Forms_Export_{timestamp}.csv"
        
        return send_file(
            csv_buffer,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/status')
def get_status():
    """Get current loading status"""
    global forms_data, last_update, is_loading, error_message
    
    return jsonify({
        'is_loading': is_loading,
        'forms_count': len(forms_data),
        'last_update': last_update.isoformat() if last_update else None,
        'error_message': error_message
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV') == 'development'
    
    app.run(host='0.0.0.0', port=port, debug=debug)
