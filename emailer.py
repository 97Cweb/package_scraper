import smtplib
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
import os
import base64
from io import BytesIO
import barcode
from barcode.writer import ImageWriter

def generate_barcode_base64(tracking_number):
    """
    Generate a barcode image as a Base64 string for embedding in HTML.
    """
    barcode_class = barcode.get_barcode_class('code128')
    barcode_obj = barcode_class(tracking_number, writer=ImageWriter())
    buffer = BytesIO()
    barcode_obj.write(buffer, {'module_width': 0.3, 'module_height': 10.0})
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode()

def send_email(subject, body, to_email, tracking_number=None):
    """
    Send an email with an optional attachment.
    This function can be reused for various tasks in Home Assistant.
    """
    with open("secrets.txt", 'r') as file:
        lines = file.readlines()
        from_email = lines[0].strip()
        password = lines[1].strip()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    # Generate barcode if tracking number is provided
    barcode_html = ""
    if tracking_number:
        barcode_data = generate_barcode_base64(tracking_number)
        image_cid = make_msgid(domain="barcode.local")
        barcode_html = f'<p>Here is your tracking barcode:</p><img src="cid:{image_cid[1:-1]}" alt="Barcode" /><br>'
        msg.add_related(
            base64.b64decode(barcode_data),
            maintype="image",
            subtype="png",
            cid=image_cid,
        )

    # Email body with embedded barcode
    html_body = f"""
    <html>
        <body>
            <p>{body}</p>
            {barcode_html}
        </body>
    </html>
    """
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(from_email, password)
            server.send_message(msg)
            print(f"Email with barcode sent to {to_email}")
            return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
