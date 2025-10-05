from http.server import BaseHTTPRequestHandler
import json
import base64
from io import BytesIO
import gspread
import pandas as pd
import qrcode
from PIL import Image, ImageDraw, ImageFont
import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- CONFIGURATION (from Vercel Environment Variables) ---
GOOGLE_SHEET_NAME = os.environ.get('GOOGLE_SHEET_NAME')
PROFILE_PIC_FOLDER_ID = os.environ.get('PROFILE_PIC_FOLDER_ID') # Folder for profile pics
GOOGLE_CREDS_JSON = os.environ.get('GOOGLE_CREDS_JSON')

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            # --- 1. Get Data from Frontend ---
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data)

            # Decode the profile picture
            profile_pic_data_url = data['file']
            header, encoded = profile_pic_data_url.split(",", 1)
            profile_pic_bytes = base64.b64decode(encoded)
            profile_pic_mimetype = header.split(":")[1].split(";")[0]

            # --- 2. Authenticate with Google ---
            creds_dict = json.loads(GOOGLE_CREDS_JSON)
            scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            gc = gspread.authorize(creds)
            drive_service = build('drive', 'v3', credentials=creds)

            # --- 3. Save Profile Pic to Drive ---
            file_metadata = {'name': f"{data['name']}_profile.png", 'parents': [PROFILE_PIC_FOLDER_ID]}
            media = MediaIoBaseUpload(BytesIO(profile_pic_bytes), mimetype=profile_pic_mimetype, resumable=True)
            uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='webViewLink').execute()
            profile_pic_url = uploaded_file.get('webViewLink')
            
            # --- 4. Save Data to Google Sheet ---
            spreadsheet = gc.open(GOOGLE_SHEET_NAME)
            worksheet = spreadsheet.sheet1
            invite_id = f"INV-{worksheet.row_count + 1:03d}"
            worksheet.append_row([
                pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'), data['name'], data['date'],
                data['mobile'], invite_id, data['year'], data['section'], profile_pic_url
            ])

            # --- 5. Generate the Invitation Image ---
            template = Image.open("./assets/background.png").convert("RGBA")
            profile_img = Image.open(BytesIO(profile_pic_bytes)).resize((180, 180))
            
            draw = ImageDraw.Draw(template)
            font_name = ImageFont.truetype("./api/Poppins-Bold.ttf", 48)
            font_details = ImageFont.truetype("./api/Poppins-Regular.ttf", 32)

            qr_data = f"Name: {data['name']}, ID: {invite_id}"
            qr_img = qrcode.make(qr_data).resize((180, 180))

            # --- Composite the image ---
            card_layer = Image.new('RGBA', template.size, (255, 255, 255, 0))
            draw_card = ImageDraw.Draw(card_layer)
            draw_card.rounded_rectangle([(100, 200), (1100, 475)], radius=30, fill=(0, 0, 0, 150))
            card_layer.paste(profile_img, (150, 248), profile_img.convert("RGBA"))
            card_layer.paste(qr_img, (880, 248))
            draw_card.text((360, 290), data['name'], font=font_name, fill='white')
            draw_card.text((360, 360), f"{data['year']} Year | Section: {data['section']}", font=font_details, fill='#cccccc')
            draw_card.text((360, 420), f"Invite ID: {invite_id}", font=font_details, fill='#cccccc')

            final_image = Image.alpha_composite(template, card_layer)

            # --- 6. Send Finished Image Back to Frontend ---
            buffer = BytesIO()
            final_image.save(buffer, format="PNG")
            img_str = base64.b64encode(buffer.getvalue()).decode()
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'success', 'image': img_str}).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode())
        return