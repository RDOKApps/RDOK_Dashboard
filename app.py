import os
import json
import sys
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
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
from http.server import HTTPServer, BaseHTTPRequestHandler#!/usr/bin/env python3
"""
ACC Forms Dashboard - Flask Web App
Fetches ACC Forms data and displays in a web dashboard
"""

import os
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
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

# Import our ACC Forms classes (we'll put them in a separate file)
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

# Global variables for storing data
forms_data = []
last_update = None
is_loading = False
error_message = None

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

@app.route('/api/load-data', methods=['POST'])
def load_data():
    """API endpoint to load ACC Forms data"""
    global forms_data, last_update, is_loading, error_message
    
    if is_loading:
        return jsonify({'status': 'error', 'message': 'Data is already being loaded'})
    
    is_loading = True
    error_message = None
    
    try:
        # Get configuration from environment
        client_id = os.getenv('AUTODESK_CLIENT_ID')
        client_secret = os.getenv('AUTODESK_CLIENT_SECRET')
        project_ids = os.getenv('AUTODESK_PROJECT_IDS', '').split(',')
        
        if not all([client_id, client_secret, project_ids[0]]):
            raise ValueError("Missing required environment variables")
        
        project_id = project_ids[0].strip()
        
        # Authenticate with Autodesk
        logger.info("Starting Autodesk authentication...")
        authenticator = AutodeskAuthenticator(client_id, client_secret)
        
        # For web deployment, we'll use a simplified auth method
        # In production, you might want to implement proper OAuth flow
        if not authenticator.authenticate():
            raise Exception("Autodesk authentication failed")
        
        # Fetch forms data
        logger.info("Fetching forms data...")
        forms_client = AutodeskFormsClient(authenticator.access_token)
        forms = forms_client.get_all_forms(project_id)
        
        if not forms:
            forms_data = []
            last_update = datetime.now()
            is_loading = False
            return jsonify({'status': 'success', 'message': 'No forms found', 'count': 0})
        
        # Store the data globally
        forms_data = forms
        last_update = datetime.now()
        is_loading = False
        
        logger.info(f"Successfully loaded {len(forms)} forms")
        return jsonify({
            'status': 'success', 
            'message': f'Successfully loaded {len(forms)} forms',
            'count': len(forms)
        })
        
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        error_message = str(e)
        is_loading = False
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
