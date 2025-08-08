#!/usr/bin/env python3
"""
Autodesk Construction Cloud Forms Client
Contains classes for authenticating and fetching forms data
"""

import requests
import json
import base64
import os
import time
import threading
import webbrowser
import urllib.parse
import csv
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import List, Dict, Any
from datetime import datetime
import urllib3

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

class AutodeskAuthenticator:
    """Handles Autodesk OAuth authentication"""
    
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.refresh_token = None
    
    def authenticate(self) -> bool:
        """Perform OAuth authentication"""
        
        # For web deployment, we'll use client credentials flow
        # This requires your Autodesk app to be configured for server-to-server auth
        return self.authenticate_client_credentials()
    
    def authenticate_client_credentials(self) -> bool:
        """Authenticate using client credentials flow (for server-to-server)"""
        
        auth_string = f"{self.client_id}:{self.client_secret}"
        auth_header = base64.b64encode(auth_string.encode()).decode()
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {auth_header}'
        }
        
        data = {
            'grant_type': 'client_credentials',
            'scope': 'data:read account:read'
        }
        
        try:
            response = requests.post(
                'https://developer.api.autodesk.com/authentication/v2/token',
                headers=headers, 
                data=data
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data['access_token']
                
                logger.info("✅ Client credentials authentication successful!")
                logger.info(f"   Token expires in: {token_data.get('expires_in', 'unknown')} seconds")
                return True
            else:
                logger.error(f"❌ Authentication failed: {response.status_code}")
                logger.error(response.text)
                return False
                
        except Exception as e:
            logger.error(f"❌ Authentication error: {e}")
            return False
    
    def authenticate_browser(self) -> bool:
        """Perform OAuth authentication via browser (fallback method)"""
        
        auth_code = {}
        
        class OAuthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed_url = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed_url.query)
                
                if 'code' in query:
                    auth_code['code'] = query['code'][0]
                    message = "✅ Authentication successful! You can close this browser."
                elif 'error' in query:
                    auth_code['error'] = query['error'][0]
                    message = f"❌ Authentication failed: {query['error'][0]}"
                else:
                    message = "❌ No authorization code found."
                
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                
                html_response = f"""
                <html><body style='font-family: Arial; text-align: center; padding: 50px;'>
                <h2>{message}</h2>
                <p>Return to your application.</p>
                </body></html>
                """
                self.wfile.write(html_response.encode('utf-8'))
            
            def log_message(self, format, *args):
                pass  # Suppress server logs
        
        def start_server():
            httpd = HTTPServer(('localhost', 3001), OAuthHandler)
            httpd.handle_request()
        
        # Start local server
        logger.info("🔄 Starting local OAuth server...")
        server_thread = threading.Thread(target=start_server, daemon=True)
        server_thread.start()
        time.sleep(1)
        
        # Build authorization URL
        redirect_uri = 'http://localhost:3001/callback'
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'scope': 'data:read account:read'
        }
        
        auth_url = f"https://developer.api.autodesk.com/authentication/v2/authorize?{urllib.parse.urlencode(params)}"
        
        logger.info("🔗 Opening browser for Autodesk authentication...")
        webbrowser.open(auth_url)
        
        # Wait for authorization code
        timeout = 120  # 2 minutes
        start_time = time.time()
        
        while 'code' not in auth_code and 'error' not in auth_code:
            if time.time() - start_time > timeout:
                logger.error("⏰ Authentication timeout!")
                return False
            time.sleep(1)
        
        if 'error' in auth_code:
            logger.error(f"❌ Authentication error: {auth_code['error']}")
            return False
        
        # Exchange code for tokens
        logger.info("🔐 Exchanging code for access token...")
        return self.exchange_code_for_token(auth_code['code'], redirect_uri)
    
    def exchange_code_for_token(self, code: str, redirect_uri: str) -> bool:
        """Exchange authorization code for access token"""
        
        auth_string = f"{self.client_id}:{self.client_secret}"
        auth_header = base64.b64encode(auth_string.encode()).decode()
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {auth_header}'
        }
        
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri
        }
        
        try:
            response = requests.post(
                'https://developer.api.autodesk.com/authentication/v2/token',
                headers=headers, 
                data=data
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data['access_token']
                self.refresh_token = token_data.get('refresh_token')
                
                logger.info("✅ Authentication successful!")
                return True
            else:
                logger.error(f"❌ Token exchange failed: {response.status_code}")
                logger.error(response.text)
                return False
                
        except Exception as e:
            logger.error(f"❌ Token exchange error: {e}")
            return False


class AutodeskFormsClient:
    """Client for fetching forms/reports from Autodesk Construction Cloud"""
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = "https://developer.api.autodesk.com/construction/forms/v1"
    
    def get_form_templates(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all form templates for a project"""
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        url = f"{self.base_url}/projects/{project_id}/form-templates"
        
        logger.info(f"📋 Fetching form templates from project {project_id[:8]}...")
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            response_data = response.json()
            
            # Handle different possible response formats
            if isinstance(response_data, list):
                templates = response_data
            elif isinstance(response_data, dict):
                templates = response_data.get('results', response_data.get('data', [response_data]))
                if not isinstance(templates, list):
                    templates = [templates] if templates else []
            else:
                logger.warning(f"Unexpected response format: {type(response_data)}")
                return []
            
            logger.info(f"✅ Found {len(templates)} form templates")
            return templates if isinstance(templates, list) else []
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error fetching templates: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching templates: {e}")
            return []
    
    def get_forms_for_template(self, project_id: str, template_id: str, template_name: str = "Unknown") -> List[Dict[str, Any]]:
        """Get all forms for a specific template"""
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        url = f"{self.base_url}/projects/{project_id}/form-templates/{template_id}/forms"
        
        logger.info(f"📝 Fetching forms for template: {template_name}")
        
        all_forms = []
        limit = 200  # Max allowed by API
        offset = 0
        
        while True:
            params = {
                'limit': limit,
                'offset': offset
            }
            
            try:
                response = requests.get(url, headers=headers, params=params)
                
                # Handle 404 specifically
                if response.status_code == 404:
                    logger.info(f"No forms found for template {template_name} (404)")
                    break
                
                response.raise_for_status()
                
                response_data = response.json()
                
                # Handle different response formats
                if isinstance(response_data, list):
                    forms = response_data
                elif isinstance(response_data, dict):
                    forms = response_data.get('results', response_data.get('data', []))
                    if not isinstance(forms, list):
                        forms = [response_data] if response_data else []
                else:
                    logger.warning(f"Unexpected forms response format: {type(response_data)}")
                    break
                
                if not forms:
                    break
                
                all_forms.extend(forms)
                logger.info(f"Fetched {len(forms)} forms (total: {len(all_forms)})")
                
                # Check if we got fewer results than requested (indicates last page)
                if len(forms) < limit:
                    break
                
                offset += limit
                
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP Error fetching forms: {e}")
                break
            except Exception as e:
                logger.error(f"Error fetching forms: {e}")
                break
        
        logger.info(f"Total forms for {template_name}: {len(all_forms)}")
        return all_forms
    
    def try_alternative_forms_endpoint(self, project_id: str) -> List[Dict[str, Any]]:
        """Try alternative endpoint to get all forms directly"""
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        url = f"{self.base_url}/projects/{project_id}/forms"
        
        logger.info("🔄 Trying alternative forms endpoint...")
        
        try:
            response = requests.get(url, headers=headers)
            
            if response.status_code == 404:
                logger.info("Alternative endpoint not available (404)")
                return []
            
            response.raise_for_status()
            
            response_data = response.json()
            
            # Handle different response formats
            if isinstance(response_data, list):
                forms = response_data
            elif isinstance(response_data, dict):
                forms = response_data.get('results', response_data.get('data', []))
                if not isinstance(forms, list):
                    forms = [response_data] if response_data else []
            else:
                logger.warning(f"Unexpected response format: {type(response_data)}")
                return []
            
            logger.info(f"✅ Found {len(forms)} forms via alternative endpoint")
            return forms
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error on alternative endpoint: {e}")
            return []
        except Exception as e:
            logger.error(f"Error on alternative endpoint: {e}")
            return []
    
    def get_all_forms(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all forms from all templates in a project"""
        
        logger.info(f"🔍 Getting all forms from project {project_id[:8]}...")
        
        # First get all templates
        templates = self.get_form_templates(project_id)
        
        if not templates:
            logger.warning("No form templates found")
            return []
        
        all_forms = []
        
        # Method 1: Get forms for each template individually
        for template in templates:
            if not isinstance(template, dict):
                continue
            
            template_id = template.get('id')
            template_name = template.get('name', 'Unnamed Template')
            
            if not template_id:
                continue
            
            try:
                forms = self.get_forms_for_template(project_id, template_id, template_name)
                
                # Add template info to each form
                for form in forms:
                    if isinstance(form, dict):
                        form['template_name'] = template_name
                        form['template_type'] = template.get('templateType', 'unknown')
                        form['template_id'] = template_id
                
                all_forms.extend(forms)
                
            except Exception as e:
                logger.error(f"Error processing template {template_name}: {e}")
                continue
        
        # Method 2: If no forms found, try alternative endpoint
        if not all_forms:
            alternative_forms = self.try_alternative_forms_endpoint(project_id)
            
            # Add basic template info if we got forms from alternative endpoint
            for form in alternative_forms:
                if isinstance(form, dict):
                    form_template_id = form.get('formTemplate', {}).get('id') if isinstance(form.get('formTemplate'), dict) else None
                    
                    # Find matching template
                    template_info = None
                    for template in templates:
                        if isinstance(template, dict) and template.get('id') == form_template_id:
                            template_info = template
                            break
                    
                    if template_info:
                        form['template_name'] = template_info.get('name', 'Unknown Template')
                        form['template_type'] = template_info.get('templateType', 'unknown')
                        form['template_id'] = template_info.get('id')
                    else:
                        form['template_name'] = 'Unknown Template'
                        form['template_type'] = 'unknown'
                        form['template_id'] = form_template_id
            
            all_forms.extend(alternative_forms)
        
        logger.info(f"📊 Total forms across all templates: {len(all_forms)}")
        return all_forms


class FormsCSVExporter:
    """Export forms data to CSV format"""
    
    def __init__(self, output_dir: str = "."):
        self.output_dir = output_dir